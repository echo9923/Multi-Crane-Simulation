from __future__ import annotations

import math

import pytest
from pydantic import ValidationError

from backend.app.schemas.command import (
    ExecutedAxisCommand,
    ExecutedCommand,
    ExecutedLeftJoystickCommand,
    ExecutedRightJoystickCommand,
    ParsedCommand,
)
from backend.app.schemas.config import ScenarioConfig
from backend.app.schemas.control import ControlTarget, ControllerConfig, ControllerStateError
from backend.app.sim.controller import Controller
from backend.app.sim.crane_model import build_crane_model_library
from backend.app.sim.layout import build_crane_configs
from backend.app.sim.physics import initialize_crane_state, step_crane_state
from backend.app.sim.safety import apply_mechanical_safety
from backend.app.tests.test_config_schema import load_fixture


def _crane_configs(count: int = 1):
    raw = load_fixture("scenario_valid.yaml")
    raw["layout"]["mode"] = "manual"
    raw["layout"]["num_cranes"] = count
    raw["cranes"] = [
        {
            "crane_id": f"C{index + 1}",
            "model_id": "generic_flat_top_55m",
            "base": [index * 35.0, 0.0, 0.0],
            "mast_height_m": 45.0 + index * 5.0,
            "theta_init_deg": 0.0 if index == 0 else 180.0,
            "slew": {"mode": "continuous"},
        }
        for index in range(count)
    ]
    scenario = ScenarioConfig.model_validate(raw)
    library = build_crane_model_library(scenario.crane_models)
    return build_crane_configs(scenario.cranes, library, scenario, source="manual")


def _raw_command(
    *,
    crane_id: str = "C1",
    command_id: str = "cmd-raw",
    slew: tuple[str, int] = ("neutral", 0),
    trolley: tuple[str, int] = ("neutral", 0),
    hoist: tuple[str, int] = ("neutral", 0),
    deadman_pressed: bool = True,
    emergency_stop: bool = False,
    time_s: float = 5.0,
    command_duration_s: float = 1.0,
    reason: str = "acceptance fixture",
) -> ParsedCommand:
    return ParsedCommand(
        command_id=command_id,
        response_id=f"resp-{command_id}",
        observation_id=f"obs-{command_id}",
        source_snapshot_id=f"snap-{command_id}",
        operator_id=f"op-{crane_id}",
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
        command_duration_s=command_duration_s,
        task_action="none",
        attention_target="module_i_acceptance",
        confidence=0.8,
        reason=reason,
    )


def _executed_command(
    *,
    crane_id: str = "C1",
    command_id: str = "cmd-exec",
    slew: tuple[str, int] = ("neutral", 0),
    trolley: tuple[str, int] = ("neutral", 0),
    hoist: tuple[str, int] = ("neutral", 0),
    speed_scales: tuple[float, float, float] = (1.0, 1.0, 1.0),
    sources: tuple[str, str, str] = ("raw", "raw", "raw"),
    deadman_pressed: bool = True,
    emergency_stop: bool = False,
    time_s: float = 5.0,
    command_duration_s: float = 1.0,
) -> ExecutedCommand:
    raw_command = _raw_command(
        crane_id=crane_id,
        command_id=command_id,
        slew=slew,
        trolley=trolley,
        hoist=hoist,
        deadman_pressed=deadman_pressed,
        emergency_stop=emergency_stop,
        time_s=time_s,
        command_duration_s=max(command_duration_s, 0.5),
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
        modification_reasons=["acceptance_fixture"] if modified else [],
    )


def _controller() -> Controller:
    return Controller(ControllerConfig(controller_hz=10.0))


@pytest.mark.parametrize(
    ("axis_name", "negative", "positive"),
    [
        ("slew", ("left", -1), ("right", 1)),
        ("trolley", ("in", -1), ("out", 1)),
        ("hoist", ("down", -1), ("up", 1)),
    ],
)
@pytest.mark.parametrize("gear", [0, 1, 2, 3, 4, 5])
def test_all_handle_commands_convert_to_control_target(
    axis_name: str,
    negative: tuple[str, int],
    positive: tuple[str, int],
    gear: int,
) -> None:
    crane = _crane_configs()[0]
    state = initialize_crane_state(crane)
    direction = "neutral" if gear == 0 else positive[0]
    axis_command = (direction, gear)
    kwargs = {"slew": ("neutral", 0), "trolley": ("neutral", 0), "hoist": ("neutral", 0)}
    kwargs[axis_name] = axis_command
    command = _executed_command(crane_id=crane.crane_id, **kwargs)

    target, diagnostic = _controller().compute_target(
        command=command,
        state=state,
        model=crane.model,
        dt_s=0.1,
    )

    assert target.crane_id == crane.crane_id
    assert target.source_command_id == command.command_id
    assert diagnostic.source_command_id == command.command_id
    assert len(diagnostic.axes) == 3


def test_outputs_do_not_exceed_mechanical_speed_or_acceleration_limits() -> None:
    crane = _crane_configs()[0]
    state = initialize_crane_state(crane)
    command = _executed_command(
        crane_id=crane.crane_id,
        slew=("right", 5),
        trolley=("out", 5),
        hoist=("up", 5),
    )

    target, diagnostic = _controller().compute_target(
        command=command,
        state=state,
        model=crane.model,
        dt_s=0.1,
    )

    assert abs(target.target_slew_velocity_rad_s) <= crane.model.slew_speed_max_rad_s
    assert abs(target.target_trolley_velocity_m_s) <= crane.model.trolley_speed_max_m_s
    assert abs(target.target_hoist_velocity_m_s) <= crane.model.hoist_speed_max_m_s
    assert (
        abs(target.target_slew_velocity_rad_s - state.theta_dot_rad_s)
        <= crane.model.slew_acc_max_rad_s2 * 0.1 + 1e-12
    )
    assert (
        abs(target.target_trolley_velocity_m_s - state.trolley_v_m_s)
        <= crane.model.trolley_acc_max_m_s2 * 0.1 + 1e-12
    )
    assert (
        abs(target.target_hoist_velocity_m_s - state.hoist_v_m_s)
        <= crane.model.hoist_acc_max_m_s2 * 0.1 + 1e-12
    )
    assert any(axis.acceleration_limited for axis in diagnostic.axes)


def test_speed_scale_from_safety_intervention_multiplies_velocity() -> None:
    crane = _crane_configs()[0]
    state = initialize_crane_state(crane)
    command = _executed_command(
        crane_id=crane.crane_id,
        trolley=("out", 5),
        speed_scales=(1.0, 0.5, 1.0),
        sources=("raw", "risk_intervention", "raw"),
    )
    fast_controller = Controller(ControllerConfig(controller_hz=1.0))

    target, diagnostic = fast_controller.compute_target(
        command=command,
        state=state,
        model=crane.model,
        dt_s=1.0,
    )

    assert target.target_trolley_velocity_m_s == pytest.approx(0.25)
    trolley_diag = next(axis for axis in diagnostic.axes if axis.axis == "trolley")
    assert trolley_diag.speed_scale == pytest.approx(0.5)
    assert trolley_diag.desired_velocity_before_speed_clamp == pytest.approx(0.25)


def test_neutral_deadman_expiry_and_emergency_stop_modes() -> None:
    crane = _crane_configs()[0]
    state = initialize_crane_state(crane).model_copy(
        update={"theta_dot_rad_s": 0.1, "trolley_v_m_s": 0.2, "hoist_v_m_s": -0.2}
    )
    controller = _controller()

    neutral_target, neutral_diag = controller.compute_target(
        command=_executed_command(crane_id=crane.crane_id),
        state=state,
        model=crane.model,
        dt_s=0.1,
    )
    expired_target, expired_diag = controller.compute_target(
        command=_executed_command(
            crane_id=crane.crane_id,
            trolley=("out", 5),
            time_s=10.0,
            command_duration_s=1.0,
        ),
        state=state,
        model=crane.model,
        dt_s=0.1,
        now_s=11.1,
    )
    deadman_target, deadman_diag = controller.compute_target(
        command=_executed_command(
            crane_id=crane.crane_id,
            slew=("right", 5),
            deadman_pressed=False,
        ),
        state=state,
        model=crane.model,
        dt_s=0.1,
    )
    emergency_target, emergency_diag = controller.compute_target(
        command=_executed_command(
            crane_id=crane.crane_id,
            hoist=("up", 5),
            emergency_stop=True,
        ),
        state=state,
        model=crane.model,
        dt_s=0.1,
    )

    assert neutral_diag.mode == "neutral_stop"
    assert expired_diag.mode == "expired_neutral_stop"
    assert expired_diag.command_expired is True
    assert deadman_diag.mode == "deadman_stop"
    assert emergency_diag.mode == "emergency_stop"
    assert emergency_target.emergency_stop is True
    for target in [neutral_target, expired_target, deadman_target, emergency_target]:
        assert abs(target.target_slew_velocity_rad_s) < abs(state.theta_dot_rad_s)
        assert abs(target.target_trolley_velocity_m_s) < abs(state.trolley_v_m_s)
        assert abs(target.target_hoist_velocity_m_s) < abs(state.hoist_v_m_s)


def test_rule_and_llm_commands_share_identical_control_logic() -> None:
    crane = _crane_configs()[0]
    state = initialize_crane_state(crane)
    controller = _controller()
    rule_command = _executed_command(
        crane_id=crane.crane_id,
        command_id="rule-command",
        trolley=("out", 4),
    )
    llm_command = _executed_command(
        crane_id=crane.crane_id,
        command_id="llm-command",
        trolley=("out", 4),
    )

    rule_target, _ = controller.compute_target(command=rule_command, state=state, model=crane.model)
    llm_target, _ = controller.compute_target(command=llm_command, state=state, model=crane.model)

    assert rule_target.model_copy(update={"source_command_id": None}) == llm_target.model_copy(
        update={"source_command_id": None}
    )


def test_h_to_i_to_c_smoke_step() -> None:
    crane = _crane_configs()[0]
    state = initialize_crane_state(crane)
    raw = _raw_command(
        crane_id=crane.crane_id,
        slew=("right", 2),
        trolley=("out", 2),
        hoist=("down", 2),
    )
    executed, _ = apply_mechanical_safety(
        command=raw,
        state=state,
        config=crane,
        dt_s=1.0,
    )

    target, diagnostic = _controller().compute_target(
        command=executed,
        state=state,
        model=crane.model,
        dt_s=0.1,
    )
    next_state = step_crane_state(crane, state, target, dt=0.1)

    assert diagnostic.mode == "normal"
    assert next_state.crane_id == crane.crane_id
    assert math.isfinite(next_state.theta_rad)
    assert math.isfinite(next_state.trolley_r_m)
    assert math.isfinite(next_state.hook_h_m)


def test_fast_gear_switch_crosses_zero_with_bounded_delta() -> None:
    crane = _crane_configs()[0]
    state = initialize_crane_state(crane).model_copy(
        update={"theta_dot_rad_s": crane.model.slew_acc_max_rad_s2 * 0.5}
    )
    command = _executed_command(crane_id=crane.crane_id, slew=("left", 5))

    target, _ = _controller().compute_target(
        command=command,
        state=state,
        model=crane.model,
        dt_s=0.1,
    )

    delta = target.target_slew_velocity_rad_s - state.theta_dot_rad_s
    assert delta < 0
    assert abs(delta) <= crane.model.slew_acc_max_rad_s2 * 0.1 + 1e-12


def test_multi_crane_batch_matches_individual_results() -> None:
    cranes = _crane_configs(2)
    states = [initialize_crane_state(crane) for crane in cranes]
    commands = [
        _executed_command(crane_id="C2", command_id="cmd-C2", trolley=("out", 5)),
        _executed_command(crane_id="C1", command_id="cmd-C1", slew=("right", 5)),
    ]
    controller = _controller()

    batch_targets, batch_diagnostics = controller.compute_batch(
        commands=commands,
        states=list(reversed(states)),
        models={crane.crane_id: crane.model for crane in cranes},
        dt_s=0.1,
    )
    individual_targets = [
        controller.compute_target(
            command=commands[0],
            state=states[1],
            model=cranes[1].model,
            dt_s=0.1,
        )[0],
        controller.compute_target(
            command=commands[1],
            state=states[0],
            model=cranes[0].model,
            dt_s=0.1,
        )[0],
    ]

    assert batch_targets == individual_targets
    assert [target.crane_id for target in batch_targets] == ["C2", "C1"]
    assert [diagnostic.crane_id for diagnostic in batch_diagnostics] == ["C2", "C1"]


def test_invalid_numeric_inputs_raise_failed_invalid_state() -> None:
    crane = _crane_configs()[0]
    bad_state = initialize_crane_state(crane).model_copy(update={"theta_dot_rad_s": math.nan})
    command = _executed_command(crane_id=crane.crane_id, slew=("right", 1))

    with pytest.raises(ControllerStateError) as exc_info:
        _controller().compute_target(command=command, state=bad_state, model=crane.model)

    assert exc_info.value.episode_status == "failed_invalid_state"
    assert exc_info.value.field_path == "current_velocity"


def test_control_target_contains_no_task_or_llm_semantics() -> None:
    forbidden = {"task_id", "task_stage", "reason", "llm_reason", "attention_target"}

    assert forbidden.isdisjoint(ControlTarget.model_fields)
    with pytest.raises(ValidationError):
        ControlTarget(
            crane_id="C1",
            target_slew_velocity_rad_s=0.0,
            target_trolley_velocity_m_s=0.0,
            target_hoist_velocity_m_s=0.0,
            reason="not allowed",
        )
