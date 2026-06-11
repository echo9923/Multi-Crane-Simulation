from __future__ import annotations

from backend.app.schemas.state import CraneState
from backend.app.schemas.task import Task, TaskPoint
from backend.app.sim.task_queue import (
    TaskSchedulerConfig,
    all_ordinary_tasks_terminal,
    build_idle_observation_context,
    complete_active_task,
    schedule_task_queues,
)


def _point(zone_type: str) -> TaskPoint:
    return TaskPoint(
        x=10.0,
        y=0.0,
        z=1.0 if zone_type == "material" else 20.0,
        zone_id=f"{zone_type}_zone",
        zone_type=zone_type,
    )


def _task(crane_id: str, index: int, planned_start_s: float | None = None) -> Task:
    return Task(
        task_id=f"T_{crane_id}_{index:03d}",
        crane_id=crane_id,
        task_type="easy_task",
        pickup=_point("material"),
        dropoff=_point("work"),
        pickup_zone_id="material_zone",
        dropoff_zone_id="work_zone",
        planned_start_s=planned_start_s,
        load_type="rebar_bundle",
        load_weight_t=2.0,
        load_size_m=[6.0, 1.0, 1.0],
        priority="medium",
        deadline_s=180.0,
        generation_seed=1,
        generation_attempt=0,
    )


def _state(crane_id: str) -> CraneState:
    return CraneState(
        crane_id=crane_id,
        theta_rad=0.0,
        theta_sin=0.0,
        theta_cos=1.0,
        trolley_r_m=10.0,
        hook_h_m=20.0,
        root_position=[0.0, 0.0, 50.0],
        tip_position=[50.0, 0.0, 50.0],
        hook_position=[10.0, 0.0, 20.0],
        cable_length_m=30.0,
    )


def test_simultaneous_first_task_activates_at_zero() -> None:
    queues = [schedule_task_queues.create_queue("C1", [_task("C1", 1, 0.0)])]
    states = {"C1": _state("C1")}

    result = schedule_task_queues(queues, states, time_s=0.0)

    queue = result.queues[0]
    assert queue.active_task_id == "T_C1_001"
    assert queue.tasks[0].status == "active"
    assert result.state_patches["C1"]["task_id"] == "T_C1_001"
    assert result.state_patches["C1"]["task_stage"] == "move_to_pickup"
    assert result.events[0].event_type == "task_started"


def test_staggered_first_task_waits_until_planned_start() -> None:
    queues = [schedule_task_queues.create_queue("C1", [_task("C1", 1, 5.0)])]
    states = {"C1": _state("C1")}

    before = schedule_task_queues(queues, states, time_s=4.9)
    after = schedule_task_queues(before.queues, states, time_s=5.0)

    assert before.queues[0].active_task_id is None
    assert before.state_patches == {}
    assert after.queues[0].active_task_id == "T_C1_001"


def test_scheduled_task_with_past_start_activates_immediately() -> None:
    queues = [schedule_task_queues.create_queue("C1", [_task("C1", 1, 3.0)])]
    states = {"C1": _state("C1")}

    result = schedule_task_queues(queues, states, time_s=10.0)

    assert result.queues[0].active_task_id == "T_C1_001"


def test_active_task_blocks_next_activation() -> None:
    queue = schedule_task_queues.create_queue(
        "C1",
        [_task("C1", 1, 0.0), _task("C1", 2, 0.0)],
    )
    first = schedule_task_queues([queue], {"C1": _state("C1")}, time_s=0.0)
    second = schedule_task_queues(first.queues, {"C1": _state("C1")}, time_s=20.0)

    assert second.queues[0].active_task_id == "T_C1_001"
    assert second.queues[0].next_task_index == 1


def test_completed_task_waits_for_inter_task_delay_and_planned_start() -> None:
    queue = schedule_task_queues.create_queue(
        "C1",
        [_task("C1", 1, 0.0), _task("C1", 2, 15.0)],
    )
    states = {"C1": _state("C1")}
    started = schedule_task_queues([queue], states, time_s=0.0)
    completed = complete_active_task(
        started.queues[0],
        states["C1"],
        time_s=3.0,
        inter_task_delay_s=10.0,
        status="completed",
    )

    delayed = schedule_task_queues([completed.queue], states, time_s=12.9)
    before_planned = schedule_task_queues([completed.queue], states, time_s=14.9)
    after = schedule_task_queues([completed.queue], states, time_s=15.0)

    assert delayed.queues[0].active_task_id is None
    assert before_planned.queues[0].active_task_id is None
    assert after.queues[0].active_task_id == "T_C1_002"


def test_recovery_block_prevents_ordinary_activation() -> None:
    queue = schedule_task_queues.create_queue("C1", [_task("C1", 1, 0.0)])
    queue = queue.model_copy(update={"blocked_by_recovery": True})

    result = schedule_task_queues([queue], {"C1": _state("C1")}, time_s=100.0)

    assert result.queues[0].active_task_id is None
    assert result.events == []


def test_idle_context_hides_next_task_details() -> None:
    queue = schedule_task_queues.create_queue("C1", [_task("C1", 1, 20.0)])
    context = build_idle_observation_context(queue, _state("C1"), time_s=0.0)
    payload = context.model_dump(mode="json")

    assert payload["has_active_task"] is False
    assert payload["task_id"] is None
    assert "T_C1_001" not in str(payload)
    assert payload["current_target"] is None


def test_all_ordinary_tasks_terminal_requires_no_recovery_block() -> None:
    terminal = schedule_task_queues.create_queue(
        "C1",
        [_task("C1", 1, 0.0).model_copy(update={"status": "completed"})],
    ).model_copy(update={"next_task_index": 1})
    blocked = terminal.model_copy(update={"blocked_by_recovery": True})
    active = terminal.model_copy(update={"active_task_id": "R_C1_T_C1_001"})

    assert all_ordinary_tasks_terminal([terminal]) is True
    assert all_ordinary_tasks_terminal([blocked]) is False
    assert all_ordinary_tasks_terminal([active]) is False


def test_scheduler_supports_arbitrary_crane_ids() -> None:
    queues = [
        schedule_task_queues.create_queue(f"TC_{index}", [_task(f"TC_{index}", 1, 0.0)])
        for index in range(1, 5)
    ]
    states = {queue.crane_id: _state(queue.crane_id) for queue in queues}

    result = schedule_task_queues(queues, states, time_s=0.0)

    assert {queue.active_task_id for queue in result.queues} == {
        "T_TC_1_001",
        "T_TC_2_001",
        "T_TC_3_001",
        "T_TC_4_001",
    }
