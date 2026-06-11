from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from backend.app.schemas.enums import StrEnum, WeatherMode

WEATHER_SCHEMA_VERSION = "1.0"


class WeatherBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class VisibilityLevel(StrEnum):
    GOOD = "good"
    MEDIUM = "medium"
    POOR = "poor"

    @classmethod
    def canonical_values(cls) -> List["VisibilityLevel"]:
        return [cls.GOOD, cls.MEDIUM, cls.POOR]


class RainLevel(StrEnum):
    NONE = "none"
    LIGHT = "light"
    MODERATE = "moderate"
    HEAVY = "heavy"


class FogLevel(StrEnum):
    NONE = "none"
    LIGHT = "light"
    MEDIUM = "medium"
    DENSE = "dense"


class WindAdvisoryLevel(StrEnum):
    NORMAL = "normal"
    CAUTION = "caution"
    GUSTY = "gusty"
    STRONG_WIND = "strong_wind"


class WeatherDiagnostic(WeatherBaseModel):
    schema_version: str = WEATHER_SCHEMA_VERSION
    code: str
    severity: str
    time_s: float
    message: str
    details: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("severity")
    @classmethod
    def validate_severity(cls, value: str) -> str:
        if value not in {"diagnostic", "warning", "error"}:
            raise ValueError("severity must be diagnostic, warning, or error")
        return value


class VisibilityProfile(WeatherBaseModel):
    schema_version: str = WEATHER_SCHEMA_VERSION
    level: VisibilityLevel
    neighbor_visibility_radius_m: float = Field(gt=0)
    distance_noise_m: float = Field(ge=0)
    hide_hook_prob: float = Field(ge=0, le=1)
    visibility_confidence: float = Field(ge=0, le=1)
    distance_precision_m: float = Field(gt=0)
    description_key: str


DEFAULT_VISIBILITY_PROFILES: Dict[VisibilityLevel, VisibilityProfile] = {
    VisibilityLevel.GOOD: VisibilityProfile(
        level=VisibilityLevel.GOOD,
        neighbor_visibility_radius_m=120.0,
        distance_noise_m=0.5,
        hide_hook_prob=0.0,
        visibility_confidence=1.0,
        distance_precision_m=0.5,
        description_key="visibility.good",
    ),
    VisibilityLevel.MEDIUM: VisibilityProfile(
        level=VisibilityLevel.MEDIUM,
        neighbor_visibility_radius_m=80.0,
        distance_noise_m=2.0,
        hide_hook_prob=0.2,
        visibility_confidence=0.7,
        distance_precision_m=2.0,
        description_key="visibility.medium",
    ),
    VisibilityLevel.POOR: VisibilityProfile(
        level=VisibilityLevel.POOR,
        neighbor_visibility_radius_m=45.0,
        distance_noise_m=5.0,
        hide_hook_prob=0.5,
        visibility_confidence=0.4,
        distance_precision_m=5.0,
        description_key="visibility.poor",
    ),
}


class WeatherState(WeatherBaseModel):
    schema_version: str = WEATHER_SCHEMA_VERSION
    time_s: float = Field(ge=0)
    mode: WeatherMode
    wind_speed_m_s: float = Field(ge=0)
    wind_gust_m_s: float = Field(ge=0)
    wind_direction_deg: float = Field(ge=0)
    wind_for_safety_m_s: Optional[float] = None
    wind_advisory_level: Optional[WindAdvisoryLevel] = None
    visibility_level: VisibilityLevel
    rain_level: RainLevel = RainLevel.NONE
    fog_level: FogLevel = FogLevel.NONE
    neighbor_visibility_radius_m: Optional[float] = None
    distance_noise_m: Optional[float] = None
    hide_hook_prob: Optional[float] = None
    visibility_confidence: Optional[float] = None
    source_segment_id: Optional[str] = None
    generation_seed: int
    generation_step: int = Field(ge=0)
    diagnostics: List[WeatherDiagnostic] = Field(default_factory=list)

    @field_validator(
        "time_s",
        "wind_speed_m_s",
        "wind_gust_m_s",
        "wind_direction_deg",
        "wind_for_safety_m_s",
        "neighbor_visibility_radius_m",
        "distance_noise_m",
        "hide_hook_prob",
        "visibility_confidence",
    )
    @classmethod
    def validate_finite_float(cls, value: Optional[float]) -> Optional[float]:
        if value is not None and not math.isfinite(value):
            raise ValueError("weather float fields must be finite")
        return value

    @model_validator(mode="after")
    def derive_and_validate_fields(self) -> "WeatherState":
        if self.wind_gust_m_s < self.wind_speed_m_s:
            raise ValueError("wind_gust_m_s must be >= wind_speed_m_s")

        self.wind_direction_deg = _normalize_direction_deg(self.wind_direction_deg)

        wind_for_safety = max(self.wind_speed_m_s, self.wind_gust_m_s)
        if self.wind_for_safety_m_s is None:
            self.wind_for_safety_m_s = wind_for_safety
        elif not math.isclose(self.wind_for_safety_m_s, wind_for_safety):
            raise ValueError(
                "wind_for_safety_m_s must equal max(wind_speed_m_s, wind_gust_m_s)"
            )

        advisory_level = advisory_level_for_wind(wind_for_safety)
        if self.wind_advisory_level is None:
            self.wind_advisory_level = advisory_level
        elif self.wind_advisory_level is not advisory_level:
            raise ValueError("wind_advisory_level does not match wind_for_safety_m_s")

        profile = DEFAULT_VISIBILITY_PROFILES[self.visibility_level]
        self.neighbor_visibility_radius_m = _fill_or_validate_float(
            self.neighbor_visibility_radius_m,
            profile.neighbor_visibility_radius_m,
            "neighbor_visibility_radius_m",
        )
        self.distance_noise_m = _fill_or_validate_float(
            self.distance_noise_m,
            profile.distance_noise_m,
            "distance_noise_m",
        )
        self.hide_hook_prob = _fill_or_validate_float(
            self.hide_hook_prob,
            profile.hide_hook_prob,
            "hide_hook_prob",
        )
        self.visibility_confidence = _fill_or_validate_float(
            self.visibility_confidence,
            profile.visibility_confidence,
            "visibility_confidence",
        )
        if self.neighbor_visibility_radius_m <= 0:
            raise ValueError("neighbor_visibility_radius_m must be positive")
        if self.distance_noise_m < 0:
            raise ValueError("distance_noise_m must be non-negative")
        if not 0 <= self.hide_hook_prob <= 1:
            raise ValueError("hide_hook_prob must be between 0 and 1")
        if not 0 <= self.visibility_confidence <= 1:
            raise ValueError("visibility_confidence must be between 0 and 1")
        return self


class WeatherGenerationReport(WeatherBaseModel):
    schema_version: str = WEATHER_SCHEMA_VERSION
    mode: str
    seed: int
    update_interval_s: float = Field(gt=0)
    timeline_segment_count: int = Field(ge=0)
    first_state: WeatherState
    config_defaults_applied: List[str] = Field(default_factory=list)
    warnings: List[WeatherDiagnostic] = Field(default_factory=list)


class WeatherEventPayload(WeatherBaseModel):
    schema_version: str = WEATHER_SCHEMA_VERSION
    event_type: str
    time_s: float = Field(ge=0)
    frame_index: Optional[int] = Field(default=None, ge=0)
    weather_code: str
    severity: str
    weather_state: WeatherState
    reason: str
    details: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("severity")
    @classmethod
    def validate_severity(cls, value: str) -> str:
        if value not in {"diagnostic", "warning", "error"}:
            raise ValueError("severity must be diagnostic, warning, or error")
        return value


def advisory_level_for_wind(wind_for_safety_m_s: float) -> WindAdvisoryLevel:
    if not math.isfinite(wind_for_safety_m_s) or wind_for_safety_m_s < 0:
        raise ValueError("wind_for_safety_m_s must be a finite non-negative value")
    if wind_for_safety_m_s >= 16.0:
        return WindAdvisoryLevel.STRONG_WIND
    if wind_for_safety_m_s >= 12.0:
        return WindAdvisoryLevel.GUSTY
    if wind_for_safety_m_s >= 8.0:
        return WindAdvisoryLevel.CAUTION
    return WindAdvisoryLevel.NORMAL


def _normalize_direction_deg(direction_deg: float) -> float:
    normalized = direction_deg % 360.0
    if math.isclose(normalized, 360.0):
        return 0.0
    return normalized


def _fill_or_validate_float(
    value: Optional[float],
    default: float,
    field_name: str,
) -> float:
    candidate = default if value is None else value
    if not math.isfinite(candidate):
        raise ValueError(f"{field_name} must be finite")
    return candidate
