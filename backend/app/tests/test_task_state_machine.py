from __future__ import annotations

import math

from backend.app.schemas.config import ScenarioConfig
from backend.app.schemas.state import CraneState
from backend.app.schemas.task import Task, TaskActionSignal, TaskPoint
from backend.app.sim.crane_model import build_crane_model_library
from backend.app.sim.layout import build_crane_configs
from backend.app.sim.physics import recompute_state_geometry
from backend.app.sim.task_state_machine import TaskRuntimeState, step_task_state_machine
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


def _task(task_type: str = "easy_task") -> Task:
    return Task(
        task_id="T_C1_001" if task_type != "recovery_release" else "R_C1_T_C1_001",
        crane_id="C1",
        task_type=task_type,
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
            zone_id="work_a" if task_type != "recovery_release" else "recovery_a",
            zone_type="work" if task_type != "recovery_release" else "recovery",
        ),
        pickup_zone_id="mat_a",
        dropoff_zone_id="work_a" if task_type != "recovery_release" else "recovery_a",
        planned_start_s=0.0,
        load_type="rebar_bundle",
        load_weight_t=2.0,
        load_size_m=[6.0, 1.0, 1.0],
        priority="high" if task_type == "recovery_release" else "medium",
        deadline_s=None if task_type == "recovery_release" else 180.0,
        status="active",
        started_at_s=0.0,
        source_failed_task_id="T_C1_001" if task_type == "recovery_release" else None,
        generation_seed=1,
        generation_attempt=0,
    )


def _state_at(
    crane,
    *,
    x: float,
    y: float,
    z: float,
    stage: str,
    load_attached: bool = False,
    load_type: str | None = None,
    load_weight_t: float = 0.0,
    theta_dot: float = 0.0,
    trolley_v: float = 0.0,
    hoist_v: float = 0.0,
) -> CraneState:
    theta = math.atan2(y - crane.base[1], x - crane.base[0])
    radius = math.hypot(x - crane.base[0], y - crane.base[1])
    state = CraneState(
        crane_id=crane.crane_id,
        theta_rad=theta,
        theta_dot_rad_s=theta_dot,
        theta_sin=math.sin(theta),
        theta_cos=math.cos(theta),
        trolley_r_m=radius,
        trolley_v_m_s=trolley_v,
        hook_h_m=z,
        hoist_v_m_s=hoist_v,
        root_position=crane.root,
        tip_position=[0.0, 0.0, 0.0],
        hook_position=[x, y, z],
        cable_length_m=crane.root[2] - z,
        load_attached=load_attached,
        load_type=load_type,
        load_weight_t=load_weight_t,
        load_size_m=[6.0, 1.0, 1.0] if load_attached else None,
        task_id="T_C1_001",
        task_stage=stage,
    )
    return recompute_state_geometry(crane, state)


def _signal(action: str = "none") -> TaskActionSignal:
    return TaskActionSignal(
        crane_id="C1",
        command_id="cmd",
        time_s=0.0,
        task_action=action,
    )


def test_pickup_approach_advances_to_align_and_lower() -> None:
    scenario, crane = _scenario_and_crane()
    task = _task()
    state = _state_at(crane, x=20.5, y=0.0, z=10.0, stage="move_to_pickup")

    aligned = step_task_state_machine(
        task, crane, state, _signal(), time_s=1.0, config=scenario.tasks.state_machine
    )
    lowered = step_task_state_machine(
        aligned.task,
        crane,
        aligned.state,
        _signal(),
        time_s=2.0,
        config=scenario.tasks.state_machine,
    )

    assert aligned.state.task_stage == "align_pickup"
    assert lowered.state.task_stage == "lower_for_attach"


def test_attach_requires_request_conditions_and_delay() -> None:
    scenario, crane = _scenario_and_crane()
    task = _task()
    state = _state_at(crane, x=20.0, y=0.0, z=1.2, stage="lower_for_attach")

    pending = step_task_state_machine(
        task,
        crane,
        state,
        _signal("request_attach"),
        time_s=10.0,
        config=scenario.tasks.state_machine,
        runtime=TaskRuntimeState(),
        attach_delay_s=2.0,
    )
    attached = step_task_state_machine(
        pending.task,
        crane,
        pending.state,
        _signal(),
        time_s=12.0,
        config=scenario.tasks.state_machine,
        runtime=pending.runtime,
        attach_delay_s=2.0,
    )

    assert pending.state.task_stage == "attach_pending"
    assert attached.state.task_stage == "lift_load"
    assert attached.state.load_attached is True
    assert attached.state.load_type == "rebar_bundle"
    assert attached.events[-1].event_type == "load_attached"


def test_attach_pending_drift_cancels_without_setting_load() -> None:
    scenario, crane = _scenario_and_crane()
    task = _task()
    pending_state = _state_at(crane, x=20.0, y=0.0, z=1.2, stage="attach_pending")
    drifted = _state_at(crane, x=22.0, y=0.0, z=1.2, stage="attach_pending")

    result = step_task_state_machine(
        task,
        crane,
        drifted,
        _signal(),
        time_s=12.0,
        config=scenario.tasks.state_machine,
        runtime=TaskRuntimeState(attach_pending_started_at_s=10.0),
        attach_delay_s=2.0,
    )

    assert pending_state.task_stage == "attach_pending"
    assert result.state.task_stage == "lower_for_attach"
    assert result.state.load_attached is False
    assert result.events[-1].event_type == "attach_pending_cancelled"


def test_wrong_stage_attach_request_is_rejected() -> None:
    scenario, crane = _scenario_and_crane()
    state = _state_at(crane, x=5.0, y=0.0, z=20.0, stage="idle")

    result = step_task_state_machine(
        _task(),
        crane,
        state,
        _signal("request_attach"),
        time_s=5.0,
        config=scenario.tasks.state_machine,
    )

    assert result.state.load_attached is False
    assert result.state.task_stage == "idle"
    assert result.events[-1].event_type == "attach_request_rejected"


def test_lift_and_dropoff_release_complete_task() -> None:
    scenario, crane = _scenario_and_crane()
    task = _task()
    lifted = _state_at(
        crane,
        x=20.0,
        y=0.0,
        z=8.0,
        stage="lift_load",
        load_attached=True,
        load_type="rebar_bundle",
        load_weight_t=2.0,
    )
    moving = step_task_state_machine(
        task, crane, lifted, _signal(), time_s=20.0, config=scenario.tasks.state_machine
    )
    near_dropoff = _state_at(
        crane,
        x=25.0,
        y=0.0,
        z=35.0,
        stage="move_to_dropoff",
        load_attached=True,
        load_type="rebar_bundle",
        load_weight_t=2.0,
    )
    aligned = step_task_state_machine(
        moving.task,
        crane,
        near_dropoff,
        _signal(),
        time_s=21.0,
        config=scenario.tasks.state_machine,
    )
    lower = step_task_state_machine(
        aligned.task,
        crane,
        aligned.state,
        _signal(),
        time_s=22.0,
        config=scenario.tasks.state_machine,
    )
    at_release = _state_at(
        crane,
        x=25.0,
        y=0.0,
        z=30.2,
        stage=lower.state.task_stage,
        load_attached=True,
        load_type="rebar_bundle",
        load_weight_t=2.0,
    )
    pending = step_task_state_machine(
        lower.task,
        crane,
        at_release,
        _signal("request_release"),
        time_s=23.0,
        config=scenario.tasks.state_machine,
        release_delay_s=2.0,
    )
    completed = step_task_state_machine(
        pending.task,
        crane,
        pending.state,
        _signal(),
        time_s=25.0,
        config=scenario.tasks.state_machine,
        runtime=pending.runtime,
        release_delay_s=2.0,
    )

    assert moving.state.task_stage == "move_to_dropoff"
    assert aligned.state.task_stage == "align_dropoff"
    assert lower.state.task_stage == "lower_for_release"
    assert pending.state.task_stage == "release_pending"
    assert completed.task.status == "completed"
    assert completed.state.task_stage == "idle"
    assert completed.state.task_id is None
    assert completed.state.load_attached is False
    assert completed.state.load_type is None


def test_release_pending_drift_cancels_and_keeps_load() -> None:
    scenario, crane = _scenario_and_crane()
    drifted = _state_at(
        crane,
        x=27.0,
        y=0.0,
        z=30.2,
        stage="release_pending",
        load_attached=True,
        load_type="rebar_bundle",
        load_weight_t=2.0,
    )

    result = step_task_state_machine(
        _task(),
        crane,
        drifted,
        _signal(),
        time_s=12.0,
        config=scenario.tasks.state_machine,
        runtime=TaskRuntimeState(release_pending_started_at_s=10.0),
        release_delay_s=2.0,
    )

    assert result.state.task_stage == "lower_for_release"
    assert result.state.load_attached is True
    assert result.events[-1].event_type == "release_pending_cancelled"


def test_speed_threshold_and_runtime_capacity_reject_attach() -> None:
    scenario, crane = _scenario_and_crane()
    fast = _state_at(
        crane,
        x=20.0,
        y=0.0,
        z=1.2,
        stage="lower_for_attach",
        theta_dot=math.radians(2.0),
    )
    too_heavy = _task().model_copy(update={"load_weight_t": 100.0})

    fast_result = step_task_state_machine(
        _task(),
        crane,
        fast,
        _signal("request_attach"),
        time_s=10.0,
        config=scenario.tasks.state_machine,
    )
    capacity_result = step_task_state_machine(
        too_heavy,
        crane,
        fast.model_copy(update={"theta_dot_rad_s": 0.0}),
        _signal("request_attach"),
        time_s=11.0,
        config=scenario.tasks.state_machine,
    )

    assert fast_result.events[-1].reason == "speed_above_threshold"
    assert capacity_result.events[-1].reason == "runtime_over_capacity"


def test_recovery_release_uses_release_pending_and_clears_load() -> None:
    scenario, crane = _scenario_and_crane()
    task = _task("recovery_release")
    state = _state_at(
        crane,
        x=25.0,
        y=0.0,
        z=30.2,
        stage="recovery_release",
        load_attached=True,
        load_type="rebar_bundle",
        load_weight_t=2.0,
    )

    pending = step_task_state_machine(
        task,
        crane,
        state,
        _signal("request_release"),
        time_s=30.0,
        config=scenario.tasks.state_machine,
        release_delay_s=1.0,
    )
    completed = step_task_state_machine(
        pending.task,
        crane,
        pending.state,
        _signal(),
        time_s=31.0,
        config=scenario.tasks.state_machine,
        runtime=pending.runtime,
        release_delay_s=1.0,
    )

    assert pending.state.task_stage == "release_pending"
    assert completed.task.status == "completed"
    assert completed.state.load_attached is False
    assert completed.events[-1].event_type == "recovery_release_completed"
