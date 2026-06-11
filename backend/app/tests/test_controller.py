from __future__ import annotations

import math

import pytest
from pydantic import ValidationError

from backend.app.schemas.config import ScenarioConfig
from backend.app.schemas.control import (
    CONTROLLER_SCHEMA_VERSION,
    DEFAULT_HOIST_GEAR_SPEEDS_M_S,
    DEFAULT_SLEW_GEAR_SPEEDS_RAD_S,
    DEFAULT_TROLLEY_GEAR_SPEEDS_M_S,
    AxisControlDiagnostic,
    ControlTarget,
    ControllerConfig,
    ControllerDiagnostic,
    ControllerStateError,
)
from backend.app.schemas.command import (
    ExecutedAxisCommand,
    ExecutedCommand,
    ExecutedLeftJoystickCommand,
    ExecutedRightJoystickCommand,
    ParsedCommand,
)
from backend.app.sim.controller import (
    compute_stop_mode_target,
    direction_sign,
    is_command_expired,
    map_axis_to_desired_velocity,
    map_command_to_desired_velocities,
    resolve_controller_mode,
    smooth_axis_velocity,
    smooth_command_velocities,
)
from backend.app.sim.crane_model import build_crane_model_library
from backend.app.sim.layout import build_crane_configs
from backend.app.sim.physics import initialize_crane_state
from backend.app.tests.test_config_schema import load_fixture


@pytest.fixture
def executed_command():
    def factory(
        *,
        slew: tuple[str, int] = ("neutral", 0),
        trolley: tuple[str, int] = ("neutral", 0),
        hoist: tuple[str, int] = ("neutral", 0),
        speed_scales: tuple[float, float, float] = (1.0, 1.0, 1.0),
        sources: tuple[str, str, str] = ("raw", "raw", "raw"),
        deadman_pressed: bool = True,
        emergency_stop: bool = False,
        command_id: str = "cmd-001",
        crane_id: str = "C1",
        time_s: float = 5.0,
        command_duration_s: float = 1.0,
    ) -> ExecutedCommand:
        raw_command = ParsedCommand(
            command_id=command_id,
            response_id=f"resp-{command_id}",
            observation_id=f"obs-{command_id}",
            source_snapshot_id=f"snap-{command_id}",
            operator_id="op-001",
            crane_id=crane_id,
            time_s=time_s,
            left_joystick={
                "slew": {"direction": slew[0], "gear": slew[1]},
                "trolley": {"direction": trolley[0], "gear": trolley[1]},
            },
            right_joystick={"hoist": {"direction": hoist[0], "gear": hoist[1]}},
            deadman_pressed=deadman_pressed,
            emergency_stop=emergency_stop,
            horn=False,
            command_duration_s=max(command_duration_s, 0.5),
            task_action="none",
            attention_target="controller_fixture",
            confidence=0.8,
            reason="controller test fixture",
        )
        modified = sources != ("raw", "raw", "raw") or speed_scales != (1.0, 1.0, 1.0)
        return ExecutedCommand(
            command_id=f"EXEC_{command_id}",
            raw_command_id=command_id,
            observation_id=raw_command.observation_id,
            source_snapshot_id=raw_command.source_snapshot_id,
            operator_id=raw_command.operator_id,
            crane_id=crane_id,
            time_s=time_s,
            raw_command=raw_command,
            left_joystick=ExecutedLeftJoystickCommand(
                slew=ExecutedAxisCommand(
                    direction=slew[0],
                    gear=slew[1],
                    speed_scale=speed_scales[0],
                    source=sources[0],
                ),
                trolley=ExecutedAxisCommand(
                    direction=trolley[0],
                    gear=trolley[1],
                    speed_scale=speed_scales[1],
                    source=sources[1],
                ),
            ),
            right_joystick=ExecutedRightJoystickCommand(
                hoist=ExecutedAxisCommand(
                    direction=hoist[0],
                    gear=hoist[1],
                    speed_scale=speed_scales[2],
                    source=sources[2],
                )
            ),
            deadman_pressed=deadman_pressed,
            emergency_stop=emergency_stop,
            horn=False,
            command_duration_s=command_duration_s,
            task_action="none",
            modified=modified,
            modification_reasons=["controller_fixture"] if modified else [],
        )

    return factory


def _crane_config(crane_id: str = "C1"):
    raw = load_fixture("scenario_valid.yaml")
    raw["layout"]["mode"] = "manual"
    raw["layout"]["num_cranes"] = 1
    raw["cranes"] = [
        {
            "crane_id": crane_id,
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


def test_controller_config_defaults_match_module_i_tables() -> None:
    config = ControllerConfig(controller_hz=20.0)

    assert config.schema_version == CONTROLLER_SCHEMA_VERSION
    assert config.controller_dt_s == pytest.approx(0.05)
    assert config.slew_gear_speeds_rad_s == DEFAULT_SLEW_GEAR_SPEEDS_RAD_S
    assert config.trolley_gear_speeds_m_s == DEFAULT_TROLLEY_GEAR_SPEEDS_M_S
    assert config.hoist_gear_speeds_m_s == DEFAULT_HOIST_GEAR_SPEEDS_M_S
    assert config.slew_gear_speeds_rad_s == {
        0: 0.0,
        1: 0.15,
        2: 0.3,
        3: 0.5,
        4: 0.65,
        5: 0.8,
    }
    assert config.trolley_gear_speeds_m_s == {
        0: 0.0,
        1: 0.08,
        2: 0.15,
        3: 0.3,
        4: 0.4,
        5: 0.5,
    }
    assert config.hoist_gear_speeds_m_s == {
        0: 0.0,
        1: 0.1,
        2: 0.2,
        3: 0.35,
        4: 0.5,
        5: 0.6,
    }


@pytest.mark.parametrize(
    "payload",
    [
        {"controller_hz": 0.0},
        {"controller_hz": math.inf},
        {"controller_hz": math.nan},
        {"controller_hz": 20.0, "slew_gear_speeds_rad_s": {0: 0.0, 1: 0.1}},
        {
            "controller_hz": 20.0,
            "trolley_gear_speeds_m_s": {
                0: 0.01,
                1: 0.08,
                2: 0.15,
                3: 0.3,
                4: 0.4,
                5: 0.5,
            },
        },
        {
            "controller_hz": 20.0,
            "hoist_gear_speeds_m_s": {
                0: 0.0,
                1: 0.1,
                2: 0.2,
                3: 0.15,
                4: 0.5,
                5: 0.6,
            },
        },
    ],
)
def test_controller_config_rejects_invalid_values(payload: dict) -> None:
    with pytest.raises(ValidationError):
        ControllerConfig.model_validate(payload)


def test_controller_diagnostic_serializes_and_forbids_extra_fields() -> None:
    axis = AxisControlDiagnostic(
        axis="slew",
        direction="right",
        gear=3,
        speed_scale=0.5,
        current_velocity=0.1,
        desired_velocity_before_speed_clamp=0.25,
        desired_velocity_after_speed_clamp=0.25,
        target_velocity=0.2,
        speed_clamped=False,
        acceleration_limited=True,
        speed_clamp_delta=0.0,
        acceleration_delta=0.1,
        max_velocity_abs=0.8,
        max_acceleration_abs=0.3,
    )
    diagnostic = ControllerDiagnostic(
        diagnostic_id="CTRL_DIAG_cmd-001",
        crane_id="C1",
        source_command_id="cmd-001",
        mode="normal",
        controller_dt_s=0.05,
        command_time_s=1.0,
        now_s=1.05,
        command_duration_s=1.0,
        command_expired=False,
        deadman_pressed=True,
        emergency_stop_requested=False,
        axes=[axis],
    )

    dumped = diagnostic.model_dump(mode="json")

    assert dumped["schema_version"] == CONTROLLER_SCHEMA_VERSION
    assert dumped["axes"][0]["axis"] == "slew"
    with pytest.raises(ValidationError):
        ControllerDiagnostic.model_validate({**dumped, "unexpected": "nope"})


def test_controller_diagnostic_rejects_nan_and_invalid_mode() -> None:
    valid_axis = {
        "axis": "trolley",
        "direction": "out",
        "gear": 2,
        "speed_scale": 1.0,
        "current_velocity": 0.0,
        "desired_velocity_before_speed_clamp": 0.15,
        "desired_velocity_after_speed_clamp": 0.15,
        "target_velocity": 0.1,
        "max_velocity_abs": 0.5,
        "max_acceleration_abs": 0.4,
    }

    with pytest.raises(ValidationError):
        AxisControlDiagnostic.model_validate({**valid_axis, "target_velocity": math.nan})

    with pytest.raises(ValidationError):
        ControllerDiagnostic(
            diagnostic_id="CTRL_DIAG_cmd-001",
            crane_id="C1",
            source_command_id="cmd-001",
            mode="not_a_mode",
            controller_dt_s=0.05,
            axes=[AxisControlDiagnostic.model_validate(valid_axis)],
        )


def test_control_target_keeps_pure_numeric_contract() -> None:
    forbidden_fields = {"task_id", "task_stage", "reason", "llm_reason"}

    assert forbidden_fields.isdisjoint(ControlTarget.model_fields)
    with pytest.raises(ValidationError):
        ControlTarget(
            crane_id="C1",
            target_slew_velocity_rad_s=0.0,
            target_trolley_velocity_m_s=0.0,
            target_hoist_velocity_m_s=0.0,
            task_id="task-001",
        )


@pytest.mark.parametrize(
    ("axis", "direction", "expected"),
    [
        ("slew", "left", -1),
        ("slew", "neutral", 0),
        ("slew", "right", 1),
        ("trolley", "in", -1),
        ("trolley", "neutral", 0),
        ("trolley", "out", 1),
        ("hoist", "down", -1),
        ("hoist", "neutral", 0),
        ("hoist", "up", 1),
    ],
)
def test_direction_signs_are_axis_specific(
    axis: str, direction: str, expected: int
) -> None:
    assert direction_sign(axis, direction) == expected


@pytest.mark.parametrize(
    ("axis", "direction", "gear", "expected"),
    [
        ("slew", "right", 1, 0.15),
        ("slew", "left", 5, -0.8),
        ("trolley", "out", 1, 0.08),
        ("trolley", "in", 5, -0.5),
        ("hoist", "up", 1, 0.1),
        ("hoist", "down", 5, -0.6),
    ],
)
def test_map_axis_to_desired_velocity_uses_module_i_axis_tables(
    axis: str, direction: str, gear: int, expected: float
) -> None:
    velocity = map_axis_to_desired_velocity(
        axis=axis,
        axis_command=ExecutedAxisCommand(
            direction=direction,
            gear=gear,
            speed_scale=1.0,
            source="raw",
        ),
        controller_config=ControllerConfig(controller_hz=20.0),
    )

    assert velocity == pytest.approx(expected)


def test_speed_scale_multiplies_desired_velocity() -> None:
    velocity = map_axis_to_desired_velocity(
        axis="trolley",
        axis_command=ExecutedAxisCommand(
            direction="out",
            gear=4,
            speed_scale=0.5,
            source="risk_intervention",
        ),
        controller_config=ControllerConfig(controller_hz=20.0),
    )

    assert velocity == pytest.approx(0.2)


@pytest.mark.parametrize(
    ("axis", "direction", "gear"),
    [
        ("slew", "neutral", 0),
        ("trolley", "neutral", 0),
        ("hoist", "neutral", 0),
        ("hoist", "up", 1),
    ],
)
def test_zero_gear_neutral_and_zero_speed_scale_map_to_zero(
    axis: str, direction: str, gear: int
) -> None:
    scale = 0.0 if direction != "neutral" else 1.0

    velocity = map_axis_to_desired_velocity(
        axis=axis,
        axis_command=ExecutedAxisCommand(
            direction=direction,
            gear=gear,
            speed_scale=scale,
            source="raw",
        ),
        controller_config=ControllerConfig(controller_hz=20.0),
    )

    assert velocity == pytest.approx(0.0)


def test_map_command_to_desired_velocities_reads_all_three_axes(executed_command) -> None:
    command = executed_command(
        slew=("right", 3),
        trolley=("in", 2),
        hoist=("up", 4),
    )

    velocities = map_command_to_desired_velocities(
        command=command,
        controller_config=ControllerConfig(controller_hz=20.0),
    )

    assert velocities == {
        "slew": pytest.approx(0.5),
        "trolley": pytest.approx(-0.15),
        "hoist": pytest.approx(0.5),
    }


def test_unknown_axis_or_direction_raises_controller_state_error() -> None:
    with pytest.raises(ControllerStateError) as exc_info:
        direction_sign("boom", "out")

    assert exc_info.value.episode_status == "failed_invalid_state"
    assert exc_info.value.field_path == "axis"

    with pytest.raises(ControllerStateError) as exc_info:
        direction_sign("slew", "up")

    assert exc_info.value.field_path == "direction"


def test_controller_module_does_not_reuse_safety_generic_gear_scale() -> None:
    import inspect
    import backend.app.sim.controller as controller_module

    source = inspect.getsource(controller_module)

    assert "GEAR_TO_SPEED_SCALE" not in source


def test_crane_model_spec_exposes_three_axis_acceleration_limits() -> None:
    model = _crane_config().model

    assert model.slew_acc_max_rad_s2 == pytest.approx(math.radians(0.3))
    assert model.trolley_acc_max_m_s2 == pytest.approx(0.4)
    assert model.hoist_acc_max_m_s2 == pytest.approx(0.5)


def test_smooth_axis_velocity_limits_acceleration_and_records_diagnostic() -> None:
    model = _crane_config().model

    target, diagnostic = smooth_axis_velocity(
        axis="trolley",
        direction="out",
        gear=5,
        speed_scale=1.0,
        current_velocity=0.0,
        desired_velocity=0.5,
        model=model,
        dt_s=0.1,
        controller_config=ControllerConfig(controller_hz=10.0),
    )

    assert target == pytest.approx(model.trolley_acc_max_m_s2 * 0.1)
    assert diagnostic.axis == "trolley"
    assert diagnostic.acceleration_limited is True
    assert diagnostic.speed_clamped is False
    assert diagnostic.desired_velocity_after_speed_clamp == pytest.approx(0.5)


def test_smooth_axis_velocity_clamps_speed_before_transition() -> None:
    model = _crane_config().model

    target, diagnostic = smooth_axis_velocity(
        axis="slew",
        direction="right",
        gear=5,
        speed_scale=1.0,
        current_velocity=0.0,
        desired_velocity=model.slew_speed_max_rad_s * 10.0,
        model=model,
        dt_s=0.5,
        controller_config=ControllerConfig(controller_hz=2.0),
    )

    assert target <= model.slew_speed_max_rad_s
    assert target == pytest.approx(model.slew_acc_max_rad_s2 * 0.5)
    assert diagnostic.speed_clamped is True
    assert diagnostic.acceleration_limited is True
    assert diagnostic.desired_velocity_after_speed_clamp == pytest.approx(
        model.slew_speed_max_rad_s
    )


def test_smooth_axis_velocity_handles_deceleration_and_reversal() -> None:
    model = _crane_config().model

    target, diagnostic = smooth_axis_velocity(
        axis="hoist",
        direction="down",
        gear=5,
        speed_scale=1.0,
        current_velocity=0.2,
        desired_velocity=-0.6,
        model=model,
        dt_s=0.2,
        controller_config=ControllerConfig(controller_hz=5.0),
    )

    assert target == pytest.approx(0.2 - model.hoist_acc_max_m_s2 * 0.2)
    assert diagnostic.acceleration_limited is True


def test_smooth_command_velocities_reads_state_current_velocities() -> None:
    crane = _crane_config()
    state = initialize_crane_state(crane).model_copy(
        update={
            "theta_dot_rad_s": 0.0,
            "trolley_v_m_s": 0.2,
            "hoist_v_m_s": -0.2,
        }
    )

    velocities, diagnostics = smooth_command_velocities(
        desired_velocities={"slew": 0.8, "trolley": 0.0, "hoist": 0.6},
        state=state,
        model=crane.model,
        dt_s=0.1,
        controller_config=ControllerConfig(controller_hz=10.0),
    )

    assert velocities["slew"] == pytest.approx(crane.model.slew_acc_max_rad_s2 * 0.1)
    assert velocities["trolley"] == pytest.approx(
        0.2 - crane.model.trolley_acc_max_m_s2 * 0.1
    )
    assert velocities["hoist"] == pytest.approx(
        -0.2 + crane.model.hoist_acc_max_m_s2 * 0.1
    )
    assert {diagnostic.axis for diagnostic in diagnostics} == {
        "slew",
        "trolley",
        "hoist",
    }


@pytest.mark.parametrize("dt_s", [0.0, -0.1, math.inf, math.nan])
def test_smooth_axis_velocity_rejects_invalid_dt(dt_s: float) -> None:
    model = _crane_config().model

    with pytest.raises(ControllerStateError) as exc_info:
        smooth_axis_velocity(
            axis="slew",
            direction="right",
            gear=1,
            speed_scale=1.0,
            current_velocity=0.0,
            desired_velocity=0.15,
            model=model,
            dt_s=dt_s,
            controller_config=ControllerConfig(controller_hz=20.0),
        )

    assert exc_info.value.episode_status == "failed_invalid_state"
    assert exc_info.value.field_path == "dt_s"


def test_smooth_axis_velocity_rejects_non_finite_current_velocity() -> None:
    model = _crane_config().model

    with pytest.raises(ControllerStateError) as exc_info:
        smooth_axis_velocity(
            axis="slew",
            direction="right",
            gear=1,
            speed_scale=1.0,
            current_velocity=math.nan,
            desired_velocity=0.15,
            model=model,
            dt_s=0.1,
            controller_config=ControllerConfig(controller_hz=20.0),
        )

    assert exc_info.value.field_path == "current_velocity"


def test_is_command_expired_uses_strict_greater_than_boundary(executed_command) -> None:
    command = executed_command(time_s=10.0, command_duration_s=1.0)

    assert is_command_expired(command=command, now_s=None) is False
    assert is_command_expired(command=command, now_s=11.0) is False
    assert is_command_expired(command=command, now_s=11.0001) is True


def test_resolve_controller_mode_prioritizes_emergency_stop(executed_command) -> None:
    command = executed_command(
        slew=("right", 5),
        trolley=("out", 5),
        hoist=("up", 5),
        deadman_pressed=False,
        emergency_stop=True,
        time_s=10.0,
        command_duration_s=1.0,
    )

    mode = resolve_controller_mode(command=command, now_s=12.0, hold_position=True)

    assert mode == "emergency_stop"


@pytest.mark.parametrize(
    ("kwargs", "now_s", "hold_position", "expected"),
    [
        ({}, None, True, "hold_position"),
        ({"deadman_pressed": False}, None, False, "deadman_stop"),
        ({"time_s": 10.0, "command_duration_s": 1.0}, 12.0, False, "expired_neutral_stop"),
        (
            {"slew": ("neutral", 0), "trolley": ("neutral", 0), "hoist": ("neutral", 0)},
            None,
            False,
            "neutral_stop",
        ),
        ({"slew": ("right", 1)}, None, False, "normal"),
    ],
)
def test_resolve_controller_mode_covers_stop_modes(
    executed_command, kwargs: dict, now_s: float | None, hold_position: bool, expected: str
) -> None:
    command = executed_command(**kwargs)

    assert (
        resolve_controller_mode(
            command=command,
            now_s=now_s,
            hold_position=hold_position,
        )
        == expected
    )


@pytest.mark.parametrize(
    ("command_kwargs", "now_s", "hold_position", "expected_mode", "emergency", "held"),
    [
        ({"deadman_pressed": False, "slew": ("right", 5)}, None, False, "deadman_stop", False, False),
        ({"emergency_stop": True, "trolley": ("out", 5)}, None, False, "emergency_stop", True, False),
        ({}, None, True, "hold_position", False, True),
        ({"time_s": 10.0, "command_duration_s": 1.0, "hoist": ("up", 5)}, 12.0, False, "expired_neutral_stop", False, False),
    ],
)
def test_compute_stop_mode_target_outputs_zero_desired_velocities_and_diagnostic(
    executed_command,
    command_kwargs: dict,
    now_s: float | None,
    hold_position: bool,
    expected_mode: str,
    emergency: bool,
    held: bool,
) -> None:
    crane = _crane_config()
    state = initialize_crane_state(crane).model_copy(
        update={
            "theta_dot_rad_s": 0.1,
            "trolley_v_m_s": 0.2,
            "hoist_v_m_s": -0.2,
        }
    )
    command = executed_command(**command_kwargs)

    target, diagnostic = compute_stop_mode_target(
        command=command,
        state=state,
        model=crane.model,
        controller_config=ControllerConfig(controller_hz=10.0),
        dt_s=0.1,
        now_s=now_s,
        hold_position=hold_position,
    )

    assert diagnostic.mode == expected_mode
    assert diagnostic.command_expired is (expected_mode == "expired_neutral_stop")
    assert target.emergency_stop is emergency
    assert target.hold_position is held
    assert target.source_command_id == command.command_id
    assert abs(target.target_slew_velocity_rad_s) < abs(state.theta_dot_rad_s)
    assert abs(target.target_trolley_velocity_m_s) < abs(state.trolley_v_m_s)
    assert abs(target.target_hoist_velocity_m_s) < abs(state.hoist_v_m_s)
