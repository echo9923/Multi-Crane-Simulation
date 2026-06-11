from __future__ import annotations

import math

from backend.app.core.config_resolver import resolve_config
from backend.app.schemas.command import ParsedCommand
from backend.app.schemas.config import (
    ForbiddenZonePolicyConfig,
    RiskConfig,
    ScenarioConfig,
)
from backend.app.schemas.control import ControllerConfig
from backend.app.schemas.enums import ForbiddenZonePolicyMode, SafetyMode
from backend.app.schemas.weather import WeatherState
from backend.app.sim.controller import Controller
from backend.app.sim.crane_model import build_crane_model_library
from backend.app.sim.layout import build_crane_configs
from backend.app.sim.physics import (
    initialize_world_state,
    recompute_state_geometry,
    step_world,
)
from backend.app.sim.safety import apply_safety_pipeline
from backend.app.tests.test_config_schema import load_fixture


def _manual_scenario_raw(count: int = 2) -> dict:
    raw = load_fixture("scenario_valid.yaml")
    raw["layout"]["mode"] = "manual"
    raw["layout"]["num_cranes"] = count
    raw["cranes"] = [
        {
            "crane_id": f"C{index + 1}",
            "model_id": "generic_flat_top_55m",
            "base": [-45.0 + index * 90.0, 0.0, 0.0],
            "mast_height_m": 45.0 + index * 8.0,
            "theta_init_deg": 0.0 if index == 0 else 180.0,
            "slew": {"mode": "continuous"},
        }
        for index in range(count)
    ]
    return raw


def _cranes_from_raw(raw: dict):
    scenario = ScenarioConfig.model_validate(raw)
    library = build_crane_model_library(scenario.crane_models)
    return scenario, build_crane_configs(scenario.cranes, library, scenario, source="manual")


def _command(
    *,
    crane_id: str,
    command_id: str,
    trolley: tuple[str, int] = ("out", 5),
    slew: tuple[str, int] = ("neutral", 0),
    hoist: tuple[str, int] = ("neutral", 0),
    time_s: float = 5.0,
) -> ParsedCommand:
    return ParsedCommand(
        command_id=command_id,
        response_id=f"resp-{command_id}",
        observation_id=f"obs-{command_id}",
        source_snapshot_id="snap-module-i-integration",
        operator_id=f"op-{crane_id}",
        crane_id=crane_id,
        time_s=time_s,
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
        attention_target="module_i_integration",
        confidence=0.8,
        reason="integration fixture",
    )


def _midspan_states(cranes):
    states = []
    for crane in cranes:
        state = initialize_world_state([crane])[0].model_copy(
            update={
                "trolley_r_m": (crane.trolley_r_min_m + crane.trolley_r_max_m) / 2.0,
                "hook_h_m": (crane.hook_h_min_world_m + crane.hook_h_max_world_m) / 2.0,
            }
        )
        states.append(recompute_state_geometry(crane, state))
    return states


def _risk_config(*, high: float = 20.0) -> RiskConfig:
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
                "near_miss": 3.0,
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


def test_resolved_config_can_construct_controller_and_drive_resolved_cranes() -> None:
    scenario_raw = _manual_scenario_raw(2)
    resolved = resolve_config(scenario_raw, load_fixture("experiment_valid.yaml"))
    _, cranes = _cranes_from_raw(scenario_raw)
    states = _midspan_states(cranes)
    commands = [
        _command(crane_id="C1", command_id="cmd-c1", trolley=("out", 5)),
        _command(crane_id="C2", command_id="cmd-c2", trolley=("in", 5)),
    ]
    safety_result = apply_safety_pipeline(
        commands=commands,
        crane_states=states,
        crane_configs=cranes,
        risk_config=_risk_config(high=5.0),
        weather_state=_weather(),
        safety_mode=SafetyMode.S0,
        forbidden_zones=[],
        forbidden_zone_policy=ForbiddenZonePolicyConfig(mode=ForbiddenZonePolicyMode.TASK_ONLY),
        source_snapshot_id="snap-module-i-integration",
        time_s=5.0,
        dt_s=0.1,
    )

    controller = Controller.from_config(resolved)
    targets, diagnostics = controller.compute_batch(
        commands=safety_result.executed_commands,
        states=states,
        models=cranes,
        dt_s=controller.config.controller_dt_s,
        now_s=5.0,
    )
    next_states = step_world(cranes, states, targets, dt=resolved.runtime.sim["dt"])

    assert [target.crane_id for target in targets] == ["C1", "C2"]
    assert all(diagnostic.mode == "normal" for diagnostic in diagnostics)
    assert next_states[0].trolley_r_m > states[0].trolley_r_m
    assert next_states[1].trolley_r_m < states[1].trolley_r_m
    assert all(math.isfinite(state.hook_position[0]) for state in next_states)


def test_h_s2_speed_scale_reduces_i_output_before_physics_step() -> None:
    scenario, cranes = _cranes_from_raw(_manual_scenario_raw(2))
    states = _midspan_states(cranes)
    commands = [
        _command(crane_id="C1", command_id="cmd-c1", trolley=("out", 5)),
        _command(crane_id="C2", command_id="cmd-c2", trolley=("in", 5)),
    ]

    safety_result = apply_safety_pipeline(
        commands=commands,
        crane_states=states,
        crane_configs=cranes,
        risk_config=_risk_config(high=100.0),
        weather_state=_weather(),
        safety_mode=SafetyMode.S2,
        forbidden_zones=[],
        forbidden_zone_policy=scenario.site.forbidden_zone_policy,
        source_snapshot_id="snap-module-i-integration",
        time_s=5.0,
        dt_s=1.0,
    )
    controller = Controller(ControllerConfig(controller_hz=1.0))

    targets, diagnostics = controller.compute_batch(
        commands=safety_result.executed_commands,
        states=states,
        models=cranes,
        dt_s=1.0,
    )
    next_states = step_world(cranes, states, targets, dt=0.1)

    assert all(command.left_joystick.trolley.speed_scale == 0.5 for command in safety_result.executed_commands)
    assert targets[0].target_trolley_velocity_m_s == 0.25
    assert targets[1].target_trolley_velocity_m_s == -0.25
    assert {
        next(axis.speed_scale for axis in diagnostic.axes if axis.axis == "trolley")
        for diagnostic in diagnostics
    } == {0.5}
    assert next_states[0].trolley_r_m > states[0].trolley_r_m
    assert next_states[1].trolley_r_m < states[1].trolley_r_m


def test_multi_tick_safety_controller_physics_loop_remains_bounded() -> None:
    scenario, cranes = _cranes_from_raw(_manual_scenario_raw(2))
    states = initialize_world_state(cranes)
    controller = Controller(ControllerConfig(controller_hz=10.0))

    for tick in range(10):
        commands = [
            _command(
                crane_id="C1",
                command_id=f"cmd-c1-{tick}",
                trolley=("out", 5),
                slew=("right", 2),
                time_s=5.0 + tick * 0.1,
            ),
            _command(
                crane_id="C2",
                command_id=f"cmd-c2-{tick}",
                trolley=("in", 5),
                slew=("left", 2),
                time_s=5.0 + tick * 0.1,
            ),
        ]
        safety_result = apply_safety_pipeline(
            commands=commands,
            crane_states=states,
            crane_configs=cranes,
            risk_config=_risk_config(high=5.0),
            weather_state=_weather(),
            safety_mode=SafetyMode.S0,
            forbidden_zones=[],
            forbidden_zone_policy=scenario.site.forbidden_zone_policy,
            source_snapshot_id="snap-module-i-integration",
            time_s=5.0 + tick * 0.1,
            dt_s=0.1,
        )
        targets, diagnostics = controller.compute_batch(
            commands=safety_result.executed_commands,
            states=states,
            models=cranes,
            dt_s=0.1,
            now_s=5.0 + tick * 0.1,
        )
        states = step_world(cranes, states, targets, dt=0.1)

        assert all(diagnostic.controller_dt_s == 0.1 for diagnostic in diagnostics)
        assert all(abs(state.theta_dot_rad_s) <= crane.model.slew_speed_max_rad_s for state, crane in zip(states, cranes))
        assert all(crane.trolley_r_min_m <= state.trolley_r_m <= crane.trolley_r_max_m for state, crane in zip(states, cranes))
        assert all(crane.hook_h_min_world_m <= state.hook_h_m <= crane.hook_h_max_world_m for state, crane in zip(states, cranes))
