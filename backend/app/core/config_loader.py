from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Tuple, Type, TypeVar

import yaml

from backend.app.core.path_utils import PathLike, PathSecurityError
from backend.app.core.secret_resolver import detect_inline_api_key_in_demo
from backend.app.schemas.config import (
    DatasetConfig,
    ExperimentConfig,
    ScenarioConfig,
)


ConfigModel = TypeVar("ConfigModel", ScenarioConfig, ExperimentConfig, DatasetConfig)


@dataclass(frozen=True)
class ConfigSourceMetadata:
    source_file: str
    config_kind: str


class ConfigLoadError(ValueError):
    def __init__(
        self,
        message: str,
        *,
        source_file: Optional[str] = None,
        field_path: Optional[str] = None,
        hint: Optional[str] = None,
        config_kind: Optional[str] = None,
    ) -> None:
        self.source_file = source_file
        self.field_path = field_path
        self.hint = hint
        self.config_kind = config_kind
        super().__init__(message)


def _read_yaml_mapping(path: PathLike) -> Dict[str, Any]:
    resolved_path = Path(path).expanduser().resolve()
    try:
        with resolved_path.open("r", encoding="utf-8") as fh:
            loaded = yaml.safe_load(fh)
    except FileNotFoundError as exc:
        raise ConfigLoadError(
            f"configuration file not found: {resolved_path}",
            source_file=str(resolved_path),
            hint="Check that the YAML path exists.",
        ) from exc
    except yaml.YAMLError as exc:
        raise ConfigLoadError(
            f"failed to parse YAML file: {resolved_path}: {exc}",
            source_file=str(resolved_path),
            hint="Fix YAML syntax before starting the episode.",
        ) from exc

    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        raise ConfigLoadError(
            f"configuration file must contain a YAML mapping: {resolved_path}",
            source_file=str(resolved_path),
            hint="Use key-value YAML at the top level.",
        )
    return loaded


def apply_overrides(
    raw: Mapping[str, Any], overrides: Optional[Mapping[str, Any]] = None
) -> Dict[str, Any]:
    merged = deepcopy(dict(raw))
    if not overrides:
        return merged

    for key, value in overrides.items():
        if value is None:
            continue
        if isinstance(value, Mapping) and not isinstance(value, (str, bytes)):
            existing = merged.get(key)
            if isinstance(existing, Mapping):
                merged[key] = apply_overrides(existing, value)
            else:
                merged[key] = apply_overrides({}, value)
            continue
        _set_dotted_path(merged, key, value)
    return merged


def _set_dotted_path(raw: Dict[str, Any], dotted_path: str, value: Any) -> None:
    parts = dotted_path.split(".")
    current = raw
    for part in parts[:-1]:
        next_value = current.get(part)
        if not isinstance(next_value, dict):
            next_value = {}
            current[part] = next_value
        current = next_value
    current[parts[-1]] = value


def _attach_source_metadata(
    config: ConfigModel, source_file: PathLike, config_kind: str
) -> ConfigModel:
    setattr(
        config,
        "_source_metadata",
        ConfigSourceMetadata(
            source_file=str(Path(source_file).expanduser().resolve()),
            config_kind=config_kind,
        ),
    )
    return config


def get_config_source_metadata(config: Any) -> Optional[ConfigSourceMetadata]:
    return getattr(config, "_source_metadata", None)


def _load_typed_config(
    path: PathLike,
    model_class: Type[ConfigModel],
    config_kind: str,
    overrides: Optional[Mapping[str, Any]] = None,
) -> ConfigModel:
    raw = _read_yaml_mapping(path)
    merged = apply_overrides(raw, overrides)
    config = model_class.model_validate(merged)
    return _attach_source_metadata(config, path, config_kind)


def load_scenario_config(
    path: PathLike, overrides: Optional[Mapping[str, Any]] = None
) -> ScenarioConfig:
    return _load_typed_config(path, ScenarioConfig, "scenario", overrides)


def load_experiment_config(
    path: PathLike, overrides: Optional[Mapping[str, Any]] = None
) -> ExperimentConfig:
    return _load_typed_config(path, ExperimentConfig, "experiment", overrides)


def load_dataset_config(
    path: PathLike, overrides: Optional[Mapping[str, Any]] = None
) -> DatasetConfig:
    return _load_typed_config(path, DatasetConfig, "dataset", overrides)


def load_demo_config(
    path: PathLike, overrides: Optional[Mapping[str, Mapping[str, Any]]] = None
) -> Tuple[ScenarioConfig, Optional[ExperimentConfig], Optional[DatasetConfig]]:
    raw = _read_yaml_mapping(path)
    detect_inline_api_key_in_demo(raw)
    resolved_path = Path(path).expanduser().resolve()
    if "scenario" not in raw:
        raise ConfigLoadError(
            f"demo config is missing required scenario section: {resolved_path}",
            source_file=str(resolved_path),
            field_path="scenario",
            hint="Add a top-level scenario mapping to the demo config.",
            config_kind="scenario",
        )

    overrides = overrides or {}
    scenario_raw = apply_overrides(raw["scenario"], overrides.get("scenario"))
    scenario = _attach_source_metadata(
        ScenarioConfig.model_validate(scenario_raw), resolved_path, "scenario"
    )

    experiment = None
    if raw.get("experiment") is not None:
        experiment_raw = apply_overrides(raw["experiment"], overrides.get("experiment"))
        experiment = _attach_source_metadata(
            ExperimentConfig.model_validate(experiment_raw), resolved_path, "experiment"
        )

    dataset = None
    if raw.get("dataset") is not None:
        dataset_raw = apply_overrides(raw["dataset"], overrides.get("dataset"))
        dataset = _attach_source_metadata(
            DatasetConfig.model_validate(dataset_raw), resolved_path, "dataset"
        )

    return scenario, experiment, dataset
