from __future__ import annotations

from pathlib import Path

from backend.app.api.production_runner import (
    ProductionTaskSystem,
    build_production_episode_runner,
)
from backend.app.sim.task_failure import TaskFailureRuntimeState
from backend.app.sim.task_queue import schedule_task_queues
from backend.app.tests.test_task_failure_recovery import (
    _scenario_and_crane,
    _state,
    _task,
)
from backend.app.tests.test_production_runner import _production_smoke_config


def test_production_task_system_activates_tasks_and_builds_context(
    tmp_path: Path,
) -> None:
    runner = build_production_episode_runner(
        episode_id="E-production-task-system",
        resolved_config=_production_smoke_config(tmp_path),
    )

    assert any(queue.tasks for queue in runner.runner.task_queues)

    result = runner.run_one_frame()

    assert result.frame_index == 1
    assert any(queue.active_task_id for queue in runner.runner.task_queues)
    assert any(
        getattr(context, "has_active_task", False)
        or (
            isinstance(context, dict)
            and context.get("task", {}).get("has_active_task")
        )
        for context in runner.runner.task_contexts.values()
    )

    run_dir = runner.recorder.run_dir
    assert run_dir is not None
    assert runner.recorder.last_frame is not None
    assert any(
        event.get("event_type") == "task_started"
        for event in runner.recorder.last_frame.events
    )
    runner.recorder.finalize(episode_status=runner.episode_status)
    events = (run_dir / "logs" / "events.jsonl").read_text(encoding="utf-8")
    assert "task_started" in events


def test_production_task_system_writes_deadline_warning_back_to_queue() -> None:
    scenario, crane = _scenario_and_crane()
    system = ProductionTaskSystem(scenario=scenario, crane_configs=[crane])
    task = _task()
    queue = schedule_task_queues.create_queue("C1", [task]).model_copy(
        update={"active_task_id": task.task_id, "next_task_index": 1}
    )
    state = _state(crane, stage="move_to_pickup", x=19.0, y=0.0, z=10.0)

    result = system.update_after_physics(
        states=[state],
        commands={},
        time_s=12.0,
        task_queues=[queue],
    )

    queued_task = result.queues[0].tasks[0]
    assert queued_task.deadline_missed is True
    assert queued_task.overtime_s == 2.0
    assert queued_task.status == "active"
    assert result.queues[0].active_task_id == task.task_id


def test_production_task_system_writes_failed_source_task_before_recovery() -> None:
    scenario, crane = _scenario_and_crane()
    system = ProductionTaskSystem(scenario=scenario, crane_configs=[crane])
    task = _task()
    queue = schedule_task_queues.create_queue("C1", [task]).model_copy(
        update={"active_task_id": task.task_id, "next_task_index": 1}
    )
    state = _state(
        crane,
        stage="release_pending",
        load_attached=True,
        x=25.0,
        y=0.0,
        z=30.0,
    )
    system.failure_runtime[task.task_id] = TaskFailureRuntimeState(
        release_stage_started_at_s=70.0,
        last_progress_at_s=199.0,
    )

    result = system.update_after_physics(
        states=[state],
        commands={},
        time_s=200.0,
        task_queues=[queue],
    )

    tasks_by_id = {task.task_id: task for task in result.queues[0].tasks}
    assert tasks_by_id[task.task_id].status == "failed"
    assert tasks_by_id[task.task_id].failure_reason == "failed_release_timeout"
    recovery_task_id = f"R_C1_{task.task_id}"
    assert tasks_by_id[recovery_task_id].status == "active"
    assert result.queues[0].active_task_id == recovery_task_id
    assert result.queues[0].blocked_by_recovery is True


def test_production_task_system_starts_release_timeout_clock_on_release_stage() -> None:
    scenario, crane = _scenario_and_crane()
    system = ProductionTaskSystem(scenario=scenario, crane_configs=[crane])
    task = _task()
    queue = schedule_task_queues.create_queue("C1", [task]).model_copy(
        update={"active_task_id": task.task_id, "next_task_index": 1}
    )
    state = _state(
        crane,
        stage="align_dropoff",
        load_attached=True,
        x=25.0,
        y=0.0,
        z=30.0,
    )

    result = system.update_after_physics(
        states=[state],
        commands={},
        time_s=42.0,
        task_queues=[queue],
    )

    assert result.states[0].task_stage == "lower_for_release"
    assert system.failure_runtime[task.task_id].release_stage_started_at_s == 42.0
    assert system.failure_runtime[task.task_id].last_progress_at_s == 42.0


def test_production_task_system_refreshes_no_progress_clock_on_stage_progress() -> None:
    scenario, crane = _scenario_and_crane()
    system = ProductionTaskSystem(scenario=scenario, crane_configs=[crane])
    task = _task()
    queue = schedule_task_queues.create_queue("C1", [task]).model_copy(
        update={"active_task_id": task.task_id, "next_task_index": 1}
    )
    state = _state(crane, stage="move_to_pickup", x=20.0, y=0.0, z=10.0)
    system.failure_runtime[task.task_id] = TaskFailureRuntimeState(
        last_progress_at_s=0.0,
    )

    result = system.update_after_physics(
        states=[state],
        commands={},
        time_s=30.0,
        task_queues=[queue],
    )

    assert result.states[0].task_stage == "align_pickup"
    assert system.failure_runtime[task.task_id].last_progress_at_s == 30.0


def test_production_task_system_refreshes_no_progress_clock_on_hook_progress() -> None:
    scenario, crane = _scenario_and_crane()
    system = ProductionTaskSystem(scenario=scenario, crane_configs=[crane])
    task = _task()
    queue = schedule_task_queues.create_queue("C1", [task]).model_copy(
        update={"active_task_id": task.task_id, "next_task_index": 1}
    )
    system.failure_runtime[task.task_id] = TaskFailureRuntimeState(
        last_progress_at_s=0.0,
    )
    first = _state(crane, stage="move_to_pickup", x=16.0, y=0.0, z=10.0)
    second = _state(crane, stage="move_to_pickup", x=16.5, y=0.0, z=10.0)

    primed = system.update_after_physics(
        states=[first],
        commands={},
        time_s=10.0,
        task_queues=[queue],
    )
    result = system.update_after_physics(
        states=[second],
        commands={},
        time_s=20.0,
        task_queues=primed.queues,
    )

    assert result.states[0].task_stage == "move_to_pickup"
    assert system.failure_runtime[task.task_id].last_progress_at_s == 20.0
