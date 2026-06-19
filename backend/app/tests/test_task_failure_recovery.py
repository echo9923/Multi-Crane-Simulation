from __future__ import annotations

import math

from backend.app.schemas.config import ScenarioConfig
from backend.app.schemas.state import CraneState
from backend.app.schemas.task import Task, TaskPoint
from backend.app.sim.crane_model import build_crane_model_library
from backend.app.sim.layout import build_crane_configs
from backend.app.sim.physics import recompute_state_geometry
from backend.app.sim.task_failure import (
    TaskFailureRuntimeState,
    handle_task_timing_and_failures,
)
from backend.app.sim.task_queue import schedule_task_queues
from backend.app.tests.test_config_schema import load_fixture


def _scenario_and_crane():
    raw = load_fixture("scenario_valid.yaml")
    raw["layout"]["mode"] = "manual"
    raw["layout"]["num_cranes"] = 1
    raw["cranes"] = [
        {
            "crane_id": "C1",
            "model_id": "generic_flat_top_55m",
            "base": [0.0, 0.0, 0.0],
            "mast_height_m": 50.0,
            "theta_init_deg": 0.0,
            "slew": {"mode": "continuous"},
        }
    ]
    scenario = ScenarioConfig.model_validate(raw)
    library = build_crane_model_library(scenario.crane_models)
    crane = build_crane_configs(scenario.cranes, library, scenario, source="manual")[0]
    return scenario, crane


def _task(stage: str = "move_to_pickup") -> Task:
    return Task(
        task_id="T_C1_001",
        crane_id="C1",
        task_type="easy_task",
        pickup=TaskPoint(
            x=20.0,
            y=0.0,
            z=1.0,
            zone_id="mat_a",
            zone_type="material",
        ),
        dropoff=TaskPoint(
            x=25.0,
            y=0.0,
            z=30.0,
            zone_id="work_a",
            zone_type="work",
        ),
        pickup_zone_id="mat_a",
        dropoff_zone_id="work_a",
        planned_start_s=0.0,
        load_type="rebar_bundle",
        load_weight_t=2.0,
        load_size_m=[6.0, 1.0, 1.0],
        priority="medium",
        deadline_s=10.0,
        status="active",
        started_at_s=0.0,
        generation_seed=1,
        generation_attempt=0,
    )


def _state(
    crane,
    *,
    stage: str,
    load_attached: bool = False,
    x: float = 20.0,
    y: float = 0.0,
    z: float = 10.0,
) -> CraneState:
    theta = math.atan2(y - crane.base[1], x - crane.base[0])
    radius = math.hypot(x - crane.base[0], y - crane.base[1])
    state = CraneState(
        crane_id=crane.crane_id,
        theta_rad=theta,
        theta_sin=math.sin(theta),
        theta_cos=math.cos(theta),
        trolley_r_m=radius,
        hook_h_m=z,
        root_position=crane.root,
        tip_position=[0.0, 0.0, 0.0],
        hook_position=[x, y, z],
        cable_length_m=crane.root[2] - z,
        load_attached=load_attached,
        load_type="rebar_bundle" if load_attached else None,
        load_weight_t=2.0 if load_attached else 0.0,
        load_size_m=[6.0, 1.0, 1.0] if load_attached else None,
        task_id="T_C1_001",
        task_stage=stage,
    )
    return recompute_state_geometry(crane, state)


def test_deadline_missed_only_marks_warning_and_updates_overtime() -> None:
    scenario, crane = _scenario_and_crane()
    task = _task()
    state = _state(crane, stage="move_to_pickup")
    queue = schedule_task_queues.create_queue("C1", [task]).model_copy(
        update={"active_task_id": task.task_id, "next_task_index": 1}
    )

    missed = handle_task_timing_and_failures(
        task,
        state,
        scenario,
        crane,
        time_s=12.0,
        runtime=TaskFailureRuntimeState(last_progress_at_s=0.0),
        queue=queue,
    )
    later = handle_task_timing_and_failures(
        missed.task,
        missed.state,
        scenario,
        crane,
        time_s=15.0,
        runtime=missed.runtime,
        queue=missed.queue,
    )

    assert missed.task.deadline_missed is True
    assert missed.task.status == "active"
    assert missed.queue is not None
    assert missed.queue.tasks[0].deadline_missed is True
    assert missed.events[0].event_type == "deadline_missed"
    assert later.task.overtime_s == 5.0
    assert later.queue is not None
    assert later.queue.tasks[0].overtime_s == 5.0


def test_attach_timeout_without_load_fails_task_and_idles_state() -> None:
    scenario, crane = _scenario_and_crane()
    state = _state(crane, stage="lower_for_attach")

    result = handle_task_timing_and_failures(
        _task(),
        state,
        scenario,
        crane,
        time_s=121.0,
        runtime=TaskFailureRuntimeState(last_progress_at_s=0.0),
    )

    assert result.task.status == "failed"
    assert result.task.failure_reason == "failed_attach_timeout"
    assert result.state.task_stage == "idle"
    assert result.state.task_id is None
    assert result.events[-1].details["error_code"] == "TASK_E_101"
    assert result.episode_failure_request is None


def test_attach_timeout_with_load_requests_invalid_state_failure() -> None:
    scenario, crane = _scenario_and_crane()
    state = _state(crane, stage="attach_pending", load_attached=True)

    result = handle_task_timing_and_failures(
        _task(),
        state,
        scenario,
        crane,
        time_s=121.0,
        runtime=TaskFailureRuntimeState(last_progress_at_s=0.0),
    )

    assert result.episode_failure_request == "failed_invalid_state"
    assert result.state.load_attached is True


def test_release_timeout_without_load_fails_and_continues() -> None:
    scenario, crane = _scenario_and_crane()
    state = _state(crane, stage="release_pending", load_attached=False)

    result = handle_task_timing_and_failures(
        _task(),
        state,
        scenario,
        crane,
        time_s=200.0,
        runtime=TaskFailureRuntimeState(
            release_stage_started_at_s=70.0,
            last_progress_at_s=190.0,
        ),
    )

    assert result.task.status == "failed"
    assert result.task.failure_reason == "failed_release_timeout"
    assert result.events[-1].details["error_code"] == "TASK_E_102"
    assert result.episode_failure_request is None


def test_release_timeout_with_load_creates_recovery_task_and_blocks_queue() -> None:
    scenario, crane = _scenario_and_crane()
    state = _state(crane, stage="release_pending", load_attached=True, x=25.0, z=30.0)
    queue = schedule_task_queues.create_queue(
        "C1",
        [
            _task(),
            _task().model_copy(update={"task_id": "T_C1_002", "status": "pending"}),
        ],
    ).model_copy(update={"active_task_id": "T_C1_001", "next_task_index": 1})

    result = handle_task_timing_and_failures(
        _task(),
        state,
        scenario,
        crane,
        time_s=200.0,
        runtime=TaskFailureRuntimeState(
            release_stage_started_at_s=70.0,
            last_progress_at_s=190.0,
        ),
        queue=queue,
    )

    assert result.task.status == "failed"
    assert result.state.task_stage == "recovery_release"
    assert result.state.load_attached is True
    assert result.recovery_task is not None
    assert result.recovery_task.task_id == "R_C1_T_C1_001"
    assert result.queue is not None
    assert result.queue.blocked_by_recovery is True
    tasks_by_id = {task.task_id: task for task in result.queue.tasks}
    assert tasks_by_id["T_C1_001"].status == "failed"
    assert tasks_by_id["T_C1_001"].failure_reason == "failed_release_timeout"
    assert result.events[-2].details["error_code"] == "TASK_E_103"
    assert result.events[-1].event_type == "recovery_release_started"


def test_recovery_completion_unblocks_queue() -> None:
    scenario, crane = _scenario_and_crane()
    recovery = _task().model_copy(
        update={
            "task_id": "R_C1_T_C1_001",
            "task_type": "recovery_release",
            "status": "completed",
        }
    )
    state = _state(crane, stage="idle", load_attached=False)
    queue = schedule_task_queues.create_queue("C1", [_task()]).model_copy(
        update={"blocked_by_recovery": True}
    )

    result = handle_task_timing_and_failures(
        recovery,
        state,
        scenario,
        crane,
        time_s=10.0,
        runtime=TaskFailureRuntimeState(recovery_started_at_s=0.0),
        queue=queue,
    )

    assert result.queue is not None
    assert result.queue.blocked_by_recovery is False


def test_recovery_timeout_returns_episode_failure_request_without_clearing_load() -> None:
    scenario, crane = _scenario_and_crane()
    recovery = _task().model_copy(
        update={
            "task_id": "R_C1_T_C1_001",
            "task_type": "recovery_release",
            "source_failed_task_id": "T_C1_001",
            "status": "active",
        }
    )
    state = _state(crane, stage="recovery_release", load_attached=True)
    queue = schedule_task_queues.create_queue("C1", [recovery]).model_copy(
        update={"active_task_id": recovery.task_id, "blocked_by_recovery": True}
    )

    result = handle_task_timing_and_failures(
        recovery,
        state,
        scenario,
        crane,
        time_s=181.0,
        runtime=TaskFailureRuntimeState(recovery_started_at_s=0.0),
        queue=queue,
    )

    assert result.task.status == "failed"
    assert result.task.failure_reason == "failed_recovery_timeout"
    assert result.queue is not None
    assert result.queue.tasks[0].status == "failed"
    assert result.queue.tasks[0].failure_reason == "failed_recovery_timeout"
    assert result.state.load_attached is True
    assert result.episode_failure_request == "failed_recovery_timeout"
    assert result.events[-1].details["error_code"] == "TASK_E_104"


def test_blocked_recovery_target_returns_task_e_105_without_clearing_load() -> None:
    scenario, crane = _scenario_and_crane()
    blocked_task = _task().model_copy(
        update={
            "dropoff": _task().dropoff.model_copy(update={"x": 80.0}),
        }
    )
    state = _state(crane, stage="release_pending", load_attached=True, x=25.0, z=30.0)
    queue = schedule_task_queues.create_queue("C1", [blocked_task]).model_copy(
        update={"active_task_id": blocked_task.task_id, "next_task_index": 1}
    )

    result = handle_task_timing_and_failures(
        blocked_task,
        state,
        scenario,
        crane,
        time_s=200.0,
        runtime=TaskFailureRuntimeState(
            release_stage_started_at_s=70.0,
            last_progress_at_s=190.0,
        ),
        queue=queue,
    )

    assert result.recovery_task is None
    assert result.queue is not None
    assert result.queue.tasks[0].status == "failed"
    assert result.queue.tasks[0].failure_reason == "failed_release_timeout"
    assert result.state.load_attached is True
    assert result.episode_failure_request == "failed_recovery_blocked"
    assert result.events[-1].details["error_code"] == "TASK_E_105"


def test_no_progress_timeout_fails_without_load_or_enters_recovery_with_load() -> None:
    scenario, crane = _scenario_and_crane()
    scenario = scenario.model_copy(
        update={
            "tasks": scenario.tasks.model_copy(
                update={
                    "state_machine": scenario.tasks.state_machine.model_copy(
                        update={"task_no_progress_timeout_s": 5.0}
                    )
                }
            )
        }
    )
    no_load = _state(crane, stage="move_to_pickup", load_attached=False)
    with_load = _state(crane, stage="move_to_dropoff", load_attached=True)

    failed = handle_task_timing_and_failures(
        _task(),
        no_load,
        scenario,
        crane,
        time_s=6.0,
        runtime=TaskFailureRuntimeState(last_progress_at_s=0.0),
    )
    recovery = handle_task_timing_and_failures(
        _task(),
        with_load,
        scenario,
        crane,
        time_s=6.0,
        runtime=TaskFailureRuntimeState(
            release_stage_started_at_s=1.0,
            last_progress_at_s=0.0,
        ),
    )

    assert failed.task.failure_reason == "failed_no_progress_timeout"
    assert failed.state.task_stage == "idle"
    assert recovery.task.failure_reason == "failed_no_progress_timeout"
    assert recovery.recovery_task is not None
    assert recovery.state.task_stage == "recovery_release"
    assert recovery.state.load_attached is True
