from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence

import pyarrow.parquet as pq
from pydantic import ValidationError

from backend.app.schemas.dataset import (
    DatasetManifest,
    DatasetSplitManifest,
    DatasetSummary,
    DatasetWindowIndexRow,
)
from backend.app.schemas.training import (
    TRAINING_E_MANIFEST_INVALID,
    TRAINING_E_SECRET_LEAKAGE,
    TRAINING_E_SPLIT_LEAKAGE,
    TRAINING_E_WINDOWS_INVALID,
    TrainingBaseModel,
    TrainingConversionError,
    assert_no_training_secret,
)


class DatasetWindowBundle(TrainingBaseModel):
    dataset_root: Path
    dataset_id: str
    manifest: DatasetManifest
    summary: DatasetSummary
    split_assignments: dict[str, str]
    windows: list[DatasetWindowIndexRow]


class DatasetWindowReader:
    def read(self, dataset_root: Path) -> DatasetWindowBundle:
        root = Path(dataset_root)
        manifest = _read_model_json(
            root / "metadata" / "dataset_manifest.json",
            DatasetManifest,
            error_code=TRAINING_E_MANIFEST_INVALID,
            context="dataset_manifest",
        )
        summary = _read_model_json(
            root / "metadata" / "dataset_summary.json",
            DatasetSummary,
            error_code=TRAINING_E_MANIFEST_INVALID,
            context="dataset_summary",
        )
        split_manifest = _read_model_json(
            root / "metadata" / "split_manifest.json",
            DatasetSplitManifest,
            error_code=TRAINING_E_MANIFEST_INVALID,
            context="split_manifest",
        )
        _validate_manifest_consistency(manifest, summary, split_manifest)
        split_assignments = _split_assignment_map(split_manifest)
        windows = _read_windows(root / "index" / "windows.parquet")
        windows = sorted(windows, key=lambda row: (row.split, row.episode_id, row.start_frame))

        bundle = DatasetWindowBundle(
            dataset_root=root,
            dataset_id=manifest.dataset_id,
            manifest=manifest,
            summary=summary,
            split_assignments=split_assignments,
            windows=windows,
        )
        self.validate_bundle(bundle)
        return bundle

    def validate_bundle(self, bundle: DatasetWindowBundle) -> None:
        for row in bundle.windows:
            if row.dataset_id != bundle.dataset_id:
                raise TrainingConversionError(
                    TRAINING_E_WINDOWS_INVALID,
                    "window dataset_id does not match dataset manifest",
                    details={
                        "episode_id": row.episode_id,
                        "start_frame": row.start_frame,
                        "expected": bundle.dataset_id,
                        "actual": row.dataset_id,
                    },
                )
            if row.prediction_end_time_s < row.input_start_time_s:
                raise TrainingConversionError(
                    TRAINING_E_WINDOWS_INVALID,
                    "window prediction_end_time_s must be after input_start_time_s",
                    details={
                        "episode_id": row.episode_id,
                        "start_frame": row.start_frame,
                    },
                )
        self.validate_no_split_leakage(bundle.windows, bundle.split_assignments)

    def validate_no_split_leakage(
        self,
        windows: Sequence[DatasetWindowIndexRow],
        split_assignments: Mapping[str, str],
    ) -> None:
        observed: dict[str, str] = {}
        for row in windows:
            expected = split_assignments.get(row.episode_id)
            if expected is not None and row.split != expected:
                raise TrainingConversionError(
                    TRAINING_E_SPLIT_LEAKAGE,
                    "window split does not match split manifest",
                    details={
                        "episode_id": row.episode_id,
                        "expected": expected,
                        "actual": row.split,
                    },
                )
            previous = observed.get(row.episode_id)
            if previous is not None and previous != row.split:
                raise TrainingConversionError(
                    TRAINING_E_SPLIT_LEAKAGE,
                    "episode windows appear in multiple splits",
                    details={
                        "episode_id": row.episode_id,
                        "splits": sorted({previous, row.split}),
                    },
                )
            observed[row.episode_id] = row.split


def _read_model_json(
    path: Path,
    model_type: type[Any],
    *,
    error_code: str,
    context: str,
) -> Any:
    if not path.exists():
        raise TrainingConversionError(
            error_code,
            "required dataset JSON artifact is missing",
            details={"path": str(path)},
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        try:
            assert_no_training_secret(payload, context=context)
        except TrainingConversionError as exc:
            if exc.code == TRAINING_E_SECRET_LEAKAGE:
                raise
            raise
        return model_type.model_validate(payload)
    except TrainingConversionError:
        raise
    except (OSError, json.JSONDecodeError, ValidationError) as exc:
        raise TrainingConversionError(
            error_code,
            "failed to read or validate dataset JSON artifact",
            details={"path": str(path), "exception_type": type(exc).__name__},
        ) from exc


def _read_windows(path: Path) -> list[DatasetWindowIndexRow]:
    if not path.exists():
        raise TrainingConversionError(
            TRAINING_E_WINDOWS_INVALID,
            "required windows.parquet artifact is missing",
            details={"path": str(path)},
        )
    try:
        rows = pq.read_table(path).to_pylist()
    except Exception as exc:
        raise TrainingConversionError(
            TRAINING_E_WINDOWS_INVALID,
            "failed to read windows.parquet",
            details={"path": str(path), "exception_type": type(exc).__name__},
        ) from exc
    windows: list[DatasetWindowIndexRow] = []
    for index, row in enumerate(rows):
        try:
            assert_no_training_secret(row, context=f"windows[{index}]")
            windows.append(DatasetWindowIndexRow.model_validate(row))
        except TrainingConversionError:
            raise
        except ValidationError as exc:
            raise TrainingConversionError(
                TRAINING_E_WINDOWS_INVALID,
                "failed to validate window row",
                details={
                    "path": str(path),
                    "row_index": index,
                    "exception_type": type(exc).__name__,
                },
            ) from exc
    return windows


def _validate_manifest_consistency(
    manifest: DatasetManifest,
    summary: DatasetSummary,
    split_manifest: DatasetSplitManifest,
) -> None:
    expected = manifest.dataset_id
    mismatches = {
        "dataset_summary": summary.dataset_id,
        "split_manifest": split_manifest.dataset_id,
    }
    for source, actual in mismatches.items():
        if actual != expected:
            raise TrainingConversionError(
                TRAINING_E_MANIFEST_INVALID,
                "dataset metadata artifacts disagree on dataset_id",
                details={"source": source, "expected": expected, "actual": actual},
            )


def _split_assignment_map(split_manifest: DatasetSplitManifest) -> dict[str, str]:
    assignments: dict[str, str] = {}
    for assignment in split_manifest.assignments:
        previous = assignments.get(assignment.episode_id)
        if previous is not None and previous != assignment.split:
            raise TrainingConversionError(
                TRAINING_E_SPLIT_LEAKAGE,
                "split manifest assigns one episode to multiple splits",
                details={
                    "episode_id": assignment.episode_id,
                    "splits": sorted({previous, assignment.split}),
                },
            )
        assignments[assignment.episode_id] = assignment.split
    return assignments


__all__ = ["DatasetWindowBundle", "DatasetWindowReader"]
