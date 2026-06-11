from __future__ import annotations

import pytest

from backend.app.schemas.config import ScenarioConfig
from backend.app.schemas.control import ControlTarget
from backend.app.sim.crane_model import build_crane_model_library
from backend.app.sim.layout import build_crane_configs
from backend.app.sim.physics import (
    PhysicsWorldError,
    initialize_crane_state,
    initialize_world_state,
    step_crane_state,
    step_world,
)
from backend.app.tests.test_config_schema import load_fixture


def _crane_configs(count: int = 2):
    raw = load_fixture("scenario_valid.yaml")
    raw["layout"]["mode"] = "manual"
    raw["layout"]["num_cranes"] = count
    raw["cranes"] = [
        {
            "crane_id": f"TC_ID_{index + 1}",
            "model_id": "generic_flat_top_55m",
            "base": [-50.0 + index * 80.0, -30.0 + index * 40.0, 0.0],
            "mast_height_m": 45.0 + index * 3.0,
            "theta_init_deg": index * 25.0,
            "slew": {"mode": "continuous"},
        }
        for index in range(count)
    ]
    scenario = ScenarioConfig.model_validate(raw)
    model_library = build_crane_model_library(scenario.crane_models)
    return build_crane_configs(scenario.cranes, model_library, scenario, source="manual")


def _target(crane_id: str, *, trolley: float = 0.0) -> ControlTarget:
    return ControlTarget(
        crane_id=crane_id,
        target_slew_velocity_rad_s=0.0,
        target_trolley_velocity_m_s=trolley,
        target_hoist_velocity_m_s=0.0,
    )


def test_step_crane_state_rejects_mismatched_state_crane_id() -> None:
    crane = _crane_configs(1)[0]
    state = initialize_crane_state(crane).model_copy(update={"crane_id": "OTHER"})

    with pytest.raises(PhysicsWorldError) as exc_info:
        step_crane_state(crane, state, _target(crane.crane_id), dt=0.05)

    assert exc_info.value.reason == "state_crane_id_mismatch"
    assert exc_info.value.crane_id == "OTHER"
    assert exc_info.value.field_path == "previous_state.crane_id"


def test_step_crane_state_rejects_mismatched_target_crane_id() -> None:
    crane = _crane_configs(1)[0]
    state = initialize_crane_state(crane)

    with pytest.raises(PhysicsWorldError) as exc_info:
        step_crane_state(crane, state, _target("OTHER"), dt=0.05)

    assert exc_info.value.reason == "target_crane_id_mismatch"
    assert exc_info.value.crane_id == "OTHER"
    assert exc_info.value.field_path == "control_target.crane_id"


def test_step_crane_state_does_not_mutate_previous_state() -> None:
    crane = _crane_configs(1)[0]
    state = initialize_crane_state(crane)
    before = state.model_dump(mode="json")

    next_state = step_crane_state(
        crane,
        state,
        _target(crane.crane_id, trolley=crane.model.trolley_speed_max_m_s),
        dt=1.0,
    )

    assert state.model_dump(mode="json") == before
    assert next_state is not state
    assert next_state.trolley_r_m > state.trolley_r_m


def test_initialize_world_state_returns_independent_state_instances() -> None:
    cranes = _crane_configs(2)

    states = initialize_world_state(cranes)
    modified_first = states[0].model_copy(update={"task_stage": "busy"})

    assert modified_first.task_stage == "busy"
    assert states[0].task_stage == "idle"
    assert states[1].task_stage == "idle"


def test_step_world_rejects_duplicate_crane_config_ids() -> None:
    cranes = _crane_configs(2)
    duplicated_configs = [cranes[0], cranes[0].model_copy()]
    states = initialize_world_state(cranes)

    with pytest.raises(PhysicsWorldError) as exc_info:
        step_world(
            duplicated_configs,
            states,
            [_target(crane.crane_id) for crane in cranes],
            dt=0.05,
        )

    assert exc_info.value.reason == "duplicate_crane_config"
    assert exc_info.value.crane_id == cranes[0].crane_id
    assert exc_info.value.field_path == "crane_configs"
