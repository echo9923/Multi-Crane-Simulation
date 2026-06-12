from __future__ import annotations

import copy
import math
from typing import Any, Literal, Mapping, Optional, Sequence

from backend.app.schemas.command import ExecutedCommand, build_neutral_stop_command
from backend.app.schemas.control import ControlTarget
from backend.app.schemas.crane import CraneConfig
from backend.app.schemas.scheduler import (
    SCH_E_COMMAND_STORE,
    SCH_E_INVALID_SNAPSHOT,
    CommandStoreSnapshot,
    SchedulerError,
    StoredCommand,
    WorldSnapshot,
)
from backend.app.schemas.state import CraneState
from backend.app.schemas.task import Task, TaskQueue
from backend.app.schemas.weather import WeatherState, WeatherVisibilityContext
from backend.app.sim.observation import ObservationWorldSnapshot

CommandReplacementSource = Literal["decision", "replay"]


def freeze_world_snapshot(
    *,
    episode_id: str,
    frame_index: int,
    time_s: float,
    llm_decision_interval_s: float,
    crane_states: Sequence[CraneState],
    crane_configs: Sequence[CraneConfig],
    weather_state: WeatherState,
    visibility_context: WeatherVisibilityContext,
    tasks: Sequence[Task] = (),
    task_queues: Sequence[TaskQueue] = (),
    task_contexts: Optional[Mapping[str, Any]] = None,
    current_commands: Optional[Mapping[str, ExecutedCommand]] = None,
    current_control_targets: Optional[Mapping[str, ControlTarget]] = None,
    recent_decisions: Optional[Mapping[str, Sequence[Mapping[str, Any]]]] = None,
    recent_events: Optional[Mapping[str, Sequence[Mapping[str, Any]]]] = None,
) -> WorldSnapshot:
    _validate_snapshot_time_inputs(
        time_s=time_s,
        llm_decision_interval_s=llm_decision_interval_s,
    )
    try:
        return WorldSnapshot(
            snapshot_id=_snapshot_id(episode_id=episode_id, frame_index=frame_index),
            episode_id=episode_id,
            frame_index=frame_index,
            time_s=time_s,
            decision_time_bucket=_decision_time_bucket(
                time_s=time_s,
                llm_decision_interval_s=llm_decision_interval_s,
            ),
            crane_states=tuple(copy.deepcopy(list(crane_states))),
            crane_configs=tuple(copy.deepcopy(list(crane_configs))),
            weather_state=copy.deepcopy(weather_state),
            visibility_context=copy.deepcopy(visibility_context),
            tasks=tuple(copy.deepcopy(list(tasks))),
            task_queues=tuple(copy.deepcopy(list(task_queues))),
            task_contexts=copy.deepcopy(dict(task_contexts or {})),
            current_commands=copy.deepcopy(dict(current_commands or {})),
            current_control_targets=copy.deepcopy(dict(current_control_targets or {})),
            recent_decisions=_copy_recent_mapping(recent_decisions),
            recent_events=_copy_recent_mapping(recent_events),
        )
    except Exception as exc:
        if isinstance(exc, SchedulerError):
            raise
        raise SchedulerError(
            "failed to freeze world snapshot",
            error_code=SCH_E_INVALID_SNAPSHOT,
            details={"reason": str(exc)},
        ) from exc


def to_observation_snapshot(
    snapshot: WorldSnapshot,
    *,
    neighbor_map: Optional[Mapping[str, Sequence[str]]] = None,
) -> ObservationWorldSnapshot:
    return ObservationWorldSnapshot(
        snapshot_id=snapshot.snapshot_id,
        time_s=snapshot.time_s,
        decision_time_bucket=snapshot.decision_time_bucket,
        crane_states=list(copy.deepcopy(snapshot.crane_states)),
        crane_configs=list(copy.deepcopy(snapshot.crane_configs)),
        weather_state=copy.deepcopy(snapshot.weather_state),
        visibility_context=copy.deepcopy(snapshot.visibility_context),
        neighbor_map={
            crane_id: list(neighbor_ids)
            for crane_id, neighbor_ids in dict(neighbor_map or {}).items()
        },
        task_contexts=copy.deepcopy(snapshot.task_contexts),
        current_commands=copy.deepcopy(snapshot.current_control_targets),
        recent_decisions=copy.deepcopy(snapshot.recent_decisions),
        recent_events=copy.deepcopy(snapshot.recent_events),
    )


class CommandStore:
    def __init__(
        self,
        *,
        crane_ids: Sequence[str],
        default_operator_ids: Optional[Mapping[str, str]] = None,
        default_command_duration_s: float = 1.0,
    ) -> None:
        self._crane_ids = _validate_crane_ids(crane_ids)
        self._default_operator_ids = {
            crane_id: (default_operator_ids or {}).get(crane_id, f"OP_{crane_id}")
            for crane_id in self._crane_ids
        }
        _validate_positive_duration(default_command_duration_s)
        self._default_command_duration_s = default_command_duration_s
        self._commands: dict[str, StoredCommand] = {}

    @classmethod
    def with_startup_neutral(
        cls,
        *,
        crane_ids: Sequence[str],
        time_s: float = 0.0,
        default_operator_ids: Optional[Mapping[str, str]] = None,
        command_duration_s: float = 1.0,
    ) -> "CommandStore":
        store = cls(
            crane_ids=crane_ids,
            default_operator_ids=default_operator_ids,
            default_command_duration_s=command_duration_s,
        )
        _validate_finite_non_negative_time(time_s, field_name="time_s")
        for crane_id in store._crane_ids:
            command = build_system_neutral_executed_command(
                crane_id=crane_id,
                operator_id=store._default_operator_ids[crane_id],
                time_s=time_s,
                source_snapshot_id=f"SNAP_STARTUP_{crane_id}",
                observation_id=f"OBS_STARTUP_{crane_id}",
                reason="startup neutral_stop",
                command_duration_s=command_duration_s,
                command_id=f"cmd-neutral-startup-{crane_id}-{_time_token(time_s)}",
            )
            store._commands[crane_id] = _stored_command(
                command=command,
                applied_at_s=time_s,
                source="startup_neutral_stop",
            )
        return store

    def replace_current_commands(
        self,
        executed_commands: Sequence[ExecutedCommand],
        *,
        sim_time: float,
        source: CommandReplacementSource = "decision",
    ) -> CommandStoreSnapshot:
        _validate_finite_non_negative_time(sim_time, field_name="sim_time")
        if source not in {"decision", "replay"}:
            raise SchedulerError(
                "command replacement source must be decision or replay",
                error_code=SCH_E_COMMAND_STORE,
                details={"source": source},
            )
        replacements = self._validated_replacements(
            executed_commands,
            sim_time=sim_time,
            source=source,
        )
        self._commands.update(replacements)
        return self.snapshot(time_s=sim_time)

    def expire_or_neutral_stop(
        self,
        *,
        sim_time: float,
        command_duration_s: Optional[float] = None,
    ) -> tuple[dict[str, ExecutedCommand], list[dict[str, Any]]]:
        _validate_finite_non_negative_time(sim_time, field_name="sim_time")
        duration = (
            self._default_command_duration_s
            if command_duration_s is None
            else command_duration_s
        )
        _validate_positive_duration(duration)
        events: list[dict[str, Any]] = []
        for crane_id in self._crane_ids:
            stored = self._commands[crane_id]
            if sim_time + 1.0e-9 < stored.expires_at_s:
                continue
            expired_command = stored.command
            neutral = build_system_neutral_executed_command(
                crane_id=crane_id,
                operator_id=expired_command.operator_id,
                time_s=sim_time,
                source_snapshot_id=expired_command.source_snapshot_id,
                observation_id=expired_command.observation_id,
                reason=f"command {expired_command.command_id} expired; neutral_stop",
                command_duration_s=duration,
                command_id=(
                    f"cmd-neutral-expired-{crane_id}-{_time_token(sim_time)}"
                ),
            )
            self._commands[crane_id] = _stored_command(
                command=neutral,
                applied_at_s=sim_time,
                source="expired_neutral_stop",
            )
            events.append(
                {
                    "event_type": "command_expired_neutral_stop",
                    "time_s": sim_time,
                    "crane_id": crane_id,
                    "expired_command_id": expired_command.command_id,
                }
            )
        return self.get_current_commands(), events

    def get_current_commands(self) -> dict[str, ExecutedCommand]:
        return {
            crane_id: copy.deepcopy(stored.command)
            for crane_id, stored in self._commands.items()
        }

    def snapshot(self, *, time_s: float) -> CommandStoreSnapshot:
        _validate_finite_non_negative_time(time_s, field_name="time_s")
        return CommandStoreSnapshot(
            time_s=time_s,
            commands=copy.deepcopy(self._commands),
        )

    def _validated_replacements(
        self,
        executed_commands: Sequence[ExecutedCommand],
        *,
        sim_time: float,
        source: CommandReplacementSource,
    ) -> dict[str, StoredCommand]:
        seen: set[str] = set()
        replacements: dict[str, StoredCommand] = {}
        for command in executed_commands:
            if command.crane_id in seen:
                raise SchedulerError(
                    "duplicate command crane_id in replacement batch",
                    error_code=SCH_E_COMMAND_STORE,
                    details={"crane_id": command.crane_id},
                )
            seen.add(command.crane_id)
            if command.crane_id not in self._crane_ids:
                raise SchedulerError(
                    "command crane_id is not managed by this store",
                    error_code=SCH_E_COMMAND_STORE,
                    details={"crane_id": command.crane_id},
                )
            if not math.isclose(command.time_s, sim_time, rel_tol=0.0, abs_tol=1.0e-9):
                raise SchedulerError(
                    "command time_s must match replacement sim_time",
                    error_code=SCH_E_COMMAND_STORE,
                    details={
                        "crane_id": command.crane_id,
                        "command_time_s": command.time_s,
                        "sim_time": sim_time,
                    },
                )
            replacements[command.crane_id] = _stored_command(
                command=command,
                applied_at_s=sim_time,
                source=source,
            )
        return replacements


def build_system_neutral_executed_command(
    *,
    crane_id: str,
    operator_id: str,
    time_s: float,
    source_snapshot_id: str,
    observation_id: str,
    reason: str,
    command_duration_s: float = 1.0,
    command_id: Optional[str] = None,
) -> ExecutedCommand:
    _validate_finite_non_negative_time(time_s, field_name="time_s")
    _validate_positive_duration(command_duration_s)
    raw = build_neutral_stop_command(
        observation_id=observation_id,
        source_snapshot_id=source_snapshot_id,
        operator_id=operator_id,
        crane_id=crane_id,
        time_s=time_s,
        command_id=command_id or f"cmd-neutral-{crane_id}-{_time_token(time_s)}",
        response_id=None,
        command_duration_s=command_duration_s,
        reason=reason,
    )
    return ExecutedCommand.from_raw(
        command_id=f"EXEC_{raw.command_id}",
        raw_command=raw,
    )


def _validate_snapshot_time_inputs(
    *,
    time_s: float,
    llm_decision_interval_s: float,
) -> None:
    if not math.isfinite(time_s) or time_s < 0:
        raise SchedulerError(
            "time_s must be finite and non-negative",
            error_code=SCH_E_INVALID_SNAPSHOT,
            details={"time_s": time_s},
        )
    if not math.isfinite(llm_decision_interval_s) or llm_decision_interval_s <= 0:
        raise SchedulerError(
            "llm_decision_interval_s must be finite and positive",
            error_code=SCH_E_INVALID_SNAPSHOT,
            details={"llm_decision_interval_s": llm_decision_interval_s},
        )


def _validate_finite_non_negative_time(value: float, *, field_name: str) -> None:
    if not math.isfinite(value) or value < 0:
        raise SchedulerError(
            f"{field_name} must be finite and non-negative",
            error_code=SCH_E_COMMAND_STORE,
            details={field_name: value},
        )


def _validate_positive_duration(value: float) -> None:
    if not math.isfinite(value) or value <= 0:
        raise SchedulerError(
            "command duration must be finite and positive",
            error_code=SCH_E_COMMAND_STORE,
            details={"command_duration_s": value},
        )


def _validate_crane_ids(crane_ids: Sequence[str]) -> tuple[str, ...]:
    ids = tuple(crane_ids)
    if not ids:
        raise SchedulerError(
            "command store requires at least one crane",
            error_code=SCH_E_COMMAND_STORE,
        )
    if len(set(ids)) != len(ids):
        raise SchedulerError(
            "command store crane_ids must be unique",
            error_code=SCH_E_COMMAND_STORE,
            details={"crane_ids": list(ids)},
        )
    return ids


def _stored_command(
    *,
    command: ExecutedCommand,
    applied_at_s: float,
    source: str,
) -> StoredCommand:
    return StoredCommand(
        crane_id=command.crane_id,
        command=copy.deepcopy(command),
        applied_at_s=applied_at_s,
        expires_at_s=command.time_s + command.command_duration_s,
        source=source,
    )


def _snapshot_id(*, episode_id: str, frame_index: int) -> str:
    return f"SNAP_{episode_id}_{frame_index:06d}"


def _decision_time_bucket(
    *,
    time_s: float,
    llm_decision_interval_s: float,
) -> int:
    return int(round((time_s + 1.0e-9) / llm_decision_interval_s))


def _time_token(time_s: float) -> str:
    return f"{time_s:.9f}".rstrip("0").rstrip(".").replace(".", "p")


def _copy_recent_mapping(
    value: Optional[Mapping[str, Sequence[Mapping[str, Any]]]]
) -> dict[str, list[dict[str, Any]]]:
    return {
        key: [dict(item) for item in sequence]
        for key, sequence in copy.deepcopy(dict(value or {})).items()
    }
