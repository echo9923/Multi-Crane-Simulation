from __future__ import annotations

import pytest

from backend.app.schemas.command import (
    ExecutedAxisCommand,
    ExecutedCommand,
    ExecutedLeftJoystickCommand,
    ExecutedRightJoystickCommand,
    ParsedCommand,
)
from backend.app.schemas.config import ScenarioConfig
from backend.app.schemas.control import ControllerConfig, ControllerStateError
from backend.app.sim.controller import Controller
from backend.app.sim.crane_model import build_crane_model_library
from backend.app.sim.layout import build_crane_configs
from backend.app.sim.physics import initialize_crane_state
from backend.app.tests.test_config_schema import load_fixture


def _crane_configs(count: int = 2):
    raw = load_fixture("scenario_valid.yaml")
    raw["layout"]["mode"] = "manual"
    raw["layout"]["num_cranes"] = count
    raw["cranes"] = [
        {
            "crane_id": f"C{index + 1}",
            "model_id": "generic_flat_top_55m",
            "base": [index * 45.0, 0.0, 0.0],
            "mast_height_m": 45.0 + index * 5.0,
            "theta_init_deg": 0.0,
            "slew": {"mode": "continuous"},
        }
        for index in range(count)
    ]
    scenario = ScenarioConfig.model_validate(raw)
    library = build_crane_model_library(scenario.crane_models)
    return build_crane_configs(scenario.cranes, library, scenario, source="manual")


def _executed_command(
    *,
    crane_id: str,
    command_id: str,
    slew: tuple[str, int] = ("neutral", 0),
    trolley: tuple[str, int] = ("neutral", 0),
    hoist: tuple[str, int] = ("neutral", 0),
    deadman_pressed: bool = True,
    emergency_stop: bool = False,
) -> ExecutedCommand:
    raw = ParsedCommand(
        command_id=command_id,
        response_id=f"resp-{command_id}",
        observation_id=f"obs-{command_id}",
        source_snapshot_id=f"snap-{command_id}",
        operator_id=f"op-{crane_id}",
        crane_id=crane_id,
        time_s=5.0,
        left_joystick={
            "slew": {"direction": slew[0], "gear": slew[1]},
            "trolley": {"direction": trolley[0], "gear": trolley[1]},
        },
        right_joystick={"hoist": {"direction": hoist[0], "gear": hoist[1]}},
        deadman_pressed=deadman_pressed,
        emergency_stop=emergency_stop,
        horn=False,
        command_duration_s=1.0,
        task_action="none",
        attention_target="module_i_edges",
        confidence=0.8,
        reason="edge fixture",
    )
    return ExecutedCommand(
        command_id=f"EXEC_{command_id}",
        raw_command_id=raw.command_id,
        observation_id=raw.observation_id,
        source_snapshot_id=raw.source_snapshot_id,
        operator_id=raw.operator_id,
        crane_id=crane_id,
        time_s=raw.time_s,
        raw_command=raw,
        left_joystick=ExecutedLeftJoystickCommand(
            slew=ExecutedAxisCommand(direction=slew[0], gear=slew[1], source="raw"),
            trolley=ExecutedAxisCommand(
                direction=trolley[0], gear=trolley[1], source="raw"
            ),
        ),
        right_joystick=ExecutedRightJoystickCommand(
            hoist=ExecutedAxisCommand(direction=hoist[0], gear=hoist[1], source="raw")
        ),
        deadman_pressed=deadman_pressed,
        emergency_stop=emergency_stop,
        horn=False,
        command_duration_s=raw.command_duration_s,
        task_action="none",
        modified=False,
    )


def test_compute_batch_accepts_crane_config_sequence_as_model_source() -> None:
    cranes = _crane_configs(2)
    states = [initialize_crane_state(cranes[1]), initialize_crane_state(cranes[0])]
    commands = [
        _executed_command(crane_id="C2", command_id="cmd-c2", trolley=("out", 5)),
        _executed_command(crane_id="C1", command_id="cmd-c1", slew=("right", 5)),
    ]

    targets, diagnostics = Controller(ControllerConfig(controller_hz=10.0)).compute_batch(
        commands=commands,
        states=states,
        models=cranes,
        dt_s=0.1,
    )

    assert [target.crane_id for target in targets] == ["C2", "C1"]
    assert [diagnostic.crane_id for diagnostic in diagnostics] == ["C2", "C1"]
    assert targets[0].target_trolley_velocity_m_s > 0
    assert targets[1].target_slew_velocity_rad_s > 0


def test_stop_mode_diagnostic_preserves_original_axis_command_metadata() -> None:
    crane = _crane_configs(1)[0]
    state = initialize_crane_state(crane)
    command = _executed_command(
        crane_id=crane.crane_id,
        command_id="cmd-deadman",
        slew=("right", 5),
        trolley=("out", 4),
        hoist=("up", 3),
        deadman_pressed=False,
    )

    _, diagnostic = Controller(ControllerConfig(controller_hz=10.0)).compute_target(
        command=command,
        state=state,
        model=crane.model,
        dt_s=0.1,
    )

    by_axis = {axis.axis: axis for axis in diagnostic.axes}
    assert diagnostic.mode == "deadman_stop"
    assert by_axis["slew"].direction == "right"
    assert by_axis["slew"].gear == 5
    assert by_axis["trolley"].direction == "out"
    assert by_axis["trolley"].gear == 4
    assert by_axis["hoist"].direction == "up"
    assert by_axis["hoist"].gear == 3


def test_compute_batch_reports_missing_model_by_crane_id() -> None:
    crane = _crane_configs(1)[0]
    state = initialize_crane_state(crane)
    command = _executed_command(
        crane_id=crane.crane_id,
        command_id="cmd-missing-model",
        trolley=("out", 1),
    )

    with pytest.raises(ControllerStateError) as exc_info:
        Controller(ControllerConfig(controller_hz=10.0)).compute_batch(
            commands=[command],
            states=[state],
            models={},
        )

    assert exc_info.value.field_path == "models"
    assert exc_info.value.crane_id == crane.crane_id
