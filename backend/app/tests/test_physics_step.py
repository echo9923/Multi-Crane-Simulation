from __future__ import annotations

import math

import pytest

from backend.app.schemas.config import ScenarioConfig
from backend.app.schemas.control import ControlTarget
from backend.app.sim.crane_model import build_crane_model_library
from backend.app.sim.layout import build_crane_configs
from backend.app.sim.physics import (
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
            "crane_id": "TC_STEP",
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
    crane_id: str = "TC_STEP",
    *,
    slew: float = 0.0,
    trolley: float = 0.0,
    hoist: float = 0.0,
    emergency_stop: bool = False,
    hold_position: bool = False,
) -> ControlTarget:
    return ControlTarget(
        crane_id=crane_id,
        target_slew_velocity_rad_s=slew,
        target_trolley_velocity_m_s=trolley,
        target_hoist_velocity_m_s=hoist,
        emergency_stop=emergency_stop,
        hold_position=hold_position,
    )


def test_neutral_target_keeps_resting_state_stable() -> None:
    crane = _crane_config()
    state = initialize_crane_state(crane)

    next_state = step_crane_state(crane, state, _target(), dt=0.05)

    assert next_state.theta_rad == pytest.approx(state.theta_rad)
    assert next_state.theta_dot_rad_s == pytest.approx(0.0)
    assert next_state.trolley_r_m == pytest.approx(state.trolley_r_m)
    assert next_state.trolley_v_m_s == pytest.approx(0.0)
    assert next_state.hook_h_m == pytest.approx(state.hook_h_m)
    assert next_state.hoist_v_m_s == pytest.approx(0.0)
    assert next_state.hook_position == pytest.approx(state.hook_position)


def test_slew_velocity_obeys_acceleration_and_speed_limits() -> None:
    crane = _crane_config()
    state = initialize_crane_state(crane)
    dt = 0.5

    next_state = step_crane_state(
        crane,
        state,
        _target(slew=crane.model.slew_speed_max_rad_s * 10.0),
        dt=dt,
    )

    expected_velocity = crane.model.slew_acc_max_rad_s2 * dt
    assert next_state.theta_dot_rad_s == pytest.approx(expected_velocity)
    assert next_state.theta_rad == pytest.approx(expected_velocity * dt)

    current = next_state
    for _ in range(1000):
        current = step_crane_state(
            crane,
            current,
            _target(slew=crane.model.slew_speed_max_rad_s * 10.0),
            dt=dt,
        )

    assert current.theta_dot_rad_s == pytest.approx(crane.model.slew_speed_max_rad_s)
    assert current.theta_rad > math.tau


def test_neutral_target_decelerates_existing_slew_velocity() -> None:
    crane = _crane_config()
    state = initialize_crane_state(crane).model_copy(
        update={"theta_dot_rad_s": crane.model.slew_acc_max_rad_s2}
    )

    next_state = step_crane_state(crane, state, _target(), dt=0.5)

    assert next_state.theta_dot_rad_s == pytest.approx(
        crane.model.slew_acc_max_rad_s2 * 0.5
    )


def test_trolley_velocity_is_limited_and_radius_is_clamped() -> None:
    crane = _crane_config()
    state = initialize_crane_state(crane)
    dt = 10.0

    next_state = step_crane_state(
        crane,
        state,
        _target(trolley=crane.model.trolley_speed_max_m_s * 10.0),
        dt=dt,
    )

    assert next_state.trolley_v_m_s == pytest.approx(crane.model.trolley_speed_max_m_s)
    assert next_state.trolley_r_m == pytest.approx(
        crane.trolley_r_min_m + crane.model.trolley_speed_max_m_s * dt
    )

    near_limit = recompute_state_geometry(
        crane,
        next_state.model_copy(update={"trolley_r_m": crane.trolley_r_max_m - 0.1}),
    )
    clamped = step_crane_state(
        crane,
        near_limit,
        _target(trolley=crane.model.trolley_speed_max_m_s),
        dt=dt,
    )

    assert clamped.trolley_r_m == pytest.approx(crane.trolley_r_max_m)
    assert clamped.trolley_v_m_s == pytest.approx(0.0)


def test_hoist_velocity_is_limited_and_hook_height_is_clamped() -> None:
    crane = _crane_config()
    state = recompute_state_geometry(
        crane,
        initialize_crane_state(crane).model_copy(
            update={"hook_h_m": crane.hook_h_min_world_m + 0.1}
        ),
    )
    dt = 10.0

    next_state = step_crane_state(
        crane,
        state,
        _target(hoist=-crane.model.hoist_speed_max_m_s * 10.0),
        dt=dt,
    )

    assert next_state.hook_h_m == pytest.approx(crane.hook_h_min_world_m)
    assert next_state.hoist_v_m_s == pytest.approx(0.0)
    assert next_state.cable_length_m == pytest.approx(
        crane.root[2] - crane.hook_h_min_world_m
    )


def test_emergency_stop_and_hold_position_force_zero_targets() -> None:
    crane = _crane_config()
    state = initialize_crane_state(crane).model_copy(
        update={
            "theta_dot_rad_s": crane.model.slew_acc_max_rad_s2,
            "trolley_v_m_s": crane.model.trolley_speed_max_m_s,
            "hoist_v_m_s": crane.model.hoist_speed_max_m_s,
        }
    )

    emergency = step_crane_state(
        crane,
        state,
        _target(
            slew=crane.model.slew_speed_max_rad_s,
            trolley=crane.model.trolley_speed_max_m_s,
            hoist=crane.model.hoist_speed_max_m_s,
            emergency_stop=True,
        ),
        dt=0.5,
    )
    held = step_crane_state(
        crane,
        state,
        _target(
            slew=crane.model.slew_speed_max_rad_s,
            trolley=crane.model.trolley_speed_max_m_s,
            hoist=crane.model.hoist_speed_max_m_s,
            hold_position=True,
        ),
        dt=0.5,
    )

    assert emergency.trolley_v_m_s == 0.0
    assert emergency.hoist_v_m_s == 0.0
    assert emergency.theta_dot_rad_s < state.theta_dot_rad_s
    assert held.trolley_v_m_s == 0.0
    assert held.hoist_v_m_s == 0.0
    assert held.theta_dot_rad_s < state.theta_dot_rad_s


def test_single_crane_step_stays_finite_for_twenty_hz_six_hundred_seconds() -> None:
    crane = _crane_config()
    state = initialize_crane_state(crane)
    target = _target(
        slew=crane.model.slew_speed_max_rad_s,
        trolley=crane.model.trolley_speed_max_m_s,
        hoist=-crane.model.hoist_speed_max_m_s,
    )

    for _ in range(int(600 / 0.05)):
        state = step_crane_state(crane, state, target, dt=0.05)

    values = [
        state.theta_rad,
        state.theta_dot_rad_s,
        state.theta_ddot_rad_s2,
        state.trolley_r_m,
        state.trolley_v_m_s,
        state.hook_h_m,
        state.hoist_v_m_s,
        state.cable_length_m,
        *state.tip_position,
        *state.hook_position,
    ]
    assert all(math.isfinite(value) for value in values)
    assert crane.trolley_r_min_m <= state.trolley_r_m <= crane.trolley_r_max_m
    assert crane.hook_h_min_world_m <= state.hook_h_m <= crane.hook_h_max_world_m
