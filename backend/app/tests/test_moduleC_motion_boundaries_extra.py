from __future__ import annotations

import math

import pytest

from backend.app.schemas.config import ScenarioConfig
from backend.app.schemas.control import ControlTarget
from backend.app.sim.crane_model import build_crane_model_library
from backend.app.sim.layout import build_crane_configs
from backend.app.sim.physics import (
    PhysicsStateError,
    initialize_crane_state,
    recompute_state_geometry,
    step_crane_state,
)
from backend.app.tests.test_config_schema import load_fixture


def _crane_config():
    raw = load_fixture("scenario_valid.yaml")
    raw["layout"]["mode"] = "manual"
    raw["layout"]["num_cranes"] = 1
    raw["cranes"] = [
        {
            "crane_id": "TC_MOTION",
            "model_id": "generic_flat_top_55m",
            "base": [0.0, 0.0, 0.0],
            "mast_height_m": 50.0,
            "theta_init_deg": 0.0,
            "slew": {"mode": "continuous"},
        }
    ]
    scenario = ScenarioConfig.model_validate(raw)
    model_library = build_crane_model_library(scenario.crane_models)
    return build_crane_configs(scenario.cranes, model_library, scenario, source="manual")[0]


def _target(
    *,
    slew: float = 0.0,
    trolley: float = 0.0,
    hoist: float = 0.0,
    hold_position: bool = False,
) -> ControlTarget:
    return ControlTarget(
        crane_id="TC_MOTION",
        target_slew_velocity_rad_s=slew,
        target_trolley_velocity_m_s=trolley,
        target_hoist_velocity_m_s=hoist,
        hold_position=hold_position,
    )


def test_reverse_slew_obeys_acceleration_and_negative_speed_limit() -> None:
    crane = _crane_config()
    state = initialize_crane_state(crane).model_copy(
        update={"theta_dot_rad_s": crane.model.slew_speed_max_rad_s}
    )

    next_state = step_crane_state(
        crane,
        state,
        _target(slew=-crane.model.slew_speed_max_rad_s * 10.0),
        dt=1.0,
    )

    assert next_state.theta_dot_rad_s == pytest.approx(
        crane.model.slew_speed_max_rad_s - crane.model.slew_acc_max_rad_s2
    )

    current = next_state
    for _ in range(10):
        current = step_crane_state(
            crane,
            current,
            _target(slew=-crane.model.slew_speed_max_rad_s * 10.0),
            dt=1.0,
        )

    assert current.theta_dot_rad_s >= -crane.model.slew_speed_max_rad_s


def test_trolley_clamps_at_min_radius_and_zeroes_velocity() -> None:
    crane = _crane_config()
    state = recompute_state_geometry(
        crane,
        initialize_crane_state(crane).model_copy(
            update={"trolley_r_m": crane.trolley_r_min_m + 0.05}
        ),
    )

    next_state = step_crane_state(
        crane,
        state,
        _target(trolley=-crane.model.trolley_speed_max_m_s),
        dt=1.0,
    )

    assert next_state.trolley_r_m == pytest.approx(crane.trolley_r_min_m)
    assert next_state.trolley_v_m_s == 0.0


def test_hoist_clamps_at_max_height_and_zeroes_velocity() -> None:
    crane = _crane_config()
    state = recompute_state_geometry(
        crane,
        initialize_crane_state(crane).model_copy(
            update={"hook_h_m": crane.hook_h_max_world_m - 0.05}
        ),
    )

    next_state = step_crane_state(
        crane,
        state,
        _target(hoist=crane.model.hoist_speed_max_m_s),
        dt=1.0,
    )

    assert next_state.hook_h_m == pytest.approx(crane.hook_h_max_world_m)
    assert next_state.hoist_v_m_s == 0.0


def test_hold_position_stops_trolley_and_hoist_without_position_drift() -> None:
    crane = _crane_config()
    state = recompute_state_geometry(
        crane,
        initialize_crane_state(crane).model_copy(
            update={
                "trolley_r_m": 20.0,
                "trolley_v_m_s": crane.model.trolley_speed_max_m_s,
                "hook_h_m": 40.0,
                "hoist_v_m_s": -crane.model.hoist_speed_max_m_s,
            }
        ),
    )

    next_state = step_crane_state(
        crane,
        state,
        _target(
            trolley=crane.model.trolley_speed_max_m_s,
            hoist=-crane.model.hoist_speed_max_m_s,
            hold_position=True,
        ),
        dt=0.5,
    )

    assert next_state.trolley_r_m == pytest.approx(state.trolley_r_m)
    assert next_state.trolley_v_m_s == 0.0
    assert next_state.hook_h_m == pytest.approx(state.hook_h_m)
    assert next_state.hoist_v_m_s == 0.0


@pytest.mark.parametrize("dt", [math.nan, math.inf, -math.inf])
def test_step_crane_state_rejects_non_finite_dt(dt: float) -> None:
    crane = _crane_config()
    state = initialize_crane_state(crane)

    with pytest.raises(PhysicsStateError) as exc_info:
        step_crane_state(crane, state, _target(), dt=dt)

    assert exc_info.value.error_code == "PHYS_E_001"
    assert exc_info.value.field_path == "dt"
    assert exc_info.value.details["reason"] == "non_finite"
