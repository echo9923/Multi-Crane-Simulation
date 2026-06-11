from __future__ import annotations

from typing import Any, Dict, List, Sequence

from pydantic import BaseModel, ConfigDict, Field

from backend.app.schemas.state import CraneState
from backend.app.schemas.task import Task, TaskEventPayload, TaskPoint, TaskQueue


class TaskSchedulerConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    inter_task_delay_s: float = Field(default=0.0, ge=0)


class TaskSchedulingResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    queues: List[TaskQueue]
    state_patches: Dict[str, Dict[str, Any]]
    events: List[TaskEventPayload]


class ActiveTaskCompletionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    queue: TaskQueue
    state_patch: Dict[str, Any]
    event: TaskEventPayload


class IdleObservationContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0"
    crane_id: str
    time_s: float
    has_active_task: bool
    task_id: None
    task_stage: str
    current_target: None
    ground_signal_hint: str


def create_queue(crane_id: str, tasks: Sequence[Task]) -> TaskQueue:
    return TaskQueue(crane_id=crane_id, tasks=list(tasks))


def schedule_task_queues(
    queues: Sequence[TaskQueue],
    states: Dict[str, CraneState],
    *,
    time_s: float,
) -> TaskSchedulingResult:
    next_queues: List[TaskQueue] = []
    state_patches: Dict[str, Dict[str, Any]] = {}
    events: List[TaskEventPayload] = []

    for queue in queues:
        updated = queue
        if _can_activate(queue, time_s):
            task = queue.tasks[queue.next_task_index]
            started = task.model_copy(
                update={
                    "status": "active",
                    "started_at_s": time_s,
                }
            )
            tasks = list(queue.tasks)
            tasks[queue.next_task_index] = started
            updated = queue.model_copy(
                update={
                    "tasks": tasks,
                    "active_task_id": started.task_id,
                    "next_task_index": queue.next_task_index + 1,
                }
            )
            state_patches[queue.crane_id] = {
                "task_id": started.task_id,
                "task_stage": "move_to_pickup",
            }
            events.append(
                TaskEventPayload(
                    event_type="task_started",
                    time_s=time_s,
                    frame_index=None,
                    crane_id=queue.crane_id,
                    task_id=started.task_id,
                    task_type=started.task_type,
                    task_status="active",
                    task_stage="move_to_pickup",
                    reason=None,
                    details={"planned_start_s": started.planned_start_s},
                )
            )
        next_queues.append(updated)

    return TaskSchedulingResult(
        queues=next_queues,
        state_patches=state_patches,
        events=events,
    )


def complete_active_task(
    queue: TaskQueue,
    state: CraneState,
    *,
    time_s: float,
    inter_task_delay_s: float,
    status: str,
) -> ActiveTaskCompletionResult:
    if queue.active_task_id is None:
        raise ValueError("queue has no active task")
    tasks = list(queue.tasks)
    active_index = next(
        index for index, task in enumerate(tasks) if task.task_id == queue.active_task_id
    )
    active = tasks[active_index]
    update: Dict[str, Any] = {"status": status}
    if status == "completed":
        update["completed_at_s"] = time_s
    elif status == "failed":
        update["failed_at_s"] = time_s
    tasks[active_index] = active.model_copy(update=update)
    updated_queue = queue.model_copy(
        update={
            "tasks": tasks,
            "active_task_id": None,
            "last_completed_task_id": active.task_id if status == "completed" else None,
            "ready_after_s": time_s + inter_task_delay_s,
        }
    )
    patch = {"task_id": None, "task_stage": "idle"}
    return ActiveTaskCompletionResult(
        queue=updated_queue,
        state_patch=patch,
        event=TaskEventPayload(
            event_type=f"task_{status}",
            time_s=time_s,
            frame_index=None,
            crane_id=state.crane_id,
            task_id=active.task_id,
            task_type=active.task_type,
            task_status=status,
            task_stage="idle",
            details={},
        ),
    )


def build_idle_observation_context(
    queue: TaskQueue,
    state: CraneState,
    *,
    time_s: float,
) -> IdleObservationContext:
    return IdleObservationContext(
        crane_id=queue.crane_id,
        time_s=time_s,
        has_active_task=False,
        task_id=None,
        task_stage=state.task_stage,
        current_target=None,
        ground_signal_hint="当前无任务，请保持塔吊安全静止并观察现场。",
    )


def all_ordinary_tasks_terminal(queues: Sequence[TaskQueue]) -> bool:
    terminal_statuses = {"completed", "failed", "skipped"}
    for queue in queues:
        if queue.blocked_by_recovery or queue.active_task_id is not None:
            return False
        if any(task.status not in terminal_statuses for task in queue.tasks):
            return False
    return True


def current_target_for_stage(task: Task, stage: str) -> TaskPoint | None:
    if stage in {
        "move_to_pickup",
        "align_pickup",
        "lower_for_attach",
        "attach_pending",
    }:
        return task.pickup
    if stage == "lift_load":
        return task.pickup.model_copy(
            update={"z": max(task.pickup.z, task.dropoff.z)}
        )
    if stage in {
        "move_to_dropoff",
        "align_dropoff",
        "lower_for_release",
        "release_pending",
        "recovery_release",
    }:
        return task.dropoff
    return None


def _can_activate(queue: TaskQueue, time_s: float) -> bool:
    if queue.blocked_by_recovery:
        return False
    if queue.active_task_id is not None:
        return False
    if queue.next_task_index >= len(queue.tasks):
        return False
    if time_s < queue.ready_after_s:
        return False
    task = queue.tasks[queue.next_task_index]
    if task.status != "pending":
        return False
    if task.planned_start_s is not None and time_s < task.planned_start_s:
        return False
    return True


schedule_task_queues.create_queue = create_queue  # type: ignore[attr-defined]
