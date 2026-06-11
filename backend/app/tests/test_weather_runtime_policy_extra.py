from __future__ import annotations

from copy import deepcopy
import math

from pydantic import ValidationError
import pytest

from backend.app.core.config_resolver import resolve_config
from backend.app.schemas.weather import WeatherState, advisory_level_for_wind
from backend.app.sim.weather import WeatherGenerator
from backend.app.tests.test_config_schema import load_fixture


def _resolved(raw: dict):
    return resolve_config(raw, load_fixture("experiment_valid.yaml"))


def _schedule_raw_with_policy(policy: str) -> dict:
    raw = load_fixture("scenario_valid.yaml")
    raw["weather"]["mode"] = "schedule"
    raw["weather"]["runtime_failure_policy"] = policy
    raw["weather"]["schedule"] = {
        "segments": [
            {
                "segment_id": "valid",
                "start_s": 0.0,
                "end_s": 5.0,
                "wind_speed_m_s": 4.0,
                "wind_gust_m_s": 6.0,
                "wind_direction_deg": 0.0,
                "visibility_level": "good",
                "rain_level": "none",
                "fog_level": "none",
                "transition_s": 0.0,
            },
            {
                "segment_id": "will-be-mutated-invalid",
                "start_s": 5.0,
                "end_s": None,
                "wind_speed_m_s": 5.0,
                "wind_gust_m_s": 7.0,
                "wind_direction_deg": 0.0,
                "visibility_level": "medium",
                "rain_level": "none",
                "fog_level": "none",
                "transition_s": 0.0,
            },
        ]
    }
    return raw


@pytest.mark.parametrize(
    ("wind_for_safety_m_s", "expected"),
    [
        (0.0, "normal"),
        (7.999, "normal"),
        (8.0, "caution"),
        (11.999, "caution"),
        (12.0, "gusty"),
        (15.999, "gusty"),
        (16.0, "strong_wind"),
        (40.0, "strong_wind"),
    ],
)
def test_wind_advisory_threshold_edges(
    wind_for_safety_m_s: float,
    expected: str,
) -> None:
    assert advisory_level_for_wind(wind_for_safety_m_s) == expected


@pytest.mark.parametrize("bad_value", [-0.01, math.inf, math.nan])
def test_wind_advisory_rejects_invalid_safety_wind(bad_value: float) -> None:
    with pytest.raises(ValueError):
        advisory_level_for_wind(bad_value)


def test_weather_state_rejects_inconsistent_explicit_derived_fields() -> None:
    with pytest.raises(ValidationError):
        WeatherState(
            time_s=0.0,
            mode="constant",
            wind_speed_m_s=4.0,
            wind_gust_m_s=6.0,
            wind_direction_deg=0.0,
            wind_for_safety_m_s=4.0,
            visibility_level="good",
            generation_seed=1,
            generation_step=0,
        )

    with pytest.raises(ValidationError):
        WeatherState(
            time_s=0.0,
            mode="constant",
            wind_speed_m_s=4.0,
            wind_gust_m_s=6.0,
            wind_direction_deg=0.0,
            wind_advisory_level="strong_wind",
            visibility_level="good",
            generation_seed=1,
            generation_step=0,
        )


def test_warn_and_use_safe_default_policy_returns_safe_state_without_prior_good() -> None:
    raw = _schedule_raw_with_policy("warn_and_use_safe_default")
    generator = WeatherGenerator.from_resolved_config(_resolved(raw))
    generator.timeline.segments[0]["wind_gust_m_s"] = 3.0

    result = generator.update(0.0)

    assert result.failure_request is None
    assert result.warnings[0].code == "WEATHER_E_101"
    assert result.weather_state.source_segment_id == "safe-default"
    assert result.weather_state.wind_speed_m_s == 0.0
    assert result.weather_state.wind_gust_m_s == 0.0
    assert result.weather_state.visibility_level == "good"


def test_fail_episode_policy_returns_failure_for_runtime_gap() -> None:
    raw = _schedule_raw_with_policy("fail_episode")
    generator = WeatherGenerator.from_resolved_config(_resolved(raw))
    generator.timeline.segments = [
        dict(generator.timeline.segments[0], end_s=2.0),
        dict(generator.timeline.segments[1], start_s=5.0),
    ]

    result = generator.update(3.0)

    assert result.weather_state is None
    assert result.failure_request["source_module"] == "E"
    assert result.failure_request["error_code"] == "WEATHER_E_101"
    assert result.failure_request["time_s"] == 3.0


def test_hold_last_good_policy_does_not_mutate_previous_state_diagnostics() -> None:
    raw = _schedule_raw_with_policy("warn_and_hold_last")
    generator = WeatherGenerator.from_resolved_config(_resolved(raw))
    good = generator.update(0.0).weather_state
    original_payload = good.model_dump(mode="json")
    generator.timeline.segments[1]["wind_gust_m_s"] = 3.0

    held = generator.update(5.0).weather_state

    assert good.model_dump(mode="json") == original_payload
    assert held.model_dump(mode="json") != original_payload
    assert held.diagnostics[-1].code == "WEATHER_E_101"


def test_weather_generator_uses_resolved_config_copy_for_schedule_segments() -> None:
    raw = _schedule_raw_with_policy("fail_episode")
    resolved = _resolved(raw)
    generator = WeatherGenerator.from_resolved_config(resolved)
    resolved.scenario["weather"]["schedule"]["segments"][0]["wind_speed_m_s"] = 99.0

    state = generator.update(0.0).weather_state

    assert state.wind_speed_m_s == 4.0


def test_same_resolved_config_builds_independent_generator_timelines() -> None:
    raw = _schedule_raw_with_policy("fail_episode")
    resolved = _resolved(raw)
    first = WeatherGenerator.from_resolved_config(resolved)
    second = WeatherGenerator.from_resolved_config(resolved)
    first.timeline.segments[0]["wind_speed_m_s"] = 99.0

    assert second.update(0.0).weather_state.wind_speed_m_s == 4.0


def test_random_safe_default_policy_still_keeps_seed_for_traceability() -> None:
    raw = load_fixture("scenario_valid.yaml")
    raw["weather"]["mode"] = "random"
    raw["weather"]["runtime_failure_policy"] = "warn_and_use_safe_default"
    generator = WeatherGenerator.from_resolved_config(_resolved(raw))
    seed = generator.seed
    generator.timeline.segments[0]["wind_gust_m_s"] = -1.0

    result = generator.update(0.0)

    assert result.weather_state.source_segment_id == "safe-default"
    assert result.weather_state.generation_seed == seed


def test_resolved_weather_is_not_affected_by_mutating_source_raw_after_resolve() -> None:
    raw = _schedule_raw_with_policy("fail_episode")
    resolved = _resolved(raw)
    mutated = deepcopy(raw)
    mutated["weather"]["wind"]["base_speed_m_s"] = 99.0

    generator = WeatherGenerator.from_resolved_config(resolved)

    assert generator.update(0.0).weather_state.wind_speed_m_s == 4.0
