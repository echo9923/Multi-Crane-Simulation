from __future__ import annotations

import pytest

from backend.app.schemas.command import ParsedCommand
from backend.app.schemas.config import (
    ForbiddenZonePolicyConfig,
    ScenarioConfig,
    ZoneConfig,
)
from backend.app.schemas.enums import ForbiddenZonePolicyMode
from backend.app.sim.crane_model import build_crane_model_library
from backend.app.sim.layout import build_crane_configs
from backend.app.sim.physics import initialize_crane_state, recompute_state_geometry
from backend.app.sim.safety import (
    MechanicalSafetyError,
    apply_forbidden_zone_policy,
    apply_mechanical_safety,
    movement_enters_forbidden_zone,
    point_in_forbidden_zone,
    predict_next_hook_position,
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
        state = recompute_state_geometry(config, state)
        if "load_position" in updates:
            state = state.model_copy(update={"load_position": updates["load_position"]})
    return state


def _command(
    *,
    slew: tuple[str, int] = ("neutral", 0),
    trolley: tuple[str, int] = ("out", 5),
    hoist: tuple[str, int] = ("neutral", 0),
    crane_id: str = "C1",
):
    raw = ParsedCommand(
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
        deadman_pressed=True,
        emergency_stop=False,
        horn=False,
        command_duration_s=1.0,
        task_action="none",
        attention_target="target",
        confidence=0.7,
        reason="fixture",
    )
    config = _crane_config()
    state = _state(trolley_r_m=20.0, hook_h_m=20.0)
    executed, _ = apply_mechanical_safety(
        command=raw, state=state, config=config, dt_s=0.1
    )
    return executed


def _box_zone(**updates) -> ZoneConfig:
    payload = {
        "zone_id": "Z_BOX",
        "type": "box",
        "center": [24.0, 0.0, 20.0],
        "size": [4.0, 4.0, 4.0],
        "z_range_m": [18.0, 22.0],
    }
    payload.update(updates)
    return ZoneConfig.model_validate(payload)


def _polygon_zone(**updates) -> ZoneConfig:
    payload = {
        "zone_id": "Z_POLY",
        "type": "polygon",
        "points": [[22.0, -2.0], [26.0, -2.0], [26.0, 2.0], [22.0, 2.0]],
        "z_range_m": [18.0, 22.0],
    }
    payload.update(updates)
    return ZoneConfig.model_validate(payload)


def _policy(
    mode: ForbiddenZonePolicyMode, *, record_violation: bool = True
) -> ForbiddenZonePolicyConfig:
    return ForbiddenZonePolicyConfig(mode=mode, record_violation=record_violation)


def test_no_forbidden_zones_does_not_modify_command() -> None:
    config = _crane_config()
    state = _state(trolley_r_m=20.0, hook_h_m=20.0)
    command = _command()

    result_command, result = apply_forbidden_zone_policy(
        command=command,
        state=state,
        config=config,
        forbidden_zones=[],
        policy=_policy(ForbiddenZonePolicyMode.HARD),
        dt_s=1.0,
    )

    assert result.violation_detected is False
    assert result.blocked is False
    assert result_command.modified == command.modified
    assert result_command.left_joystick.trolley.direction == "out"


def test_task_only_policy_records_violation_without_modifying_command() -> None:
    config = _crane_config()
    state = _state(trolley_r_m=20.0, hook_h_m=20.0)
    command = _command()

    result_command, result = apply_forbidden_zone_policy(
        command=command,
        state=state,
        config=config,
        forbidden_zones=[_box_zone()],
        policy=_policy(ForbiddenZonePolicyMode.TASK_ONLY),
        dt_s=5.0,
    )

    assert result.violation_detected is True
    assert result.blocked is False
    assert result.zone_ids == ["Z_BOX"]
    assert result.events[0].reason == "forbidden_zone_violation"
    assert result_command.left_joystick.trolley.direction == "out"
    assert "forbidden_zone" not in result_command.modification_reasons


def test_hard_policy_blocks_motion_entering_forbidden_zone() -> None:
    config = _crane_config()
    state = _state(trolley_r_m=20.0, hook_h_m=20.0)
    command = _command()

    result_command, result = apply_forbidden_zone_policy(
        command=command,
        state=state,
        config=config,
        forbidden_zones=[_box_zone()],
        policy=_policy(ForbiddenZonePolicyMode.HARD),
        dt_s=5.0,
    )

    assert result.violation_detected is True
    assert result.blocked is True
    assert result.zone_ids == ["Z_BOX"]
    assert result.events[0].reason == "forbidden_zone_blocked"
    assert result_command.modified is True
    assert result_command.left_joystick.trolley.direction == "neutral"
    assert result_command.left_joystick.trolley.source == "forbidden_zone"
    assert "forbidden_zone" in result_command.modification_reasons


def test_hard_policy_blocks_slew_only_motion_entering_forbidden_zone() -> None:
    config = _crane_config()
    state = _state(trolley_r_m=20.0, hook_h_m=20.0)
    command = _command(slew=("right", 5), trolley=("neutral", 0))

    result_command, result = apply_forbidden_zone_policy(
        command=command,
        state=state,
        config=config,
        forbidden_zones=[
            _box_zone(
                center=[20.0, 0.75, 20.0],
                size=[1.0, 0.4, 4.0],
                z_range_m=[18.0, 22.0],
            )
        ],
        policy=_policy(ForbiddenZonePolicyMode.HARD),
        dt_s=5.0,
    )

    assert result.violation_detected is True
    assert result.blocked is True
    assert result.zone_ids == ["Z_BOX"]
    assert result_command.left_joystick.slew.direction == "neutral"
    assert result_command.left_joystick.slew.source == "forbidden_zone"
    assert result_command.left_joystick.trolley.direction == "neutral"
    assert result_command.right_joystick.hoist.direction == "neutral"


def test_hard_policy_blocks_hoist_only_motion_entering_forbidden_zone() -> None:
    config = _crane_config()
    state = _state(trolley_r_m=20.0, hook_h_m=20.0)
    command = _command(trolley=("neutral", 0), hoist=("up", 5))

    result_command, result = apply_forbidden_zone_policy(
        command=command,
        state=state,
        config=config,
        forbidden_zones=[
            _box_zone(
                center=[20.0, 0.0, 21.5],
                size=[4.0, 4.0, 1.0],
                z_range_m=[21.0, 22.0],
            )
        ],
        policy=_policy(ForbiddenZonePolicyMode.HARD),
        dt_s=5.0,
    )

    assert result.violation_detected is True
    assert result.blocked is True
    assert result.zone_ids == ["Z_BOX"]
    assert result_command.left_joystick.slew.direction == "neutral"
    assert result_command.left_joystick.trolley.direction == "neutral"
    assert result_command.right_joystick.hoist.direction == "neutral"
    assert result_command.right_joystick.hoist.source == "forbidden_zone"


def test_record_violation_false_suppresses_events_but_returns_result() -> None:
    config = _crane_config()
    state = _state(trolley_r_m=20.0, hook_h_m=20.0)
    command = _command()

    _, result = apply_forbidden_zone_policy(
        command=command,
        state=state,
        config=config,
        forbidden_zones=[_box_zone()],
        policy=_policy(ForbiddenZonePolicyMode.TASK_ONLY, record_violation=False),
        dt_s=5.0,
    )

    assert result.violation_detected is True
    assert result.events == []


def test_load_position_is_checked_before_hook_position() -> None:
    config = _crane_config()
    state = _state(
        trolley_r_m=20.0,
        hook_h_m=20.0,
        load_attached=True,
        load_position=[23.0, 0.0, 20.0],
    )
    command = _command(trolley=("neutral", 0))

    _, result = apply_forbidden_zone_policy(
        command=command,
        state=state,
        config=config,
        forbidden_zones=[_box_zone()],
        policy=_policy(ForbiddenZonePolicyMode.TASK_ONLY),
        dt_s=1.0,
    )

    assert result.violation_detected is True
    assert result.zone_ids == ["Z_BOX"]


def test_polygon_zone_and_z_range_are_supported() -> None:
    assert point_in_forbidden_zone(point=[23.0, 0.0, 20.0], zone=_polygon_zone())
    assert not point_in_forbidden_zone(point=[23.0, 0.0, 25.0], zone=_polygon_zone())


def test_movement_enters_forbidden_zone_samples_segment() -> None:
    zones = [_box_zone()]

    assert movement_enters_forbidden_zone(
        current_point=[20.0, 0.0, 20.0],
        next_point=[26.0, 0.0, 20.0],
        zones=zones,
    ) == ["Z_BOX"]


def test_predict_next_hook_position_uses_executed_trolley_direction() -> None:
    config = _crane_config()
    state = _state(trolley_r_m=20.0, hook_h_m=20.0)
    command = _command()

    next_position = predict_next_hook_position(
        command=command,
        state=state,
        config=config,
        dt_s=1.0,
    )

    assert next_position[0] > state.hook_position[0]
    assert next_position[2] == pytest.approx(state.hook_position[2])


def test_unsupported_zone_type_raises_mechanical_safety_error() -> None:
    with pytest.raises(MechanicalSafetyError):
        point_in_forbidden_zone(
            point=[0.0, 0.0, 0.0],
            zone=ZoneConfig(zone_id="bad", type="circle", center=[0.0, 0.0, 0.0]),
        )


def test_forbidden_zone_policy_requires_matching_crane_ids() -> None:
    config = _crane_config()
    state = _state(trolley_r_m=20.0, hook_h_m=20.0)
    command = _command().model_copy(update={"crane_id": "C2"})

    with pytest.raises(MechanicalSafetyError):
        apply_forbidden_zone_policy(
            command=command,
            state=state,
            config=config,
            forbidden_zones=[_box_zone()],
            policy=_policy(ForbiddenZonePolicyMode.TASK_ONLY),
            dt_s=1.0,
        )
