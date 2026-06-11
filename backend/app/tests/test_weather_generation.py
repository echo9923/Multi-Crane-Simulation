from __future__ import annotations

from copy import deepcopy
import random

import pytest

from backend.app.core.config_resolver import resolve_config
from backend.app.sim.weather import WeatherGenerator
from backend.app.tests.test_config_schema import load_fixture


def _resolved(scenario_raw: dict | None = None):
    return resolve_config(
        scenario_raw or load_fixture("scenario_valid.yaml"),
        load_fixture("experiment_valid.yaml"),
    )


def _generator(scenario_raw: dict | None = None) -> WeatherGenerator:
    return WeatherGenerator.from_resolved_config(_resolved(scenario_raw))


def test_constant_mode_is_idempotent_and_keeps_weather_values_constant() -> None:
    raw = load_fixture("scenario_valid.yaml")
    raw["weather"]["mode"] = "constant"
    raw["weather"]["wind"]["base_speed_m_s"] = 5.0
    raw["weather"]["wind"]["gust_speed_m_s"] = 9.0
    raw["weather"]["wind"]["direction_deg"] = 360.0
    raw["weather"]["visibility"]["base_level"] = "good"
    generator = _generator(raw)

    first = generator.update(0.0).weather_state
    second = generator.update(10.0).weather_state
    repeated = generator.update(10.0).weather_state

    assert first.wind_speed_m_s == second.wind_speed_m_s == 5.0
    assert first.wind_gust_m_s == second.wind_gust_m_s == 9.0
    assert first.wind_direction_deg == second.wind_direction_deg == 0.0
    assert first.visibility_level == second.visibility_level == "good"
    assert first.source_segment_id == "constant"
    assert second.generation_step == 200
    assert second.model_dump(mode="json") == repeated.model_dump(mode="json")


def test_schedule_mode_selects_segment_boundaries() -> None:
    raw = load_fixture("scenario_valid.yaml")
    raw["weather"]["mode"] = "schedule"
    raw["weather"]["schedule"] = {
        "segments": [
            {
                "segment_id": "calm",
                "start_s": 0.0,
                "end_s": 30.0,
                "wind_speed_m_s": 4.0,
                "wind_gust_m_s": 7.0,
                "wind_direction_deg": 10.0,
                "visibility_level": "medium",
                "rain_level": "none",
                "fog_level": "none",
                "transition_s": 0.0,
            },
            {
                "segment_id": "gusty",
                "start_s": 30.0,
                "end_s": None,
                "wind_speed_m_s": 11.0,
                "wind_gust_m_s": 16.0,
                "wind_direction_deg": 350.0,
                "visibility_level": "poor",
                "rain_level": "light",
                "fog_level": "dense",
                "transition_s": 0.0,
            },
        ]
    }
    generator = _generator(raw)

    before = generator.update(29.999).weather_state
    at_boundary = generator.update(30.0).weather_state

    assert before.source_segment_id == "calm"
    assert before.visibility_level == "medium"
    assert at_boundary.source_segment_id == "gusty"
    assert at_boundary.visibility_level == "poor"
    assert at_boundary.wind_advisory_level == "strong_wind"
    assert at_boundary.rain_level == "light"
    assert at_boundary.fog_level == "dense"


def test_random_mode_is_seeded_reproducible_and_bounds_checked() -> None:
    raw = load_fixture("scenario_valid.yaml")
    raw["weather"]["mode"] = "random"
    raw["weather"]["random"] = {
        "change_interval_s": [5.0, 5.0],
        "wind_speed_range_m_s": [1.0, 3.0],
        "gust_extra_range_m_s": [2.0, 4.0],
        "direction_change_range_deg": [-10.0, 10.0],
        "visibility_distribution": {"good": 0.5, "medium": 0.5, "poor": 0.0},
    }
    first = _generator(raw)
    second = _generator(deepcopy(raw))
    changed_seed_raw = deepcopy(raw)
    changed_seed_raw["seed"] = raw["seed"] + 1
    different = _generator(changed_seed_raw)

    first_states = [first.update(time_s).weather_state for time_s in [0.0, 5.0, 10.0]]
    second_states = [second.update(time_s).weather_state for time_s in [0.0, 5.0, 10.0]]
    different_states = [
        different.update(time_s).weather_state for time_s in [0.0, 5.0, 10.0]
    ]

    assert [state.model_dump(mode="json") for state in first_states] == [
        state.model_dump(mode="json") for state in second_states
    ]
    assert [state.model_dump(mode="json") for state in first_states] != [
        state.model_dump(mode="json") for state in different_states
    ]
    for state in first_states:
        assert 1.0 <= state.wind_speed_m_s <= 3.0
        assert state.wind_speed_m_s + 2.0 <= state.wind_gust_m_s <= state.wind_speed_m_s + 4.0
        assert state.source_segment_id.startswith("random-")
        assert state.visibility_level in {"good", "medium"}


def test_random_mode_does_not_pollute_global_random_state() -> None:
    raw = load_fixture("scenario_valid.yaml")
    raw["weather"]["mode"] = "random"
    random.seed(12345)
    expected_first = random.random()
    random.seed(12345)

    generator = _generator(raw)
    generator.update(0.0)
    after_weather = random.random()

    assert after_weather == expected_first


def test_negative_time_returns_failure_request() -> None:
    result = _generator().update(-0.1)

    assert result.weather_state is None
    assert result.failure_request["error_code"] == "WEATHER_E_101"
    assert result.failure_request["default_episode_status"] == "failed_invalid_state"


def test_runtime_invalid_weather_can_hold_last_good_state() -> None:
    raw = load_fixture("scenario_valid.yaml")
    raw["weather"]["runtime_failure_policy"] = "warn_and_hold_last"
    raw["weather"]["schedule"] = {
        "segments": [
            {
                "segment_id": "good",
                "start_s": 0.0,
                "end_s": 10.0,
                "wind_speed_m_s": 4.0,
                "wind_gust_m_s": 4.0,
                "wind_direction_deg": 0.0,
                "visibility_level": "good",
                "rain_level": "none",
                "fog_level": "none",
                "transition_s": 0.0,
            },
            {
                "segment_id": "bad",
                "start_s": 10.0,
                "end_s": None,
                "wind_speed_m_s": 6.0,
                "wind_gust_m_s": 8.0,
                "wind_direction_deg": 0.0,
                "visibility_level": "good",
                "rain_level": "none",
                "fog_level": "none",
                "transition_s": 0.0,
            },
        ]
    }
    generator = _generator(raw)
    good = generator.update(0.0).weather_state
    generator.timeline.segments[1]["wind_gust_m_s"] = 5.0

    result = generator.update(10.0)

    assert result.weather_state.source_segment_id == good.source_segment_id
    assert result.failure_request is None
    assert result.warnings[0].code == "WEATHER_E_101"


def test_preview_timeline_report_exposes_generation_metadata() -> None:
    generator = _generator()

    report = generator.preview_timeline(duration_s=20.0)

    assert report.mode == "schedule"
    assert report.seed == _resolved().seeds.weather
    assert report.timeline_segment_count == 1
    assert report.first_state.time_s == 0.0
