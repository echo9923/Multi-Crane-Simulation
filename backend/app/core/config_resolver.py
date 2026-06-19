from __future__ import annotations

from typing import Any, Dict, List, Optional, Union

from backend.app.core.config_hash import compute_resolved_config_hash
from backend.app.core.secret_resolver import (
    mask_api_key,
)
from backend.app.schemas.config import DatasetConfig, ExperimentConfig, ScenarioConfig
from backend.app.schemas.enums import LayoutMode
from backend.app.schemas.weather import DEFAULT_VISIBILITY_PROFILES
from backend.app.schemas.resolved_config import (
    DefaultApplied,
    PersistedProviderSummary,
    ResolvedConfig,
    ResolvedLayoutConfig,
    ResolvedOperatorsConfig,
    ResolvedOutputConfig,
    ResolvedRuntimeConfig,
    ResolvedSeeds,
    ResolvedTaskConfig,
)
from backend.app.sim.crane_model import build_crane_model_library
from backend.app.sim.auto_layout import generate_auto_layout
from backend.app.sim.layout import (
    build_crane_configs,
    build_layout_diagnostics,
    validate_manual_layout,
)


ConfigInput = Union[ScenarioConfig, ExperimentConfig, DatasetConfig, Dict[str, Any]]


def resolve_config(
    scenario: Union[ScenarioConfig, Dict[str, Any]],
    experiment: Union[ExperimentConfig, Dict[str, Any]],
    dataset: Optional[Union[DatasetConfig, Dict[str, Any]]] = None,
    provider_summary: Optional[PersistedProviderSummary] = None,
) -> ResolvedConfig:
    scenario_config = _ensure_scenario_config(scenario)
    experiment_config = _ensure_experiment_config(experiment)
    dataset_config = _ensure_dataset_config(dataset) if dataset is not None else None

    defaults_applied: List[DefaultApplied] = []
    seeds = _derive_seeds(
        scenario_config.seed, experiment_config.seed, defaults_applied=defaults_applied
    )
    provider = provider_summary or build_persisted_provider_summary(experiment_config)

    scenario_payload = _safe_dump(scenario_config)
    scenario_payload["weather"] = _resolve_weather(
        scenario_config,
        experiment_config,
        defaults_applied=defaults_applied,
    )
    experiment_payload = _safe_dump(experiment_config)
    dataset_payload = _safe_dump(dataset_config) if dataset_config is not None else None

    layout = _resolve_layout(scenario_config, seeds.layout, seeds.task)
    resolved = ResolvedConfig(
        schema_version=scenario_config.schema_version,
        scenario=scenario_payload,
        experiment=experiment_payload,
        dataset=dataset_payload,
        defaults_applied=defaults_applied,
        seeds=seeds,
        layout=layout,
        tasks=ResolvedTaskConfig(generation=scenario_payload["tasks"]),
        operators=ResolvedOperatorsConfig(
            assignment=experiment_payload["operators"],
        ),
        provider=provider,
        runtime=ResolvedRuntimeConfig(
            runtime=experiment_payload["runtime"],
            sim=experiment_payload["sim"],
            risk_prompt_mode=experiment_config.risk_prompt_mode.value,
            safety_mode=experiment_config.safety_mode.value,
        ),
        output=ResolvedOutputConfig(**experiment_payload["output"]),
        resolved_config_hash="",
    )
    resolved_hash = compute_resolved_config_hash(resolved)
    return resolved.model_copy(update={"resolved_config_hash": resolved_hash})


def build_persisted_provider_summary(
    experiment: ExperimentConfig,
) -> PersistedProviderSummary:
    llm = experiment.llm
    api_key = llm.api_key.get_secret_value() if llm.api_key is not None else None
    if api_key:
        key_source = "inline"
        key_env_name = None
        key_masked = mask_api_key(api_key)
    elif llm.api_key_env:
        key_source = "env"
        key_env_name = llm.api_key_env
        key_masked = None
    else:
        key_source = "none"
        key_env_name = None
        key_masked = None
    return PersistedProviderSummary(
        provider=llm.provider.value,
        model=llm.model,
        base_url=llm.base_url,
        temperature=llm.temperature,
        timeout_s=llm.timeout_s,
        max_retries=llm.max_retries,
        key_source=key_source,
        key_env_name=key_env_name,
        key_masked=key_masked,
    )


def _derive_seeds(
    scenario_seed: int,
    experiment_seed: int,
    *,
    defaults_applied: List[DefaultApplied],
) -> ResolvedSeeds:
    derived = {
        "layout": _stable_seed(scenario_seed, 101),
        "task": _stable_seed(scenario_seed, 202),
        "weather": _stable_seed(scenario_seed, 303),
        "operator_assignment": _stable_seed(experiment_seed, 404),
    }
    for name, value in derived.items():
        defaults_applied.append(
            DefaultApplied(
                field_path=f"seeds.{name}",
                value=value,
                source="derived",
                reason=f"Derived deterministically from {'experiment' if name == 'operator_assignment' else 'scenario'} seed.",
            )
        )
    return ResolvedSeeds(
        scenario=scenario_seed,
        experiment=experiment_seed,
        layout=derived["layout"],
        task=derived["task"],
        weather=derived["weather"],
        operator_assignment=derived["operator_assignment"],
    )


def _stable_seed(base_seed: int, salt: int) -> int:
    return (base_seed * 1_000_003 + salt) % (2**31 - 1)


def _resolve_weather(
    scenario_config: ScenarioConfig,
    experiment_config: ExperimentConfig,
    *,
    defaults_applied: List[DefaultApplied],
) -> Dict[str, Any]:
    weather_config = scenario_config.weather
    payload = _safe_dump(weather_config)

    if weather_config.update_interval_s is None:
        payload["update_interval_s"] = experiment_config.sim.dt
        defaults_applied.append(
            DefaultApplied(
                field_path="scenario.weather.update_interval_s",
                value=experiment_config.sim.dt,
                source="experiment.sim.dt",
                reason="Weather update interval defaults to the simulation frame dt.",
            )
        )

    _track_present_default(
        defaults_applied,
        field_path="scenario.weather.enabled",
        value=payload["enabled"],
        reason="Weather generation is enabled by default for every scenario.",
    )
    _track_present_default(
        defaults_applied,
        field_path="scenario.weather.runtime_failure_policy",
        value=payload["runtime_failure_policy"],
        reason="Runtime weather invalid state defaults to episode failure.",
    )

    if not payload["visibility"].get("levels"):
        payload["visibility"]["levels"] = {
            level.value: profile.model_dump(mode="json")
            for level, profile in DEFAULT_VISIBILITY_PROFILES.items()
        }
        defaults_applied.append(
            DefaultApplied(
                field_path="scenario.weather.visibility.levels",
                value=payload["visibility"]["levels"],
                source="moduleE.default_visibility_profiles",
                reason="Visibility profiles default to the module E canonical profiles.",
            )
        )

    if "precipitation" in payload:
        _track_present_default(
            defaults_applied,
            field_path="scenario.weather.precipitation",
            value=payload["precipitation"],
            reason="MVP weather defaults to no rain and no fog.",
        )

    if not payload["schedule"]["segments"]:
        payload["schedule"]["segments"] = [_default_schedule_segment(payload)]
        defaults_applied.append(
            DefaultApplied(
                field_path="scenario.weather.schedule.segments",
                value=payload["schedule"]["segments"],
                source="backward_compatibility",
                reason="Legacy schedule weather without segments becomes a single open-ended segment.",
            )
        )

    random_payload = payload["random"]
    random_defaults = {
        "change_interval_s": [30.0, 120.0],
        "smoothing_time_s": 10.0,
        "wind_speed_range_m_s": [0.0, 12.0],
        "gust_extra_range_m_s": [0.0, 8.0],
        "direction_change_range_deg": [-30.0, 30.0],
        "visibility_distribution": {"good": 0.5, "medium": 0.35, "poor": 0.15},
        "rain_distribution": {"none": 1.0, "light": 0.0, "moderate": 0.0, "heavy": 0.0},
        "fog_distribution": {"none": 1.0, "light": 0.0, "medium": 0.0, "dense": 0.0},
    }
    applied_random_defaults: Dict[str, Any] = {}
    for key, value in random_defaults.items():
        if random_payload.get(key) is None:
            random_payload[key] = value
            applied_random_defaults[key] = value
    if applied_random_defaults:
        defaults_applied.append(
            DefaultApplied(
                field_path="scenario.weather.random",
                value=applied_random_defaults,
                source="moduleE.random_defaults",
                reason="Random weather mode uses deterministic default generation ranges.",
            )
        )

    if payload.get("wind_advisory_thresholds_m_s") is None:
        payload["wind_advisory_thresholds_m_s"] = {
            "caution": 8.0,
            "gusty": 12.0,
            "strong_wind": 16.0,
        }
        defaults_applied.append(
            DefaultApplied(
                field_path="scenario.weather.wind_advisory_thresholds_m_s",
                value=payload["wind_advisory_thresholds_m_s"],
                source="moduleE.wind_advisory_defaults",
                reason="Wind advisory thresholds default to module E warning levels.",
            )
        )

    if payload["wind"].get("speed_bounds_m_s") is None:
        payload["wind"]["speed_bounds_m_s"] = [0.0, 25.0]
        defaults_applied.append(
            DefaultApplied(
                field_path="scenario.weather.wind.speed_bounds_m_s",
                value=payload["wind"]["speed_bounds_m_s"],
                source="moduleE.wind_defaults",
                reason="Weather wind speed bounds default to the MVP accepted range.",
            )
        )

    if payload["wind"].get("gust_duration_s") is None:
        payload["wind"]["gust_duration_s"] = [3.0, 10.0]
        defaults_applied.append(
            DefaultApplied(
                field_path="scenario.weather.wind.gust_duration_s",
                value=payload["wind"]["gust_duration_s"],
                source="moduleE.wind_defaults",
                reason="Gust duration defaults support future random weather generation.",
            )
        )

    return payload


def _track_present_default(
    defaults_applied: List[DefaultApplied],
    *,
    field_path: str,
    value: Any,
    reason: str,
) -> None:
    defaults_applied.append(
        DefaultApplied(
            field_path=field_path,
            value=value,
            source="schema_default",
            reason=reason,
        )
    )


def _default_schedule_segment(weather_payload: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "segment_id": "schedule-default-0",
        "start_s": 0.0,
        "end_s": None,
        "wind_speed_m_s": weather_payload["wind"]["base_speed_m_s"],
        "wind_gust_m_s": weather_payload["wind"]["gust_speed_m_s"],
        "wind_direction_deg": weather_payload["wind"]["direction_deg"],
        "visibility_level": weather_payload["visibility"]["base_level"],
        "rain_level": weather_payload["precipitation"]["rain_level"],
        "fog_level": weather_payload["precipitation"]["fog_level"],
        "transition_s": 0.0,
    }


def _resolve_layout(
    scenario_config: ScenarioConfig,
    layout_seed: int,
    task_seed: int,
) -> ResolvedLayoutConfig:
    layout_payload = _safe_dump(scenario_config.layout)
    model_library = build_crane_model_library(scenario_config.crane_models)
    model_snapshot = {
        model_id: model.model_dump(mode="json")
        for model_id, model in sorted(model_library.items())
    }
    if scenario_config.layout.mode is LayoutMode.MANUAL:
        validation = validate_manual_layout(scenario_config, model_library)
        crane_configs = build_crane_configs(
            validation.cranes,
            model_library,
            scenario_config,
            source="manual",
        )
        diagnostics = build_layout_diagnostics(
            crane_configs,
            mode=LayoutMode.MANUAL.value,
            warnings=validation.diagnostics.warnings,
            quality_score=None,
        )
        return ResolvedLayoutConfig(
            mode=LayoutMode.MANUAL.value,
            auto_params=None,
            manual_cranes=[_safe_dump(crane) for crane in scenario_config.cranes or []],
            resolved_cranes=[crane.model_dump(mode="json") for crane in crane_configs],
            layout_diagnostics=diagnostics.model_dump(mode="json"),
            model_library_snapshot=model_snapshot,
        )
    crane_configs, diagnostics = generate_auto_layout(
        scenario_config,
        model_library,
        seed=layout_seed,
        task_seed=task_seed,
    )
    return ResolvedLayoutConfig(
        mode=LayoutMode.AUTO.value,
        auto_params=layout_payload,
        manual_cranes=None,
        resolved_cranes=[crane.model_dump(mode="json") for crane in crane_configs],
        layout_diagnostics=diagnostics.model_dump(mode="json"),
        model_library_snapshot=model_snapshot,
    )


def _ensure_scenario_config(
    config: Union[ScenarioConfig, Dict[str, Any]]
) -> ScenarioConfig:
    if isinstance(config, ScenarioConfig):
        return config
    return ScenarioConfig.model_validate(config)


def _ensure_experiment_config(
    config: Union[ExperimentConfig, Dict[str, Any]]
) -> ExperimentConfig:
    if isinstance(config, ExperimentConfig):
        return config
    return ExperimentConfig.model_validate(config)


def _ensure_dataset_config(
    config: Union[DatasetConfig, Dict[str, Any]]
) -> DatasetConfig:
    if isinstance(config, DatasetConfig):
        return config
    return DatasetConfig.model_validate(config)


def _safe_dump(config: Any) -> Dict[str, Any]:
    if config is None:
        return {}
    payload = config.model_dump(mode="json")
    return _remove_secret_values(payload)


def _remove_secret_values(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _remove_secret_values(item)
            for key, item in value.items()
            if key != "api_key"
        }
    if isinstance(value, list):
        return [_remove_secret_values(item) for item in value]
    return value
