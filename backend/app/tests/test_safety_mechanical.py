from __future__ import annotations

import math

import pytest

from backend.app.schemas.command import ParsedCommand
from backend.app.schemas.config import ScenarioConfig
from backend.app.sim.crane_model import build_crane_model_library
from backend.app.sim.layout import build_crane_configs
from backend.app.sim.physics import initialize_crane_state
from backend.app.sim.safety import (
    MechanicalSafetyError,
    apply_mechanical_safety,
    command_would_exceed_hoist_limits,
    command_would_exceed_load_or_moment,
    command_would_exceed_trolley_limits,
    estimate_axis_velocity,
)
from backend.app.tests.test_config_schema import load_fixture


def _crane_config():
    raw = load_fixture("scenario_valid.yaml")
    raw["layout"]["mode"] = "manual"
    raw["layout"]["num_cranes"] = 1
    raw["cranes"] = [
        {
            "crane_id": "C1",
            "model_id": "generic_flat_top_55m",
            "base": [0.0, 0.0, 0.0],
            "mast_height_m": 45.0,
            "theta_init_deg": 0.0,
            "slew": {"mode": "continuous"},
        }
    ]
    scenario = ScenarioConfig.model_validate(raw)
    library = build_crane_model_library(scenario.crane_models)
    return build_crane_configs(scenario.cranes, library, scenario, source="manual")[0]


def _state(**updates):
    config = _crane_config()
    state = initialize_crane_state(config)
    if updates:
        state = state.model_copy(update=updates)
    return state


def _command(
    *,
    slew: tuple[str, int] = ("left", 2),
    trolley: tuple[str, int] = ("out", 2),
    hoist: tuple[str, int] = ("down", 2),
    deadman_pressed: bool = True,
    emergency_stop: bool = False,
    crane_id: str = "C1",
) -> ParsedCommand:
    return ParsedCommand(
        command_id="cmd-001",
        response_id="resp-001",
        observation_id="obs-001",
        source_snapshot_id="snap-001",
        operator_id="op-001",
        crane_id=crane_id,
        time_s=5.0,
        left_joystick={
            "slew": {"direction": slew[0], "gear": slew[1]},
            "trolley": {"direction": trolley[0], "gear": trolley[1]},
        },
        right_joystick={"hoist": {"direction": hoist[0], "gear": hoist[1]}},
        deadman_pressed=deadman_pressed,
        emergency_stop=emergency_stop,
        horn=True,
        command_duration_s=1.0,
        task_action="none",
        attention_target="target",
        confidence=0.7,
        reason="fixture",
    )


def _event_reasons(result) -> list[str]:
    return [event.reason for event in result.events]


def test_valid_command_is_not_modified() -> None:
    config = _crane_config()
    state = _state(trolley_r_m=20.0, hook_h_m=20.0)

    executed, result = apply_mechanical_safety(
        command=_command(slew=("neutral", 0)),
        state=state,
        config=config,
        dt_s=0.1,
    )

    assert result.modified is False
    assert executed.modified is False
    assert executed.left_joystick.slew.direction == "neutral"
    assert executed.left_joystick.trolley.direction == "out"
    assert executed.right_joystick.hoist.direction == "down"
    assert executed.raw_command.command_id == "cmd-001"


def test_deadman_release_neutralizes_all_motion_axes() -> None:
    config = _crane_config()
    state = _state(trolley_r_m=20.0, hook_h_m=20.0)

    executed, result = apply_mechanical_safety(
        command=_command(deadman_pressed=False),
        state=state,
        config=config,
        dt_s=0.1,
    )

    assert executed.modified is True
    assert executed.left_joystick.slew.direction == "neutral"
    assert executed.left_joystick.trolley.direction == "neutral"
    assert executed.right_joystick.hoist.direction == "neutral"
    assert set(result.blocked_axes) == {"slew", "trolley", "hoist"}
    assert "deadman_released" in result.applied_limits
    assert "deadman_released" in _event_reasons(result)
    assert "deadman_released" in executed.modification_reasons


def test_emergency_stop_neutralizes_all_motion_axes() -> None:
    config = _crane_config()
    state = _state(trolley_r_m=20.0, hook_h_m=20.0)

    executed, result = apply_mechanical_safety(
        command=_command(emergency_stop=True),
        state=state,
        config=config,
        dt_s=0.1,
    )

    assert executed.modified is True
    assert executed.left_joystick.slew.gear == 0
    assert executed.left_joystick.trolley.gear == 0
    assert executed.right_joystick.hoist.gear == 0
    assert "emergency_stop" in result.applied_limits
    assert "emergency_stop" in _event_reasons(result)


@pytest.mark.parametrize(
    ("radius_offset", "direction", "expected_reason"),
    [
        (-0.01, "out", "trolley_limit"),
        (0.01, "in", "trolley_limit"),
    ],
)
def test_trolley_limits_clamp_out_and_in_commands(
    radius_offset: float, direction: str, expected_reason: str
) -> None:
    config = _crane_config()
    limit = (
        config.trolley_r_max_m
        if direction == "out"
        else config.trolley_r_min_m
    )
    state = _state(trolley_r_m=limit + radius_offset, hook_h_m=20.0)

    executed, result = apply_mechanical_safety(
        command=_command(trolley=(direction, 5), slew=("neutral", 0), hoist=("neutral", 0)),
        state=state,
        config=config,
        dt_s=1.0,
    )

    assert executed.left_joystick.trolley.direction == "neutral"
    assert executed.left_joystick.trolley.gear == 0
    assert "trolley" in result.clamped_axes
    assert expected_reason in result.applied_limits


@pytest.mark.parametrize(
    ("height_offset", "direction"),
    [
        (-0.01, "up"),
        (0.01, "down"),
    ],
)
def test_hoist_limits_clamp_up_and_down_commands(
    height_offset: float, direction: str
) -> None:
    config = _crane_config()
    limit = config.hook_h_max_world_m if direction == "up" else config.hook_h_min_world_m
    state = _state(trolley_r_m=20.0, hook_h_m=limit + height_offset)

    executed, result = apply_mechanical_safety(
        command=_command(hoist=(direction, 5), slew=("neutral", 0), trolley=("neutral", 0)),
        state=state,
        config=config,
        dt_s=1.0,
    )

    assert executed.right_joystick.hoist.direction == "neutral"
    assert executed.right_joystick.hoist.gear == 0
    assert "hoist" in result.clamped_axes
    assert "hoist_limit" in result.applied_limits


def test_moment_limit_prevents_overload_motion() -> None:
    config = _crane_config()
    state = _state(
        trolley_r_m=config.trolley_r_max_m - 1.0,
        hook_h_m=20.0,
        load_attached=True,
        load_weight_t=config.model.capacity_at_radius_t(config.trolley_r_max_m) + 1.0,
    )

    executed, result = apply_mechanical_safety(
        command=_command(trolley=("out", 5), slew=("neutral", 0), hoist=("neutral", 0)),
        state=state,
        config=config,
        dt_s=1.0,
    )

    assert executed.left_joystick.trolley.direction == "neutral"
    assert "overload_prevented" in result.applied_limits
    assert "moment_limit" in result.applied_limits
    assert "trolley" in result.blocked_axes


def test_continuous_slew_keeps_command_when_physics_will_smooth_acceleration() -> None:
    config = _crane_config()
    state = _state(trolley_r_m=20.0, hook_h_m=20.0, theta_dot_rad_s=0.0)

    executed, result = apply_mechanical_safety(
        command=_command(slew=("right", 5), trolley=("neutral", 0), hoist=("neutral", 0)),
        state=state,
        config=config,
        dt_s=0.1,
    )

    assert executed.left_joystick.slew.direction == "right"
    assert executed.left_joystick.slew.gear == 5
    assert "slew_limit" not in result.applied_limits
    assert "slew" not in result.clamped_axes


def test_estimate_axis_velocity_uses_model_limits_and_direction_sign() -> None:
    config = _crane_config()

    assert estimate_axis_velocity(
        axis="trolley", direction="out", gear=5, config=config
    ) == pytest.approx(config.model.trolley_speed_max_m_s)
    assert estimate_axis_velocity(
        axis="trolley", direction="in", gear=5, config=config
    ) == pytest.approx(-config.model.trolley_speed_max_m_s)
    assert estimate_axis_velocity(
        axis="hoist", direction="neutral", gear=0, config=config
    ) == 0.0


def test_limit_prediction_helpers_are_exposed() -> None:
    config = _crane_config()
    state = _state(
        trolley_r_m=config.trolley_r_max_m - 0.01,
        hook_h_m=config.hook_h_min_world_m + 0.01,
    )

    assert command_would_exceed_trolley_limits(
        state=state, config=config, direction="out", gear=5, dt_s=1.0
    )
    assert command_would_exceed_hoist_limits(
        state=state, config=config, direction="down", gear=5, dt_s=1.0
    )
    assert not command_would_exceed_load_or_moment(
        state=state,
        config=config,
        proposed_trolley_r_m=config.trolley_r_min_m,
    )


@pytest.mark.parametrize("dt_s", [0.0, -0.1, math.inf])
def test_invalid_dt_raises_mechanical_safety_error(dt_s: float) -> None:
    config = _crane_config()
    state = _state(trolley_r_m=20.0, hook_h_m=20.0)

    with pytest.raises(MechanicalSafetyError) as exc_info:
        apply_mechanical_safety(
            command=_command(),
            state=state,
            config=config,
            dt_s=dt_s,
        )

    assert exc_info.value.error_code == "SAFETY_E_INVALID_STATE"


def test_crane_id_mismatch_raises_mechanical_safety_error() -> None:
    config = _crane_config()
    state = _state(trolley_r_m=20.0, hook_h_m=20.0)

    with pytest.raises(MechanicalSafetyError) as exc_info:
        apply_mechanical_safety(
            command=_command(crane_id="C2"),
            state=state,
            config=config,
            dt_s=0.1,
        )

    assert exc_info.value.error_code == "SAFETY_E_INVALID_STATE"
