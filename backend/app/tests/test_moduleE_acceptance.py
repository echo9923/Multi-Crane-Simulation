from __future__ import annotations

import ast
from pathlib import Path

from backend.app.core.config_resolver import resolve_config
from backend.app.schemas.weather import WeatherWorldSnapshot
from backend.app.sim.weather import (
    WeatherGenerator,
    build_weather_frame_summary,
    build_weather_record_row,
    build_weather_visibility_context,
    build_wind_advisory,
)
from backend.app.tests.test_config_schema import load_fixture


REPO_ROOT = Path(__file__).resolve().parents[3]


def _module_e_demo_raw() -> dict:
    raw = load_fixture("scenario_valid.yaml")
    raw["layout"]["mode"] = "manual"
    raw["layout"]["num_cranes"] = 3
    raw["cranes"] = [
        {
            "crane_id": "E1",
            "model_id": "generic_flat_top_55m",
            "base": [-30.0, -20.0, 0.0],
            "mast_height_m": 50.0,
            "theta_init_deg": 0.0,
            "slew": {"mode": "continuous"},
        },
        {
            "crane_id": "E2",
            "model_id": "generic_flat_top_55m",
            "base": [20.0, -20.0, 0.0],
            "mast_height_m": 52.0,
            "theta_init_deg": 90.0,
            "slew": {"mode": "continuous"},
        },
        {
            "crane_id": "E3",
            "model_id": "generic_flat_top_55m",
            "base": [-5.0, 25.0, 0.0],
            "mast_height_m": 54.0,
            "theta_init_deg": 180.0,
            "slew": {"mode": "continuous"},
        },
    ]
    raw["weather"] = {
        "mode": "schedule",
        "wind": {
            "base_speed_m_s": 6.0,
            "gust_speed_m_s": 9.0,
            "direction_deg": 90.0,
        },
        "visibility": {"base_level": "medium"},
        "schedule": {
            "segments": [
                {
                    "segment_id": "medium-moderate",
                    "start_s": 0.0,
                    "end_s": 30.0,
                    "wind_speed_m_s": 6.0,
                    "wind_gust_m_s": 9.0,
                    "wind_direction_deg": 90.0,
                    "visibility_level": "medium",
                    "rain_level": "none",
                    "fog_level": "none",
                    "transition_s": 0.0,
                },
                {
                    "segment_id": "poor-gusty",
                    "start_s": 30.0,
                    "end_s": None,
                    "wind_speed_m_s": 10.0,
                    "wind_gust_m_s": 14.0,
                    "wind_direction_deg": 120.0,
                    "visibility_level": "poor",
                    "rain_level": "light",
                    "fog_level": "dense",
                    "transition_s": 0.0,
                },
            ]
        },
    }
    return raw


def test_module_e_two_segment_demo_contract() -> None:
    resolved = resolve_config(_module_e_demo_raw(), load_fixture("experiment_valid.yaml"))
    generator = WeatherGenerator.from_resolved_config(resolved)

    state_0 = generator.update(0.0).weather_state
    state_29 = generator.update(29.0).weather_state
    state_30 = generator.update(30.0).weather_state

    assert state_0.visibility_level == "medium"
    assert state_29.source_segment_id == "medium-moderate"
    assert state_30.visibility_level == "poor"
    assert state_30.source_segment_id == "poor-gusty"
    assert state_30.wind_advisory_level == "gusty"
    assert build_wind_advisory(state_30).recommended_behavior_keys

    visibility = build_weather_visibility_context(
        state_30,
        weather_seed=resolved.seeds.weather,
        decision_time_bucket=30,
    )
    assert visibility.visibility_confidence == 0.4
    assert visibility.neighbor_visibility_radius_m == 45.0

    snapshot = WeatherWorldSnapshot(
        time_s=30.0,
        crane_states=[],
        tasks=[],
        weather=state_30,
        recent_events=[],
    )
    row = build_weather_record_row(
        state_30,
        episode_id="ep-module-e",
        scenario_id=resolved.scenario["scenario_id"],
        frame_index=600,
    )
    summary = build_weather_frame_summary(state_30)

    assert snapshot.weather.wind_for_safety_m_s == 14.0
    assert row["frame"] == 600
    assert row["visibility_level"] == "poor"
    assert row["wind_advisory_level"] == "gusty"
    assert summary == {
        "wind_speed_m_s": 10.0,
        "wind_gust_m_s": 14.0,
        "wind_direction_deg": 120.0,
        "visibility_level": "poor",
        "rain_level": "light",
        "fog_level": "dense",
        "wind_advisory_level": "gusty",
    }


def test_module_e_boundaries_remain_static() -> None:
    banned_imports = (
        "backend.app.llm",
        "backend.app.recorder",
        "backend.app.risk",
        "backend.app.sim.risk",
        "backend.app.schemas.control",
        "backend.app.sim.physics",
        "backend.app.schemas.state",
        "backend.app.sim.task_observation",
    )
    banned_names = {
        "ControlTarget",
        "ExecutedCommand",
        "CraneState",
        "near_miss",
        "collision",
        "offline_label",
        "episode_status",
        "TaskStage",
    }

    for relative_path in ["backend/app/sim/weather.py", "backend/app/schemas/weather.py"]:
        path = REPO_ROOT / relative_path
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imported = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.append(node.module)

        assert not [module for module in imported if module.startswith(banned_imports)]
        names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
        assert banned_names.isdisjoint(names)
