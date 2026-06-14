from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Optional

import pyarrow as pa
import pyarrow.parquet as pq

from backend.app.schemas.dataset import DatasetWindowIndexRow
from backend.app.schemas.training import (
    TRAINING_E_LABEL_MISSING,
    TRAINING_E_SECRET_LEAKAGE,
    TRAINING_E_SOURCE_MISSING,
    TRAINING_E_SOURCE_SCHEMA_INVALID,
    TRAINING_E_TIME_AXIS_INVALID,
    TrainingBaseModel,
    TrainingConversionError,
    assert_no_training_secret,
)

REQUIRED_TRAJECTORY_FIELDS = {
    "schema_version",
    "episode_id",
    "frame",
    "time_s",
    "crane_id",
    "theta_sin",
    "theta_cos",
    "theta_dot_rad_s",
    "trolley_r_m",
    "trolley_v_m_s",
    "hook_h_m",
    "hoist_v_m_s",
    "root_x",
    "root_y",
    "root_z",
    "tip_x",
    "tip_y",
    "tip_z",
    "hook_x",
    "hook_y",
    "hook_z",
    "load_attached",
    "task_stage",
}
REQUIRED_PAIR_RISK_FIELDS = {
    "schema_version",
    "episode_id",
    "frame",
    "time_s",
    "crane_i",
    "crane_j",
    "clearance_min_now_m",
    "risk_level_now",
}


class EpisodeTables(TrainingBaseModel):
    episode_id: str
    scenario_id: Optional[str] = None
    trajectories: pa.Table
    pair_risks: pa.Table
    graph_edges: Optional[pa.Table] = None
    tasks: Optional[pa.Table] = None
    episode_summary: dict[str, Any]
    episode_manifest: dict[str, Any]
    source_paths: dict[str, Path]


class EpisodeParquetSource:
    def __init__(
        self,
        *,
        dataset_root: Path,
        allow_graph_edge_fallback: bool = False,
    ) -> None:
        self.dataset_root = Path(dataset_root)
        self.allow_graph_edge_fallback = allow_graph_edge_fallback

    def load_for_window(self, window: DatasetWindowIndexRow) -> EpisodeTables:
        source_paths = self._resolve_source_paths(window.source_paths)
        trajectories = _read_parquet(source_paths["trajectories"], role="trajectories")
        pair_risks = _read_parquet(source_paths["pair_risks"], role="pair_risks")
        graph_edges = self._optional_graph_edges(source_paths)
        tasks = _read_optional_parquet(source_paths.get("tasks"), role="tasks")
        episode_summary = _read_json(source_paths["episode_summary"], role="episode_summary")
        episode_manifest = _read_json(source_paths["episode_manifest"], role="episode_manifest")

        tables = EpisodeTables(
            episode_id=window.episode_id,
            scenario_id=window.scenario_id,
            trajectories=trajectories,
            pair_risks=pair_risks,
            graph_edges=graph_edges,
            tasks=tasks,
            episode_summary=episode_summary,
            episode_manifest=episode_manifest,
            source_paths=source_paths,
        )
        self.validate_for_window(window=window, tables=tables)
        return tables

    def validate_for_window(
        self,
        *,
        window: DatasetWindowIndexRow,
        tables: EpisodeTables,
    ) -> None:
        _require_columns(
            tables.trajectories,
            REQUIRED_TRAJECTORY_FIELDS,
            role="trajectories",
            code=TRAINING_E_SOURCE_SCHEMA_INVALID,
        )
        if not (window.num_cranes <= 1 and tables.pair_risks.num_rows == 0):
            _require_columns(
                tables.pair_risks,
                REQUIRED_PAIR_RISK_FIELDS | _required_horizon_fields(window.label_horizons_s),
                role="pair_risks",
                code=TRAINING_E_LABEL_MISSING,
            )
        _validate_json_episode_id(
            tables.episode_summary,
            window.episode_id,
            role="episode_summary",
        )
        _validate_json_episode_id(
            tables.episode_manifest,
            window.episode_id,
            role="episode_manifest",
        )
        _validate_trajectory_rows(window, tables.trajectories)
        _validate_pair_rows(window, tables.pair_risks)
        if tables.graph_edges is not None:
            _validate_graph_edges(window, tables.graph_edges)

    def _resolve_source_paths(self, source_paths: Mapping[str, str]) -> dict[str, Path]:
        required = {
            "trajectories",
            "pair_risks",
            "episode_summary",
            "episode_manifest",
        }
        missing = sorted(required - set(source_paths))
        if missing:
            raise TrainingConversionError(
                TRAINING_E_SOURCE_MISSING,
                "window source_paths is missing required roles",
                details={"missing_roles": missing},
            )
        resolved: dict[str, Path] = {}
        for role, raw_path in source_paths.items():
            path = Path(raw_path)
            if not path.is_absolute():
                path = self.dataset_root / path
            resolved[role] = path
        return resolved

    def _optional_graph_edges(
        self,
        source_paths: Mapping[str, Path],
    ) -> Optional[pa.Table]:
        path = source_paths.get("graph_edges")
        if path is None or not path.exists():
            if self.allow_graph_edge_fallback:
                return None
            raise TrainingConversionError(
                TRAINING_E_SOURCE_MISSING,
                "graph_edges source is required unless fallback is enabled",
                details={"role": "graph_edges", "path": str(path) if path else None},
            )
        return _read_parquet(path, role="graph_edges")


def _read_parquet(path: Path, *, role: str) -> pa.Table:
    if not path.exists():
        raise TrainingConversionError(
            TRAINING_E_SOURCE_MISSING,
            "episode source parquet is missing",
            details={"role": role, "path": str(path)},
        )
    try:
        table = pq.read_table(path)
        for index, row in enumerate(table.to_pylist()):
            assert_no_training_secret(row, context=f"{role}[{index}]")
        return table
    except TrainingConversionError:
        raise
    except Exception as exc:
        raise TrainingConversionError(
            TRAINING_E_SOURCE_SCHEMA_INVALID,
            "failed to read episode source parquet",
            details={"role": role, "path": str(path), "exception_type": type(exc).__name__},
        ) from exc


def _read_optional_parquet(path: Optional[Path], *, role: str) -> Optional[pa.Table]:
    if path is None or not path.exists():
        return None
    return _read_parquet(path, role=role)


def _read_json(path: Path, *, role: str) -> dict[str, Any]:
    if not path.exists():
        raise TrainingConversionError(
            TRAINING_E_SOURCE_MISSING,
            "episode source JSON is missing",
            details={"role": role, "path": str(path)},
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert_no_training_secret(payload, context=role)
        return payload
    except TrainingConversionError:
        raise
    except (OSError, json.JSONDecodeError) as exc:
        raise TrainingConversionError(
            TRAINING_E_SOURCE_SCHEMA_INVALID,
            "failed to read episode source JSON",
            details={"role": role, "path": str(path), "exception_type": type(exc).__name__},
        ) from exc


def _require_columns(
    table: pa.Table,
    required: set[str],
    *,
    role: str,
    code: str,
) -> None:
    missing = sorted(required - set(table.column_names))
    if missing:
        raise TrainingConversionError(
            code,
            "episode source table is missing required columns",
            details={"role": role, "missing_fields": missing},
        )


def _validate_json_episode_id(payload: dict[str, Any], episode_id: str, *, role: str) -> None:
    actual = payload.get("episode_id")
    if actual != episode_id:
        raise TrainingConversionError(
            TRAINING_E_SOURCE_SCHEMA_INVALID,
            "episode JSON artifact does not match window episode_id",
            details={"role": role, "expected": episode_id, "actual": actual},
        )


def _validate_trajectory_rows(window: DatasetWindowIndexRow, table: pa.Table) -> None:
    rows = table.to_pylist()
    if not rows:
        raise TrainingConversionError(
            TRAINING_E_TIME_AXIS_INVALID,
            "trajectory table is empty",
            details={"episode_id": window.episode_id},
        )
    required_frames = set(
        range(window.start_frame, window.start_frame + window.input_steps + window.pred_steps)
    )
    frames: dict[int, dict[str, float | set[str]]] = {}
    seen_pairs: set[tuple[int, str]] = set()
    for row in rows:
        if row.get("episode_id") != window.episode_id:
            raise TrainingConversionError(
                TRAINING_E_SOURCE_SCHEMA_INVALID,
                "trajectory row episode_id does not match window episode_id",
                details={
                    "expected": window.episode_id,
                    "actual": row.get("episode_id"),
                    "frame": row.get("frame"),
                },
            )
        frame = int(row["frame"])
        crane_id = str(row["crane_id"])
        key = (frame, crane_id)
        if key in seen_pairs:
            raise TrainingConversionError(
                TRAINING_E_TIME_AXIS_INVALID,
                "duplicate trajectory row for frame/crane",
                details={"episode_id": window.episode_id, "frame": frame, "crane_id": crane_id},
            )
        seen_pairs.add(key)
        frame_info = frames.setdefault(
            frame,
            {"time_s": float(row["time_s"]), "cranes": set()},
        )
        if float(row["time_s"]) != frame_info["time_s"]:
            raise TrainingConversionError(
                TRAINING_E_TIME_AXIS_INVALID,
                "trajectory rows in one frame disagree on time_s",
                details={"episode_id": window.episode_id, "frame": frame},
            )
        frame_info["cranes"].add(crane_id)  # type: ignore[union-attr]

    missing_frames = sorted(required_frames - set(frames))
    if missing_frames:
        raise TrainingConversionError(
            TRAINING_E_TIME_AXIS_INVALID,
            "trajectory table does not cover the requested window",
            details={"episode_id": window.episode_id, "missing_frames": missing_frames},
        )

    sorted_frames = sorted(frames)
    previous_time: Optional[float] = None
    reference_cranes: Optional[set[str]] = None
    for frame in sorted_frames:
        time_s = frames[frame]["time_s"]
        if previous_time is not None and float(time_s) <= previous_time:
            raise TrainingConversionError(
                TRAINING_E_TIME_AXIS_INVALID,
                "trajectory time_s must be strictly increasing by frame",
                details={"episode_id": window.episode_id, "frame": frame},
            )
        previous_time = float(time_s)
        cranes = frames[frame]["cranes"]
        if reference_cranes is None:
            reference_cranes = set(cranes)  # type: ignore[arg-type]
        elif set(cranes) != reference_cranes:  # type: ignore[arg-type]
            raise TrainingConversionError(
                TRAINING_E_TIME_AXIS_INVALID,
                "trajectory crane set changes across frames",
                details={"episode_id": window.episode_id, "frame": frame},
            )

    if reference_cranes is not None and len(reference_cranes) != window.num_cranes:
        raise TrainingConversionError(
            TRAINING_E_SOURCE_SCHEMA_INVALID,
            "trajectory crane count does not match window num_cranes",
            details={
                "episode_id": window.episode_id,
                "expected": window.num_cranes,
                "actual": len(reference_cranes),
            },
        )


def _validate_pair_rows(window: DatasetWindowIndexRow, table: pa.Table) -> None:
    rows = table.to_pylist()
    if not rows and window.num_cranes <= 1:
        return
    anchor_frame = window.start_frame + window.input_steps - 1
    has_anchor = False
    for row in rows:
        if row.get("episode_id") != window.episode_id:
            raise TrainingConversionError(
                TRAINING_E_SOURCE_SCHEMA_INVALID,
                "pair_risks row episode_id does not match window episode_id",
                details={
                    "expected": window.episode_id,
                    "actual": row.get("episode_id"),
                    "frame": row.get("frame"),
                },
            )
        if row.get("frame") == anchor_frame:
            has_anchor = True
    if window.num_cranes > 1 and not has_anchor:
        raise TrainingConversionError(
            TRAINING_E_LABEL_MISSING,
            "pair_risks does not contain the risk label anchor frame",
            details={"episode_id": window.episode_id, "anchor_frame": anchor_frame},
        )


def _validate_graph_edges(window: DatasetWindowIndexRow, table: pa.Table) -> None:
    _require_columns(
        table,
        {"schema_version", "episode_id", "frame", "time_s", "src_crane_id", "dst_crane_id"},
        role="graph_edges",
        code=TRAINING_E_SOURCE_SCHEMA_INVALID,
    )
    for row in table.to_pylist():
        if row.get("episode_id") != window.episode_id:
            raise TrainingConversionError(
                TRAINING_E_SOURCE_SCHEMA_INVALID,
                "graph_edges row episode_id does not match window episode_id",
                details={
                    "expected": window.episode_id,
                    "actual": row.get("episode_id"),
                    "frame": row.get("frame"),
                },
            )


def _required_horizon_fields(horizons_s: list[float]) -> set[str]:
    fields: set[str] = set()
    for horizon in horizons_s:
        suffix = _horizon_suffix(horizon)
        fields.update(
            {
                f"risk_level_{suffix}",
                f"collision_label_{suffix}",
                f"min_clearance_future_{suffix}_m",
                f"ttc_{suffix}_s",
            }
        )
    return fields


def _horizon_suffix(horizon: float) -> str:
    if horizon.is_integer():
        return f"{int(horizon)}s"
    return f"{horizon:g}s"


__all__ = [
    "EpisodeTables",
    "EpisodeParquetSource",
    "REQUIRED_TRAJECTORY_FIELDS",
    "REQUIRED_PAIR_RISK_FIELDS",
]
