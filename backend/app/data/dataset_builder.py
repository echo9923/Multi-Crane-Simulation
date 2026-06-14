from __future__ import annotations

import json
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any, Sequence

import pyarrow as pa
import pyarrow.parquet as pq

from backend.app.data.catalog import DatasetCatalog
from backend.app.data.quality import DatasetQualityGate
from backend.app.data.splits import DatasetSplitPlanner
from backend.app.data.summary import build_dataset_summary
from backend.app.data.window_index import DatasetWindowIndexer
from backend.app.schemas.config import DatasetConfig
from backend.app.schemas.dataset import (
    DATASET_E_INSUFFICIENT_EPISODES,
    DATASET_E_QUALITY_FAILED,
    DATASET_E_WRITE_FAILED,
    DatasetBuildError,
    DatasetBuildOptions,
    DatasetBuildResult,
    DatasetEpisodeRecord,
    DatasetFileRecord,
    DatasetManifest,
    DatasetQualityReport,
    DatasetSplitAssignment,
    DatasetWindowIndexRow,
    assert_no_secret_payload,
)


class DatasetBuilder:
    def __init__(
        self,
        *,
        catalog: DatasetCatalog,
        quality_gate: DatasetQualityGate,
        split_planner: DatasetSplitPlanner,
        window_indexer: DatasetWindowIndexer,
    ) -> None:
        self.catalog = catalog
        self.quality_gate = quality_gate
        self.split_planner = split_planner
        self.window_indexer = window_indexer

    def build(
        self,
        *,
        config: DatasetConfig,
        options: DatasetBuildOptions,
    ) -> DatasetBuildResult:
        dataset_dir = options.output_root / config.dataset_id
        metadata_dir = dataset_dir / "metadata"
        index_dir = dataset_dir / "index"
        splits_dir = dataset_dir / "splits"
        quarantine_dir = dataset_dir / "quarantine"
        for path in (metadata_dir, index_dir, splits_dir, quarantine_dir):
            path.mkdir(parents=True, exist_ok=True)

        episodes = self.catalog.discover_episodes(options.source_roots, max_episodes=options.max_episodes)
        quality_reports = self.quality_gate.evaluate_many(episodes)
        quality_by_id = {report.episode_id: report for report in quality_reports}
        passed = [
            episode
            for episode in episodes
            if quality_by_id[episode.episode_id].quality_status != "failed"
        ]
        quarantined = [
            episode
            for episode in episodes
            if quality_by_id[episode.episode_id].quality_status == "failed"
        ]
        if options.fail_on_quality_error and quarantined:
            raise DatasetBuildError(
                DATASET_E_QUALITY_FAILED,
                "one or more episodes failed dataset quality gate",
                details={
                    "failed_episode_ids": sorted(
                        episode.episode_id for episode in quarantined
                    )
                },
            )
        if not passed:
            raise DatasetBuildError(
                DATASET_E_INSUFFICIENT_EPISODES,
                "no episodes passed dataset quality gate",
                details={"source_roots": [str(path) for path in options.source_roots]},
            )

        assignments = self.split_planner.assign(passed, quality_by_id)
        windows = self.window_indexer.build(episodes=passed, assignments=assignments)
        file_records = _file_records(
            dataset_id=config.dataset_id,
            episodes=passed,
            copy_mode=options.copy_mode,
        )
        summary = build_dataset_summary(
            config=config,
            episodes=passed,
            quarantined=quarantined,
            quality_reports=quality_reports,
            windows=windows,
            source_roots=[str(path) for path in options.source_roots],
            copy_mode=options.copy_mode,
            git_commit=_git_commit(),
        )
        split_manifest = self.split_planner.build_split_manifest(assignments, passed)
        manifest = DatasetManifest(
            dataset_id=config.dataset_id,
            created_at=summary.created_at,
            git_commit=summary.git_commit,
            source_roots=[str(path) for path in options.source_roots],
            copy_mode=options.copy_mode,
            split_strategy=config.split.strategy,
            window_config=config.windows.model_dump(mode="json"),
            config={"dataset": config.model_dump(mode="json")},
            files=file_records,
            warnings=summary.warnings,
        )

        self._write_json(metadata_dir / "dataset_summary.json", summary.model_dump(mode="json"))
        self._write_json(metadata_dir / "dataset_manifest.json", manifest.model_dump(mode="json"))
        self._write_json(metadata_dir / "quality_summary.json", _quality_summary(quality_reports))
        self._write_json(metadata_dir / "split_manifest.json", split_manifest)
        self._write_parquet(index_dir / "episodes.parquet", [episode.model_dump(mode="json") for episode in passed])
        self._write_parquet(index_dir / "windows.parquet", [row.model_dump(mode="json") for row in windows])
        self._write_parquet(index_dir / "files.parquet", [row.model_dump(mode="json") for row in file_records])
        self._write_split_files(splits_dir, assignments)
        self._write_quarantine_reports(quarantine_dir, quality_by_id, quarantined)

        return DatasetBuildResult(
            dataset_id=config.dataset_id,
            dataset_dir=dataset_dir,
            summary_path=metadata_dir / "dataset_summary.json",
            manifest_path=metadata_dir / "dataset_manifest.json",
            split_manifest_path=metadata_dir / "split_manifest.json",
            window_index_path=index_dir / "windows.parquet",
            num_episodes=len(passed),
            num_quarantined=len(quarantined),
            warnings=summary.warnings,
        )

    def _write_json(self, path: Path, payload: dict[str, Any]) -> None:
        assert_no_secret_payload(payload, context=path.name)
        try:
            path.write_text(
                json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
                encoding="utf-8",
            )
        except Exception as exc:
            raise DatasetBuildError(
                DATASET_E_WRITE_FAILED,
                "failed to write dataset JSON artifact",
                details={"path": str(path), "exception_type": type(exc).__name__},
            ) from exc

    def _write_parquet(self, path: Path, rows: list[dict[str, Any]]) -> None:
        if not rows:
            rows = [{"schema_version": "1.0"}]
        try:
            pq.write_table(pa.Table.from_pylist(_parquet_safe_rows(rows)), path)
        except Exception as exc:
            raise DatasetBuildError(
                DATASET_E_WRITE_FAILED,
                "failed to write dataset parquet artifact",
                details={"path": str(path), "exception_type": type(exc).__name__},
            ) from exc

    def _write_split_files(
        self,
        splits_dir: Path,
        assignments: Sequence[DatasetSplitAssignment],
    ) -> None:
        for split, split_assignments in _group_assignments(assignments).items():
            split_dir = splits_dir / split
            split_dir.mkdir(parents=True, exist_ok=True)
            lines = [
                json.dumps(assignment.model_dump(mode="json"), sort_keys=True)
                for assignment in split_assignments
            ]
            (split_dir / "episodes.jsonl").write_text(
                "".join(f"{line}\n" for line in lines),
                encoding="utf-8",
            )

    def _write_quarantine_reports(
        self,
        quarantine_dir: Path,
        quality_by_id: dict[str, DatasetQualityReport],
        quarantined: Sequence[DatasetEpisodeRecord],
    ) -> None:
        for episode in quarantined:
            episode_dir = quarantine_dir / episode.episode_id
            episode_dir.mkdir(parents=True, exist_ok=True)
            report = quality_by_id[episode.episode_id]
            (episode_dir / "quality_report.json").write_text(
                json.dumps(report.model_dump(mode="json"), sort_keys=True, indent=2) + "\n",
                encoding="utf-8",
            )


def _file_records(
    *,
    dataset_id: str,
    episodes: Sequence[DatasetEpisodeRecord],
    copy_mode: str,
) -> list[DatasetFileRecord]:
    records: list[DatasetFileRecord] = []
    for episode in episodes:
        for role, path in sorted(episode.source_files.items()):
            records.append(
                DatasetFileRecord(
                    dataset_id=dataset_id,
                    episode_id=episode.episode_id,
                    file_role=role,
                    path=str(path),
                    source_path=str(path),
                    copy_mode=copy_mode,  # type: ignore[arg-type]
                )
            )
    return records


def _parquet_safe_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {key: _parquet_safe_value(value) for key, value in row.items()}
        for row in rows
    ]


def _parquet_safe_value(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(_json_safe_value(value), ensure_ascii=False, sort_keys=True)
    return value


def _json_safe_value(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_safe_value(child) for key, child in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe_value(child) for child in value]
    return value


def _quality_summary(reports: Sequence[DatasetQualityReport]) -> dict[str, Any]:
    counts = Counter(report.quality_status for report in reports)
    return {
        "schema_version": "1.0",
        "quality_counts": dict(sorted(counts.items())),
        "reports": [report.model_dump(mode="json") for report in reports],
    }


def _group_assignments(
    assignments: Sequence[DatasetSplitAssignment],
) -> dict[str, list[DatasetSplitAssignment]]:
    grouped: dict[str, list[DatasetSplitAssignment]] = {}
    for assignment in assignments:
        grouped.setdefault(assignment.split, []).append(assignment)
    return grouped


def _git_commit() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            text=True,
            capture_output=True,
            check=True,
        )
    except Exception:
        return None
    return result.stdout.strip() or None


__all__ = ["DatasetBuilder"]
