from __future__ import annotations

from typing import Any, Dict, List, Optional, Union

from backend.app.core.config_hash import compute_resolved_config_hash
from backend.app.core.secret_resolver import (
    mask_api_key,
)
from backend.app.schemas.config import DatasetConfig, ExperimentConfig, ScenarioConfig
from backend.app.schemas.enums import LayoutMode
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
    experiment_payload = _safe_dump(experiment_config)
    dataset_payload = _safe_dump(dataset_config) if dataset_config is not None else None

    layout = _resolve_layout(scenario_config)
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


def _resolve_layout(scenario_config: ScenarioConfig) -> ResolvedLayoutConfig:
    layout_payload = _safe_dump(scenario_config.layout)
    if scenario_config.layout.mode is LayoutMode.MANUAL:
        return ResolvedLayoutConfig(
            mode=LayoutMode.MANUAL.value,
            auto_params=None,
            manual_cranes=[_safe_dump(crane) for crane in scenario_config.cranes or []],
            resolved_cranes=None,
        )
    return ResolvedLayoutConfig(
        mode=LayoutMode.AUTO.value,
        auto_params=layout_payload,
        manual_cranes=None,
        resolved_cranes=None,
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
