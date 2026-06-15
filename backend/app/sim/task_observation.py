from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from backend.app.schemas.state import CraneState
from backend.app.schemas.task import Task, TaskEventPayload, TaskPoint
from backend.app.sim.layout_geometry import horizontal_distance
from backend.app.sim.task_queue import current_target_for_stage


class TaskObservationContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0"
    crane_id: str
    time_s: float
    has_active_task: bool
    task_id: Optional[str] = None
    task_type: Optional[str] = None
    task_stage: str
    priority: Optional[str] = None
    deadline_s: Optional[float] = None
    deadline_missed: bool = False
    overtime_s: float = 0.0
    pickup: Optional[TaskPoint] = None
    dropoff: Optional[TaskPoint] = None
    current_target: Optional[TaskPoint] = None
    load_type: Optional[str] = None
    load_weight_t: Optional[float] = None
    load_size_m: Optional[List[float]] = None
    load_attached: bool = False
    ground_signal_hint: Optional[str] = None
    recent_task_events: List[Dict[str, object]] = Field(default_factory=list)
    crane_config: Optional[Any] = Field(default=None, exclude=True)
    state_machine_config: Optional[Any] = Field(default=None, exclude=True)


def build_task_observation_context(
    crane_id: str,
    state: CraneState,
    *,
    active_task: Optional[Task],
    time_s: float,
    recent_events: List[TaskEventPayload],
    crane_config: Optional[Any] = None,
    state_machine_config: Optional[Any] = None,
) -> TaskObservationContext:
    if active_task is None or state.task_stage == "idle":
        return TaskObservationContext(
            crane_id=crane_id,
            time_s=time_s,
            has_active_task=False,
            task_stage="idle",
            load_attached=state.load_attached,
            ground_signal_hint="当前无任务，请保持塔吊安全静止并观察现场。",
            recent_task_events=[
                event.model_dump(mode="json") for event in recent_events
            ],
            crane_config=crane_config,
            state_machine_config=state_machine_config,
        )

    target = current_target_for_stage(
        active_task,
        state.task_stage,
        state_machine_config=state_machine_config,
    )
    hint = _ground_signal_hint(state, active_task, target)
    return TaskObservationContext(
        crane_id=crane_id,
        time_s=time_s,
        has_active_task=True,
        task_id=active_task.task_id,
        task_type=active_task.task_type,
        task_stage=state.task_stage,
        priority=active_task.priority,
        deadline_s=active_task.deadline_s,
        deadline_missed=active_task.deadline_missed,
        overtime_s=active_task.overtime_s,
        pickup=active_task.pickup,
        dropoff=active_task.dropoff,
        current_target=target,
        load_type=active_task.load_type,
        load_weight_t=active_task.load_weight_t,
        load_size_m=active_task.load_size_m,
        load_attached=state.load_attached,
        ground_signal_hint=hint,
        recent_task_events=[event.model_dump(mode="json") for event in recent_events],
        crane_config=crane_config,
        state_machine_config=state_machine_config,
    )


def _ground_signal_hint(
    state: CraneState,
    task: Task,
    target: Optional[TaskPoint],
) -> Optional[str]:
    if target is None:
        return None
    dx = state.hook_position[0] - target.x
    dy = state.hook_position[1] - target.y
    dz = state.hook_position[2] - target.z
    horizontal_error = horizontal_distance(state.hook_position, target.as_xyz())
    east_west = "东侧" if dx > 0 else "西侧" if dx < 0 else "东西向对齐"
    north_south = "北侧" if dy > 0 else "南侧" if dy < 0 else "南北向对齐"
    height = "高度偏高" if dz > 0 else "高度偏低" if dz < 0 else "高度对齐"
    prefix = "当前处于恢复卸载，" if task.task_type == "recovery_release" else ""
    return (
        f"{prefix}吊钩在目标点{east_west} {abs(dx):.1f}m、{north_south} "
        f"{abs(dy):.1f}m，水平误差 {horizontal_error:.1f}m，{height} "
        f"{abs(dz):.1f}m，请进行局部微调。"
    )
