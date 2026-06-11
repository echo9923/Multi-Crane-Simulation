from __future__ import annotations

from copy import deepcopy

import pytest
from pydantic import ValidationError

from backend.app.core.config_resolver import resolve_config
from backend.app.schemas.config import ScenarioConfig
from backend.app.tests.test_config_schema import load_fixture


def _resolved_from_scenario(scenario_raw: dict):
    return resolve_config(scenario_raw, load_fixture("experiment_valid.yaml"))


def test_weather_config_accepts_canonical_and_legacy_visibility_inputs() -> None:
    for raw_level, canonical in [
        ("good", "good"),
        ("medium", "medium"),
        ("poor", "poor"),
        ("high", "good"),
        ("low", "poor"),
    ]:
        raw = load_fixture("scenario_valid.yaml")
        raw["weather"]["visibility"]["base_level"] = raw_level

        config = ScenarioConfig.model_validate(raw)
        resolved = _resolved_from_scenario(raw)

        assert config.weather.visibility.base_level == canonical
        assert resolved.scenario["weather"]["visibility"]["base_level"] == canonical


def test_weather_resolve_materializes_defaults_for_legacy_fixture_shape() -> None:
    resolved = _resolved_from_scenario(load_fixture("scenario_valid.yaml"))
    weather = resolved.scenario["weather"]

    assert weather["enabled"] is True
    assert weather["mode"] == "schedule"
    assert weather["update_interval_s"] == 0.05
    assert weather["runtime_failure_policy"] == "fail_episode"
    assert weather["visibility"]["base_level"] == "medium"
    assert weather["visibility"]["levels"]["good"]["neighbor_visibility_radius_m"] == 120.0
    assert weather["visibility"]["levels"]["medium"]["hide_hook_prob"] == 0.2
    assert weather["visibility"]["levels"]["poor"]["visibility_confidence"] == 0.4
    assert weather["precipitation"] == {"rain_level": "none", "fog_level": "none"}
    assert weather["schedule"]["segments"] == [
        {
            "segment_id": "schedule-default-0",
            "start_s": 0.0,
            "end_s": None,
            "wind_speed_m_s": 6.0,
            "wind_gust_m_s": 12.0,
            "wind_direction_deg": 90.0,
            "visibility_level": "medium",
            "rain_level": "none",
            "fog_level": "none",
            "transition_s": 0.0,
        }
    ]
    assert weather["random"]["wind_speed_range_m_s"] == [0.0, 12.0]
    assert weather["wind_advisory_thresholds_m_s"] == {
        "caution": 8.0,
        "gusty": 12.0,
        "strong_wind": 16.0,
    }


def test_weather_defaults_are_tracked_in_resolved_config() -> None:
    resolved = _resolved_from_scenario(load_fixture("scenario_valid.yaml"))

    paths = {item.field_path for item in resolved.defaults_applied}

    assert "scenario.weather.enabled" in paths
    assert "scenario.weather.update_interval_s" in paths
    assert "scenario.weather.visibility.levels" in paths
    assert "scenario.weather.precipitation" in paths
    assert "scenario.weather.schedule.segments" in paths
    assert "scenario.weather.wind_advisory_thresholds_m_s" in paths


def test_weather_changes_affect_resolved_config_hash() -> None:
    scenario_a = load_fixture("scenario_valid.yaml")
    scenario_b = deepcopy(scenario_a)
    scenario_c = deepcopy(scenario_a)

    scenario_b["weather"]["wind"]["base_speed_m_s"] = 7.0
    scenario_c["weather"]["visibility"]["base_level"] = "poor"

    baseline_hash = _resolved_from_scenario(scenario_a).resolved_config_hash

    assert _resolved_from_scenario(scenario_b).resolved_config_hash != baseline_hash
    assert _resolved_from_scenario(scenario_c).resolved_config_hash != baseline_hash


def test_schedule_segments_validate_start_order_and_gaps() -> None:
    raw = load_fixture("scenario_valid.yaml")
    raw["weather"]["schedule"] = {
        "segments": [
            {
                "segment_id": "late",
                "start_s": 5.0,
                "end_s": None,
                "wind_speed_m_s": 4.0,
                "wind_gust_m_s": 8.0,
                "wind_direction_deg": 90.0,
                "visibility_level": "medium",
                "rain_level": "none",
                "fog_level": "none",
                "transition_s": 0.0,
            }
        ]
    }

    with pytest.raises(ValidationError) as exc_info:
        ScenarioConfig.model_validate(raw)

    assert "WEATHER_E_002" in str(exc_info.value)


def test_random_weather_distribution_must_sum_to_one() -> None:
    raw = load_fixture("scenario_valid.yaml")
    raw["weather"]["mode"] = "random"
    raw["weather"]["random"] = {
        "visibility_distribution": {"good": 0.5, "medium": 0.5, "poor": 0.5}
    }

    with pytest.raises(ValidationError) as exc_info:
        ScenarioConfig.model_validate(raw)

    assert "WEATHER_E_003" in str(exc_info.value)
