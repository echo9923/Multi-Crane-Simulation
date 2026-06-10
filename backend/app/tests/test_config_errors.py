from __future__ import annotations

from copy import deepcopy

import pytest
from pydantic import ValidationError

from backend.app.core.config_errors import (
    StartupFailureResult,
    config_error_from_exception,
    pydantic_errors_to_config_errors,
)
from backend.app.core.config_hash import ConfigHashError
from backend.app.core.config_loader import ConfigLoadError, load_scenario_config
from backend.app.core.secret_resolver import SecretGovernanceError
from backend.app.schemas.config import ExperimentConfig, ScenarioConfig
from backend.app.tests.test_config_schema import FIXTURE_DIR, load_fixture


def test_scenario_validation_failure_maps_to_cfg_e_001() -> None:
    raw = load_fixture("scenario_valid.yaml")
    raw.pop("site")

    with pytest.raises(ValidationError) as exc_info:
        ScenarioConfig.model_validate(raw)

    errors = pydantic_errors_to_config_errors(
        exc_info.value,
        config_kind="scenario",
        source_file="scenario.yaml",
    )

    assert errors[0].error_code == "CFG_E_001"
    assert errors[0].category == "startup_error"
    assert errors[0].field_path == "site"
    assert errors[0].source_file == "scenario.yaml"


def test_experiment_validation_failure_maps_to_cfg_e_002() -> None:
    raw = load_fixture("experiment_valid.yaml")
    raw.pop("sim")

    with pytest.raises(ValidationError) as exc_info:
        ExperimentConfig.model_validate(raw)

    errors = pydantic_errors_to_config_errors(
        exc_info.value,
        config_kind="experiment",
        source_file="experiment.yaml",
    )

    assert errors[0].error_code == "CFG_E_002"
    assert errors[0].field_path == "sim"


def test_dataset_validation_failure_is_startup_error_with_dataset_detail() -> None:
    raw = load_fixture("dataset_valid.yaml")
    raw.pop("sources")

    from backend.app.schemas.config import DatasetConfig

    with pytest.raises(ValidationError) as exc_info:
        DatasetConfig.model_validate(raw)

    errors = pydantic_errors_to_config_errors(
        exc_info.value,
        config_kind="dataset",
        source_file="dataset.yaml",
    )

    assert errors[0].category == "startup_error"
    assert errors[0].details["config_kind"] == "dataset"


def test_hash_error_maps_to_cfg_e_003() -> None:
    error = config_error_from_exception(
        ConfigHashError("not serializable"),
        config_kind="resolved",
        source_file="resolved_config",
    )

    assert error.error_code == "CFG_E_003"
    assert error.field_path == "resolved_config_hash"


def test_error_object_contains_required_fields() -> None:
    raw = load_fixture("scenario_valid.yaml")
    raw["layout"]["mode"] = "not-valid"

    with pytest.raises(ValidationError) as exc_info:
        ScenarioConfig.model_validate(raw)

    error = pydantic_errors_to_config_errors(
        exc_info.value,
        config_kind="scenario",
        source_file="scenario.yaml",
    )[0]
    payload = error.model_dump()

    for field in [
        "schema_version",
        "error_code",
        "severity",
        "category",
        "message",
        "field_path",
        "source_file",
        "hint",
        "details",
    ]:
        assert field in payload


def test_nested_pydantic_error_uses_stable_field_path() -> None:
    raw = load_fixture("experiment_valid.yaml")
    raw["llm"]["provider"] = "bad"

    with pytest.raises(ValidationError) as exc_info:
        ExperimentConfig.model_validate(raw)

    error = pydantic_errors_to_config_errors(
        exc_info.value,
        config_kind="experiment",
        source_file="experiment.yaml",
    )[0]

    assert error.field_path == "llm.provider"


def test_loader_source_metadata_can_be_attached_to_validation_error() -> None:
    raw = load_fixture("scenario_valid.yaml")
    raw["layout"]["mode"] = "bad"
    source_file = str((FIXTURE_DIR / "scenario_valid.yaml").resolve())

    with pytest.raises(ValidationError) as exc_info:
        load_scenario_config(FIXTURE_DIR / "scenario_valid.yaml", overrides={"layout.mode": "bad"})

    errors = pydantic_errors_to_config_errors(
        exc_info.value,
        config_kind="scenario",
        source_file=source_file,
    )

    assert errors[0].source_file == source_file


def test_secret_error_converts_without_leaking_full_key() -> None:
    exc = SecretGovernanceError(
        "provider deepseek requires an API key before startup",
        provider="deepseek",
        key_source="env",
        missing_env="DEEPSEEK_API_KEY",
        hint="Set env var.",
    )

    error = config_error_from_exception(
        exc,
        config_kind="experiment",
        source_file="experiment.yaml",
        forbidden_secret_values=["sk-inline-secret-123456"],
    )

    assert error.category == "startup_error"
    assert error.details["provider"] == "deepseek"
    assert "sk-inline-secret-123456" not in str(error.model_dump())


def test_config_error_prevents_episode_startup() -> None:
    error = config_error_from_exception(
        ConfigLoadError("missing file", source_file="scenario.yaml"),
        config_kind="scenario",
        source_file="scenario.yaml",
    )
    result = StartupFailureResult(errors=[error])

    assert result.can_start is False
    assert result.errors[0].category == "startup_error"


def test_error_object_scrubs_forbidden_secret_values() -> None:
    error = config_error_from_exception(
        ConfigLoadError(
            "bad secret sk-inline-secret-123456",
            source_file="experiment.yaml",
        ),
        config_kind="experiment",
        source_file="experiment.yaml",
        forbidden_secret_values=["sk-inline-secret-123456"],
    )

    assert "sk-inline-secret-123456" not in str(error.model_dump())
    assert "[REDACTED]" in error.message
