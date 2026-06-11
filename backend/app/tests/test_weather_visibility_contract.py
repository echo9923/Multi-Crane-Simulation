from __future__ import annotations

import ast
from pathlib import Path

from backend.app.core.config_resolver import resolve_config
from backend.app.sim.weather import (
    WeatherGenerator,
    build_visibility_sampling_key,
    build_weather_visibility_context,
)
from backend.app.tests.test_config_schema import load_fixture


REPO_ROOT = Path(__file__).resolve().parents[3]


def _state(level: str = "poor"):
    raw = load_fixture("scenario_valid.yaml")
    raw["weather"]["mode"] = "constant"
    raw["weather"]["visibility"]["base_level"] = level
    resolved = resolve_config(raw, load_fixture("experiment_valid.yaml"))
    return WeatherGenerator.from_resolved_config(resolved).update(12.3).weather_state


def test_visibility_context_is_derived_from_weather_state_profile() -> None:
    state = _state("poor")

    context = build_weather_visibility_context(
        state,
        weather_seed=123,
        decision_time_bucket=12,
    )

    assert context.time_s == state.time_s
    assert context.visibility_level == "poor"
    assert context.neighbor_visibility_radius_m == 45.0
    assert context.distance_noise_m == 5.0
    assert context.hide_hook_prob == 0.5
    assert context.visibility_confidence == 0.4
    assert context.distance_precision_m == 5.0
    assert context.profile_source == "default"
    assert isinstance(context.noise_seed, int)


def test_visibility_context_reflects_config_profile_source() -> None:
    state = _state("good").model_copy(
        update={
            "neighbor_visibility_radius_m": 160.0,
            "distance_noise_m": 1.5,
            "hide_hook_prob": 0.1,
            "visibility_confidence": 0.9,
        }
    )

    context = build_weather_visibility_context(
        state,
        weather_seed=123,
        decision_time_bucket=2,
    )

    assert context.neighbor_visibility_radius_m == 160.0
    assert context.distance_noise_m == 1.5
    assert context.profile_source == "config"


def test_visibility_sampling_key_is_stable_and_namespaced() -> None:
    key_a = build_visibility_sampling_key(
        noise_seed=123,
        observer_crane_id="C1",
        target_crane_id="C2",
        decision_time_bucket=4,
        purpose="hook_visibility",
    )
    key_b = build_visibility_sampling_key(
        noise_seed=123,
        observer_crane_id="C1",
        target_crane_id="C2",
        decision_time_bucket=4,
        purpose="hook_visibility",
    )
    key_c = build_visibility_sampling_key(
        noise_seed=123,
        observer_crane_id="C2",
        target_crane_id="C1",
        decision_time_bucket=4,
        purpose="hook_visibility",
    )
    key_d = build_visibility_sampling_key(
        noise_seed=123,
        observer_crane_id="C1",
        target_crane_id="C2",
        decision_time_bucket=4,
        purpose="distance_noise",
    )

    assert key_a == key_b
    assert key_a != key_c
    assert key_a != key_d


def test_weather_module_does_not_construct_observation_or_read_crane_state() -> None:
    tree = ast.parse((REPO_ROOT / "backend/app/sim/weather.py").read_text(encoding="utf-8"))
    imported = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)

    banned_prefixes = (
        "backend.app.schemas.state",
        "backend.app.sim.task_observation",
        "backend.app.llm",
        "backend.app.risk",
    )
    assert not [module for module in imported if module.startswith(banned_prefixes)]
