from __future__ import annotations

import copy
import math
from typing import Any, Mapping, Optional, Sequence

from backend.app.schemas.command import ExecutedCommand
from backend.app.schemas.control import ControlTarget
from backend.app.schemas.crane import CraneConfig
from backend.app.schemas.scheduler import (
    SCH_E_INVALID_SNAPSHOT,
    SchedulerError,
    WorldSnapshot,
)
from backend.app.schemas.state import CraneState
from backend.app.schemas.task import Task, TaskQueue
from backend.app.schemas.weather import WeatherState, WeatherVisibilityContext
from backend.app.sim.observation import ObservationWorldSnapshot


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


def _snapshot_id(*, episode_id: str, frame_index: int) -> str:
    return f"SNAP_{episode_id}_{frame_index:06d}"


def _decision_time_bucket(
    *,
    time_s: float,
    llm_decision_interval_s: float,
) -> int:
    return int(round((time_s + 1.0e-9) / llm_decision_interval_s))


def _copy_recent_mapping(
    value: Optional[Mapping[str, Sequence[Mapping[str, Any]]]]
) -> dict[str, list[dict[str, Any]]]:
    return {
        key: [dict(item) for item in sequence]
        for key, sequence in copy.deepcopy(dict(value or {})).items()
    }
