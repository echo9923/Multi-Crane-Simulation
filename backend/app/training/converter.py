from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Sequence

import pyarrow as pa
import pyarrow.parquet as pq

from backend.app.schemas.training import (
    TRAINING_E_WRITE_FAILED,
    StgnnConversionOptions,
    StgnnConversionResult,
    StgnnFeatureSpec,
    StgnnManifest,
    StgnnSampleIndexRow,
    TrainingConversionError,
    default_stgnn_feature_spec,
)
from backend.app.training.edge_features import EdgeFeatureBuilder
from backend.app.training.episode_source import EpisodeParquetSource
from backend.app.training.labels import LabelBuilder
from backend.app.training.metadata import (
    ConversionSummaryBuilder,
    SampleMetadataBuilder,
    build_sample_index_row,
)
from backend.app.training.node_features import NodeFeatureBuilder
from backend.app.training.variable_nodes import VariableNodeStrategy
from backend.app.training.window_reader import DatasetWindowReader


class StgnnDatasetConverter:
    def __init__(
        self,
        *,
        options: StgnnConversionOptions | None = None,
        feature_spec: StgnnFeatureSpec | None = None,
        strict: bool | None = None,
        dry_run: bool | None = None,
        max_nodes: int | None = None,
    ) -> None:
        self.options = options
        self.feature_spec = feature_spec
        self.strict_override = strict
        self.dry_run_override = dry_run
        self.max_nodes_override = max_nodes

    def convert(
        self,
        *,
        dataset_root: Path,
        output_root: Path | None = None,
        splits: Sequence[str] | None = None,
    ) -> StgnnConversionResult:
        dataset_root = Path(dataset_root)
        output_root = Path(output_root) if output_root is not None else dataset_root / "training" / "stgnn"
        strict = self.strict_override if self.strict_override is not None else (
            self.options.strict if self.options is not None else True
        )
        dry_run = self.dry_run_override if self.dry_run_override is not None else (
            self.options.dry_run if self.options is not None else False
        )
        max_nodes_option = self.max_nodes_override if self.max_nodes_override is not None else (
            self.options.max_nodes if self.options is not None else None
        )
        requested_splits = list(splits) if splits is not None else (
            self.options.splits if self.options is not None else None
        )

        bundle = DatasetWindowReader().read(dataset_root)
        windows = [
            window for window in bundle.windows
            if requested_splits is None or window.split in requested_splits
        ]
        max_nodes = max_nodes_option or max((window.num_cranes for window in windows), default=1)
        feature_spec = self.feature_spec or default_stgnn_feature_spec(
            max_nodes=max_nodes,
            risk_label_horizons_s=_window_horizons(windows),
        )
        samples: list[StgnnSampleIndexRow] = []
        warnings: list[dict] = []
        skipped_counts: Counter[str] = Counter()

        source = EpisodeParquetSource(
            dataset_root=dataset_root,
            allow_graph_edge_fallback=True,
        )
        variable_nodes = VariableNodeStrategy()
        node_builder = NodeFeatureBuilder(feature_spec=feature_spec)
        edge_builder = EdgeFeatureBuilder(
            feature_spec=feature_spec,
            allow_graph_edge_fallback=True,
        )
        label_builder = LabelBuilder(feature_spec=feature_spec)
        metadata_builder = SampleMetadataBuilder()

        for window in windows:
            try:
                tables = source.load_for_window(window)
                crane_order = variable_nodes.crane_order_for_window(
                    window=window,
                    tables=tables,
                )
                variable_nodes.plan(
                    windows=[window],
                    episode_cranes={window.episode_id: crane_order},
                    configured_max_nodes=feature_spec.max_nodes,
                )
                node_builder.build(
                    window=window,
                    tables=tables,
                    crane_order=crane_order,
                    max_nodes=feature_spec.max_nodes,
                )
                edge_builder.build(
                    window=window,
                    tables=tables,
                    crane_order=crane_order,
                    max_nodes=feature_spec.max_nodes,
                )
                label_builder.build_traj(
                    window=window,
                    tables=tables,
                    crane_order=crane_order,
                    max_nodes=feature_spec.max_nodes,
                )
                label_builder.build_risk(
                    window=window,
                    tables=tables,
                    crane_order=crane_order,
                    max_nodes=feature_spec.max_nodes,
                )
                metadata = metadata_builder.build(
                    window=window,
                    feature_spec=feature_spec,
                    source_paths=tables.source_paths,
                    crane_order=crane_order,
                )
                samples.append(
                    build_sample_index_row(
                        metadata=metadata,
                        feature_spec=feature_spec,
                        num_nodes=len(crane_order),
                    )
                )
            except TrainingConversionError as exc:
                if strict:
                    raise
                skipped_counts[window.split] += 1
                warnings.append(
                    {
                        "warning_code": exc.code,
                        "message": exc.message,
                        "episode_id": window.episode_id,
                        "split": window.split,
                        "details": exc.details,
                    }
                )

        summary = ConversionSummaryBuilder().build(
            dataset_id=bundle.dataset_id,
            samples=samples,
            feature_spec=feature_spec,
            skipped_counts=dict(skipped_counts),
            risk_distribution=bundle.summary.risk_distribution,
            warnings=warnings,
        )
        manifest = StgnnManifest(
            dataset_id=bundle.dataset_id,
            source_dataset_root=str(dataset_root),
            output_root=str(output_root),
            feature_spec=feature_spec,
            sample_index_path=str(output_root / "index" / "samples.parquet"),
            summary_path=str(output_root / "metadata" / "stgnn_summary.json"),
            warnings=warnings,
        )
        result = StgnnConversionResult(
            manifest=manifest,
            summary=summary,
            samples=samples,
        )
        if not dry_run:
            _write_result(output_root, result, warnings)
        return result


def _window_horizons(windows: Sequence) -> list[float]:
    for window in windows:
        if window.label_horizons_s:
            return list(window.label_horizons_s)
    return [5.0]


def _write_result(
    output_root: Path,
    result: StgnnConversionResult,
    warnings: list[dict],
) -> None:
    metadata_dir = output_root / "metadata"
    index_dir = output_root / "index"
    metadata_dir.mkdir(parents=True, exist_ok=True)
    index_dir.mkdir(parents=True, exist_ok=True)
    _write_json_atomic(
        metadata_dir / "stgnn_manifest.json",
        result.manifest.model_dump(mode="json"),
    )
    _write_json_atomic(
        metadata_dir / "stgnn_summary.json",
        result.summary.model_dump(mode="json"),
    )
    _write_json_atomic(
        metadata_dir / "conversion_report.json",
        {
            "schema_version": result.schema_version,
            "dataset_id": result.summary.dataset_id,
            "num_samples": len(result.samples),
            "warnings": warnings,
        },
    )
    rows = [sample.model_dump(mode="json") for sample in result.samples]
    _write_parquet_atomic(index_dir / "samples.parquet", rows)


def _write_json_atomic(path: Path, payload: dict) -> None:
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    try:
        tmp_path.write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        tmp_path.replace(path)
    except Exception as exc:
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass
        raise TrainingConversionError(
            TRAINING_E_WRITE_FAILED,
            "failed to write training JSON artifact",
            details={"path": str(path), "exception_type": type(exc).__name__},
        ) from exc


def _write_parquet_atomic(path: Path, rows: list[dict]) -> None:
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    try:
        if rows:
            table = pa.Table.from_pylist(rows)
        else:
            table = pa.Table.from_pylist([{"schema_version": "1.0"}])
        pq.write_table(table, tmp_path)
        tmp_path.replace(path)
    except Exception as exc:
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass
        raise TrainingConversionError(
            TRAINING_E_WRITE_FAILED,
            "failed to write training parquet artifact",
            details={"path": str(path), "exception_type": type(exc).__name__},
        ) from exc


__all__ = ["StgnnDatasetConverter"]
