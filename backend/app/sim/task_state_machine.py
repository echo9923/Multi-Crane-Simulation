from __future__ import annotations

import math
from typing import Dict, List, Optional

from pydantic import BaseModel, ConfigDict

from backend.app.schemas.config import TaskStateMachineConfig
from backend.app.schemas.crane import CraneConfig
from backend.app.schemas.state import CraneState
from backend.app.schemas.task import Task, TaskActionSignal, TaskEventPayload
from backend.app.sim.layout_geometry import horizontal_distance


class TaskRuntimeState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    attach_pending_started_at_s: Optional[float] = None
    release_pending_started_at_s: Optional[float] = None


class TaskStateMachineResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task: Task
    state: CraneState
    runtime: TaskRuntimeState
    events: List[TaskEventPayload]


def step_task_state_machine(
    task: Task,
    crane: CraneConfig,
    state: CraneState,
    signal: TaskActionSignal,
    *,
    time_s: float,
    config: TaskStateMachineConfig,
    runtime: Optional[TaskRuntimeState] = None,
    attach_delay_s: float = 0.0,
    release_delay_s: float = 0.0,
) -> TaskStateMachineResult:
    runtime_state = runtime or TaskRuntimeState()
    events: List[TaskEventPayload] = []
    current_stage = state.task_stage

    if signal.task_action == "request_attach" and current_stage != "lower_for_attach":
        events.append(
            _event(
                "attach_request_rejected",
                time_s,
                state,
                task,
                reason="wrong_stage",
            )
        )
        return _result(task, state, runtime_state, events)

    if signal.task_action == "request_release" and current_stage not in {
        "lower_for_release",
        "recovery_release",
    }:
        events.append(
            _event(
                "release_request_rejected",
                time_s,
                state,
                task,
                reason="wrong_stage",
            )
        )
        return _result(task, state, runtime_state, events)

    if current_stage == "move_to_pickup" and _xy_error(state, task.pickup.as_xyz()) <= config.align_xy_threshold_m:
        return _stage_changed(task, state, runtime_state, events, "align_pickup", time_s)

    if (
        current_stage == "align_pickup"
        and _xy_error(state, task.pickup.as_xyz()) <= config.align_xy_threshold_m
        and state.hook_h_m > task.pickup.z + config.attach_height_threshold_m
    ):
        return _stage_changed(task, state, runtime_state, events, "lower_for_attach", time_s)

    if current_stage == "lower_for_attach":
        if signal.task_action == "request_attach":
            reason = _attach_rejection_reason(task, crane, state, config)
            if reason is None:
                next_state = state.model_copy(update={"task_stage": "attach_pending"})
                next_runtime = runtime_state.model_copy(
                    update={"attach_pending_started_at_s": time_s}
                )
                events.append(
                    _event(
                        "attach_pending_started",
                        time_s,
                        next_state,
                        task,
                    )
                )
                return _result(task, next_state, next_runtime, events)
            events.append(
                _event(
                    "attach_request_rejected",
                    time_s,
                    state,
                    task,
                    reason=reason,
                    details=_attach_release_details(state, task.pickup.as_xyz()),
                )
            )
        return _result(task, state, runtime_state, events)

    if current_stage == "attach_pending":
        if _attach_rejection_reason(task, crane, state, config) is not None:
            next_state = state.model_copy(update={"task_stage": "lower_for_attach"})
            next_runtime = runtime_state.model_copy(
                update={"attach_pending_started_at_s": None}
            )
            events.append(
                _event(
                    "attach_pending_cancelled",
                    time_s,
                    next_state,
                    task,
                    reason="conditions_drifted",
                )
            )
            return _result(task, next_state, next_runtime, events)
        started_at = runtime_state.attach_pending_started_at_s
        if started_at is not None and time_s - started_at >= attach_delay_s:
            next_state = state.model_copy(
                update={
                    "load_attached": True,
                    "load_type": task.load_type,
                    "load_weight_t": task.load_weight_t,
                    "load_size_m": task.load_size_m,
                    "task_stage": "lift_load",
                }
            )
            next_runtime = runtime_state.model_copy(
                update={"attach_pending_started_at_s": None}
            )
            events.append(
                _event(
                    "load_attached",
                    time_s,
                    next_state,
                    task,
                    details={
                        "load_type": task.load_type,
                        "load_weight_t": task.load_weight_t,
                        "load_size_m": task.load_size_m,
                    },
                )
            )
            return _result(task, next_state, next_runtime, events)
        return _result(task, state, runtime_state, events)

    if current_stage == "lift_load":
        threshold = max(
            task.pickup.z + config.lift_clearance_m,
            config.safe_transport_height_m,
        )
        if state.hook_h_m >= threshold:
            return _stage_changed(task, state, runtime_state, events, "move_to_dropoff", time_s)
        return _result(task, state, runtime_state, events)

    if current_stage == "move_to_dropoff" and _xy_error(state, task.dropoff.as_xyz()) <= config.align_xy_threshold_m:
        return _stage_changed(task, state, runtime_state, events, "align_dropoff", time_s)

    if (
        current_stage == "align_dropoff"
        and _xy_error(state, task.dropoff.as_xyz()) <= config.align_xy_threshold_m
        and state.hook_h_m > task.dropoff.z + config.release_height_threshold_m
        and state.load_attached
    ):
        return _stage_changed(task, state, runtime_state, events, "lower_for_release", time_s)

    if current_stage in {"lower_for_release", "recovery_release"}:
        if signal.task_action == "request_release":
            reason = _release_rejection_reason(task, state, config)
            if reason is None:
                next_state = state.model_copy(update={"task_stage": "release_pending"})
                next_runtime = runtime_state.model_copy(
                    update={"release_pending_started_at_s": time_s}
                )
                events.append(
                    _event(
                        "release_pending_started",
                        time_s,
                        next_state,
                        task,
                    )
                )
                return _result(task, next_state, next_runtime, events)
            events.append(
                _event(
                    "release_request_rejected",
                    time_s,
                    state,
                    task,
                    reason=reason,
                    details=_attach_release_details(state, task.dropoff.as_xyz()),
                )
            )
        return _result(task, state, runtime_state, events)

    if current_stage == "release_pending":
        if _release_rejection_reason(task, state, config) is not None:
            fallback_stage = (
                "recovery_release"
                if task.task_type == "recovery_release"
                else "lower_for_release"
            )
            next_state = state.model_copy(update={"task_stage": fallback_stage})
            next_runtime = runtime_state.model_copy(
                update={"release_pending_started_at_s": None}
            )
            events.append(
                _event(
                    "release_pending_cancelled",
                    time_s,
                    next_state,
                    task,
                    reason="conditions_drifted",
                )
            )
            return _result(task, next_state, next_runtime, events)
        started_at = runtime_state.release_pending_started_at_s
        if started_at is not None and time_s - started_at >= release_delay_s:
            event_type = (
                "recovery_release_completed"
                if task.task_type == "recovery_release"
                else "task_completed"
            )
            next_task = task.model_copy(
                update={"status": "completed", "completed_at_s": time_s}
            )
            next_state = state.model_copy(
                update={
                    "load_attached": False,
                    "load_type": None,
                    "load_weight_t": 0.0,
                    "load_size_m": None,
                    "task_id": None,
                    "task_stage": "idle",
                }
            )
            next_runtime = runtime_state.model_copy(
                update={"release_pending_started_at_s": None}
            )
            events.append(
                _event(
                    "load_released",
                    time_s,
                    next_state,
                    next_task,
                    details={
                        "load_type": task.load_type,
                        "load_weight_t": task.load_weight_t,
                        "dropoff_zone_id": task.dropoff_zone_id,
                    },
                )
            )
            events.append(_event(event_type, time_s, next_state, next_task))
            return _result(next_task, next_state, next_runtime, events)
        return _result(task, state, runtime_state, events)

    return _result(task, state, runtime_state, events)


def _attach_rejection_reason(
    task: Task,
    crane: CraneConfig,
    state: CraneState,
    config: TaskStateMachineConfig,
) -> Optional[str]:
    if state.load_attached:
        return "load_already_attached"
    if _xy_error(state, task.pickup.as_xyz()) > config.attach_xy_threshold_m:
        return "xy_error_too_large"
    if abs(state.hook_h_m - task.pickup.z) > config.attach_height_threshold_m:
        return "height_error_too_large"
    if not _speeds_below_threshold(
        state,
        slew_deg_s=config.attach_speed_threshold.slew_deg_s,
        trolley_m_s=config.attach_speed_threshold.trolley_m_s,
        hoist_m_s=config.attach_speed_threshold.hoist_m_s,
    ):
        return "speed_above_threshold"
    radius = horizontal_distance(crane.base, state.hook_position)
    if crane.model.capacity_at_radius_t(radius) < task.load_weight_t:
        return "runtime_over_capacity"
    return None


def _release_rejection_reason(
    task: Task,
    state: CraneState,
    config: TaskStateMachineConfig,
) -> Optional[str]:
    if not state.load_attached:
        return "load_not_attached"
    if _xy_error(state, task.dropoff.as_xyz()) > config.release_xy_threshold_m:
        return "xy_error_too_large"
    if abs(state.hook_h_m - task.dropoff.z) > config.release_height_threshold_m:
        return "height_error_too_large"
    if not _speeds_below_threshold(
        state,
        slew_deg_s=config.release_speed_threshold.slew_deg_s,
        trolley_m_s=config.release_speed_threshold.trolley_m_s,
        hoist_m_s=config.release_speed_threshold.hoist_m_s,
    ):
        return "speed_above_threshold"
    return None


def _speeds_below_threshold(
    state: CraneState,
    *,
    slew_deg_s: float,
    trolley_m_s: float,
    hoist_m_s: float,
) -> bool:
    return (
        abs(state.theta_dot_rad_s) <= math.radians(slew_deg_s)
        and abs(state.trolley_v_m_s) <= trolley_m_s
        and abs(state.hoist_v_m_s) <= hoist_m_s
    )


def _xy_error(state: CraneState, target: List[float]) -> float:
    return horizontal_distance(state.hook_position, target)


def _stage_changed(
    task: Task,
    state: CraneState,
    runtime: TaskRuntimeState,
    events: List[TaskEventPayload],
    next_stage: str,
    time_s: float,
) -> TaskStateMachineResult:
    next_state = state.model_copy(update={"task_stage": next_stage})
    events.append(_event("task_stage_changed", time_s, next_state, task))
    return _result(task, next_state, runtime, events)


def _result(
    task: Task,
    state: CraneState,
    runtime: TaskRuntimeState,
    events: List[TaskEventPayload],
) -> TaskStateMachineResult:
    return TaskStateMachineResult(
        task=task,
        state=state,
        runtime=runtime,
        events=events,
    )


def _event(
    event_type: str,
    time_s: float,
    state: CraneState,
    task: Task,
    *,
    reason: Optional[str] = None,
    details: Optional[Dict[str, object]] = None,
) -> TaskEventPayload:
    return TaskEventPayload(
        event_type=event_type,
        time_s=time_s,
        frame_index=None,
        crane_id=state.crane_id,
        task_id=task.task_id,
        task_type=task.task_type,
        task_status=task.status,
        task_stage=state.task_stage,
        reason=reason,
        details=details or {},
    )


def _attach_release_details(state: CraneState, target: List[float]) -> Dict[str, object]:
    return {
        "xy_error_m": round(_xy_error(state, target), 6),
        "height_error_m": round(abs(state.hook_h_m - target[2]), 6),
        "slew_speed_deg_s": round(math.degrees(state.theta_dot_rad_s), 6),
        "trolley_speed_m_s": state.trolley_v_m_s,
        "hoist_speed_m_s": state.hoist_v_m_s,
        "load_attached": state.load_attached,
    }
