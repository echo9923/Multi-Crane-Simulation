from __future__ import annotations

import math
import random
import hashlib
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from backend.app.schemas.enums import VisibilityLevel
from backend.app.schemas.enums import WeatherMode
from backend.app.schemas.resolved_config import ResolvedConfig
from backend.app.schemas.weather import (
    DEFAULT_VISIBILITY_PROFILES,
    WeatherDiagnostic,
    WeatherGenerationReport,
    WeatherState,
    WeatherVisibilityContext,
    WindAdvisory,
)


class WeatherUpdateResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    weather_state: Optional[WeatherState] = None
    events: List[Dict[str, Any]] = Field(default_factory=list)
    warnings: List[WeatherDiagnostic] = Field(default_factory=list)
    failure_request: Optional[Dict[str, Any]] = None


@dataclass
class WeatherTimeline:
    mode: str
    segments: List[Dict[str, Any]]

    def segment_at(self, time_s: float) -> Dict[str, Any]:
        for segment in self.segments:
            end_s = segment.get("end_s")
            if segment["start_s"] <= time_s and (end_s is None or time_s < end_s):
                return segment
        if self.segments and time_s >= self.segments[-1]["start_s"]:
            last = self.segments[-1]
            if last.get("end_s") is None:
                return last
        raise ValueError(f"WEATHER_E_101 no weather segment covers time_s={time_s}")


class WeatherGenerator:
    def __init__(
        self,
        *,
        weather_config: Dict[str, Any],
        seed: int,
        timeline: WeatherTimeline,
    ) -> None:
        self.weather_config = weather_config
        self.seed = seed
        self.timeline = timeline
        self.update_interval_s = weather_config["update_interval_s"]
        self.runtime_failure_policy = weather_config["runtime_failure_policy"]
        self._last_good_state: Optional[WeatherState] = None

    @classmethod
    def from_resolved_config(cls, resolved_config: ResolvedConfig) -> "WeatherGenerator":
        weather_config = resolved_config.scenario["weather"]
        seed = resolved_config.seeds.weather
        mode = weather_config["mode"]
        if mode == WeatherMode.CONSTANT.value:
            timeline = WeatherTimeline(mode=mode, segments=[_constant_segment(weather_config)])
        elif mode == WeatherMode.SCHEDULE.value:
            timeline = WeatherTimeline(
                mode=mode,
                segments=[dict(segment) for segment in weather_config["schedule"]["segments"]],
            )
        elif mode == WeatherMode.RANDOM.value:
            duration_s = resolved_config.runtime.sim["duration_s"]
            timeline = WeatherTimeline(
                mode=mode,
                segments=_build_random_segments(weather_config, seed, duration_s),
            )
        else:
            raise ValueError(f"WEATHER_E_001 unsupported weather mode: {mode}")
        return cls(weather_config=weather_config, seed=seed, timeline=timeline)

    def update(self, time_s: float) -> WeatherUpdateResult:
        if not math.isfinite(time_s) or time_s < 0:
            return WeatherUpdateResult(
                failure_request=_failure_request(
                    time_s=time_s,
                    reason="weather time_s must be finite and non-negative",
                    details={"time_s": time_s},
                )
            )
        try:
            state = self._state_for_time(time_s)
        except (ValueError, TypeError) as exc:
            return self._handle_runtime_invalid(time_s, exc)

        self._last_good_state = state
        warnings = list(state.diagnostics)
        return WeatherUpdateResult(
            weather_state=state,
            warnings=warnings,
            events=[],
            failure_request=None,
        )

    def preview_timeline(self, duration_s: float) -> WeatherGenerationReport:
        first = self.update(0.0).weather_state
        if first is None:
            raise ValueError("WEATHER_E_101 cannot preview timeline without first state")
        return WeatherGenerationReport(
            mode=self.timeline.mode,
            seed=self.seed,
            update_interval_s=self.update_interval_s,
            timeline_segment_count=len(self.timeline.segments),
            first_state=first,
            config_defaults_applied=[],
            warnings=[],
        )

    def _state_for_time(self, time_s: float) -> WeatherState:
        segment = self.timeline.segment_at(time_s)
        generation_step = math.floor(time_s / self.update_interval_s)
        state = WeatherState(
            time_s=time_s,
            mode=self.timeline.mode,
            wind_speed_m_s=segment["wind_speed_m_s"],
            wind_gust_m_s=segment["wind_gust_m_s"],
            wind_direction_deg=segment["wind_direction_deg"],
            visibility_level=segment["visibility_level"],
            rain_level=segment.get("rain_level", "none"),
            fog_level=segment.get("fog_level", "none"),
            source_segment_id=segment.get("segment_id"),
            generation_seed=self.seed,
            generation_step=generation_step,
            diagnostics=[],
        )
        diagnostics = _diagnostics_for_state(state)
        if diagnostics:
            state = state.model_copy(update={"diagnostics": diagnostics})
        return state

    def _handle_runtime_invalid(self, time_s: float, exc: Exception) -> WeatherUpdateResult:
        warning = WeatherDiagnostic(
            code="WEATHER_E_101",
            severity="warning",
            time_s=max(time_s, 0.0) if math.isfinite(time_s) else 0.0,
            message="runtime weather generated an invalid state",
            details={"error": str(exc)},
        )
        if self.runtime_failure_policy == "warn_and_hold_last" and self._last_good_state:
            state = self._last_good_state.model_copy(
                update={
                    "time_s": self._last_good_state.time_s,
                    "diagnostics": [*self._last_good_state.diagnostics, warning],
                }
            )
            return WeatherUpdateResult(
                weather_state=state,
                warnings=[warning],
                failure_request=None,
            )
        if self.runtime_failure_policy == "warn_and_use_safe_default":
            state = WeatherState(
                time_s=max(time_s, 0.0),
                mode=self.timeline.mode,
                wind_speed_m_s=0.0,
                wind_gust_m_s=0.0,
                wind_direction_deg=0.0,
                visibility_level="good",
                rain_level="none",
                fog_level="none",
                source_segment_id="safe-default",
                generation_seed=self.seed,
                generation_step=0,
                diagnostics=[warning],
            )
            self._last_good_state = state
            return WeatherUpdateResult(
                weather_state=state,
                warnings=[warning],
                failure_request=None,
            )
        return WeatherUpdateResult(
            weather_state=None,
            warnings=[],
            failure_request=_failure_request(
                time_s=time_s,
                reason="runtime weather generated an invalid state",
                details={"error": str(exc)},
            ),
        )


def _constant_segment(weather_config: Dict[str, Any]) -> Dict[str, Any]:
    precipitation = weather_config["precipitation"]
    return {
        "segment_id": "constant",
        "start_s": 0.0,
        "end_s": None,
        "wind_speed_m_s": weather_config["wind"]["base_speed_m_s"],
        "wind_gust_m_s": weather_config["wind"]["gust_speed_m_s"],
        "wind_direction_deg": weather_config["wind"]["direction_deg"],
        "visibility_level": weather_config["visibility"]["base_level"],
        "rain_level": precipitation["rain_level"],
        "fog_level": precipitation["fog_level"],
        "transition_s": 0.0,
    }


def _build_random_segments(
    weather_config: Dict[str, Any],
    seed: int,
    duration_s: float,
) -> List[Dict[str, Any]]:
    rng = random.Random(seed)
    random_config = weather_config["random"]
    min_interval, max_interval = random_config["change_interval_s"]
    wind_min, wind_max = random_config["wind_speed_range_m_s"]
    gust_min, gust_max = random_config["gust_extra_range_m_s"]
    direction_delta_min, direction_delta_max = random_config["direction_change_range_deg"]
    direction = weather_config["wind"]["direction_deg"]
    segments: List[Dict[str, Any]] = []
    start_s = 0.0
    index = 0
    while start_s <= duration_s or not segments:
        interval_s = rng.uniform(min_interval, max_interval)
        end_s = start_s + interval_s
        direction = (direction + rng.uniform(direction_delta_min, direction_delta_max)) % 360.0
        wind_speed = rng.uniform(wind_min, wind_max)
        gust_extra = rng.uniform(gust_min, gust_max)
        segments.append(
            {
                "segment_id": f"random-{index:04d}",
                "start_s": start_s,
                "end_s": end_s,
                "wind_speed_m_s": wind_speed,
                "wind_gust_m_s": wind_speed + gust_extra,
                "wind_direction_deg": direction,
                "visibility_level": _weighted_choice(
                    rng,
                    random_config["visibility_distribution"],
                ),
                "rain_level": _weighted_choice(rng, random_config["rain_distribution"]),
                "fog_level": _weighted_choice(rng, random_config["fog_distribution"]),
                "transition_s": 0.0,
            }
        )
        start_s = end_s
        index += 1
    segments[-1]["end_s"] = None
    return segments


def _weighted_choice(rng: random.Random, distribution: Dict[str, float]) -> str:
    draw = rng.random()
    cumulative = 0.0
    last_key = ""
    for key, weight in distribution.items():
        last_key = key
        cumulative += weight
        if draw <= cumulative:
            return key
    return last_key


def _diagnostics_for_state(state: WeatherState) -> List[WeatherDiagnostic]:
    diagnostics: List[WeatherDiagnostic] = []
    if state.wind_advisory_level == "strong_wind":
        diagnostics.append(
            WeatherDiagnostic(
                code="WEATHER_W_201",
                severity="warning",
                time_s=state.time_s,
                message="wind or gust reached the strong wind advisory threshold",
                details={
                    "wind_for_safety_m_s": state.wind_for_safety_m_s,
                    "wind_advisory_level": state.wind_advisory_level,
                },
            )
        )
    if state.visibility_level == "poor":
        diagnostics.append(
            WeatherDiagnostic(
                code="WEATHER_W_202",
                severity="warning",
                time_s=state.time_s,
                message="visibility is poor",
                details={
                    "visibility_level": state.visibility_level,
                    "visibility_confidence": state.visibility_confidence,
                },
            )
        )
    return diagnostics


def _failure_request(
    *,
    time_s: float,
    reason: str,
    details: Dict[str, Any],
) -> Dict[str, Any]:
    return {
        "source_module": "E",
        "error_code": "WEATHER_E_101",
        "reason": reason,
        "time_s": time_s,
        "details": details,
        "default_episode_status": "failed_invalid_state",
    }


def build_weather_visibility_context(
    weather_state: WeatherState,
    *,
    weather_seed: int,
    decision_time_bucket: int,
) -> WeatherVisibilityContext:
    level = VisibilityLevel(weather_state.visibility_level)
    default_profile = DEFAULT_VISIBILITY_PROFILES[level]
    distance_precision_m = default_profile.distance_precision_m
    profile_source = "default"
    if (
        not math.isclose(
            weather_state.neighbor_visibility_radius_m,
            default_profile.neighbor_visibility_radius_m,
        )
        or not math.isclose(weather_state.distance_noise_m, default_profile.distance_noise_m)
        or not math.isclose(weather_state.hide_hook_prob, default_profile.hide_hook_prob)
        or not math.isclose(
            weather_state.visibility_confidence,
            default_profile.visibility_confidence,
        )
    ):
        profile_source = "config"

    noise_seed = _stable_int_hash(
        [
            "weather_visibility_context",
            str(weather_seed),
            str(decision_time_bucket),
            str(weather_state.visibility_level),
        ]
    )
    return WeatherVisibilityContext(
        time_s=weather_state.time_s,
        visibility_level=weather_state.visibility_level,
        neighbor_visibility_radius_m=weather_state.neighbor_visibility_radius_m,
        distance_noise_m=weather_state.distance_noise_m,
        hide_hook_prob=weather_state.hide_hook_prob,
        visibility_confidence=weather_state.visibility_confidence,
        distance_precision_m=distance_precision_m,
        noise_seed=noise_seed,
        profile_source=profile_source,
    )


def build_visibility_sampling_key(
    *,
    noise_seed: int,
    observer_crane_id: str,
    target_crane_id: str,
    decision_time_bucket: int,
    purpose: str,
) -> int:
    return _stable_int_hash(
        [
            "weather_visibility_sampling",
            str(noise_seed),
            observer_crane_id,
            target_crane_id,
            str(decision_time_bucket),
            purpose,
        ]
    )


def _stable_int_hash(parts: List[str]) -> int:
    encoded = "\x1f".join(parts).encode("utf-8")
    digest = hashlib.sha256(encoded).hexdigest()
    return int(digest[:16], 16)


def build_wind_advisory(weather_state: WeatherState) -> WindAdvisory:
    level = weather_state.wind_advisory_level
    level_value = level.value if hasattr(level, "value") else str(level)
    behavior_keys = _recommended_behavior_keys(level)
    return WindAdvisory(
        time_s=weather_state.time_s,
        level=level,
        wind_speed_m_s=weather_state.wind_speed_m_s,
        wind_gust_m_s=weather_state.wind_gust_m_s,
        wind_direction_deg=weather_state.wind_direction_deg,
        wind_for_safety_m_s=weather_state.wind_for_safety_m_s,
        message_key=f"weather.wind.{level_value}",
        recommended_behavior_keys=behavior_keys,
    )


def _recommended_behavior_keys(level: str) -> List[str]:
    if level == "normal":
        return []
    if level == "caution":
        return ["increase_observation"]
    if level == "gusty":
        return [
            "reduce_gear",
            "slow_hoist",
            "avoid_sudden_slew",
            "increase_observation",
        ]
    return [
        "reduce_gear",
        "slow_hoist",
        "avoid_sudden_slew",
        "increase_observation",
        "pause_if_gusty",
    ]


def build_weather_record_row(
    weather_state: WeatherState,
    *,
    episode_id: str,
    scenario_id: str,
    frame_index: int,
) -> Dict[str, Any]:
    return {
        "schema_version": weather_state.schema_version,
        "episode_id": episode_id,
        "scenario_id": scenario_id,
        "frame": frame_index,
        "time_s": weather_state.time_s,
        "wind_speed_m_s": weather_state.wind_speed_m_s,
        "wind_gust_m_s": weather_state.wind_gust_m_s,
        "wind_direction_deg": weather_state.wind_direction_deg,
        "visibility_level": _value(weather_state.visibility_level),
        "rain_level": _value(weather_state.rain_level),
        "fog_level": _value(weather_state.fog_level),
        "wind_for_safety_m_s": weather_state.wind_for_safety_m_s,
        "wind_advisory_level": _value(weather_state.wind_advisory_level),
        "neighbor_visibility_radius_m": weather_state.neighbor_visibility_radius_m,
        "distance_noise_m": weather_state.distance_noise_m,
        "hide_hook_prob": weather_state.hide_hook_prob,
        "visibility_confidence": weather_state.visibility_confidence,
        "source_segment_id": weather_state.source_segment_id,
        "generation_seed": weather_state.generation_seed,
        "generation_step": weather_state.generation_step,
    }


def build_weather_frame_summary(weather_state: WeatherState) -> Dict[str, Any]:
    return {
        "wind_speed_m_s": weather_state.wind_speed_m_s,
        "wind_gust_m_s": weather_state.wind_gust_m_s,
        "wind_direction_deg": weather_state.wind_direction_deg,
        "visibility_level": _value(weather_state.visibility_level),
        "rain_level": _value(weather_state.rain_level),
        "fog_level": _value(weather_state.fog_level),
        "wind_advisory_level": _value(weather_state.wind_advisory_level),
    }


def compare_weather_replay_row(
    weather_state: WeatherState,
    historical_row: Dict[str, Any],
    *,
    abs_tol: float = 1e-9,
) -> Optional[Dict[str, Any]]:
    expected = build_weather_record_row(
        weather_state,
        episode_id=str(historical_row.get("episode_id", "")),
        scenario_id=str(historical_row.get("scenario_id", "")),
        frame_index=weather_state.generation_step,
    )
    fields = [
        "frame",
        "time_s",
        "wind_speed_m_s",
        "wind_gust_m_s",
        "wind_direction_deg",
        "visibility_level",
        "rain_level",
    ]
    for field in fields:
        actual = historical_row.get(field)
        expected_value = expected[field]
        if isinstance(expected_value, float):
            if actual is None or not math.isclose(float(actual), expected_value, abs_tol=abs_tol):
                return _replay_mismatch(field, expected_value, actual)
        elif actual != expected_value:
            return _replay_mismatch(field, expected_value, actual)
    return None


def _replay_mismatch(field: str, expected: Any, actual: Any) -> Dict[str, Any]:
    return {
        "source_module": "E",
        "error_code": "WEATHER_E_REPLAY_MISMATCH",
        "field": field,
        "expected": expected,
        "actual": actual,
        "default_episode_status": "failed_replay_mismatch",
    }


def _value(value: Any) -> Any:
    return value.value if hasattr(value, "value") else value
