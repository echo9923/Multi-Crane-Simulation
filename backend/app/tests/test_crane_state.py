from __future__ import annotations

import math

import pytest

from backend.app.schemas.config import ScenarioConfig
from backend.app.sim.crane_model import build_crane_model_library
from backend.app.sim.layout import build_crane_configs
from backend.app.sim.physics import initialize_crane_state, initialize_world_state
from backend.app.tests.test_config_schema import load_fixture


def _crane_configs(count: int = 2):
    raw = load_fixture("scenario_valid.yaml")
    raw["layout"]["mode"] = "manual"
    raw["layout"]["num_cranes"] = count
    raw["cranes"] = [
        {
            "crane_id": f"TC_{index + 1}",
            "model_id": "generic_flat_top_55m",
            "base": [-60.0 + index * 80.0, -40.0 + index * 20.0, 0.0],
            "mast_height_m": 45.0 + index * 5.0,
            "theta_init_deg": 30.0 + index * 45.0,
            "slew": {"mode": "continuous"},
        }
        for index in range(count)
    ]
    scenario = ScenarioConfig.model_validate(raw)
    model_library = build_crane_model_library(scenario.crane_models)
    return build_crane_configs(scenario.cranes, model_library, scenario, source="manual")


def test_initialize_crane_state_uses_crane_config_only() -> None:
    crane = _crane_configs(1)[0]

    state = initialize_crane_state(crane)

    assert state.schema_version == "1.0"
    assert state.crane_id == crane.crane_id
    assert state.theta_rad == pytest.approx(crane.theta_init_rad)
    assert state.theta_dot_rad_s == 0.0
    assert state.theta_ddot_rad_s2 == 0.0
    assert state.theta_sin == pytest.approx(math.sin(crane.theta_init_rad))
    assert state.theta_cos == pytest.approx(math.cos(crane.theta_init_rad))
    assert state.trolley_r_m == pytest.approx(crane.trolley_r_min_m)
    assert state.trolley_v_m_s == 0.0
    assert state.hook_h_m == pytest.approx(crane.hook_h_max_world_m)
    assert state.hoist_v_m_s == 0.0
    assert state.root_position == pytest.approx(crane.root)
    assert state.tip_position == pytest.approx(
        [
            crane.root[0] + crane.jib_length_m * math.cos(crane.theta_init_rad),
            crane.root[1] + crane.jib_length_m * math.sin(crane.theta_init_rad),
            crane.root[2],
        ]
    )
    assert state.hook_position == pytest.approx(
        [
            crane.base[0] + crane.trolley_r_min_m * math.cos(crane.theta_init_rad),
            crane.base[1] + crane.trolley_r_min_m * math.sin(crane.theta_init_rad),
            crane.hook_h_max_world_m,
        ]
    )
    assert state.cable_length_m == pytest.approx(
        crane.root[2] - crane.hook_h_max_world_m
    )
    assert state.load_position is None
    assert state.swing_angle_rad == 0.0
    assert state.swing_velocity_rad_s == 0.0
    assert state.wind_effect_on_swing is None
    assert state.load_attached is False
    assert state.load_type is None
    assert state.load_weight_t == 0.0
    assert state.load_size_m is None
    assert state.task_id is None
    assert state.task_stage == "idle"


def test_initialize_world_state_supports_arbitrary_crane_ids_in_input_order() -> None:
    cranes = _crane_configs(3)

    states = initialize_world_state(cranes)

    assert [state.crane_id for state in states] == ["TC_1", "TC_2", "TC_3"]
    assert [state.theta_rad for state in states] == pytest.approx(
        [crane.theta_init_rad for crane in cranes]
    )
