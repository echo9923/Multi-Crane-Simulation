from __future__ import annotations

import pytest

from backend.app.schemas.command import ParsedCommand
from backend.app.schemas.config import (
    ForbiddenZonePolicyConfig,
    RiskConfig,
    ScenarioConfig,
)
from backend.app.schemas.enums import ForbiddenZonePolicyMode, SafetyMode
from backend.app.schemas.weather import WeatherState
from backend.app.sim.crane_model import build_crane_model_library
from backend.app.sim.layout import build_crane_configs
from backend.app.sim.physics import initialize_crane_state, recompute_state_geometry
from backend.app.sim.safety import (
    MechanicalSafetyError,
    apply_risk_interventions,
    apply_safety_pipeline,
    force_stop_on_high_risk,
    limit_speed_on_high_risk,
)
from backend.app.tests.test_config_schema import load_fixture


def _configs(*, spacing_m: float = 30.0):
    raw = load_fixture("scenario_valid.yaml")
    raw["layout"]["mode"] = "manual"
    raw["layout"]["num_cranes"] = 2
    raw["cranes"] = [
        {
            "crane_id": "C1",
            "model_id": "generic_flat_top_55m",
            "base": [0.0, 0.0, 0.0],
            "mast_height_m": 45.0,
            "theta_init_deg": 0.0,
            "slew": {"mode": "continuous"},
        },
        {
            "crane_id": "C2",
            "model_id": "generic_flat_top_55m",
            "base": [spacing_m, 0.0, 0.0],
            "mast_height_m": 60.0,
            "theta_init_deg": 180.0,
            "slew": {"mode": "continuous"},
        },
    ]
    scenario = ScenarioConfig.model_validate(raw)
    library = build_crane_model_library(scenario.crane_models)
    return build_crane_configs(scenario.cranes, library, scenario, source="manual")


def _states(configs, *, trolley_r_m: float = 10.0):
    states = []
    for config in configs:
        state = initialize_crane_state(config).model_copy(
            update={"trolley_r_m": trolley_r_m, "hook_h_m": 20.0}
        )
        states.append(recompute_state_geometry(config, state))
    return states


def _command(config, *, trolley: tuple[str, int] = ("out", 5), snapshot_id: str = "snap-001"):
    return ParsedCommand(
        command_id=f"cmd-{config.crane_id}",
        response_id="resp",
        observation_id=f"obs-{config.crane_id}",
        source_snapshot_id=snapshot_id,
        operator_id=f"op-{config.crane_id}",
        crane_id=config.crane_id,
        time_s=5.0,
        left_joystick={
            "slew": {"direction": "neutral", "gear": 0},
            "trolley": {"direction": trolley[0], "gear": trolley[1]},
        },
        right_joystick={"hoist": {"direction": "neutral", "gear": 0}},
        deadman_pressed=True,
        emergency_stop=False,
        horn=False,
        command_duration_s=1.0,
        task_action="none",
        attention_target="risk",
        confidence=0.8,
        reason="fixture",
    )


def _risk_config(*, high: float = 20.0, near_miss: float = 3.0) -> RiskConfig:
    return RiskConfig.model_validate(
        {
            "geometry_envelope": {
                "jib_radius_m": 0.5,
                "hook_radius_m": 0.5,
                "load_radius_m": 0.8,
            },
            "thresholds_m": {
                "low": 40.0,
                "medium": 30.0,
                "high": high,
                "near_miss": near_miss,
            },
            "ttc_threshold_level": "high",
            "wind_safe_distance_factor": {
                "enabled": False,
                "extra_clearance_per_10m_s_wind_m": 2.0,
            },
        }
    )


def _weather() -> WeatherState:
    return WeatherState(
        time_s=5.0,
        mode="constant",
        wind_speed_m_s=0.0,
        wind_gust_m_s=0.0,
        wind_direction_deg=90.0,
        visibility_level="good",
        rain_level="none",
        fog_level="none",
        generation_seed=1,
        generation_step=0,
    )


def _policy() -> ForbiddenZonePolicyConfig:
    return ForbiddenZonePolicyConfig(mode=ForbiddenZonePolicyMode.TASK_ONLY)


def _pipeline(*, safety_mode: SafetyMode, high: float = 20.0, spacing_m: float = 30.0):
    configs = _configs(spacing_m=spacing_m)
    states = _states(configs)
    commands = [_command(config) for config in configs]
    return apply_safety_pipeline(
        commands=commands,
        crane_states=states,
        crane_configs=configs,
        risk_config=_risk_config(high=high),
        weather_state=_weather(),
        safety_mode=safety_mode,
        forbidden_zones=[],
        forbidden_zone_policy=_policy(),
        source_snapshot_id="snap-001",
        time_s=5.0,
        dt_s=0.1,
    )


def test_s0_records_risk_without_risk_intervention() -> None:
    result = _pipeline(safety_mode=SafetyMode.S0)

    assert result.online_risk.global_risk_level in {"high", "near_miss", "collision"}
    assert all(command.left_joystick.trolley.speed_scale == 1.0 for command in result.executed_commands)
    assert result.events == []


def test_s1_records_non_modifying_ignored_risk_records() -> None:
    result = _pipeline(safety_mode=SafetyMode.S1)

    assert result.online_risk.global_risk_level in {"high", "near_miss", "collision"}
    assert all(command.left_joystick.trolley.speed_scale == 1.0 for command in result.executed_commands)
    assert all(
        intervention.action == "ignored_risk_hint"
        for command in result.executed_commands
        for intervention in command.interventions
    )


def test_s2_limits_speed_on_high_risk() -> None:
    result = _pipeline(safety_mode=SafetyMode.S2)

    assert result.online_risk.global_risk_level in {"high", "near_miss", "collision"}
    for command in result.executed_commands:
        assert command.modified is True
        assert command.left_joystick.trolley.speed_scale == 0.5
        assert "risk_intervention" in command.modification_reasons
        assert command.interventions[0].action == "limit_speed_on_high_risk"
    assert all(event.reason == "intervention_applied" for event in result.events)


def test_s2_does_not_limit_speed_on_medium_risk() -> None:
    result = _pipeline(safety_mode=SafetyMode.S2, high=5.0, spacing_m=55.0)

    assert result.online_risk.global_risk_level in {"safe", "low", "medium"}
    assert all(command.left_joystick.trolley.speed_scale == 1.0 for command in result.executed_commands)
    assert result.events == []


def test_s3_forces_stop_on_high_risk() -> None:
    result = _pipeline(safety_mode=SafetyMode.S3)

    for command in result.executed_commands:
        assert command.modified is True
        assert command.left_joystick.trolley.direction == "neutral"
        assert command.left_joystick.trolley.gear == 0
        assert command.right_joystick.hoist.direction == "neutral"
        assert command.interventions[0].action == "force_stop_on_high_risk"


def test_limit_speed_helper_preserves_direction_and_caps_scale() -> None:
    result = _pipeline(safety_mode=SafetyMode.S0)
    command = result.executed_commands[0]

    limited = limit_speed_on_high_risk(command=command, reason="fixture")

    assert limited.left_joystick.trolley.direction == command.left_joystick.trolley.direction
    assert limited.left_joystick.trolley.gear == command.left_joystick.trolley.gear
    assert limited.left_joystick.trolley.speed_scale == 0.5
    assert limited.left_joystick.trolley.source == "risk_intervention"


def test_force_stop_helper_neutralizes_motion_axes() -> None:
    result = _pipeline(safety_mode=SafetyMode.S0)
    command = result.executed_commands[0]

    stopped = force_stop_on_high_risk(command=command, reason="fixture")

    assert stopped.left_joystick.slew.direction == "neutral"
    assert stopped.left_joystick.trolley.direction == "neutral"
    assert stopped.right_joystick.hoist.direction == "neutral"
    assert stopped.task_action == command.task_action


def test_pipeline_rejects_snapshot_mismatch() -> None:
    configs = _configs()
    states = _states(configs)
    commands = [
        _command(configs[0], snapshot_id="snap-001"),
        _command(configs[1], snapshot_id="snap-002"),
    ]

    with pytest.raises(MechanicalSafetyError):
        apply_safety_pipeline(
            commands=commands,
            crane_states=states,
            crane_configs=configs,
            risk_config=_risk_config(),
            weather_state=_weather(),
            safety_mode=SafetyMode.S2,
            forbidden_zones=[],
            forbidden_zone_policy=_policy(),
            source_snapshot_id="snap-001",
            time_s=5.0,
            dt_s=0.1,
        )


def test_apply_risk_interventions_can_be_called_directly() -> None:
    result = _pipeline(safety_mode=SafetyMode.S0)

    commands, interventions = apply_risk_interventions(
        commands=result.executed_commands,
        online_risk=result.online_risk,
        safety_mode=SafetyMode.S2,
    )

    assert interventions
    assert all(command.modified for command in commands)
