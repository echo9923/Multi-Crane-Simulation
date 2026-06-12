from __future__ import annotations

import math
from typing import Any, Dict, List, Literal, Mapping, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from backend.app.schemas.command import ExecutedCommand
from backend.app.schemas.control import ControlTarget
from backend.app.schemas.crane import CraneConfig
from backend.app.schemas.enums import LLMSchedulingMode, RuntimeMode, StrEnum
from backend.app.schemas.state import CraneState
from backend.app.schemas.task import Task, TaskQueue
from backend.app.schemas.weather import WeatherState, WeatherVisibilityContext

SCHEDULER_SCHEMA_VERSION = "1.0"

SCH_E_INVALID_CONFIG = "SCH_E_INVALID_CONFIG"
SCH_E_INVALID_SNAPSHOT = "SCH_E_INVALID_SNAPSHOT"
SCH_E_COMMAND_STORE = "SCH_E_COMMAND_STORE"
SCH_E_FRAME_LOOP = "SCH_E_FRAME_LOOP"
SCH_E_REPLAY_MISMATCH = "SCH_E_REPLAY_MISMATCH"
SCH_E_STOPPED_BY_USER = "SCH_E_STOPPED_BY_USER"

FORBIDDEN_SNAPSHOT_KEYS = {
    "offline_label",
    "offline_risk_label",
    "offline_ttc",
    "future_min_distance",
    "future_min_distance_m",
    "future_ttc",
    "llm_reason",
    "raw_llm_response",
    "raw_response",
    "provider_secret",
    "api_key",
    "authorization",
    "token",
}


class SchedulerBaseModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        allow_inf_nan=False,
        validate_default=True,
        arbitrary_types_allowed=True,
    )


class EpisodeStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    TIMEOUT = "timeout"
    FAILED_COLLISION = "failed_collision"
    FAILED_INVALID_STATE = "failed_invalid_state"
    LLM_FAILED = "llm_failed"
    FAILED_REPLAY_MISMATCH = "failed_replay_mismatch"
    FAILED_RECOVERY_BLOCKED = "failed_recovery_blocked"
    FAILED_RECOVERY_TIMEOUT = "failed_recovery_timeout"
    STOPPED_BY_USER = "stopped_by_user"


class ReplayValidationConfig(SchedulerBaseModel):
    schema_version: str = SCHEDULER_SCHEMA_VERSION
    strict: bool = True
    require_resolved_config_hash_match: bool = True
    position_tolerance_m: float = Field(default=1.0e-5, gt=0)
    angle_tolerance_rad: float = Field(default=1.0e-7, gt=0)
    velocity_tolerance: float = Field(default=1.0e-6, gt=0)
    replay_file: Optional[str] = None


class SchedulerConfig(SchedulerBaseModel):
    schema_version: str = SCHEDULER_SCHEMA_VERSION
    dt_s: float = Field(gt=0)
    duration_s: float = Field(gt=0)
    min_duration_s: float = Field(default=0.0, ge=0)
    stop_when_all_tasks_done: bool = True
    completion_cooldown_s: float = Field(default=0.0, ge=0)
    controller_hz: float = Field(gt=0)
    llm_decision_interval_s: float = Field(gt=0)
    run_mode: RuntimeMode
    llm_scheduling_mode: Optional[LLMSchedulingMode] = None
    max_consecutive_llm_failures: Optional[int] = Field(default=None, gt=0)
    realtime_wall_clock: bool = False
    replay: Optional[ReplayValidationConfig] = None

    @classmethod
    def from_config(cls, config: object) -> "SchedulerConfig":
        data = _as_mapping(config)
        if "dt_s" in data:
            return cls.model_validate(data)

        sim = _extract_sim_mapping(data)
        runtime = _extract_runtime_mapping(data)
        llm = _extract_llm_mapping(data)

        replay_file = _first_present(runtime, "replay_file")
        payload: Dict[str, Any] = {
            "dt_s": sim.get("dt"),
            "duration_s": sim.get("duration_s"),
            "min_duration_s": sim.get("min_duration_s", 0.0),
            "stop_when_all_tasks_done": sim.get("stop_when_all_tasks_done", True),
            "completion_cooldown_s": sim.get("completion_cooldown_s", 0.0),
            "controller_hz": sim.get("controller_hz"),
            "llm_decision_interval_s": sim.get("llm_decision_interval_s"),
            "run_mode": runtime.get("mode"),
            "llm_scheduling_mode": _extract_llm_scheduling_mode(llm),
            "max_consecutive_llm_failures": llm.get("max_consecutive_failures"),
            "replay": {"replay_file": replay_file} if replay_file else None,
        }
        return cls.model_validate(payload)


class WorldSnapshot(SchedulerBaseModel):
    schema_version: str = SCHEDULER_SCHEMA_VERSION
    snapshot_id: str
    episode_id: str
    frame_index: int = Field(ge=0)
    time_s: float = Field(ge=0)
    decision_time_bucket: int = Field(ge=0)
    crane_states: Tuple[CraneState, ...]
    crane_configs: Tuple[CraneConfig, ...]
    weather_state: WeatherState
    visibility_context: WeatherVisibilityContext
    tasks: Tuple[Task, ...] = Field(default_factory=tuple)
    task_queues: Tuple[TaskQueue, ...] = Field(default_factory=tuple)
    task_contexts: Dict[str, Any] = Field(default_factory=dict)
    current_commands: Dict[str, ExecutedCommand] = Field(default_factory=dict)
    current_control_targets: Dict[str, ControlTarget] = Field(default_factory=dict)
    recent_decisions: Dict[str, List[Dict[str, Any]]] = Field(default_factory=dict)
    recent_events: Dict[str, List[Dict[str, Any]]] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def reject_forbidden_snapshot_keys(cls, value: object) -> object:
        offending = _find_forbidden_key(value)
        if offending is not None:
            raise ValueError(f"forbidden snapshot field: {offending}")
        return value

    @model_validator(mode="after")
    def validate_snapshot_contract(self) -> "WorldSnapshot":
        non_finite_path = _find_non_finite_number(self)
        if non_finite_path is not None:
            raise ValueError(f"snapshot contains non-finite number: {non_finite_path}")

        state_ids = [state.crane_id for state in self.crane_states]
        config_ids = [config.crane_id for config in self.crane_configs]
        _ensure_unique_ids(state_ids, "crane_states")
        _ensure_unique_ids(config_ids, "crane_configs")
        missing_configs = sorted(set(state_ids) - set(config_ids))
        if missing_configs:
            raise ValueError(f"missing crane_configs for states: {missing_configs}")

        for key, command in self.current_commands.items():
            if key != command.crane_id:
                raise ValueError("current_commands key must match command.crane_id")
            if key not in state_ids:
                raise ValueError("current_commands key must reference a crane state")
        for key, target in self.current_control_targets.items():
            if key != target.crane_id:
                raise ValueError(
                    "current_control_targets key must match target.crane_id"
                )
            if key not in state_ids:
                raise ValueError(
                    "current_control_targets key must reference a crane state"
                )
        return self


StoredCommandSource = Literal[
    "decision",
    "replay",
    "expired_neutral_stop",
    "llm_timeout_neutral_stop",
    "startup_neutral_stop",
]


class StoredCommand(SchedulerBaseModel):
    schema_version: str = SCHEDULER_SCHEMA_VERSION
    crane_id: str
    command: ExecutedCommand
    applied_at_s: float = Field(ge=0)
    expires_at_s: float = Field(ge=0)
    source: StoredCommandSource

    @model_validator(mode="after")
    def validate_command_identity_and_expiry(self) -> "StoredCommand":
        if self.crane_id != self.command.crane_id:
            raise ValueError("crane_id must match command.crane_id")
        expected_expires_at_s = self.command.time_s + self.command.command_duration_s
        if not math.isclose(
            self.expires_at_s,
            expected_expires_at_s,
            rel_tol=0.0,
            abs_tol=1.0e-9,
        ):
            raise ValueError(
                "expires_at_s must equal command.time_s + command.command_duration_s"
            )
        return self


class CommandStoreSnapshot(SchedulerBaseModel):
    schema_version: str = SCHEDULER_SCHEMA_VERSION
    time_s: float = Field(ge=0)
    commands: Dict[str, StoredCommand] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_command_keys(self) -> "CommandStoreSnapshot":
        for key, stored in self.commands.items():
            if key != stored.crane_id:
                raise ValueError("commands key must match stored command crane_id")
        return self


class TerminalStatusCandidate(SchedulerBaseModel):
    schema_version: str = SCHEDULER_SCHEMA_VERSION
    status: EpisodeStatus
    source_module: str
    reason: str
    time_s: float = Field(ge=0)
    frame_index: Optional[int] = Field(default=None, ge=0)
    details: Dict[str, Any] = Field(default_factory=dict)


class FrameStepResult(SchedulerBaseModel):
    schema_version: str = SCHEDULER_SCHEMA_VERSION
    frame_index: int = Field(ge=0)
    time_s: float = Field(ge=0)
    status: EpisodeStatus
    snapshot_id: Optional[str] = None
    events: List[Dict[str, Any]] = Field(default_factory=list)


class EpisodeResult(SchedulerBaseModel):
    schema_version: str = SCHEDULER_SCHEMA_VERSION
    episode_id: str
    status: EpisodeStatus
    final_time_s: float = Field(ge=0)
    final_frame_index: int = Field(ge=0)
    reason: Optional[str] = None
    terminal_candidate: Optional[TerminalStatusCandidate] = None
    metrics: Dict[str, Any] = Field(default_factory=dict)


class SchedulerError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        error_code: str,
        episode_status: EpisodeStatus = EpisodeStatus.FAILED_INVALID_STATE,
        source_module: str = "J",
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.episode_status = EpisodeStatus(episode_status)
        self.source_module = source_module
        self.details = dict(details or {})


def _as_mapping(config: object) -> Dict[str, Any]:
    if isinstance(config, Mapping):
        return dict(config)
    if hasattr(config, "model_dump"):
        return config.model_dump(mode="python")
    if hasattr(config, "__dict__"):
        return dict(vars(config))
    raise TypeError("scheduler config must be a mapping or pydantic-like object")


def _extract_sim_mapping(data: Mapping[str, Any]) -> Dict[str, Any]:
    runtime = data.get("runtime")
    if isinstance(runtime, Mapping) and isinstance(runtime.get("sim"), Mapping):
        return dict(runtime["sim"])
    sim = data.get("sim")
    if isinstance(sim, Mapping):
        return dict(sim)
    raise ValueError("scheduler config missing sim settings")


def _extract_runtime_mapping(data: Mapping[str, Any]) -> Dict[str, Any]:
    runtime = data.get("runtime")
    if isinstance(runtime, Mapping):
        nested_runtime = runtime.get("runtime")
        if isinstance(nested_runtime, Mapping):
            result = dict(nested_runtime)
            if "replay_file" in runtime and "replay_file" not in result:
                result["replay_file"] = runtime["replay_file"]
            return result
        return dict(runtime)
    raise ValueError("scheduler config missing runtime settings")


def _extract_llm_mapping(data: Mapping[str, Any]) -> Dict[str, Any]:
    llm = data.get("llm")
    if isinstance(llm, Mapping):
        return dict(llm)
    experiment = data.get("experiment")
    if isinstance(experiment, Mapping) and isinstance(experiment.get("llm"), Mapping):
        return dict(experiment["llm"])
    return {}


def _extract_llm_scheduling_mode(
    llm: Mapping[str, Any],
) -> Optional[LLMSchedulingMode]:
    scheduling = llm.get("scheduling")
    if not isinstance(scheduling, Mapping):
        return None
    mode = scheduling.get("mode")
    if mode is None:
        return None
    return LLMSchedulingMode(mode)


def _first_present(data: Mapping[str, Any], key: str) -> Any:
    value = data.get(key)
    if value is not None:
        return value
    return None


def _ensure_unique_ids(ids: List[str], field_path: str) -> None:
    seen = set()
    duplicates = set()
    for item_id in ids:
        if item_id in seen:
            duplicates.add(item_id)
        seen.add(item_id)
    if duplicates:
        raise ValueError(f"duplicate ids in {field_path}: {sorted(duplicates)}")


def _find_forbidden_key(value: object, path: str = "") -> Optional[str]:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="python")
    if isinstance(value, Mapping):
        for key, child in value.items():
            key_text = str(key)
            lowered = key_text.lower()
            current_path = f"{path}.{key_text}" if path else key_text
            if lowered in FORBIDDEN_SNAPSHOT_KEYS:
                return current_path
            found = _find_forbidden_key(child, current_path)
            if found is not None:
                return found
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            found = _find_forbidden_key(child, f"{path}[{index}]")
            if found is not None:
                return found
    return None


def _find_non_finite_number(value: object, path: str = "") -> Optional[str]:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="python")
    if isinstance(value, float):
        if not math.isfinite(value):
            return path or "<root>"
        return None
    if isinstance(value, Mapping):
        for key, child in value.items():
            current_path = f"{path}.{key}" if path else str(key)
            found = _find_non_finite_number(child, current_path)
            if found is not None:
                return found
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            found = _find_non_finite_number(child, f"{path}[{index}]")
            if found is not None:
                return found
    return None
