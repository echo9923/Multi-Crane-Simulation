from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Sequence

import yaml
from pydantic import ValidationError

from backend.app.schemas.dataset import (
    DATASET_E_CONFIG_INVALID,
    DATASET_E_EPISODE_DISCOVERY_FAILED,
    DATASET_E_SOURCE_NOT_FOUND,
    DatasetBuildError,
    DatasetEpisodeRecord,
    DatasetSummary,
    assert_no_secret_payload,
)

REQUIRED_TRAINING_FILES = {
    "episode_summary": "metadata/episode_summary.json",
    "episode_manifest": "visual/episode_manifest.json",
    "trajectories": "data/trajectories.parquet",
    "pair_risks": "data/pair_risks.parquet",
    "graph_edges": "data/graph_edges.parquet",
    "tasks": "data/tasks.parquet",
    "weather": "data/weather.parquet",
}

OPTIONAL_SOURCE_FILES = {
    "resolved_config": "config/resolved_config.yaml",
    "events": "logs/events.jsonl",
    "command_replay": "replay/command_replay.jsonl",
    "frames": "visual/frames.jsonl",
}

_SCENARIO_CLASSES = {
    "normal_independent",
    "overlap_safe",
    "crossing_near_miss",
    "multi_crane_yielding",
    "operation_delay",
    "poor_visibility",
    "wind_gust",
    "aggressive_operator",
    "safety_intervention",
    "easy_task",
    "overlap_task",
    "stress_task",
    "mixed_operator_profiles",
}


class DatasetCatalog:
    def __init__(self, *, dataset_root: Path | None = None) -> None:
        self.dataset_root = Path(dataset_root).resolve() if dataset_root is not None else None

    def discover_episodes(
        self,
        roots: Sequence[Path],
        *,
        max_episodes: int | None = None,
    ) -> list[DatasetEpisodeRecord]:
        records: list[DatasetEpisodeRecord] = []
        for root_input in roots:
            root = Path(root_input)
            if not root.exists():
                raise DatasetBuildError(
                    DATASET_E_SOURCE_NOT_FOUND,
                    "episode source root not found",
                    details={"source_root": str(root)},
                )
            if not root.is_dir():
                raise DatasetBuildError(
                    DATASET_E_SOURCE_NOT_FOUND,
                    "episode source root is not a directory",
                    details={"source_root": str(root)},
                )
            for child in sorted(path for path in root.iterdir() if path.is_dir()):
                if not (child / REQUIRED_TRAINING_FILES["episode_summary"]).is_file():
                    continue
                records.append(self.read_episode(child))
                if max_episodes is not None and len(records) >= max_episodes:
                    return sorted(records, key=lambda record: record.episode_id)
        return sorted(records, key=lambda record: record.episode_id)

    def read_episode(self, run_dir: Path) -> DatasetEpisodeRecord:
        run_path = Path(run_dir)
        if not run_path.is_dir():
            raise DatasetBuildError(
                DATASET_E_SOURCE_NOT_FOUND,
                "episode run directory not found",
                details={"run_dir": str(run_path)},
            )
        summary_path = run_path / REQUIRED_TRAINING_FILES["episode_summary"]
        summary = _read_json(summary_path, context="episode summary")
        manifest = _read_optional_json(
            run_path / REQUIRED_TRAINING_FILES["episode_manifest"],
            context="episode manifest",
        )
        resolved_config = _read_optional_yaml(
            run_path / OPTIONAL_SOURCE_FILES["resolved_config"],
            context="resolved config",
        )

        payload = _episode_record_payload(
            run_dir=run_path,
            summary=summary,
            manifest=manifest or {},
            resolved_config=resolved_config or {},
        )
        try:
            record = DatasetEpisodeRecord.model_validate(payload)
        except ValidationError as exc:
            raise DatasetBuildError(
                DATASET_E_EPISODE_DISCOVERY_FAILED,
                "episode record validation failed",
                details={"run_dir": str(run_path), "errors": exc.errors()},
            ) from exc
        assert_no_secret_payload(record.model_dump(mode="json"), context="episode_record")
        return record

    def read_dataset_summary(self, dataset_id: str) -> DatasetSummary:
        dataset_dir = self._dataset_dir(dataset_id)
        summary_path = dataset_dir / "metadata" / "dataset_summary.json"
        summary = _read_json(summary_path, context="dataset summary")
        assert_no_secret_payload(summary, context="dataset_summary")
        try:
            return DatasetSummary.model_validate(summary)
        except ValidationError as exc:
            raise DatasetBuildError(
                DATASET_E_CONFIG_INVALID,
                "dataset summary validation failed",
                details={"dataset_id": dataset_id, "errors": exc.errors()},
            ) from exc

    def list_datasets(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[DatasetSummary], int]:
        if self.dataset_root is None:
            raise DatasetBuildError(
                DATASET_E_SOURCE_NOT_FOUND,
                "dataset root is not configured",
                details={},
            )
        if limit < 1 or offset < 0:
            raise DatasetBuildError(
                DATASET_E_CONFIG_INVALID,
                "invalid dataset pagination",
                details={"limit": limit, "offset": offset},
            )
        if not self.dataset_root.exists():
            return [], 0
        dataset_dirs = sorted(path for path in self.dataset_root.iterdir() if path.is_dir())
        summaries: list[DatasetSummary] = []
        for path in dataset_dirs:
            summary_path = path / "metadata" / "dataset_summary.json"
            if not summary_path.is_file():
                continue
            summaries.append(self.read_dataset_summary(path.name))
        return summaries[offset : offset + limit], len(summaries)

    def _dataset_dir(self, dataset_id: str) -> Path:
        if self.dataset_root is None:
            raise DatasetBuildError(
                DATASET_E_SOURCE_NOT_FOUND,
                "dataset root is not configured",
                details={},
            )
        if "/" in dataset_id or "\\" in dataset_id or dataset_id in {"", ".", ".."}:
            raise DatasetBuildError(
                DATASET_E_SOURCE_NOT_FOUND,
                "dataset id is invalid",
                details={"dataset_id": dataset_id},
            )
        root = self.dataset_root.resolve()
        path = (root / dataset_id).resolve()
        if root not in path.parents and path != root:
            raise DatasetBuildError(
                DATASET_E_SOURCE_NOT_FOUND,
                "dataset id resolves outside dataset root",
                details={"dataset_id": dataset_id},
            )
        if not path.is_dir():
            raise DatasetBuildError(
                DATASET_E_SOURCE_NOT_FOUND,
                "dataset not found",
                details={"dataset_id": dataset_id},
            )
        return path


def _episode_record_payload(
    *,
    run_dir: Path,
    summary: dict[str, Any],
    manifest: dict[str, Any],
    resolved_config: dict[str, Any],
) -> dict[str, Any]:
    source_files = _source_files(run_dir)
    scenario_id = summary.get("scenario_id") or manifest.get("scenario_id")
    scenario_class = _scenario_class(
        summary=summary,
        manifest=manifest,
        resolved_config=resolved_config,
        scenario_id=scenario_id,
    )
    return {
        "episode_id": str(summary.get("episode_id") or manifest.get("episode_id") or run_dir.name),
        "scenario_id": scenario_id,
        "experiment_id": summary.get("experiment_id") or _nested_get(
            resolved_config,
            ("experiment", "experiment_id"),
        ),
        "run_dir": run_dir,
        "episode_status": str(summary.get("episode_status") or manifest.get("episode_status") or "unknown"),
        "duration_s": float(summary.get("duration_s", 0.0)),
        "frame_count": int(summary.get("frame_count", manifest.get("frame_count", 0))),
        "num_cranes": int(summary.get("num_cranes", _manifest_crane_count(manifest))),
        "scenario_class": scenario_class,
        "layout_hash": _layout_hash(resolved_config),
        "resolved_config_hash": summary.get("resolved_config_hash")
        or resolved_config.get("resolved_config_hash"),
        "operator_profile_distribution": dict(
            summary.get("operator_profile_distribution") or {}
        ),
        "risk_frame_ratio_by_level": dict(
            summary.get("risk_frame_ratio_by_level") or {}
        ),
        "near_miss_count": int(summary.get("near_miss_count", 0)),
        "collision_count": int(summary.get("collision_count", 0)),
        "source_files": source_files,
    }


def _source_files(run_dir: Path) -> dict[str, Path]:
    files: dict[str, Path] = {}
    for role, relative in {**REQUIRED_TRAINING_FILES, **OPTIONAL_SOURCE_FILES}.items():
        path = run_dir / relative
        if path.is_file():
            files[role] = path
    return files


def _scenario_class(
    *,
    summary: dict[str, Any],
    manifest: dict[str, Any],
    resolved_config: dict[str, Any],
    scenario_id: Any,
) -> str:
    for candidate in (
        summary.get("scenario_class"),
        manifest.get("scenario_class"),
        _nested_get(resolved_config, ("scenario", "scenario_class")),
    ):
        if isinstance(candidate, str) and candidate:
            return candidate
    if isinstance(scenario_id, str):
        normalized = scenario_id.replace("-", "_")
        for scenario_class in _SCENARIO_CLASSES:
            if scenario_class in normalized:
                return scenario_class
    return "unknown"


def _layout_hash(resolved_config: dict[str, Any]) -> str | None:
    layout = _nested_get(resolved_config, ("scenario", "layout"))
    cranes = _nested_get(resolved_config, ("scenario", "cranes"))
    if layout is None and cranes is None:
        return None
    payload = json.dumps(
        {"layout": layout, "cranes": cranes},
        sort_keys=True,
        default=str,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _manifest_crane_count(manifest: dict[str, Any]) -> int:
    cranes = manifest.get("cranes")
    return len(cranes) if isinstance(cranes, list) else 0


def _nested_get(payload: dict[str, Any], keys: tuple[str, ...]) -> Any:
    current: Any = payload
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _read_json(path: Path, *, context: str) -> dict[str, Any]:
    if not path.is_file():
        raise DatasetBuildError(
            DATASET_E_SOURCE_NOT_FOUND,
            f"{context} file not found",
            details={"path": str(path)},
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise DatasetBuildError(
            DATASET_E_EPISODE_DISCOVERY_FAILED,
            f"failed to read {context}",
            details={"path": str(path), "exception_type": type(exc).__name__},
        ) from exc
    if not isinstance(payload, dict):
        raise DatasetBuildError(
            DATASET_E_EPISODE_DISCOVERY_FAILED,
            f"{context} must be a JSON object",
            details={"path": str(path)},
        )
    return payload


def _read_optional_json(path: Path, *, context: str) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    return _read_json(path, context=context)


def _read_optional_yaml(path: Path, *, context: str) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise DatasetBuildError(
            DATASET_E_EPISODE_DISCOVERY_FAILED,
            f"failed to read {context}",
            details={"path": str(path), "exception_type": type(exc).__name__},
        ) from exc
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise DatasetBuildError(
            DATASET_E_EPISODE_DISCOVERY_FAILED,
            f"{context} must be a mapping",
            details={"path": str(path)},
        )
    return payload


__all__ = [
    "DatasetCatalog",
    "OPTIONAL_SOURCE_FILES",
    "REQUIRED_TRAINING_FILES",
]
