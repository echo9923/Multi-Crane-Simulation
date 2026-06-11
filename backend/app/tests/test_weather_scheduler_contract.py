from __future__ import annotations

import json

from backend.app.core.config_resolver import resolve_config
from backend.app.schemas.state import CraneState
from backend.app.schemas.weather import WeatherWorldSnapshot
from backend.app.sim.weather import (
    WeatherGenerator,
    build_weather_frame_summary,
    build_weather_record_row,
    compare_weather_replay_row,
)
from backend.app.tests.test_config_schema import load_fixture


def _weather_state():
    raw = load_fixture("scenario_valid.yaml")
    raw["weather"]["mode"] = "constant"
    raw["weather"]["wind"]["base_speed_m_s"] = 8.0
    raw["weather"]["wind"]["gust_speed_m_s"] = 12.0
    raw["weather"]["wind"]["direction_deg"] = 90.0
    resolved = resolve_config(raw, load_fixture("experiment_valid.yaml"))
    return WeatherGenerator.from_resolved_config(resolved).update(0.0).weather_state


def _crane_state() -> CraneState:
    return CraneState(
        crane_id="C1",
        theta_rad=0.0,
        theta_sin=0.0,
        theta_cos=1.0,
        trolley_r_m=10.0,
        hook_h_m=20.0,
        root_position=[0.0, 0.0, 50.0],
        tip_position=[50.0, 0.0, 50.0],
        hook_position=[10.0, 0.0, 20.0],
        cable_length_m=30.0,
    )


def test_world_snapshot_can_include_weather_state() -> None:
    state = _weather_state()
    crane = _crane_state()
    snapshot = WeatherWorldSnapshot(
        time_s=0.0,
        crane_states=[crane.model_dump(mode="json")],
        tasks=[],
        weather=state,
        recent_events=[],
    )
    crane = crane.model_copy(update={"task_stage": "modified_after_snapshot"})

    payload = snapshot.model_dump(mode="json")
    json.dumps(payload, ensure_ascii=False)
    assert payload["weather"]["wind_gust_m_s"] == 12.0
    assert payload["crane_states"][0]["task_stage"] == "idle"
    assert crane.task_stage == "modified_after_snapshot"


def test_weather_record_row_maps_parquet_minimum_fields() -> None:
    state = _weather_state()

    row = build_weather_record_row(
        state,
        episode_id="ep-001",
        scenario_id="site_001",
        frame_index=0,
    )

    assert row == {
        "schema_version": "1.0",
        "episode_id": "ep-001",
        "scenario_id": "site_001",
        "frame": 0,
        "time_s": 0.0,
        "wind_speed_m_s": 8.0,
        "wind_gust_m_s": 12.0,
        "wind_direction_deg": 90.0,
        "visibility_level": "medium",
        "rain_level": "none",
        "fog_level": "none",
        "wind_for_safety_m_s": 12.0,
        "wind_advisory_level": "gusty",
        "neighbor_visibility_radius_m": 80.0,
        "distance_noise_m": 2.0,
        "hide_hook_prob": 0.2,
        "visibility_confidence": 0.7,
        "source_segment_id": "constant",
        "generation_seed": state.generation_seed,
        "generation_step": 0,
    }


def test_weather_frame_summary_contains_display_fields_only() -> None:
    summary = build_weather_frame_summary(_weather_state())

    assert summary == {
        "wind_speed_m_s": 8.0,
        "wind_gust_m_s": 12.0,
        "wind_direction_deg": 90.0,
        "visibility_level": "medium",
        "rain_level": "none",
        "fog_level": "none",
        "wind_advisory_level": "gusty",
    }
    assert "generation_seed" not in summary
    assert "source_segment_id" not in summary


def test_replay_weather_row_comparison_uses_float_tolerance_and_exact_enums() -> None:
    state = _weather_state()
    matching = build_weather_record_row(
        state,
        episode_id="ep-001",
        scenario_id="site_001",
        frame_index=0,
    )
    matching["wind_speed_m_s"] += 1e-10

    mismatch = dict(matching)
    mismatch["visibility_level"] = "poor"

    assert compare_weather_replay_row(state, matching, abs_tol=1e-9) is None
    replay_error = compare_weather_replay_row(state, mismatch, abs_tol=1e-9)
    assert replay_error["error_code"] == "WEATHER_E_REPLAY_MISMATCH"
    assert replay_error["field"] == "visibility_level"
