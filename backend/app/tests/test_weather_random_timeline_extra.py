from __future__ import annotations

from copy import deepcopy

from backend.app.core.config_resolver import resolve_config
from backend.app.sim.weather import WeatherGenerator
from backend.app.tests.test_config_schema import load_fixture


def _random_raw() -> dict:
    raw = load_fixture("scenario_valid.yaml")
    raw["weather"]["mode"] = "random"
    raw["weather"]["random"] = {
        "change_interval_s": [2.5, 2.5],
        "wind_speed_range_m_s": [1.0, 1.0],
        "gust_extra_range_m_s": [0.5, 0.5],
        "direction_change_range_deg": [0.0, 0.0],
        "visibility_distribution": {"good": 0.0, "medium": 1.0, "poor": 0.0},
        "rain_distribution": {
            "none": 0.0,
            "light": 1.0,
            "moderate": 0.0,
            "heavy": 0.0,
        },
        "fog_distribution": {
            "none": 0.0,
            "light": 0.0,
            "medium": 0.0,
            "dense": 1.0,
        },
    }
    return raw


def _generator(raw: dict | None = None) -> WeatherGenerator:
    return WeatherGenerator.from_resolved_config(
        resolve_config(raw or _random_raw(), load_fixture("experiment_valid.yaml"))
    )


def test_random_fixed_bounds_make_segment_values_exact_and_traceable() -> None:
    generator = _generator()

    for time_s in [0.0, 2.499, 2.5, 5.0, 599.999]:
        state = generator.update(time_s).weather_state
        assert state.wind_speed_m_s == 1.0
        assert state.wind_gust_m_s == 1.5
        assert state.wind_direction_deg == 90.0
        assert state.visibility_level == "medium"
        assert state.rain_level == "light"
        assert state.fog_level == "dense"


def test_random_timeline_last_segment_is_open_ended_for_duration_tail() -> None:
    generator = _generator()

    assert generator.timeline.segments[-1]["end_s"] is None
    assert generator.update(10_000.0).weather_state.source_segment_id == (
        generator.timeline.segments[-1]["segment_id"]
    )


def test_random_generation_step_uses_resolved_update_interval_floor() -> None:
    generator = _generator()

    assert generator.update(0.049).weather_state.generation_step == 0
    assert generator.update(0.05).weather_state.generation_step == 1
    assert generator.update(0.099).weather_state.generation_step == 1
    assert generator.update(0.10).weather_state.generation_step == 2


def test_random_timeline_report_segment_count_matches_generated_segments() -> None:
    generator = _generator()

    report = generator.preview_timeline(duration_s=600.0)

    assert report.timeline_segment_count == len(generator.timeline.segments)
    assert report.mode == "random"
    assert report.first_state.source_segment_id == "random-0000"


def test_random_visibility_distribution_zero_weight_levels_are_never_selected() -> None:
    generator = _generator()
    levels = {
        generator.update(time_s).weather_state.visibility_level
        for time_s in [0.0, 2.5, 5.0, 7.5, 10.0, 12.5]
    }

    assert levels == {"medium"}


def test_random_different_direction_delta_changes_reproducible_timeline() -> None:
    baseline_raw = _random_raw()
    changed_raw = deepcopy(baseline_raw)
    changed_raw["weather"]["random"]["direction_change_range_deg"] = [10.0, 10.0]

    baseline = _generator(baseline_raw)
    changed = _generator(changed_raw)

    assert baseline.update(0.0).weather_state.wind_direction_deg == 90.0
    assert changed.update(0.0).weather_state.wind_direction_deg == 100.0
    assert changed.update(2.5).weather_state.wind_direction_deg == 110.0


def test_random_timeline_generation_does_not_depend_on_update_call_order() -> None:
    raw = _random_raw()
    first = _generator(raw)
    second = _generator(deepcopy(raw))
    ordered = [first.update(time_s).weather_state.model_dump(mode="json") for time_s in [0, 5, 10]]
    reversed_order = [
        second.update(time_s).weather_state.model_dump(mode="json")
        for time_s in [10, 5, 0]
    ]

    assert ordered == list(reversed(reversed_order))


def test_random_weighted_choice_uses_last_key_for_roundoff_tail() -> None:
    raw = _random_raw()
    raw["weather"]["random"]["visibility_distribution"] = {
        "good": 0.0,
        "medium": 0.0,
        "poor": 1.0,
    }
    generator = _generator(raw)

    assert generator.update(0.0).weather_state.visibility_level == "poor"
