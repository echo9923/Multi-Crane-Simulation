from __future__ import annotations

import ast
from pathlib import Path

from backend.app.schemas.weather import WeatherState
from backend.app.sim.weather import build_wind_advisory


REPO_ROOT = Path(__file__).resolve().parents[3]


def _state(wind_speed: float, gust: float) -> WeatherState:
    return WeatherState(
        time_s=3.0,
        mode="schedule",
        wind_speed_m_s=wind_speed,
        wind_gust_m_s=gust,
        wind_direction_deg=90.0,
        visibility_level="medium",
        rain_level="none",
        fog_level="none",
        source_segment_id="wind",
        generation_seed=303,
        generation_step=3,
    )


def test_wind_for_safety_is_max_average_and_gust() -> None:
    state = _state(6.0, 14.0)

    assert state.wind_for_safety_m_s == 14.0
    assert state.wind_advisory_level == "gusty"


def test_wind_advisory_contains_prompt_behavior_keys_without_commands() -> None:
    advisory = build_wind_advisory(_state(10.0, 17.0))

    payload = advisory.model_dump(mode="json")
    assert payload["level"] == "strong_wind"
    assert payload["wind_for_safety_m_s"] == 17.0
    assert payload["message_key"] == "weather.wind.strong_wind"
    assert payload["recommended_behavior_keys"] == [
        "reduce_gear",
        "slow_hoist",
        "avoid_sudden_slew",
        "increase_observation",
        "pause_if_gusty",
    ]
    assert "target_slew_velocity_rad_s" not in str(payload)
    assert "emergency_stop" not in str(payload)


def test_normal_wind_advisory_keeps_behavior_keys_empty() -> None:
    advisory = build_wind_advisory(_state(3.0, 4.0))

    assert advisory.level == "normal"
    assert advisory.recommended_behavior_keys == []


def test_weather_module_does_not_import_risk_control_or_physics_state() -> None:
    for relative_path in ["backend/app/sim/weather.py", "backend/app/schemas/weather.py"]:
        tree = ast.parse((REPO_ROOT / relative_path).read_text(encoding="utf-8"))
        imported = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.append(node.module)

        banned_prefixes = (
            "backend.app.risk",
            "backend.app.sim.risk",
            "backend.app.schemas.control",
            "backend.app.sim.physics",
            "backend.app.schemas.state",
        )
        assert not [module for module in imported if module.startswith(banned_prefixes)]
