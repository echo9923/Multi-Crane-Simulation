from __future__ import annotations

import math

import pytest

from backend.app.schemas.command import ParsedCommand
from backend.app.schemas.config import (
    ForbiddenZonePolicyConfig,
    RiskConfig,
    ScenarioConfig,
)
from backend.app.schemas.enums import ForbiddenZonePolicyMode, SafetyMode
from backend.app.schemas.weather import WeatherState
from backend.app.sim.collision import (
    detect_collisions,
    detect_pair_collision,
    point_segment_distance_3d,
    segment_distance_3d,
    segments_intersect_2d,
)
from backend.app.sim.crane_model import build_crane_model_library
from backend.app.sim.layout import build_crane_configs
from backend.app.sim.physics import initialize_crane_state, recompute_state_geometry
from backend.app.sim.safety import apply_safety_pipeline
from backend.app.tests.test_config_schema import load_fixture


def _risk_config() -> RiskConfig:
    return RiskConfig.model_validate(
        {
            "geometry_envelope": {
                "jib_radius_m": 0.5,
                "hook_radius_m": 0.5,
                "load_radius_m": 0.8,
            },
            "thresholds_m": {
                "low": 20.0,
                "medium": 12.0,
                "high": 8.0,
                "near_miss": 3.0,
            },
            "ttc_threshold_level": "high",
            "wind_safe_distance_factor": {
                "enabled": False,
                "extra_clearance_per_10m_s_wind_m": 0.0,
            },
        }
    )


def _configs(*, spacing_m: float = 20.0, angles: tuple[float, float] = (0.0, 180.0), heights: tuple[float, float] = (45.0, 45.0)):
    raw = load_fixture("scenario_valid.yaml")
    raw["layout"]["mode"] = "manual"
    raw["layout"]["num_cranes"] = 2
    raw["cranes"] = [
        {
            "crane_id": "C1",
            "model_id": "generic_flat_top_55m",
            "base": [0.0, 0.0, 0.0],
            "mast_height_m": heights[0],
            "theta_init_deg": angles[0],
            "slew": {"mode": "continuous"},
        },
        {
            "crane_id": "C2",
            "model_id": "generic_flat_top_55m",
            "base": [spacing_m, 0.0, 0.0],
            "mast_height_m": heights[1],
            "theta_init_deg": angles[1],
            "slew": {"mode": "continuous"},
        },
    ]
    scenario = ScenarioConfig.model_validate(raw)
    library = build_crane_model_library(scenario.crane_models)
    return build_crane_configs(scenario.cranes, library, scenario, source="manual")


def _state(config, *, trolley_r_m: float = 10.0, hook_h_m: float = 20.0):
    return recompute_state_geometry(
        config,
        initialize_crane_state(config).model_copy(
            update={"trolley_r_m": trolley_r_m, "hook_h_m": hook_h_m}
        ),
    )


def _command(config):
    return ParsedCommand(
        command_id=f"cmd-{config.crane_id}",
        response_id="resp",
        observation_id=f"obs-{config.crane_id}",
        source_snapshot_id="snap-001",
        operator_id=f"op-{config.crane_id}",
        crane_id=config.crane_id,
        time_s=5.0,
        left_joystick={
            "slew": {"direction": "neutral", "gear": 0},
            "trolley": {"direction": "neutral", "gear": 0},
        },
        right_joystick={"hoist": {"direction": "neutral", "gear": 0}},
        deadman_pressed=True,
        emergency_stop=False,
        horn=False,
        command_duration_s=1.0,
        task_action="none",
        attention_target="collision",
        confidence=0.8,
        reason="fixture",
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


def test_segments_intersect_2d_crossing_parallel_and_touching() -> None:
    assert segments_intersect_2d((0.0, 0.0), (4.0, 4.0), (0.0, 4.0), (4.0, 0.0))
    assert not segments_intersect_2d((0.0, 0.0), (4.0, 0.0), (0.0, 2.0), (4.0, 2.0))
    assert segments_intersect_2d((0.0, 0.0), (4.0, 0.0), (4.0, 0.0), (4.0, 4.0))


def test_distance_helpers_compute_expected_values() -> None:
    assert point_segment_distance_3d([2.0, 2.0, 0.0], [0.0, 0.0, 0.0], [4.0, 0.0, 0.0]) == pytest.approx(2.0)
    assert segment_distance_3d(
        [0.0, 0.0, 0.0],
        [4.0, 0.0, 0.0],
        [2.0, 2.0, 0.0],
        [2.0, 4.0, 0.0],
    ) == pytest.approx(2.0)


def test_hook_hook_collision_generates_failed_collision_event() -> None:
    configs = _configs(spacing_m=20.0, heights=(45.0, 60.0))
    state_a = _state(configs[0], trolley_r_m=10.0, hook_h_m=20.0)
    state_b = _state(configs[1], trolley_r_m=10.0, hook_h_m=20.0)

    event = detect_pair_collision(
        state_a=state_a,
        config_a=configs[0],
        state_b=state_b,
        config_b=configs[1],
        risk_config=_risk_config(),
        source_snapshot_id="snap-001",
        time_s=5.0,
    )

    assert event is not None
    assert event.episode_status == "failed_collision"
    assert event.object_a == "hook"
    assert event.object_b == "hook"


def test_horizontal_jib_crossing_with_height_clearance_is_not_collision() -> None:
    configs = _configs(spacing_m=20.0, angles=(0.0, 180.0), heights=(45.0, 60.0))
    states = [
        _state(configs[0], trolley_r_m=10.0, hook_h_m=20.0),
        _state(configs[1], trolley_r_m=10.0, hook_h_m=35.0),
    ]

    assert detect_collisions(
        crane_states=states,
        crane_configs=configs,
        risk_config=_risk_config(),
        source_snapshot_id="snap-001",
        time_s=5.0,
    ) is None


def test_jib_jib_collision_detected_when_3d_distance_within_envelope() -> None:
    configs = _configs(spacing_m=20.0, angles=(0.0, 180.0), heights=(45.0, 45.0))
    states = [_state(config, trolley_r_m=10.0, hook_h_m=20.0) for config in configs]

    event = detect_collisions(
        crane_states=states,
        crane_configs=configs,
        risk_config=_risk_config(),
        source_snapshot_id="snap-001",
        time_s=5.0,
    )

    assert event is not None
    assert {event.object_a, event.object_b} == {"jib"}


def test_pipeline_marks_failed_collision_when_collision_detected() -> None:
    configs = _configs(spacing_m=20.0)
    states = [_state(config, trolley_r_m=10.0, hook_h_m=20.0) for config in configs]

    result = apply_safety_pipeline(
        commands=[_command(config) for config in configs],
        crane_states=states,
        crane_configs=configs,
        risk_config=_risk_config(),
        weather_state=_weather(),
        safety_mode=SafetyMode.S0,
        forbidden_zones=[],
        forbidden_zone_policy=ForbiddenZonePolicyConfig(mode=ForbiddenZonePolicyMode.TASK_ONLY),
        source_snapshot_id="snap-001",
        time_s=5.0,
        dt_s=0.1,
    )

    assert result.collision is not None
    assert result.episode_status == "failed_collision"
    assert result.events[-1].event_type == "collision"
