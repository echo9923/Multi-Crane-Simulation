from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Literal, Mapping, Optional, Sequence, Type

import pyarrow as pa
import pyarrow.parquet as pq
import yaml
from pydantic import BaseModel, ValidationError

from backend.app.schemas.recorder import (
    RECORDER_SCHEMA_VERSION,
    CommandLogEntry,
    DataExportWarning,
    DecisionLogEntry,
    EventLogEntry,
    EpisodeManifest,
    EpisodeSummary,
    GraphEdgeRow,
    InterventionLogEntry,
    ObservationLogEntry,
    OfflineFrameLabels,
    PairRiskRow,
    RecorderBaseModel,
    SimFrame,
    SimFrameCrane,
    SimFramePair,
    SimFrameWeather,
    TaskParquetRow,
    TrajectoryRow,
    WeatherParquetRow,
)
from backend.app.schemas.risk import OfflineRiskLabel
from backend.app.schemas.resolved_config import ResolvedConfig
from backend.app.schemas.state import CraneState
from backend.app.schemas.weather import WeatherState

FORBIDDEN_EXPORT_SECRET_KEYS = {
    "api_key",
    "resolved_full_api_key",
    "raw_api_key",
    "secret",
    "token",
    "authorization",
}

ALLOWED_MASKED_SECRET_KEYS = {"key_source", "key_env_name", "key_masked"}


class DataExportError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        error_code: str,
        category: Literal["data_export_error"] = "data_export_error",
        episode_id: Optional[str] = None,
        frame: Optional[int] = None,
        file_path: Optional[str] = None,
        field_path: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.category = category
        self.episode_id = episode_id
        self.frame = frame
        self.file_path = file_path
        self.field_path = field_path
        self.details = details or {}


@dataclass(frozen=True)
class RunDirectoryLayout:
    run_root: Path
    config_dir: Path
    metadata_dir: Path
    logs_dir: Path
    data_dir: Path
    replay_dir: Path
    visual_dir: Path
    resolved_config_path: Path
    scenario_config_path: Path
    experiment_config_path: Path
    dataset_config_path: Path
    episode_metadata_path: Path
    episode_summary_path: Path
    dataset_summary_path: Path
    episode_manifest_path: Path
    frames_jsonl_path: Path
    trajectories_path: Path
    pair_risks_path: Path
    graph_edges_path: Path
    tasks_path: Path
    weather_path: Path
    observations_path: Path
    decisions_path: Path
    commands_path: Path
    interventions_path: Path
    events_path: Path


def init_run_directory(
    *,
    config: object,
    episode_id: str,
    scenario_id: Optional[str] = None,
    run_root_override: Optional[Path] = None,
) -> RunDirectoryLayout:
    resolved_config = _coerce_resolved_config(config)
    layout = _build_layout(
        resolved_config=resolved_config,
        episode_id=episode_id,
        run_root_override=run_root_override,
    )
    try:
        for directory in [
            layout.config_dir,
            layout.metadata_dir,
            layout.logs_dir,
            layout.data_dir,
            layout.replay_dir,
            layout.visual_dir,
        ]:
            directory.mkdir(parents=True, exist_ok=True)
        _write_config_files(layout, resolved_config)
        _write_episode_metadata(
            layout,
            resolved_config=resolved_config,
            episode_id=episode_id,
            scenario_id=scenario_id or _scenario_id_from_config(resolved_config),
        )
    except OSError as exc:
        raise DataExportError(
            "failed to initialize recorder run directory",
            error_code="RECORDER_E_RUN_DIRECTORY",
            episode_id=episode_id,
            file_path=str(layout.run_root),
            details={"exception_type": type(exc).__name__, "reason": str(exc)},
        ) from exc
    return layout


class ParquetTableWriter:
    def __init__(
        self,
        *,
        output_path: Path,
        row_model: Type[RecorderBaseModel],
    ) -> None:
        self.output_path = output_path
        self.row_model = row_model
        self._rows: List[Dict[str, Any]] = []
        self.warnings: List[DataExportWarning] = []

    def append(
        self,
        rows: Sequence[RecorderBaseModel],
    ) -> None:
        for index, row in enumerate(rows):
            row_payload = _model_or_mapping_to_dict(row)
            sanitized = _sanitize_for_export(
                row_payload,
                file_name=str(self.output_path),
                warning_sink=self.warnings,
            )
            try:
                validated = self.row_model.model_validate(sanitized)
            except ValidationError as exc:
                raise DataExportError(
                    "invalid parquet row",
                    error_code="RECORDER_E_PARQUET_SCHEMA",
                    file_path=str(self.output_path),
                    field_path=str(index),
                    details={"errors": exc.errors()},
                ) from exc
            self._rows.append(validated.model_dump(mode="json"))

    def flush(self) -> None:
        if not self._rows:
            return
        tmp_path = self.output_path.with_name(f".{self.output_path.name}.tmp")
        try:
            table = pa.Table.from_pylist(self._rows)
            pq.write_table(table, tmp_path)
            tmp_path.replace(self.output_path)
        except Exception as exc:
            try:
                tmp_path.unlink()
            except OSError:
                pass
            raise DataExportError(
                "failed to write parquet table",
                error_code="RECORDER_E_PARQUET_WRITE",
                file_path=str(self.output_path),
                details={"exception_type": type(exc).__name__, "reason": str(exc)},
            ) from exc

    def close(self) -> None:
        self.flush()


class RecorderParquetWriters:
    def __init__(
        self,
        *,
        trajectories: ParquetTableWriter,
        pair_risks: ParquetTableWriter,
        graph_edges: ParquetTableWriter,
        tasks: ParquetTableWriter,
        weather: ParquetTableWriter,
    ) -> None:
        self.trajectories = trajectories
        self.pair_risks = pair_risks
        self.graph_edges = graph_edges
        self.tasks = tasks
        self.weather = weather

    @classmethod
    def from_layout(cls, layout: RunDirectoryLayout) -> "RecorderParquetWriters":
        return cls(
            trajectories=ParquetTableWriter(
                output_path=layout.trajectories_path,
                row_model=TrajectoryRow,
            ),
            pair_risks=ParquetTableWriter(
                output_path=layout.pair_risks_path,
                row_model=PairRiskRow,
            ),
            graph_edges=ParquetTableWriter(
                output_path=layout.graph_edges_path,
                row_model=GraphEdgeRow,
            ),
            tasks=ParquetTableWriter(
                output_path=layout.tasks_path,
                row_model=TaskParquetRow,
            ),
            weather=ParquetTableWriter(
                output_path=layout.weather_path,
                row_model=WeatherParquetRow,
            ),
        )

    @property
    def warnings(self) -> List[DataExportWarning]:
        return [
            *self.trajectories.warnings,
            *self.pair_risks.warnings,
            *self.graph_edges.warnings,
            *self.tasks.warnings,
            *self.weather.warnings,
        ]

    def write_trajectories(self, rows: Sequence[Any]) -> None:
        self.trajectories.append(rows)

    def write_pair_risks(self, rows: Sequence[Any]) -> None:
        self.pair_risks.append(rows)

    def write_graph_edges(self, rows: Sequence[Any]) -> None:
        self.graph_edges.append(rows)

    def write_tasks(self, rows: Sequence[Any]) -> None:
        self.tasks.append(rows)

    def write_weather(self, rows: Sequence[Any]) -> None:
        self.weather.append(rows)

    def flush_all(self) -> None:
        self.trajectories.flush()
        self.pair_risks.flush()
        self.graph_edges.flush()
        self.tasks.flush()
        self.weather.flush()

    def close_all(self) -> None:
        self.flush_all()


class JsonlWriter:
    def __init__(
        self,
        *,
        output_path: Path,
        row_model: Type[RecorderBaseModel],
    ) -> None:
        self.output_path = output_path
        self.row_model = row_model
        self._rows: List[Dict[str, Any]] = []
        self.warnings: List[DataExportWarning] = []

    def append(self, rows: Sequence[Any]) -> None:
        for index, row in enumerate(rows):
            row_payload = _model_or_mapping_to_dict(row)
            secret_path = _find_forbidden_secret_key(row_payload)
            if secret_path is not None:
                raise DataExportError(
                    "refusing to write secret-bearing JSONL payload",
                    error_code="RECORDER_E_SECRET_FIELD",
                    file_path=str(self.output_path),
                    field_path=secret_path,
                )
            sanitized = _sanitize_for_export(
                row_payload,
                file_name=str(self.output_path),
                warning_sink=self.warnings,
            )
            try:
                validated = self.row_model.model_validate(sanitized)
            except ValidationError as exc:
                raise DataExportError(
                    "invalid JSONL row",
                    error_code="RECORDER_E_JSONL_SCHEMA",
                    file_path=str(self.output_path),
                    field_path=str(index),
                    details={"errors": exc.errors()},
                ) from exc
            self._rows.append(validated.model_dump(mode="json"))

    def flush(self) -> None:
        if not self._rows:
            return
        try:
            self.output_path.parent.mkdir(parents=True, exist_ok=True)
            with self.output_path.open("w", encoding="utf-8") as handle:
                for row in self._rows:
                    handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True))
                    handle.write("\n")
        except (OSError, TypeError, ValueError) as exc:
            raise DataExportError(
                "failed to write JSONL file",
                error_code="RECORDER_E_JSONL_WRITE",
                file_path=str(self.output_path),
                details={"exception_type": type(exc).__name__, "reason": str(exc)},
            ) from exc

    def close(self) -> None:
        self.flush()


class RecorderJsonlWriters:
    def __init__(
        self,
        *,
        observations: JsonlWriter,
        decisions: JsonlWriter,
        commands: JsonlWriter,
        interventions: JsonlWriter,
        events: JsonlWriter,
    ) -> None:
        self.observations = observations
        self.decisions = decisions
        self.commands = commands
        self.interventions = interventions
        self.events = events

    @classmethod
    def from_layout(cls, layout: RunDirectoryLayout) -> "RecorderJsonlWriters":
        return cls(
            observations=JsonlWriter(
                output_path=layout.observations_path,
                row_model=ObservationLogEntry,
            ),
            decisions=JsonlWriter(
                output_path=layout.decisions_path,
                row_model=DecisionLogEntry,
            ),
            commands=JsonlWriter(
                output_path=layout.commands_path,
                row_model=CommandLogEntry,
            ),
            interventions=JsonlWriter(
                output_path=layout.interventions_path,
                row_model=InterventionLogEntry,
            ),
            events=JsonlWriter(
                output_path=layout.events_path,
                row_model=EventLogEntry,
            ),
        )

    @property
    def warnings(self) -> List[DataExportWarning]:
        return [
            *self.observations.warnings,
            *self.decisions.warnings,
            *self.commands.warnings,
            *self.interventions.warnings,
            *self.events.warnings,
        ]

    def write_observations(self, rows: Sequence[Any]) -> None:
        self.observations.append(rows)

    def write_decisions(self, rows: Sequence[Any]) -> None:
        self.decisions.append(rows)

    def write_commands(self, rows: Sequence[Any]) -> None:
        self.commands.append(rows)

    def write_interventions(self, rows: Sequence[Any]) -> None:
        self.interventions.append(rows)

    def write_events(self, rows: Sequence[Any]) -> None:
        self.events.append(rows)

    def flush_all(self) -> None:
        self.observations.flush()
        self.decisions.flush()
        self.commands.flush()
        self.interventions.flush()
        self.events.flush()

    def close_all(self) -> None:
        self.flush_all()


def build_sim_frame(
    *,
    episode_id: str,
    scenario_id: Optional[str],
    frame_index: int,
    time_s: float,
    episode_status: object,
    states: Sequence[CraneState],
    weather_state: WeatherState,
    commands: Optional[Mapping[str, Any]] = None,
    pairs: Sequence[Any] = (),
    tasks: Sequence[Any] = (),
    task_queues: Sequence[Any] = (),
    events: Sequence[Any] = (),
    offline_labels: Sequence[OfflineRiskLabel] = (),
    for_realtime: bool = False,
) -> SimFrame:
    if for_realtime and offline_labels:
        raise DataExportError(
            "realtime SimFrame must not include offline labels",
            error_code="RECORDER_E_OFFLINE_LABEL_LEAK",
            episode_id=episode_id,
            frame=frame_index,
            field_path="offline_labels",
        )
    command_map = dict(commands or {})
    frame = SimFrame(
        episode_id=episode_id,
        scenario_id=scenario_id,
        frame=frame_index,
        time_s=time_s,
        episode_status=_enum_or_value(episode_status),
        cranes=[
            _sim_frame_crane_from_state(state, command_map.get(state.crane_id))
            for state in states
        ],
        pairs=[_sim_frame_pair_from_any(pair) for pair in pairs],
        tasks=[_dump_for_json(task) for task in [*tasks, *task_queues]],
        weather=_sim_frame_weather_from_state(weather_state),
        events=[_dump_for_json(event) for event in events],
        offline_labels=(
            OfflineFrameLabels(
                pair_labels=[
                    _offline_label_to_frame_payload(label) for label in offline_labels
                ]
            )
            if offline_labels
            else None
        ),
    )
    return frame


def build_episode_manifest(
    *,
    episode_id: str,
    scenario_id: Optional[str],
    episode_status: object,
    frame_count: int,
    dt_s: float,
    crane_configs: Sequence[Any],
    resolved_config: Optional[object] = None,
    offline_labels_available: bool = False,
) -> EpisodeManifest:
    resolved_payload = (
        _dump_for_json(resolved_config) if resolved_config is not None else {}
    )
    return EpisodeManifest(
        episode_id=episode_id,
        scenario_id=scenario_id,
        episode_status=_enum_or_value(episode_status),
        frame_count=frame_count,
        dt=dt_s,
        coordinate_system="ENU",
        cranes=[_dump_for_json(config) for config in crane_configs],
        site=resolved_payload.get("scenario", {}).get("site", {})
        if isinstance(resolved_payload, dict)
        else {},
        material_zones=resolved_payload.get("scenario", {})
        .get("site", {})
        .get("material_zones", [])
        if isinstance(resolved_payload, dict)
        else [],
        work_zones=resolved_payload.get("scenario", {})
        .get("site", {})
        .get("work_zones", [])
        if isinstance(resolved_payload, dict)
        else [],
        forbidden_zones=resolved_payload.get("scenario", {})
        .get("site", {})
        .get("forbidden_zones", [])
        if isinstance(resolved_payload, dict)
        else [],
        overlap_zones=resolved_payload.get("scenario", {})
        .get("site", {})
        .get("overlap_zones", [])
        if isinstance(resolved_payload, dict)
        else [],
        offline_labels_available=offline_labels_available,
    )


class VisualFrameWriter:
    def __init__(self, *, frames_path: Path, manifest_path: Path) -> None:
        self.frames_path = frames_path
        self.manifest_path = manifest_path
        self._frames: List[Dict[str, Any]] = []
        self._manifest: Optional[Dict[str, Any]] = None

    def append_frame(self, frame: SimFrame) -> None:
        self._frames.append(frame.model_dump(mode="json"))

    def write_manifest(self, manifest: EpisodeManifest) -> None:
        self._manifest = manifest.model_dump(mode="json")

    def flush(self) -> None:
        try:
            self.frames_path.parent.mkdir(parents=True, exist_ok=True)
            if self._frames:
                with self.frames_path.open("w", encoding="utf-8") as handle:
                    for frame in self._frames:
                        handle.write(
                            json.dumps(frame, ensure_ascii=False, sort_keys=True)
                        )
                        handle.write("\n")
            if self._manifest is not None:
                self.manifest_path.parent.mkdir(parents=True, exist_ok=True)
                self.manifest_path.write_text(
                    json.dumps(
                        self._manifest,
                        ensure_ascii=False,
                        sort_keys=True,
                        indent=2,
                    ),
                    encoding="utf-8",
                )
        except OSError as exc:
            raise DataExportError(
                "failed to write visual recorder files",
                error_code="RECORDER_E_VISUAL_WRITE",
                file_path=str(self.frames_path),
                details={"exception_type": type(exc).__name__, "reason": str(exc)},
            ) from exc

    def close(self) -> None:
        self.flush()


def build_episode_summary(
    *,
    episode_id: str,
    scenario_id: Optional[str],
    episode_status: object,
    duration_s: float,
    num_cranes: int,
    tasks: Sequence[Any],
    pair_risk_rows: Sequence[Any] = (),
    command_logs: Sequence[Any] = (),
    event_logs: Sequence[Any] = (),
    warnings: Sequence[Any] = (),
    state_jump_max_m: Optional[float] = None,
    replay_available: bool = False,
    dt_s: float = 0.0,
) -> EpisodeSummary:
    task_rows = [_validate_summary_row(TaskParquetRow, task) for task in tasks]
    pair_rows = [_validate_summary_row(PairRiskRow, row) for row in pair_risk_rows]
    command_rows = [
        _validate_summary_row(CommandLogEntry, row) for row in command_logs
    ]
    event_rows = [_validate_summary_row(EventLogEntry, row) for row in event_logs]
    warning_rows = [
        warning
        if isinstance(warning, DataExportWarning)
        else DataExportWarning.model_validate(warning)
        for warning in warnings
    ]

    total_tasks = len(task_rows)
    completed_tasks = sum(1 for task in task_rows if task.status == "completed")
    failed_tasks = sum(1 for task in task_rows if task.status == "failed")
    completed_durations = [
        task.completed_time_s - task.actual_start_s
        for task in task_rows
        if task.status == "completed"
        and task.completed_time_s is not None
        and task.actual_start_s is not None
    ]
    overtime_values = [task.overtime_s for task in task_rows]

    risk_counts: Dict[str, int] = {}
    clearances: List[float] = []
    high_risk_rows = 0
    for row in pair_rows:
        if row.risk_level_now:
            risk_counts[row.risk_level_now] = risk_counts.get(row.risk_level_now, 0) + 1
            if row.risk_level_now in {"high", "near_miss", "collision"}:
                high_risk_rows += 1
        if row.clearance_min_now_m is not None:
            clearances.append(row.clearance_min_now_m)
    risk_total = sum(risk_counts.values())
    risk_ratio = (
        {level: count / risk_total for level, count in risk_counts.items()}
        if risk_total
        else {}
    )

    event_type_counts: Dict[str, int] = {}
    for event in event_rows:
        event_type_counts[event.event_type] = event_type_counts.get(event.event_type, 0) + 1

    latencies = [
        command.latency_ms
        for command in command_rows
        if command.latency_ms is not None
    ]
    profile_distribution: Dict[str, int] = {}
    for command in command_rows:
        if command.operator_profile:
            profile_distribution[command.operator_profile] = (
                profile_distribution.get(command.operator_profile, 0) + 1
            )

    has_nan = any(warning.warning_type == "nan_to_null" for warning in warning_rows)
    has_inf = any(warning.warning_type == "inf_to_null" for warning in warning_rows)

    return EpisodeSummary(
        episode_id=episode_id,
        scenario_id=scenario_id,
        episode_status=_enum_or_value(episode_status),
        duration_s=duration_s,
        num_cranes=num_cranes,
        num_tasks_total=total_tasks,
        num_tasks_completed=completed_tasks,
        num_tasks_failed=failed_tasks,
        task_completion_rate=completed_tasks / total_tasks if total_tasks else 0.0,
        mean_task_duration_s=(
            sum(completed_durations) / len(completed_durations)
            if completed_durations
            else None
        ),
        deadline_missed_count=sum(1 for task in task_rows if task.deadline_missed),
        overtime_mean_s=(
            sum(overtime_values) / len(overtime_values) if overtime_values else 0.0
        ),
        risk_frame_ratio_by_level=risk_ratio,
        near_miss_count=event_type_counts.get("near_miss", 0),
        collision_count=event_type_counts.get("collision", 0),
        min_clearance_over_episode=min(clearances) if clearances else None,
        high_risk_duration_s=high_risk_rows * dt_s,
        num_llm_calls=len(command_rows),
        llm_invalid_output_count=sum(
            1 for command in command_rows if command.validation_errors
        )
        + event_type_counts.get("llm_invalid_output", 0),
        llm_timeout_count=event_type_counts.get("llm_timeout", 0),
        mean_latency_ms=sum(latencies) / len(latencies) if latencies else None,
        cache_hit_count=sum(1 for command in command_rows if command.cache_hit),
        operator_profile_distribution=profile_distribution,
        ignored_risk_hint_count=event_type_counts.get("ignored_risk_hint", 0),
        emergency_stop_count=event_type_counts.get("emergency_stop_triggered", 0),
        forbidden_zone_violation_count=event_type_counts.get(
            "forbidden_zone_violation", 0
        ),
        overlap_zone_shared_count=event_type_counts.get("overlap_zone_shared", 0),
        has_nan=has_nan,
        has_inf=has_inf,
        max_state_jump=state_jump_max_m,
        replay_available=replay_available,
        warnings=list(warning_rows),
    )


def write_episode_summary(
    *,
    layout: RunDirectoryLayout,
    summary: EpisodeSummary,
) -> None:
    try:
        layout.episode_summary_path.write_text(
            json.dumps(
                summary.model_dump(mode="json"),
                ensure_ascii=False,
                sort_keys=True,
                indent=2,
            ),
            encoding="utf-8",
        )
        metadata = {}
        if layout.episode_metadata_path.exists():
            metadata = json.loads(
                layout.episode_metadata_path.read_text(encoding="utf-8")
            )
        metadata["episode_status"] = summary.episode_status
        metadata["updated_at"] = datetime.now(timezone.utc).isoformat()
        files = dict(metadata.get("files", {}))
        files["episode_summary"] = "metadata/episode_summary.json"
        metadata["files"] = files
        layout.episode_metadata_path.write_text(
            json.dumps(metadata, ensure_ascii=False, sort_keys=True, indent=2),
            encoding="utf-8",
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise DataExportError(
            "failed to write episode summary",
            error_code="RECORDER_E_SUMMARY_WRITE",
            episode_id=summary.episode_id,
            file_path=str(layout.episode_summary_path),
            details={"exception_type": type(exc).__name__, "reason": str(exc)},
        ) from exc


def _coerce_resolved_config(config: object) -> ResolvedConfig:
    if isinstance(config, ResolvedConfig):
        return config
    if isinstance(config, Mapping):
        return ResolvedConfig.model_validate(config)
    if hasattr(config, "model_dump"):
        return ResolvedConfig.model_validate(config.model_dump(mode="json"))
    raise DataExportError(
        "recorder requires a ResolvedConfig-compatible object",
        error_code="RECORDER_E_INVALID_CONFIG",
        field_path="config",
    )


def _build_layout(
    *,
    resolved_config: ResolvedConfig,
    episode_id: str,
    run_root_override: Optional[Path],
) -> RunDirectoryLayout:
    root = Path(
        run_root_override or resolved_config.output.run_root
    ).expanduser().resolve()
    run_root = root / episode_id
    config_dir = run_root / "config"
    metadata_dir = run_root / "metadata"
    logs_dir = run_root / "logs"
    data_dir = run_root / "data"
    replay_dir = run_root / "replay"
    visual_dir = run_root / "visual"
    return RunDirectoryLayout(
        run_root=run_root,
        config_dir=config_dir,
        metadata_dir=metadata_dir,
        logs_dir=logs_dir,
        data_dir=data_dir,
        replay_dir=replay_dir,
        visual_dir=visual_dir,
        resolved_config_path=config_dir / "resolved_config.yaml",
        scenario_config_path=config_dir / "scenario.yaml",
        experiment_config_path=config_dir / "experiment.yaml",
        dataset_config_path=config_dir / "dataset.yaml",
        episode_metadata_path=metadata_dir / "episode_metadata.json",
        episode_summary_path=metadata_dir / "episode_summary.json",
        dataset_summary_path=metadata_dir / "dataset_summary.json",
        episode_manifest_path=visual_dir / "episode_manifest.json",
        frames_jsonl_path=visual_dir / "frames.jsonl",
        trajectories_path=data_dir / "trajectories.parquet",
        pair_risks_path=data_dir / "pair_risks.parquet",
        graph_edges_path=data_dir / "graph_edges.parquet",
        tasks_path=data_dir / "tasks.parquet",
        weather_path=data_dir / "weather.parquet",
        observations_path=logs_dir / "llm_observations.jsonl",
        decisions_path=logs_dir / "llm_decisions.jsonl",
        commands_path=logs_dir / "commands.jsonl",
        interventions_path=logs_dir / "interventions.jsonl",
        events_path=logs_dir / "events.jsonl",
    )


def _write_config_files(
    layout: RunDirectoryLayout,
    resolved_config: ResolvedConfig,
) -> None:
    payload = resolved_config.model_dump(mode="json")
    _write_yaml(layout.resolved_config_path, payload)
    _write_yaml(layout.scenario_config_path, resolved_config.scenario)
    _write_yaml(layout.experiment_config_path, resolved_config.experiment)
    if resolved_config.dataset is not None:
        _write_yaml(layout.dataset_config_path, resolved_config.dataset)


def _write_yaml(path: Path, payload: object) -> None:
    path.write_text(
        yaml.safe_dump(payload, sort_keys=True, allow_unicode=True),
        encoding="utf-8",
    )


def _write_episode_metadata(
    layout: RunDirectoryLayout,
    *,
    resolved_config: ResolvedConfig,
    episode_id: str,
    scenario_id: Optional[str],
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    existing_created_at = now
    if layout.episode_metadata_path.exists():
        try:
            existing = json.loads(
                layout.episode_metadata_path.read_text(encoding="utf-8")
            )
            existing_created_at = existing.get("created_at", now)
        except (OSError, json.JSONDecodeError):
            existing_created_at = now
    metadata = {
        "schema_version": RECORDER_SCHEMA_VERSION,
        "episode_id": episode_id,
        "scenario_id": scenario_id,
        "episode_status": "running",
        "resolved_config_hash": resolved_config.resolved_config_hash,
        "created_at": existing_created_at,
        "updated_at": now,
        "files": {
            "trajectories": "data/trajectories.parquet",
            "pair_risks": "data/pair_risks.parquet",
            "graph_edges": "data/graph_edges.parquet",
            "tasks": "data/tasks.parquet",
            "weather": "data/weather.parquet",
            "frames": "visual/frames.jsonl",
            "episode_manifest": "visual/episode_manifest.json",
            "commands": "logs/commands.jsonl",
            "events": "logs/events.jsonl",
            "llm_observations": "logs/llm_observations.jsonl",
            "llm_decisions": "logs/llm_decisions.jsonl",
            "interventions": "logs/interventions.jsonl",
        },
        "warnings": [],
    }
    layout.episode_metadata_path.write_text(
        json.dumps(metadata, ensure_ascii=False, sort_keys=True, indent=2),
        encoding="utf-8",
    )


def _scenario_id_from_config(resolved_config: ResolvedConfig) -> Optional[str]:
    scenario = resolved_config.scenario
    value = scenario.get("scenario_id") if isinstance(scenario, dict) else None
    return str(value) if value is not None else None


def _sim_frame_crane_from_state(
    state: CraneState,
    command: Optional[Any],
) -> SimFrameCrane:
    return SimFrameCrane(
        crane_id=state.crane_id,
        base=(
            float(state.root_position[0]),
            float(state.root_position[1]),
            0.0,
        ),
        root=_xyz_tuple(state.root_position),
        tip=_xyz_tuple(state.tip_position),
        hook=_xyz_tuple(state.hook_position),
        theta_rad=state.theta_rad,
        trolley_r_m=state.trolley_r_m,
        hook_h_m=state.hook_h_m,
        load_attached=state.load_attached,
        load_type=state.load_type,
        load_size_m=_optional_xyz_tuple(state.load_size_m),
        task_id=state.task_id,
        task_stage=state.task_stage,
        current_command=_command_for_frame(command),
    )


def _sim_frame_weather_from_state(weather_state: WeatherState) -> SimFrameWeather:
    return SimFrameWeather(
        wind_speed_m_s=weather_state.wind_speed_m_s,
        wind_gust_m_s=weather_state.wind_gust_m_s,
        wind_direction_deg=weather_state.wind_direction_deg,
        visibility=_enum_or_value(weather_state.visibility_level),
        rain_level=_enum_or_value(weather_state.rain_level),
        fog_level=_enum_or_value(weather_state.fog_level),
    )


def _sim_frame_pair_from_any(pair: Any) -> SimFramePair:
    payload = _dump_for_json(pair)
    if not isinstance(payload, dict):
        raise DataExportError(
            "SimFrame pair must be a mapping-like object",
            error_code="RECORDER_E_SIM_FRAME_PAIR",
        )
    return SimFramePair(
        crane_i=payload.get("crane_i") or payload.get("crane_id_a"),
        crane_j=payload.get("crane_j") or payload.get("crane_id_b"),
        distance_min_raw_now_m=payload.get("distance_min_raw_now_m")
        or payload.get("d_min_online_m"),
        clearance_min_now_m=payload.get("clearance_min_now_m"),
        risk_level_now=payload.get("risk_level_now") or payload.get("risk_level"),
    )


def _offline_label_to_frame_payload(label: OfflineRiskLabel) -> Dict[str, Any]:
    payload = label.model_dump(mode="json")
    label_15s = payload.get("future_window_labels", {}).get("15s")
    return {
        "crane_i": payload["crane_i"],
        "crane_j": payload["crane_j"],
        "frame": payload["frame"],
        "time_s": payload["time_s"],
        "min_clearance_future_5s_m": payload.get("min_clearance_future_5s_m"),
        "min_clearance_future_10s_m": payload.get("min_clearance_future_10s_m"),
        "min_clearance_future_15s_m": (
            label_15s.get("min_clearance_future_m")
            if isinstance(label_15s, dict)
            else None
        ),
        "risk_level_5s": payload.get("risk_level_5s"),
        "risk_level_10s": payload.get("risk_level_10s"),
        "risk_level_15s": (
            label_15s.get("risk_level") if isinstance(label_15s, dict) else None
        ),
        "collision_label_5s": payload.get("collision_label_5s"),
        "collision_label_10s": payload.get("collision_label_10s"),
        "collision_label_15s": (
            label_15s.get("collision_label") if isinstance(label_15s, dict) else None
        ),
    }


def _command_for_frame(command: Optional[Any]) -> Optional[Dict[str, Any]]:
    if command is None:
        return None
    payload = _dump_for_json(command)
    if not isinstance(payload, dict):
        return None
    return {
        key: payload[key]
        for key in [
            "left_joystick",
            "right_joystick",
            "deadman_pressed",
            "emergency_stop",
            "horn",
            "command_duration_s",
            "task_action",
        ]
        if key in payload
    }


def _xyz_tuple(values: Sequence[float]) -> tuple:
    return (float(values[0]), float(values[1]), float(values[2]))


def _optional_xyz_tuple(values: Optional[Sequence[float]]) -> Optional[tuple]:
    if values is None:
        return None
    return _xyz_tuple(values)


def _dump_for_json(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, Mapping):
        return {
            str(key): _dump_for_json(child)
            for key, child in value.items()
        }
    if isinstance(value, list):
        return [_dump_for_json(child) for child in value]
    if isinstance(value, tuple):
        return [_dump_for_json(child) for child in value]
    return _enum_or_value(value)


def _enum_or_value(value: Any) -> Any:
    return getattr(value, "value", value)


def _model_or_mapping_to_dict(row: object) -> Dict[str, Any]:
    if isinstance(row, BaseModel):
        return row.model_dump(mode="json")
    if isinstance(row, Mapping):
        return dict(row)
    raise DataExportError(
        "parquet row must be a Pydantic model or mapping",
        error_code="RECORDER_E_PARQUET_ROW_TYPE",
        details={"row_type": type(row).__name__},
    )


def _validate_summary_row(
    row_model: Type[RecorderBaseModel],
    row: Any,
) -> RecorderBaseModel:
    try:
        return row_model.model_validate(_model_or_mapping_to_dict(row))
    except ValidationError as exc:
        raise DataExportError(
            "invalid summary input row",
            error_code="RECORDER_E_SUMMARY_SCHEMA",
            details={"errors": exc.errors(), "row_model": row_model.__name__},
        ) from exc


def _sanitize_for_export(
    value: Any,
    *,
    file_name: str,
    warning_sink: List[DataExportWarning],
    field_path: str = "",
) -> Any:
    if isinstance(value, float) and not math.isfinite(value):
        warning_type = "nan_to_null" if math.isnan(value) else "inf_to_null"
        warning_sink.append(
            DataExportWarning(
                warning_id=f"warning-{len(warning_sink) + 1:06d}",
                file_name=file_name,
                field_path=field_path or None,
                warning_type=warning_type,
                message=f"converted non-finite float to null at {field_path}",
            )
        )
        return None
    if isinstance(value, dict):
        return {
            key: _sanitize_for_export(
                child,
                file_name=file_name,
                warning_sink=warning_sink,
                field_path=f"{field_path}.{key}" if field_path else str(key),
            )
            for key, child in value.items()
        }
    if isinstance(value, list):
        return [
            _sanitize_for_export(
                child,
                file_name=file_name,
                warning_sink=warning_sink,
                field_path=f"{field_path}[{index}]",
            )
            for index, child in enumerate(value)
        ]
    return value


def _find_forbidden_secret_key(value: Any, path: str = "") -> Optional[str]:
    if isinstance(value, dict):
        for key, child in value.items():
            key_text = str(key)
            current_path = f"{path}.{key_text}" if path else key_text
            key_lower = key_text.lower()
            if (
                key_lower in FORBIDDEN_EXPORT_SECRET_KEYS
                and key_lower not in ALLOWED_MASKED_SECRET_KEYS
            ):
                return current_path
            found = _find_forbidden_secret_key(child, current_path)
            if found is not None:
                return found
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found = _find_forbidden_secret_key(child, f"{path}[{index}]")
            if found is not None:
                return found
    return None
