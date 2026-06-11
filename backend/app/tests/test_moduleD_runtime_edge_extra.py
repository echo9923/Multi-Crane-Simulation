from __future__ import annotations

import math

from backend.app.schemas.config import ScenarioConfig
from backend.app.schemas.state import CraneState
from backend.app.schemas.task import Task, TaskActionSignal, TaskPoint
from backend.app.sim.crane_model import build_crane_model_library
from backend.app.sim.layout import build_crane_configs
from backend.app.sim.physics import recompute_state_geometry
from backend.app.sim.task_failure import (
    TaskFailureRuntimeState,
    handle_task_timing_and_failures,
)
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


def _task() -> Task:
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


def _state_at(
    crane,
    *,
    x: float,
    y: float,
    z: float,
    stage: str,
    load_attached: bool = False,
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


def test_disabled_deadline_policy_suppresses_deadline_missed_event() -> None:
    scenario, crane = _scenario_and_crane()
    scenario = scenario.model_copy(
        update={
            "tasks": scenario.tasks.model_copy(
                update={
                    "deadline_policy": scenario.tasks.deadline_policy.model_copy(
                        update={"enabled": False}
                    )
                }
            )
        }
    )
    state = _state_at(crane, x=20.0, y=0.0, z=10.0, stage="move_to_pickup")

    result = handle_task_timing_and_failures(
        _task(),
        state,
        scenario,
        crane,
        time_s=99.0,
        runtime=TaskFailureRuntimeState(last_progress_at_s=98.0),
    )

    assert result.task.deadline_missed is False
    assert result.task.overtime_s == 0.0
    assert result.events == []


def test_task_action_signal_for_other_crane_is_ignored() -> None:
    scenario, crane = _scenario_and_crane()
    state = _state_at(crane, x=20.0, y=0.0, z=1.0, stage="lower_for_attach")
    foreign_signal = TaskActionSignal(
        crane_id="C2",
        command_id="cmd_foreign",
        time_s=1.0,
        task_action="request_attach",
    )

    result = step_task_state_machine(
        _task(),
        crane,
        state,
        foreign_signal,
        time_s=1.0,
        config=scenario.tasks.state_machine,
        runtime=TaskRuntimeState(),
        attach_delay_s=0.0,
    )

    assert result.state.task_stage == "lower_for_attach"
    assert result.state.load_attached is False
    assert result.events == []


def test_release_request_with_foreign_signal_does_not_clear_load() -> None:
    scenario, crane = _scenario_and_crane()
    state = _state_at(
        crane,
        x=25.0,
        y=0.0,
        z=30.0,
        stage="lower_for_release",
        load_attached=True,
    )
    foreign_signal = TaskActionSignal(
        crane_id="C2",
        command_id="cmd_foreign",
        time_s=2.0,
        task_action="request_release",
    )

    result = step_task_state_machine(
        _task(),
        crane,
        state,
        foreign_signal,
        time_s=2.0,
        config=scenario.tasks.state_machine,
        runtime=TaskRuntimeState(),
        release_delay_s=0.0,
    )

    assert result.state.task_stage == "lower_for_release"
    assert result.state.load_attached is True
    assert result.task.status == "active"
    assert result.events == []
