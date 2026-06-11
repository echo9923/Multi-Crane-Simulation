from __future__ import annotations

import json

from backend.app.core.config_resolver import resolve_config
from backend.app.schemas.weather import WeatherWorldSnapshot
from backend.app.sim.weather import (
    WeatherGenerator,
    build_visibility_sampling_key,
    build_weather_frame_summary,
    build_weather_record_row,
    build_weather_visibility_context,
    compare_weather_replay_row,
)
from backend.app.tests.test_config_schema import load_fixture


def _state(level: str = "medium"):
    raw = load_fixture("scenario_valid.yaml")
    raw["weather"]["mode"] = "constant"
    raw["weather"]["visibility"]["base_level"] = level
    resolved = resolve_config(raw, load_fixture("experiment_valid.yaml"))
    generator = WeatherGenerator.from_resolved_config(resolved)
    return resolved, generator.update(3.25).weather_state


def test_record_row_is_json_serializable_and_keeps_record_identity_separate() -> None:
    _, state = _state()

    row_a = build_weather_record_row(
        state,
        episode_id="ep-a",
        scenario_id="site-a",
        frame_index=65,
    )
    row_b = build_weather_record_row(
        state,
        episode_id="ep-b",
        scenario_id="site-b",
        frame_index=65,
    )

    json.dumps(row_a, ensure_ascii=False)
    assert row_a["episode_id"] == "ep-a"
    assert row_b["episode_id"] == "ep-b"
    assert row_a["generation_seed"] == row_b["generation_seed"]
    assert row_a["wind_gust_m_s"] == row_b["wind_gust_m_s"]


def test_frame_summary_omits_replay_and_profile_internals() -> None:
    _, state = _state("poor")

    summary = build_weather_frame_summary(state)

    assert set(summary) == {
        "wind_speed_m_s",
        "wind_gust_m_s",
        "wind_direction_deg",
        "visibility_level",
        "rain_level",
        "fog_level",
        "wind_advisory_level",
    }
    assert "visibility_confidence" not in summary
    assert "generation_seed" not in summary
    assert "source_segment_id" not in summary


def test_replay_comparison_ignores_non_core_identity_fields() -> None:
    _, state = _state()
    row = build_weather_record_row(
        state,
        episode_id="historical-episode",
        scenario_id="historical-scenario",
        frame_index=state.generation_step,
    )
    row["episode_id"] = "different-episode"
    row["scenario_id"] = "different-scenario"
    row["generation_seed"] = -1
    row["source_segment_id"] = "different-segment"

    assert compare_weather_replay_row(state, row) is None


def test_replay_comparison_detects_frame_time_and_rain_mismatches() -> None:
    _, state = _state()
    row = build_weather_record_row(
        state,
        episode_id="ep",
        scenario_id="site",
        frame_index=state.generation_step,
    )

    wrong_frame = dict(row, frame=row["frame"] + 1)
    wrong_time = dict(row, time_s=row["time_s"] + 0.01)
    wrong_rain = dict(row, rain_level="heavy")

    assert compare_weather_replay_row(state, wrong_frame)["field"] == "frame"
    assert compare_weather_replay_row(state, wrong_time)["field"] == "time_s"
    assert compare_weather_replay_row(state, wrong_rain)["field"] == "rain_level"


def test_visibility_noise_seed_changes_with_bucket_and_level_but_not_time_fraction() -> None:
    resolved, medium = _state("medium")
    _, poor = _state("poor")

    medium_bucket_3 = build_weather_visibility_context(
        medium,
        weather_seed=resolved.seeds.weather,
        decision_time_bucket=3,
    )
    medium_bucket_3_again = build_weather_visibility_context(
        medium.model_copy(update={"time_s": 3.99}),
        weather_seed=resolved.seeds.weather,
        decision_time_bucket=3,
    )
    medium_bucket_4 = build_weather_visibility_context(
        medium,
        weather_seed=resolved.seeds.weather,
        decision_time_bucket=4,
    )
    poor_bucket_3 = build_weather_visibility_context(
        poor,
        weather_seed=resolved.seeds.weather,
        decision_time_bucket=3,
    )

    assert medium_bucket_3.noise_seed == medium_bucket_3_again.noise_seed
    assert medium_bucket_3.noise_seed != medium_bucket_4.noise_seed
    assert medium_bucket_3.noise_seed != poor_bucket_3.noise_seed


def test_visibility_sampling_key_distinguishes_direction_and_purpose() -> None:
    hook_forward = build_visibility_sampling_key(
        noise_seed=123,
        observer_crane_id="A",
        target_crane_id="B",
        decision_time_bucket=1,
        purpose="hook_visibility",
    )
    hook_reverse = build_visibility_sampling_key(
        noise_seed=123,
        observer_crane_id="B",
        target_crane_id="A",
        decision_time_bucket=1,
        purpose="hook_visibility",
    )
    distance_forward = build_visibility_sampling_key(
        noise_seed=123,
        observer_crane_id="A",
        target_crane_id="B",
        decision_time_bucket=1,
        purpose="distance_noise",
    )

    assert hook_forward != hook_reverse
    assert hook_forward != distance_forward


def test_world_snapshot_serialization_freezes_weather_payload() -> None:
    _, state = _state("medium")
    snapshot = WeatherWorldSnapshot(
        time_s=state.time_s,
        crane_states=[],
        tasks=[],
        weather=state,
        recent_events=[],
    )
    mutated = state.model_copy(update={"source_segment_id": "mutated-after-snapshot"})

    payload = snapshot.model_dump(mode="json")

    assert payload["weather"]["source_segment_id"] == "constant"
    assert mutated.source_segment_id == "mutated-after-snapshot"
