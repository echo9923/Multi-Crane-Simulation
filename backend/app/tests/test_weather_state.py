from __future__ import annotations

import json
import math

import pytest
from pydantic import ValidationError

from backend.app.schemas.state import CraneState
from backend.app.schemas.weather import (
    DEFAULT_VISIBILITY_PROFILES,
    FogLevel,
    RainLevel,
    VisibilityLevel,
    WeatherDiagnostic,
    WeatherEventPayload,
    WeatherGenerationReport,
    WeatherState,
    WindAdvisoryLevel,
)


def _weather_state(**overrides) -> WeatherState:
    payload = {
        "time_s": 12.5,
        "mode": "schedule",
        "wind_speed_m_s": 8.0,
        "wind_gust_m_s": 12.0,
        "wind_direction_deg": 450.0,
        "visibility_level": "medium",
        "rain_level": "none",
        "fog_level": "none",
        "source_segment_id": "seg-001",
        "generation_seed": 303,
        "generation_step": 12,
    }
    payload.update(overrides)
    return WeatherState.model_validate(payload)


def test_weather_state_serializes_and_derives_runtime_fields() -> None:
    state = _weather_state()

    payload = state.model_dump(mode="json")
    json.dumps(payload, ensure_ascii=False)

    assert payload["schema_version"] == "1.0"
    assert payload["wind_direction_deg"] == 90.0
    assert payload["wind_for_safety_m_s"] == 12.0
    assert payload["wind_advisory_level"] == "gusty"
    assert payload["neighbor_visibility_radius_m"] == 80.0
    assert payload["distance_noise_m"] == 2.0
    assert payload["hide_hook_prob"] == 0.2
    assert payload["visibility_confidence"] == 0.7


def test_weather_state_rejects_invalid_weather_numbers() -> None:
    invalid_payloads = [
        {"wind_speed_m_s": -0.1},
        {"wind_speed_m_s": math.inf},
        {"wind_gust_m_s": 7.9},
        {"wind_direction_deg": math.nan},
        {"hide_hook_prob": 1.1},
        {"visibility_confidence": -0.1},
    ]

    for overrides in invalid_payloads:
        with pytest.raises(ValidationError):
            _weather_state(**overrides)


def test_weather_contract_enums_use_canonical_values() -> None:
    assert {level.value for level in VisibilityLevel.canonical_values()} == {
        "good",
        "medium",
        "poor",
    }
    assert RainLevel.NONE.value == "none"
    assert FogLevel.NONE.value == "none"
    assert WindAdvisoryLevel.STRONG_WIND.value == "strong_wind"


def test_visibility_profiles_have_expected_defaults() -> None:
    good = DEFAULT_VISIBILITY_PROFILES[VisibilityLevel.GOOD]
    medium = DEFAULT_VISIBILITY_PROFILES[VisibilityLevel.MEDIUM]
    poor = DEFAULT_VISIBILITY_PROFILES[VisibilityLevel.POOR]

    assert good.neighbor_visibility_radius_m == 120.0
    assert good.distance_noise_m == 0.5
    assert good.hide_hook_prob == 0.0
    assert medium.neighbor_visibility_radius_m == 80.0
    assert medium.visibility_confidence == 0.7
    assert poor.neighbor_visibility_radius_m == 45.0
    assert poor.distance_precision_m == 5.0


def test_weather_diagnostic_report_and_event_payload_are_json_serializable() -> None:
    diagnostic = WeatherDiagnostic(
        code="WEATHER_W_201",
        severity="warning",
        time_s=12.5,
        message="gust advisory",
        details={"wind_for_safety_m_s": 12.0},
    )
    state = _weather_state(diagnostics=[diagnostic])
    report = WeatherGenerationReport(
        mode="schedule",
        seed=303,
        update_interval_s=1.0,
        timeline_segment_count=1,
        first_state=state,
        config_defaults_applied=["weather.update_interval_s"],
        warnings=[diagnostic],
    )
    event = WeatherEventPayload(
        event_type="gust_warning",
        time_s=12.5,
        frame_index=12,
        weather_code="WEATHER_W_201",
        severity="warning",
        weather_state=state,
        reason="gust_advisory",
        details={"source": "weather"},
    )

    json.dumps(report.model_dump(mode="json"), ensure_ascii=False)
    payload = event.model_dump(mode="json")
    assert payload["weather_state"]["wind_advisory_level"] == "gusty"
    assert payload["weather_code"] == "WEATHER_W_201"


def test_module_e_does_not_write_crane_wind_swing_fields() -> None:
    state = CraneState(
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

    _weather_state()

    assert state.wind_effect_on_swing is None
    assert state.swing_angle_rad == 0.0
    assert state.swing_velocity_rad_s == 0.0
