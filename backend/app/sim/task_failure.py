from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict

from backend.app.schemas.config import ScenarioConfig
from backend.app.schemas.crane import CraneConfig
from backend.app.schemas.state import CraneState
from backend.app.schemas.task import Task, TaskEventPayload, TaskPoint, TaskQueue
from backend.app.sim.layout_geometry import (
    horizontal_distance,
    point_in_boundary,
    point_in_zone,
)


class TaskFailureRuntimeState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    release_stage_started_at_s: Optional[float] = None
    last_progress_at_s: Optional[float] = None
    recovery_started_at_s: Optional[float] = None


class TaskFailureResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task: Task
    state: CraneState
    runtime: TaskFailureRuntimeState
    events: List[TaskEventPayload]
    recovery_task: Optional[Task] = None
    queue: Optional[TaskQueue] = None
    episode_failure_request: Optional[str] = None


def handle_task_timing_and_failures(
    task: Task,
    state: CraneState,
    scenario: ScenarioConfig,
    crane: CraneConfig,
    *,
    time_s: float,
    runtime: TaskFailureRuntimeState,
    queue: Optional[TaskQueue] = None,
) -> TaskFailureResult:
    events: List[TaskEventPayload] = []
    updated_task = task
    updated_state = state
    updated_runtime = runtime
    updated_queue = queue

    if task.task_type == "recovery_release":
        if task.status == "completed" and queue is not None and not state.load_attached:
            return _result(
                task,
                state,
                runtime,
                events,
                queue=queue.model_copy(update={"blocked_by_recovery": False}),
            )
        if (
            runtime.recovery_started_at_s is not None
            and time_s - runtime.recovery_started_at_s
            > scenario.tasks.state_machine.recovery_release_timeout_s
            and task.status == "active"
        ):
            failed = task.model_copy(
                update={
                    "status": "failed",
                    "failed_at_s": time_s,
                    "failure_reason": "failed_recovery_timeout",
                }
            )
            events.append(
                _event(
                    "recovery_release_failed",
                    time_s,
                    state,
                    failed,
                    reason="failed_recovery_timeout",
                    details={"error_code": "TASK_E_104", "load_attached": state.load_attached},
                )
            )
            return _result(
                failed,
                state,
                runtime,
                events,
                queue=_replace_task_in_queue(queue, failed) if queue is not None else None,
                episode_failure_request="failed_recovery_timeout",
            )

    if scenario.tasks.deadline_policy.enabled:
        updated_task, deadline_events = _update_deadline(updated_task, state, time_s)
        events.extend(deadline_events)

    attach_timeout = scenario.tasks.state_machine.attach_stage_timeout_s
    release_timeout = scenario.tasks.state_machine.release_stage_timeout_s
    no_progress_timeout = scenario.tasks.state_machine.task_no_progress_timeout_s

    if (
        state.task_stage
        in {"move_to_pickup", "align_pickup", "lower_for_attach", "attach_pending"}
        and task.started_at_s is not None
        and time_s - task.started_at_s > attach_timeout
    ):
        if state.load_attached:
            events.append(
                _event(
                    "task_failed",
                    time_s,
                    state,
                    updated_task,
                    reason="failed_invalid_state",
                    details={"error_code": "TASK_E_101", "load_attached": True},
                )
            )
            return _result(
                updated_task,
                state,
                runtime,
                events,
                queue=queue,
                episode_failure_request="failed_invalid_state",
            )
        return _fail_without_recovery(
            updated_task,
            state,
            runtime,
            events,
            time_s,
            failure_reason="failed_attach_timeout",
            error_code="TASK_E_101",
            queue=queue,
        )

    if (
        state.task_stage
        in {"move_to_dropoff", "align_dropoff", "lower_for_release", "release_pending"}
        and runtime.release_stage_started_at_s is not None
        and time_s - runtime.release_stage_started_at_s > release_timeout
    ):
        if state.load_attached:
            return _enter_recovery(
                updated_task,
                state,
                runtime,
                events,
                time_s,
                scenario,
                crane,
                failure_reason="failed_release_timeout",
                error_code="TASK_E_103",
                queue=queue,
            )
        return _fail_without_recovery(
            updated_task,
            state,
            runtime,
            events,
            time_s,
            failure_reason="failed_release_timeout",
            error_code="TASK_E_102",
            queue=queue,
        )

    if (
        runtime.last_progress_at_s is not None
        and time_s - runtime.last_progress_at_s > no_progress_timeout
        and task.status == "active"
    ):
        if state.load_attached:
            return _enter_recovery(
                updated_task,
                state,
                runtime,
                events,
                time_s,
                scenario,
                crane,
                failure_reason="failed_no_progress_timeout",
                error_code="TASK_E_103",
                queue=queue,
            )
        return _fail_without_recovery(
            updated_task,
            state,
            runtime,
            events,
            time_s,
            failure_reason="failed_no_progress_timeout",
            error_code="TASK_E_101",
            queue=queue,
        )

    if updated_queue is not None:
        updated_queue = _replace_task_in_queue(updated_queue, updated_task)

    return _result(
        updated_task,
        updated_state,
        updated_runtime,
        events,
        queue=updated_queue,
    )


def _update_deadline(
    task: Task,
    state: CraneState,
    time_s: float,
) -> tuple[Task, List[TaskEventPayload]]:
    if task.deadline_s is None or task.started_at_s is None or task.status != "active":
        return task, []
    deadline_time = task.started_at_s + task.deadline_s
    overtime = max(0.0, time_s - deadline_time)
    if overtime <= 0:
        return task.model_copy(update={"overtime_s": 0.0}), []
    events: List[TaskEventPayload] = []
    updated = task.model_copy(
        update={
            "deadline_missed": True,
            "overtime_s": overtime,
        }
    )
    if not task.deadline_missed:
        events.append(
            _event(
                "deadline_missed",
                time_s,
                state,
                updated,
                reason="deadline_missed",
                details={
                    "deadline_s": task.deadline_s,
                    "started_at_s": task.started_at_s,
                    "deadline_time_s": deadline_time,
                    "overtime_s": overtime,
                    "priority": task.priority,
                },
            )
        )
    return updated, events


def _fail_without_recovery(
    task: Task,
    state: CraneState,
    runtime: TaskFailureRuntimeState,
    events: List[TaskEventPayload],
    time_s: float,
    *,
    failure_reason: str,
    error_code: str,
    queue: Optional[TaskQueue],
) -> TaskFailureResult:
    failed = task.model_copy(
        update={
            "status": "failed",
            "failed_at_s": time_s,
            "failure_reason": failure_reason,
        }
    )
    next_state = state.model_copy(update={"task_id": None, "task_stage": "idle"})
    events.append(
        _event(
            "task_failed",
            time_s,
            next_state,
            failed,
            reason=failure_reason,
            details={"error_code": error_code, "load_attached": state.load_attached},
        )
    )
    next_queue = queue
    if queue is not None:
        next_queue = _replace_task_in_queue(queue, failed).model_copy(
            update={"active_task_id": None}
        )
    return _result(failed, next_state, runtime, events, queue=next_queue)


def _enter_recovery(
    task: Task,
    state: CraneState,
    runtime: TaskFailureRuntimeState,
    events: List[TaskEventPayload],
    time_s: float,
    scenario: ScenarioConfig,
    crane: CraneConfig,
    *,
    failure_reason: str,
    error_code: str,
    queue: Optional[TaskQueue],
) -> TaskFailureResult:
    failed = task.model_copy(
        update={
            "status": "failed",
            "failed_at_s": time_s,
            "failure_reason": failure_reason,
        }
    )
    next_state = state.model_copy(update={"task_stage": "recovery_release"})
    if not _recovery_target_available(failed.dropoff, scenario, crane):
        events.append(
            _event(
                "recovery_release_failed",
                time_s,
                next_state,
                failed,
                reason="failed_recovery_blocked",
                details={"error_code": "TASK_E_105", "load_attached": state.load_attached},
            )
        )
        return _result(
            failed,
            next_state,
            runtime,
            events,
            queue=_replace_task_in_queue(queue, failed) if queue is not None else None,
            episode_failure_request="failed_recovery_blocked",
        )
    recovery = _create_recovery_task(failed, state, crane, time_s)
    next_runtime = runtime.model_copy(update={"recovery_started_at_s": time_s})
    events.append(
        _event(
            "task_failed",
            time_s,
            next_state,
            failed,
            reason=failure_reason,
            details={
                "error_code": error_code,
                "load_attached": state.load_attached,
                "recovery_task_id": recovery.task_id,
            },
        )
    )
    events.append(
        _event(
            "recovery_release_started",
            time_s,
            next_state,
            recovery,
            reason=failure_reason,
            details={"source_failed_task_id": failed.task_id},
        )
    )
    next_queue = (
        _replace_task_in_queue(queue, failed).model_copy(
            update={"blocked_by_recovery": True}
        )
        if queue
        else None
    )
    return _result(
        failed,
        next_state,
        next_runtime,
        events,
        recovery_task=recovery,
        queue=next_queue,
    )


def _create_recovery_task(
    failed_task: Task,
    state: CraneState,
    crane: CraneConfig,
    time_s: float,
) -> Task:
    pickup = TaskPoint(
        x=state.hook_position[0],
        y=state.hook_position[1],
        z=state.hook_position[2],
        zone_id="current_load_position",
        zone_type="recovery",
    )
    dropoff = failed_task.dropoff.model_copy(update={"zone_type": "recovery"})
    return Task(
        task_id=f"R_{failed_task.crane_id}_{failed_task.task_id}",
        crane_id=failed_task.crane_id,
        task_type="recovery_release",
        pickup=pickup,
        dropoff=dropoff,
        pickup_zone_id="current_load_position",
        dropoff_zone_id=dropoff.zone_id,
        planned_start_s=time_s,
        load_type=state.load_type or failed_task.load_type,
        load_weight_t=state.load_weight_t or failed_task.load_weight_t,
        load_size_m=state.load_size_m or failed_task.load_size_m,
        priority="high",
        deadline_s=None,
        status="active",
        started_at_s=time_s,
        source_failed_task_id=failed_task.task_id,
        generation_seed=failed_task.generation_seed,
        generation_attempt=0,
    )


def _recovery_target_available(
    target: TaskPoint,
    scenario: ScenarioConfig,
    crane: CraneConfig,
) -> bool:
    radius = horizontal_distance(crane.base, target.as_xyz())
    if radius < crane.trolley_r_min_m or radius > crane.trolley_r_max_m:
        return False
    if target.z < crane.hook_h_min_world_m or target.z > crane.hook_h_max_world_m:
        return False
    if not point_in_boundary(target.as_xyz(), scenario.site.boundary):
        return False
    for zone in scenario.site.forbidden_zones:
        if point_in_zone(target.as_xyz(), zone):
            return False
    return True


def _replace_task_in_queue(queue: TaskQueue, task: Task) -> TaskQueue:
    tasks = [task if existing.task_id == task.task_id else existing for existing in queue.tasks]
    return queue.model_copy(update={"tasks": tasks})


def _result(
    task: Task,
    state: CraneState,
    runtime: TaskFailureRuntimeState,
    events: List[TaskEventPayload],
    *,
    recovery_task: Optional[Task] = None,
    queue: Optional[TaskQueue] = None,
    episode_failure_request: Optional[str] = None,
) -> TaskFailureResult:
    return TaskFailureResult(
        task=task,
        state=state,
        runtime=runtime,
        events=events,
        recovery_task=recovery_task,
        queue=queue,
        episode_failure_request=episode_failure_request,
    )


def _event(
    event_type: str,
    time_s: float,
    state: CraneState,
    task: Task,
    *,
    reason: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
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
