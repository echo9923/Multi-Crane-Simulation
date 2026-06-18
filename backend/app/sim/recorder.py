from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Literal, Mapping, Optional, Sequence, Type, Union, get_args, get_origin

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


class Recorder:
    def __init__(
        self,
        *,
        resolved_config: ResolvedConfig,
        scenario_id: Optional[str] = None,
    ) -> None:
        self.resolved_config = resolved_config
        self.scenario_id = scenario_id or _scenario_id_from_config(resolved_config)
        self.layout: Optional[RunDirectoryLayout] = None
        self.parquet_writers: Optional[RecorderParquetWriters] = None
        self.jsonl_writers: Optional[RecorderJsonlWriters] = None
        self.visual_writer: Optional[VisualFrameWriter] = None
        self._episode_id: Optional[str] = None
        self._last_time_s = 0.0
        self._last_frame_index = 0
        self._last_num_cranes = 0
        self._trajectory_rows: List[TrajectoryRow] = []
        self._pair_risk_rows: List[PairRiskRow] = []
        self._task_rows: List[TaskParquetRow] = []
        self._command_logs: List[CommandLogEntry] = []
        self._event_logs: List[EventLogEntry] = []

    @classmethod
    def from_config(cls, config: object) -> "Recorder":
        resolved_config = _coerce_resolved_config(config)
        return cls(resolved_config=resolved_config)

    def record_initial_frame(
        self,
        *,
        episode_id: str,
        frame_index: int,
        time_s: float,
        states: Sequence[CraneState],
        weather_state: WeatherState,
        visibility_context: Optional[Any] = None,
        commands: Optional[Mapping[str, Any]] = None,
        task_queues: Sequence[Any] = (),
        events: Sequence[Any] = (),
        status: object = "running",
        **extra: Any,
    ) -> SimFrame:
        if frame_index != 0 or not math.isclose(time_s, 0.0):
            raise DataExportError(
                "initial frame must be recorded at frame_index=0 and time_s=0",
                error_code="RECORDER_E_INITIAL_FRAME_TIME",
                episode_id=episode_id,
                frame=frame_index,
            )
        return self._record_frame(
            episode_id=episode_id,
            frame_index=frame_index,
            time_s=time_s,
            states=states,
            weather_state=weather_state,
            commands=commands,
            task_queues=task_queues,
            events=events,
            status=status,
            online_risk=extra.get("online_risk"),
            observations=(),
            llm_calls=(),
            interventions=extra.get("interventions", ()),
        )

    def record_step(
        self,
        *,
        episode_id: str,
        frame_index: int,
        time_s: float,
        states: Sequence[CraneState],
        weather_state: WeatherState,
        visibility_context: Optional[Any] = None,
        commands: Optional[Mapping[str, Any]] = None,
        control_targets: Sequence[Any] = (),
        controller_diagnostics: Sequence[Any] = (),
        task_queues: Sequence[Any] = (),
        events: Sequence[Any] = (),
        status: object = "running",
        snapshot_id: Optional[str] = None,
        online_risk: Optional[Any] = None,
        observations: Sequence[Any] = (),
        llm_calls: Sequence[Any] = (),
        interventions: Sequence[Any] = (),
        **extra: Any,
    ) -> SimFrame:
        return self._record_frame(
            episode_id=episode_id,
            frame_index=frame_index,
            time_s=time_s,
            states=states,
            weather_state=weather_state,
            commands=commands,
            task_queues=task_queues,
            events=events,
            status=status,
            online_risk=online_risk,
            observations=observations,
            llm_calls=llm_calls,
            interventions=interventions,
        )

    def write_offline_labels(self, labels: Sequence[OfflineRiskLabel]) -> None:
        if not labels:
            return
        episode_id = labels[0].episode_id
        self._ensure_started(episode_id)
        rows = [_pair_risk_row_from_offline_label(label) for label in labels]
        assert self.parquet_writers is not None
        self.parquet_writers.write_pair_risks(rows)
        self._pair_risk_rows.extend(rows)

    def finalize(self, *, episode_status: object) -> EpisodeSummary:
        if self.layout is None or self._episode_id is None:
            raise DataExportError(
                "cannot finalize recorder before any frame is recorded",
                error_code="RECORDER_E_FINALIZE_EMPTY",
            )
        assert self.parquet_writers is not None
        assert self.jsonl_writers is not None
        assert self.visual_writer is not None
        summary = build_episode_summary(
            episode_id=self._episode_id,
            scenario_id=self.scenario_id,
            episode_status=episode_status,
            duration_s=self._last_time_s,
            num_cranes=self._last_num_cranes,
            tasks=self._task_rows,
            pair_risk_rows=self._pair_risk_rows,
            command_logs=self._command_logs,
            event_logs=self._event_logs,
            warnings=[*self.parquet_writers.warnings, *self.jsonl_writers.warnings],
            state_jump_max_m=None,
            replay_available=False,
            dt_s=_infer_dt_s(self._trajectory_rows),
        )
        self.parquet_writers.flush_all()
        self.jsonl_writers.flush_all()
        manifest = build_episode_manifest(
            episode_id=self._episode_id,
            scenario_id=self.scenario_id,
            episode_status=episode_status,
            frame_count=self._last_frame_index + 1,
            dt_s=max(_infer_dt_s(self._trajectory_rows), 1.0e-9),
            crane_configs=_resolved_crane_configs(self.resolved_config),
            resolved_config=self.resolved_config,
            offline_labels_available=bool(self._pair_risk_rows),
        )
        self.visual_writer.write_manifest(manifest)
        self.visual_writer.flush()
        write_episode_summary(layout=self.layout, summary=summary)
        return summary

    def _record_frame(
        self,
        *,
        episode_id: str,
        frame_index: int,
        time_s: float,
        states: Sequence[CraneState],
        weather_state: WeatherState,
        commands: Optional[Mapping[str, Any]],
        task_queues: Sequence[Any],
        events: Sequence[Any],
        status: object,
        online_risk: Optional[Any],
        observations: Sequence[Any],
        llm_calls: Sequence[Any],
        interventions: Sequence[Any],
    ) -> SimFrame:
        self._ensure_started(episode_id)
        assert self.parquet_writers is not None
        assert self.jsonl_writers is not None
        assert self.visual_writer is not None
        command_map = dict(commands or {})
        trajectory_rows = [
            _trajectory_row_from_state(
                state=state,
                episode_id=episode_id,
                scenario_id=self.scenario_id,
                frame_index=frame_index,
                time_s=time_s,
                command=command_map.get(state.crane_id),
                weather_state=weather_state,
            )
            for state in states
        ]
        weather_row = _weather_row_from_state(
            episode_id=episode_id,
            scenario_id=self.scenario_id,
            frame_index=frame_index,
            time_s=time_s,
            weather_state=weather_state,
        )
        event_rows = [
            _event_log_entry_from_any(
                event,
                episode_id=episode_id,
                scenario_id=self.scenario_id,
                frame_index=frame_index,
                time_s=time_s,
            )
            for event in events
        ]
        pair_risk_rows = _pair_risk_rows_from_online_risk(
            online_risk,
            episode_id=episode_id,
            scenario_id=self.scenario_id,
            frame_index=frame_index,
            time_s=time_s,
        )
        graph_edge_rows = _graph_edge_rows_from_online_risk(
            online_risk,
            episode_id=episode_id,
            frame_index=frame_index,
            time_s=time_s,
        )
        task_rows = _task_rows_from_task_queues(
            task_queues,
            episode_id=episode_id,
            scenario_id=self.scenario_id,
        )
        observation_rows = [
            _observation_log_entry_from_any(
                observation,
                episode_id=episode_id,
                time_s=time_s,
            )
            for observation in observations
        ]
        decision_rows = [
            _decision_log_entry_from_any(
                call,
                episode_id=episode_id,
                time_s=time_s,
            )
            for call in llm_calls
        ]
        command_rows = _command_log_entries_from_calls(
            llm_calls=llm_calls,
            commands=command_map,
            episode_id=episode_id,
            time_s=time_s,
        )
        intervention_rows = [
            _intervention_log_entry_from_any(
                intervention,
                episode_id=episode_id,
                time_s=time_s,
            )
            for intervention in [
                *interventions,
                *_interventions_from_commands(command_map.values()),
            ]
        ]
        frame = build_sim_frame(
            episode_id=episode_id,
            scenario_id=self.scenario_id,
            frame_index=frame_index,
            time_s=time_s,
            episode_status=status,
            states=states,
            weather_state=weather_state,
            commands=commands,
            pairs=_online_risk_pairs(online_risk),
            task_queues=task_queues,
            events=[row.model_dump(mode="json") for row in event_rows],
            for_realtime=False,
        )
        self.parquet_writers.write_trajectories(trajectory_rows)
        self.parquet_writers.write_pair_risks(pair_risk_rows)
        self.parquet_writers.write_graph_edges(graph_edge_rows)
        self.parquet_writers.write_tasks(task_rows)
        self.parquet_writers.write_weather([weather_row])
        self.jsonl_writers.write_observations(observation_rows)
        self.jsonl_writers.write_decisions(decision_rows)
        self.jsonl_writers.write_commands(command_rows)
        self.jsonl_writers.write_interventions(intervention_rows)
        self.jsonl_writers.write_events(event_rows)
        self.visual_writer.append_frame(frame)
        self._trajectory_rows.extend(trajectory_rows)
        self._pair_risk_rows.extend(pair_risk_rows)
        self._task_rows = task_rows
        self._command_logs.extend(command_rows)
        self._event_logs.extend(event_rows)
        self._last_time_s = time_s
        self._last_frame_index = frame_index
        self._last_num_cranes = len(states)
        return frame

    def _ensure_started(self, episode_id: str) -> None:
        if self.layout is not None:
            if episode_id != self._episode_id:
                raise DataExportError(
                    "recorder cannot switch episode_id after start",
                    error_code="RECORDER_E_EPISODE_SWITCH",
                    episode_id=episode_id,
                )
            return
        self._episode_id = episode_id
        self.layout = init_run_directory(
            config=self.resolved_config,
            episode_id=episode_id,
            scenario_id=self.scenario_id,
        )
        self.parquet_writers = RecorderParquetWriters.from_layout(self.layout)
        self.jsonl_writers = RecorderJsonlWriters.from_layout(self.layout)
        self.visual_writer = VisualFrameWriter(
            frames_path=self.layout.frames_jsonl_path,
            manifest_path=self.layout.episode_manifest_path,
        )


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
        tmp_path = self.output_path.with_name(f".{self.output_path.name}.tmp")
        try:
            table = (
                pa.Table.from_pylist(self._rows)
                if self._rows
                else pa.Table.from_pylist([], schema=_arrow_schema_for_model(self.row_model))
            )
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
    enum_value = _enum_or_value(value)
    if enum_value is not value:
        return enum_value
    if hasattr(value, "__dict__"):
        return {
            str(key): _dump_for_json(child)
            for key, child in vars(value).items()
            if not str(key).startswith("_")
        }
    return value


def _enum_or_value(value: Any) -> Any:
    return getattr(value, "value", value)


def _trajectory_row_from_state(
    *,
    state: CraneState,
    episode_id: str,
    scenario_id: Optional[str],
    frame_index: int,
    time_s: float,
    command: Optional[Any],
    weather_state: Optional[WeatherState],
) -> TrajectoryRow:
    command_payload = _command_for_frame(command) or {}
    load_size = state.load_size_m or [None, None, None]
    return TrajectoryRow(
        episode_id=episode_id,
        scenario_id=scenario_id,
        frame=frame_index,
        time_s=time_s,
        crane_id=state.crane_id,
        theta_rad=state.theta_rad,
        theta_sin=state.theta_sin,
        theta_cos=state.theta_cos,
        theta_dot_rad_s=state.theta_dot_rad_s,
        theta_ddot_rad_s2=state.theta_ddot_rad_s2,
        trolley_r_m=state.trolley_r_m,
        trolley_v_m_s=state.trolley_v_m_s,
        hook_h_m=state.hook_h_m,
        hoist_v_m_s=state.hoist_v_m_s,
        root_x=state.root_position[0],
        root_y=state.root_position[1],
        root_z=state.root_position[2],
        tip_x=state.tip_position[0],
        tip_y=state.tip_position[1],
        tip_z=state.tip_position[2],
        hook_x=state.hook_position[0],
        hook_y=state.hook_position[1],
        hook_z=state.hook_position[2],
        load_attached=state.load_attached,
        load_type=state.load_type,
        load_weight_t=state.load_weight_t,
        load_size_x_m=load_size[0],
        load_size_y_m=load_size[1],
        load_size_z_m=load_size[2],
        task_id=state.task_id,
        task_stage=state.task_stage,
        executed_slew_direction=_nested_get(
            command_payload, ["left_joystick", "slew", "direction"]
        ),
        executed_slew_gear=_nested_get(
            command_payload, ["left_joystick", "slew", "gear"]
        ),
        executed_trolley_direction=_nested_get(
            command_payload, ["left_joystick", "trolley", "direction"]
        ),
        executed_trolley_gear=_nested_get(
            command_payload, ["left_joystick", "trolley", "gear"]
        ),
        executed_hoist_direction=_nested_get(
            command_payload, ["right_joystick", "hoist", "direction"]
        ),
        executed_hoist_gear=_nested_get(
            command_payload, ["right_joystick", "hoist", "gear"]
        ),
        executed_deadman_pressed=command_payload.get("deadman_pressed"),
        executed_emergency_stop=command_payload.get("emergency_stop"),
        executed_task_action=command_payload.get("task_action"),
        wind_speed_m_s=weather_state.wind_speed_m_s if weather_state else None,
        wind_gust_m_s=weather_state.wind_gust_m_s if weather_state else None,
        wind_direction_deg=weather_state.wind_direction_deg if weather_state else None,
        visibility_level=(
            _enum_or_value(weather_state.visibility_level) if weather_state else None
        ),
    )


def _weather_row_from_state(
    *,
    episode_id: str,
    scenario_id: Optional[str],
    frame_index: int,
    time_s: float,
    weather_state: WeatherState,
) -> WeatherParquetRow:
    return WeatherParquetRow(
        episode_id=episode_id,
        scenario_id=scenario_id,
        frame=frame_index,
        time_s=time_s,
        wind_speed_m_s=weather_state.wind_speed_m_s,
        wind_gust_m_s=weather_state.wind_gust_m_s,
        wind_direction_deg=weather_state.wind_direction_deg,
        visibility_level=_enum_or_value(weather_state.visibility_level),
        rain_level=_enum_or_value(weather_state.rain_level),
    )


def _task_rows_from_task_queues(
    task_queues: Sequence[Any],
    *,
    episode_id: str,
    scenario_id: Optional[str],
) -> List[TaskParquetRow]:
    rows: List[TaskParquetRow] = []
    seen: set[str] = set()
    for queue in task_queues:
        queue_payload = _payload_dict(queue)
        for task in queue_payload.get("tasks", []) or []:
            if not isinstance(task, Mapping):
                continue
            task_payload = dict(task)
            task_id = str(task_payload.get("task_id") or "")
            if not task_id or task_id in seen:
                continue
            seen.add(task_id)
            pickup = _nested_payload(task_payload, "pickup")
            dropoff = _nested_payload(task_payload, "dropoff")
            load_size = list(task_payload.get("load_size_m") or [0.0, 0.0, 0.0])
            if len(load_size) < 3:
                load_size = [*load_size, *([0.0] * (3 - len(load_size)))]
            completed_time_s = task_payload.get("completed_at_s")
            actual_start_s = task_payload.get("started_at_s")
            deadline_s = task_payload.get("deadline_s")
            overtime_s = task_payload.get("overtime_s")
            if overtime_s is None:
                overtime_s = _compute_overtime_s(completed_time_s, deadline_s)
            rows.append(
                TaskParquetRow(
                    episode_id=episode_id,
                    scenario_id=scenario_id,
                    task_id=task_id,
                    crane_id=str(
                        task_payload.get("crane_id")
                        or queue_payload.get("crane_id")
                        or "unknown"
                    ),
                    task_type=str(task_payload.get("task_type") or "easy_task"),
                    status=str(task_payload.get("status") or "pending"),
                    failure_reason=task_payload.get("failure_reason"),
                    pickup_x=float(pickup.get("x", 0.0)),
                    pickup_y=float(pickup.get("y", 0.0)),
                    pickup_z=float(pickup.get("z", 0.0)),
                    dropoff_x=float(dropoff.get("x", 0.0)),
                    dropoff_y=float(dropoff.get("y", 0.0)),
                    dropoff_z=float(dropoff.get("z", 0.0)),
                    pickup_surface_z_m=_optional_float(pickup.get("surface_z_m")),
                    dropoff_surface_z_m=_optional_float(dropoff.get("surface_z_m")),
                    pickup_hook_target_z_m=_optional_float(pickup.get("hook_target_z_m")),
                    dropoff_hook_target_z_m=_optional_float(dropoff.get("hook_target_z_m")),
                    pickup_floor_id=_optional_str(pickup.get("floor_id")),
                    dropoff_floor_id=_optional_str(dropoff.get("floor_id")),
                    pickup_building_id=_optional_str(pickup.get("building_id")),
                    dropoff_building_id=_optional_str(dropoff.get("building_id")),
                    pickup_zone_id=str(
                        task_payload.get("pickup_zone_id")
                        or pickup.get("zone_id")
                        or "unknown"
                    ),
                    dropoff_zone_id=str(
                        task_payload.get("dropoff_zone_id")
                        or dropoff.get("zone_id")
                        or "unknown"
                    ),
                    load_type=str(task_payload.get("load_type") or "unknown"),
                    load_weight_t=float(task_payload.get("load_weight_t") or 0.0),
                    load_size_x_m=float(load_size[0] or 0.0),
                    load_size_y_m=float(load_size[1] or 0.0),
                    load_size_z_m=float(load_size[2] or 0.0),
                    planned_start_s=task_payload.get("planned_start_s"),
                    actual_start_s=actual_start_s,
                    completed_time_s=completed_time_s,
                    deadline_s=deadline_s,
                    deadline_missed=bool(task_payload.get("deadline_missed", False)),
                    overtime_s=float(overtime_s or 0.0),
                )
            )
    return rows


def _event_log_entry_from_any(
    event: Any,
    *,
    episode_id: str,
    scenario_id: Optional[str],
    frame_index: int,
    time_s: float,
) -> EventLogEntry:
    payload = _dump_for_json(event)
    if not isinstance(payload, dict):
        payload = {
            "event_type": str(payload),
            "details": {"raw_event": str(payload)},
        }
    event_id = payload.get("event_id") or (
        f"EVT_{frame_index:06d}_{abs(hash(str(payload))) % 100000:05d}"
    )
    event_frame = payload.get("frame", payload.get("frame_index", frame_index))
    if event_frame is None:
        event_frame = frame_index
    event_time_s = payload.get("time_s", time_s)
    if event_time_s is None:
        event_time_s = time_s
    return EventLogEntry(
        event_id=event_id,
        event_type=str(payload.get("event_type", "unknown")),
        episode_id=str(payload.get("episode_id", episode_id)),
        scenario_id=payload.get("scenario_id", scenario_id),
        frame=int(event_frame),
        time_s=float(event_time_s),
        crane_ids=list(payload.get("crane_ids", [])),
        risk_level=payload.get("risk_level"),
        distance_min_raw_now_m=payload.get("distance_min_raw_now_m"),
        clearance_min_now_m=payload.get("clearance_min_now_m"),
        details=dict(payload.get("details", {})),
    )


def _observation_log_entry_from_any(
    observation: Any,
    *,
    episode_id: str,
    time_s: float,
) -> ObservationLogEntry:
    payload = _payload_dict(observation)
    observation_body = payload.get("observation")
    if observation_body is None:
        observation_body = {
            key: value
            for key, value in payload.items()
            if key
            not in {
                "schema_version",
                "observation_id",
                "episode_id",
                "time_s",
                "crane_id",
                "risk_prompt_mode",
                "source_snapshot_id",
            }
        }
    return ObservationLogEntry(
        observation_id=payload.get("observation_id"),
        episode_id=str(payload.get("episode_id", episode_id)),
        time_s=float(payload.get("time_s", time_s)),
        crane_id=payload.get("crane_id"),
        risk_prompt_mode=str(_enum_or_value(payload.get("risk_prompt_mode", "unknown"))),
        observation=dict(observation_body),
        source_snapshot_id=payload.get("source_snapshot_id", "unknown"),
    )


def _decision_log_entry_from_any(
    call: Any,
    *,
    episode_id: str,
    time_s: float,
) -> DecisionLogEntry:
    payload = _payload_dict(call)
    parsed = _nested_payload(payload, "parsed_command")
    raw = _nested_payload(payload, "raw_response")
    return DecisionLogEntry(
        episode_id=episode_id,
        time_s=float(
            payload.get("time_s")
            or parsed.get("time_s")
            or raw.get("time_s")
            or time_s
        ),
        crane_id=str(
            payload.get("crane_id")
            or parsed.get("crane_id")
            or raw.get("crane_id")
            or "unknown"
        ),
        provider=str(_enum_or_value(payload.get("provider", "unknown"))),
        model=str(payload.get("model", raw.get("model", "unknown"))),
        call_record=payload,
    )


def _command_log_entries_from_calls(
    *,
    llm_calls: Sequence[Any],
    commands: Mapping[str, Any],
    episode_id: str,
    time_s: float,
) -> List[CommandLogEntry]:
    if llm_calls:
        return [
            _command_log_entry_from_call(
                call,
                executed_command=commands.get(
                    str(
                        _nested_payload(_payload_dict(call), "parsed_command").get(
                            "crane_id", ""
                        )
                    )
                ),
                episode_id=episode_id,
                time_s=time_s,
            )
            for call in llm_calls
        ]
    return [
        _command_log_entry_from_executed_command(
            command,
            episode_id=episode_id,
            time_s=time_s,
        )
        for command in commands.values()
    ]


def _command_log_entry_from_call(
    call: Any,
    *,
    executed_command: Optional[Any],
    episode_id: str,
    time_s: float,
) -> CommandLogEntry:
    payload = _payload_dict(call)
    parsed = _nested_payload(payload, "parsed_command")
    raw = _nested_payload(payload, "raw_response")
    executed = _payload_dict(executed_command) if executed_command is not None else {}
    return CommandLogEntry(
        episode_id=episode_id,
        time_s=float(payload.get("time_s") or parsed.get("time_s") or time_s),
        decision_index=payload.get("attempt_index"),
        crane_id=str(parsed.get("crane_id") or raw.get("crane_id") or "unknown"),
        operator_id=parsed.get("operator_id") or raw.get("operator_id"),
        observation_id=parsed.get("observation_id") or raw.get("observation_id"),
        provider=str(_enum_or_value(payload.get("provider", raw.get("provider"))))
        if payload.get("provider", raw.get("provider")) is not None
        else None,
        model=payload.get("model") or raw.get("model"),
        raw_llm_response=raw or None,
        parsed_command=parsed or None,
        executed_command=executed or None,
        modified_by_intervention=bool(executed.get("interventions")),
        modified_by_mechanical_safety=bool(
            executed.get("mechanical_limit") or executed.get("forbidden_zone")
        ),
        intervention_reason=_joined_reasons(executed.get("modification_reasons")),
        latency_ms=payload.get("latency_ms") or raw.get("latency_ms"),
        token_usage=payload.get("token_usage") or raw.get("token_usage"),
        retry_count=int(payload.get("attempt_index", 0)),
        validation_errors=list(payload.get("validation_errors", [])),
        cache_hit=bool(payload.get("cache_hit", False)),
        confidence=parsed.get("confidence"),
        attention_target=parsed.get("attention_target"),
        reason=parsed.get("reason"),
    )


def _command_log_entry_from_executed_command(
    command: Any,
    *,
    episode_id: str,
    time_s: float,
) -> CommandLogEntry:
    payload = _payload_dict(command)
    parsed = _nested_payload(payload, "raw_command")
    return CommandLogEntry(
        episode_id=episode_id,
        time_s=float(payload.get("time_s") or parsed.get("time_s") or time_s),
        crane_id=str(payload.get("crane_id") or parsed.get("crane_id") or "unknown"),
        operator_id=payload.get("operator_id") or parsed.get("operator_id"),
        observation_id=payload.get("observation_id") or parsed.get("observation_id"),
        parsed_command=parsed or None,
        executed_command=payload,
        modified_by_intervention=bool(payload.get("interventions")),
        modified_by_mechanical_safety=bool(
            payload.get("mechanical_limit") or payload.get("forbidden_zone")
        ),
        intervention_reason=_joined_reasons(payload.get("modification_reasons")),
        confidence=parsed.get("confidence"),
        attention_target=parsed.get("attention_target"),
        reason=parsed.get("reason"),
    )


def _interventions_from_commands(commands: Sequence[Any]) -> List[Any]:
    interventions: List[Any] = []
    for command in commands:
        payload = _payload_dict(command)
        interventions.extend(payload.get("interventions", []) or [])
    return interventions


def _intervention_log_entry_from_any(
    intervention: Any,
    *,
    episode_id: str,
    time_s: float,
) -> InterventionLogEntry:
    payload = _payload_dict(intervention)
    return InterventionLogEntry(
        episode_id=episode_id,
        time_s=float(payload.get("time_s", time_s)),
        intervention_id=payload.get("intervention_id"),
        crane_id=payload.get("crane_id"),
        safety_mode=str(_enum_or_value(payload.get("safety_mode")))
        if payload.get("safety_mode") is not None
        else None,
        risk_level=payload.get("risk_level"),
        action=payload.get("action", "none"),
        modified=bool(payload.get("modified", False)),
        reason=payload.get("reason", ""),
        pair_ids=list(payload.get("pair_ids", [])),
    )


def _pair_risk_rows_from_online_risk(
    online_risk: Optional[Any],
    *,
    episode_id: str,
    scenario_id: Optional[str],
    frame_index: int,
    time_s: float,
) -> List[PairRiskRow]:
    rows: List[PairRiskRow] = []
    for pair in _online_risk_pairs(online_risk):
        pair_payload = _payload_dict(pair)
        rows.append(
            PairRiskRow(
                episode_id=episode_id,
                scenario_id=scenario_id,
                frame=frame_index,
                time_s=float(pair_payload.get("time_s", time_s)),
                crane_i=str(
                    pair_payload.get("crane_i")
                    or pair_payload.get("crane_id_a")
                    or pair_payload.get("src_crane_id")
                ),
                crane_j=str(
                    pair_payload.get("crane_j")
                    or pair_payload.get("crane_id_b")
                    or pair_payload.get("dst_crane_id")
                ),
                distance_min_raw_now_m=pair_payload.get("distance_min_raw_now_m")
                or pair_payload.get("d_min_online_m"),
                clearance_min_now_m=pair_payload.get("clearance_min_now_m")
                or pair_payload.get("d_hat_min_m"),
                ttc_5s_s=pair_payload.get("ttc_5s_s")
                or pair_payload.get("ttc_hat_s"),
                risk_level_now=pair_payload.get("risk_level_now")
                or pair_payload.get("risk_level"),
            )
        )
    return rows


def _graph_edge_rows_from_online_risk(
    online_risk: Optional[Any],
    *,
    episode_id: str,
    frame_index: int,
    time_s: float,
) -> List[GraphEdgeRow]:
    rows: List[GraphEdgeRow] = []
    for pair in _online_risk_pairs(online_risk):
        pair_payload = _payload_dict(pair)
        crane_i = str(pair_payload.get("crane_i") or pair_payload.get("crane_id_a"))
        crane_j = str(pair_payload.get("crane_j") or pair_payload.get("crane_id_b"))
        for src, dst in [(crane_i, crane_j), (crane_j, crane_i)]:
            rows.append(
                GraphEdgeRow(
                    episode_id=episode_id,
                    frame=frame_index,
                    time_s=float(pair_payload.get("time_s", time_s)),
                    src_crane_id=src,
                    dst_crane_id=dst,
                    edge_distance_m=pair_payload.get("edge_distance_m")
                    or pair_payload.get("d_min_online_m"),
                    edge_ttc_s=pair_payload.get("edge_ttc_s")
                    or pair_payload.get("ttc_hat_s"),
                    edge_risk_level=pair_payload.get("edge_risk_level")
                    or pair_payload.get("risk_level"),
                    edge_weight_physics_prior=pair_payload.get(
                        "edge_weight_physics_prior"
                    )
                    or pair_payload.get("confidence"),
                )
            )
    return rows


def _online_risk_pairs(online_risk: Optional[Any]) -> List[Any]:
    if online_risk is None:
        return []
    payload = _payload_dict(online_risk)
    pairs = payload.get("pairs", [])
    return list(pairs or [])


def _pair_risk_row_from_offline_label(label: OfflineRiskLabel) -> PairRiskRow:
    payload = label.model_dump(mode="json")
    label_15s = payload.get("future_window_labels", {}).get("15s", {})
    return PairRiskRow(
        episode_id=payload["episode_id"],
        scenario_id=payload.get("scenario_id"),
        frame=payload["frame"],
        time_s=payload["time_s"],
        crane_i=payload["crane_i"],
        crane_j=payload["crane_j"],
        distance_min_raw_now_m=payload.get("distance_min_raw_now_m"),
        clearance_min_now_m=payload.get("clearance_min_now_m"),
        distance_jib_jib_raw_now_m=payload.get("distance_jib_jib_raw_now_m"),
        clearance_jib_jib_now_m=payload.get("clearance_jib_jib_now_m"),
        distance_jib_i_hook_j_raw_now_m=payload.get(
            "distance_jib_i_hook_j_raw_now_m"
        ),
        clearance_jib_i_hook_j_now_m=payload.get("clearance_jib_i_hook_j_now_m"),
        distance_jib_j_hook_i_raw_now_m=payload.get(
            "distance_jib_j_hook_i_raw_now_m"
        ),
        clearance_jib_j_hook_i_now_m=payload.get("clearance_jib_j_hook_i_now_m"),
        distance_hook_hook_raw_now_m=payload.get("distance_hook_hook_raw_now_m"),
        clearance_hook_hook_now_m=payload.get("clearance_hook_hook_now_m"),
        min_clearance_future_5s_m=payload.get("min_clearance_future_5s_m"),
        min_clearance_future_10s_m=payload.get("min_clearance_future_10s_m"),
        min_clearance_future_15s_m=label_15s.get("min_clearance_future_m"),
        ttc_5s_s=payload.get("ttc_5s_s"),
        ttc_10s_s=payload.get("ttc_10s_s"),
        ttc_15s_s=label_15s.get("ttc_s"),
        risk_level_5s=payload.get("risk_level_5s"),
        risk_level_10s=payload.get("risk_level_10s"),
        risk_level_15s=label_15s.get("risk_level"),
        collision_label_5s=payload.get("collision_label_5s"),
        collision_label_10s=payload.get("collision_label_10s"),
        collision_label_15s=label_15s.get("collision_label"),
    )


def _compute_overtime_s(
    completed_time_s: Optional[float],
    deadline_s: Optional[float],
) -> float:
    if completed_time_s is None or deadline_s is None:
        return 0.0
    return max(0.0, float(completed_time_s) - float(deadline_s))


def _resolved_crane_configs(resolved_config: ResolvedConfig) -> List[Any]:
    cranes = resolved_config.layout.resolved_cranes or []
    return list(cranes)


def _infer_dt_s(rows: Sequence[TrajectoryRow]) -> float:
    times = sorted({row.time_s for row in rows})
    if len(times) < 2:
        return 0.0
    deltas = [
        right - left
        for left, right in zip(times, times[1:])
        if right > left
    ]
    return min(deltas) if deltas else 0.0


def _nested_get(payload: Mapping[str, Any], path: Sequence[str]) -> Any:
    current: Any = payload
    for key in path:
        if not isinstance(current, Mapping) or key not in current:
            return None
        current = current[key]
    return current


def _optional_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    return float(value)


def _optional_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value)
    return text if text else None


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


def _payload_dict(value: Any) -> Dict[str, Any]:
    payload = _dump_for_json(value)
    if isinstance(payload, Mapping):
        return dict(payload)
    raise DataExportError(
        "recorder export payload must be mapping-like",
        error_code="RECORDER_E_EXPORT_PAYLOAD_TYPE",
        details={"payload_type": type(value).__name__},
    )


def _nested_payload(payload: Mapping[str, Any], key: str) -> Dict[str, Any]:
    value = payload.get(key)
    return dict(value) if isinstance(value, Mapping) else {}


def _joined_reasons(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, list):
        return "; ".join(str(item) for item in value) or None
    return str(value)


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


def _arrow_schema_for_model(row_model: Type[RecorderBaseModel]) -> pa.Schema:
    fields = [
        pa.field(name, _arrow_type_for_annotation(field.annotation))
        for name, field in row_model.model_fields.items()
    ]
    return pa.schema(fields)


def _arrow_type_for_annotation(annotation: Any) -> pa.DataType:
    origin = get_origin(annotation)
    if origin is Union:
        non_none_args = [arg for arg in get_args(annotation) if arg is not type(None)]
        if len(non_none_args) == 1:
            return _arrow_type_for_annotation(non_none_args[0])
    if origin in {dict, Dict, Mapping}:
        return pa.string()
    if origin in {list, List, tuple}:
        return pa.string()
    if annotation is str or origin is Literal:
        return pa.string()
    if annotation is int:
        return pa.int64()
    if annotation is float:
        return pa.float64()
    if annotation is bool:
        return pa.bool_()
    return pa.string()


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
