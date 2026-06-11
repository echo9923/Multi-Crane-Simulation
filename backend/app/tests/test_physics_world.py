from __future__ import annotations

import pytest

from backend.app.schemas.config import ScenarioConfig
from backend.app.schemas.control import ControlTarget
from backend.app.sim.crane_model import build_crane_model_library
from backend.app.sim.layout import build_crane_configs
from backend.app.sim.physics import (
    PhysicsWorldError,
    initialize_world_state,
    step_world,
)
from backend.app.tests.test_config_schema import load_fixture


def _crane_configs(count: int = 4):
    raw = load_fixture("scenario_valid.yaml")
    raw["layout"]["mode"] = "manual"
    raw["layout"]["num_cranes"] = count
    raw["cranes"] = [
        {
            "crane_id": f"TC_{index + 1}",
            "model_id": "generic_flat_top_55m",
            "base": [-80.0 + index * 35.0, -70.0 + index * 25.0, 0.0],
            "mast_height_m": 45.0 + index,
            "theta_init_deg": index * 20.0,
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


@pytest.mark.parametrize("count", [2, 3, 6])
def test_step_world_steps_two_to_six_cranes_in_config_order(count: int) -> None:
    cranes = _crane_configs(count)
    states = initialize_world_state(cranes)
    targets = [
        _target(crane.crane_id, trolley=crane.model.trolley_speed_max_m_s)
        for crane in reversed(cranes)
    ]

    next_states = step_world(cranes, list(reversed(states)), targets, dt=1.0)

    assert [state.crane_id for state in next_states] == [
        crane.crane_id for crane in cranes
    ]
    assert [state.trolley_r_m for state in next_states] == pytest.approx(
        [
            crane.trolley_r_min_m + crane.model.trolley_speed_max_m_s
            for crane in cranes
        ]
    )


def test_step_world_rejects_missing_target_with_clear_error() -> None:
    cranes = _crane_configs(2)
    states = initialize_world_state(cranes)

    with pytest.raises(PhysicsWorldError) as exc_info:
        step_world(cranes, states, [_target("TC_1")], dt=1.0)

    assert exc_info.value.reason == "missing_control_target"
    assert exc_info.value.crane_id == "TC_2"
    assert exc_info.value.field_path == "control_targets"


def test_step_world_rejects_unknown_target_id_with_clear_error() -> None:
    cranes = _crane_configs(2)
    states = initialize_world_state(cranes)

    with pytest.raises(PhysicsWorldError) as exc_info:
        step_world(cranes, states, [_target("TC_1"), _target("TC_UNKNOWN")], dt=1.0)

    assert exc_info.value.reason == "unknown_control_target"
    assert exc_info.value.crane_id == "TC_UNKNOWN"


def test_step_world_rejects_duplicate_state_ids() -> None:
    cranes = _crane_configs(2)
    states = initialize_world_state(cranes)
    duplicated = [states[0], states[0].model_copy()]

    with pytest.raises(PhysicsWorldError) as exc_info:
        step_world(cranes, duplicated, [_target("TC_1"), _target("TC_2")], dt=1.0)

    assert exc_info.value.reason == "duplicate_previous_state"
    assert exc_info.value.crane_id == "TC_1"


def test_step_world_rejects_missing_previous_state() -> None:
    cranes = _crane_configs(2)
    states = initialize_world_state(cranes)

    with pytest.raises(PhysicsWorldError) as exc_info:
        step_world(cranes, states[:1], [_target("TC_1"), _target("TC_2")], dt=1.0)

    assert exc_info.value.reason == "missing_previous_state"
    assert exc_info.value.crane_id == "TC_2"
