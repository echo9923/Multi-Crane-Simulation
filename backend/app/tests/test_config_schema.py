from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from backend.app.schemas.config import (
    DatasetConfig,
    ExperimentConfig,
    ScenarioConfig,
)
from backend.app.schemas.enums import (
    LayoutMode,
    LLMProviderName,
    RiskPromptMode,
    SafetyMode,
)


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "configs"


def load_fixture(name: str) -> dict:
    with (FIXTURE_DIR / name).open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def test_valid_scenario_yaml_loads_successfully() -> None:
    config = ScenarioConfig.model_validate(load_fixture("scenario_valid.yaml"))

    assert config.schema_version == "1.0"
    assert config.scenario_id == "site_001"
    assert config.layout.mode is LayoutMode.AUTO
    assert config.layout.num_cranes == 4


def test_valid_experiment_yaml_loads_successfully() -> None:
    config = ExperimentConfig.model_validate(load_fixture("experiment_valid.yaml"))

    assert config.schema_version == "1.0"
    assert config.risk_prompt_mode is RiskPromptMode.R1
    assert config.safety_mode is SafetyMode.S1
    assert config.llm.provider is LLMProviderName.DEEPSEEK


def test_valid_dataset_yaml_loads_successfully() -> None:
    config = DatasetConfig.model_validate(load_fixture("dataset_valid.yaml"))

    assert config.schema_version == "1.0"
    assert config.dataset_id == "tower_crane_llm_dataset_v1"
    assert len(config.sources) == 2


@pytest.mark.parametrize(
    "model_class,fixture_name",
    [
        (ScenarioConfig, "scenario_valid.yaml"),
        (ExperimentConfig, "experiment_valid.yaml"),
        (DatasetConfig, "dataset_valid.yaml"),
    ],
)
def test_missing_schema_version_fails(model_class, fixture_name: str) -> None:
    raw = load_fixture(fixture_name)
    raw.pop("schema_version")

    with pytest.raises(ValidationError) as exc_info:
        model_class.model_validate(raw)

    assert exc_info.value.errors()[0]["loc"] == ("schema_version",)


def test_invalid_layout_mode_fails() -> None:
    raw = load_fixture("scenario_valid.yaml")
    raw["layout"]["mode"] = "freeform"

    with pytest.raises(ValidationError) as exc_info:
        ScenarioConfig.model_validate(raw)

    assert ("layout", "mode") in [error["loc"] for error in exc_info.value.errors()]


def test_invalid_risk_prompt_mode_fails() -> None:
    raw = load_fixture("experiment_valid.yaml")
    raw["risk_prompt_mode"] = "R9"

    with pytest.raises(ValidationError) as exc_info:
        ExperimentConfig.model_validate(raw)

    assert ("risk_prompt_mode",) in [error["loc"] for error in exc_info.value.errors()]


def test_invalid_safety_mode_fails() -> None:
    raw = load_fixture("experiment_valid.yaml")
    raw["safety_mode"] = "S9"

    with pytest.raises(ValidationError) as exc_info:
        ExperimentConfig.model_validate(raw)

    assert ("safety_mode",) in [error["loc"] for error in exc_info.value.errors()]


def test_invalid_llm_provider_fails() -> None:
    raw = load_fixture("experiment_valid.yaml")
    raw["llm"]["provider"] = "unknown"

    with pytest.raises(ValidationError) as exc_info:
        ExperimentConfig.model_validate(raw)

    assert ("llm", "provider") in [error["loc"] for error in exc_info.value.errors()]


def test_manual_layout_requires_cranes() -> None:
    raw = load_fixture("scenario_valid.yaml")
    raw["layout"]["mode"] = "manual"
    raw.pop("cranes", None)

    with pytest.raises(ValidationError) as exc_info:
        ScenarioConfig.model_validate(raw)

    errors = exc_info.value.errors()
    assert any(error["loc"] == () and "cranes" in error["msg"] for error in errors)


def test_auto_layout_allows_missing_cranes() -> None:
    raw = load_fixture("scenario_valid.yaml")
    raw["layout"]["mode"] = "auto"
    raw.pop("cranes", None)

    config = ScenarioConfig.model_validate(raw)

    assert config.cranes is None


def test_experiment_api_key_uses_secret_field() -> None:
    raw = load_fixture("experiment_valid.yaml")
    raw["llm"]["api_key"] = "sk-secret-value-123456"

    config = ExperimentConfig.model_validate(raw)

    assert "sk-secret-value-123456" not in repr(config)
    assert "sk-secret-value-123456" not in str(config.model_dump(mode="json"))
    assert config.llm.api_key.get_secret_value() == "sk-secret-value-123456"


def test_task_type_distribution_rejects_negative_weight() -> None:
    raw = load_fixture("scenario_valid.yaml")
    raw["tasks"]["task_type_distribution"]["easy_task"] = -0.1

    with pytest.raises(ValidationError) as exc_info:
        ScenarioConfig.model_validate(raw)

    assert ("tasks", "task_type_distribution") in [
        error["loc"] for error in exc_info.value.errors()
    ]


def test_task_type_distribution_must_sum_to_one() -> None:
    raw = load_fixture("scenario_valid.yaml")
    raw["tasks"]["task_type_distribution"]["easy_task"] = 0.9

    with pytest.raises(ValidationError) as exc_info:
        ScenarioConfig.model_validate(raw)

    assert ("tasks", "task_type_distribution") in [
        error["loc"] for error in exc_info.value.errors()
    ]


def test_site_boundary_min_values_must_be_less_than_max_values() -> None:
    raw = load_fixture("scenario_valid.yaml")
    raw["site"]["boundary"]["x_min"] = 100
    raw["site"]["boundary"]["x_max"] = -100

    with pytest.raises(ValidationError) as exc_info:
        ScenarioConfig.model_validate(raw)

    assert ("site", "boundary") in [error["loc"] for error in exc_info.value.errors()]


def test_manual_layout_accepts_crane_input_without_geometry_validation() -> None:
    raw = load_fixture("scenario_valid.yaml")
    raw["layout"]["mode"] = "manual"
    raw["cranes"] = [
        {
            "crane_id": "C1",
            "model_id": "generic_flat_top_55m",
            "base": [999, 999, 0],
            "mast_height_m": 45,
            "theta_init_deg": 20,
            "slew": {"mode": "continuous"},
        }
    ]

    config = ScenarioConfig.model_validate(raw)

    assert config.cranes[0].base == [999.0, 999.0, 0.0]


def test_config_models_can_export_json_schema() -> None:
    scenario_schema = ScenarioConfig.model_json_schema()
    experiment_schema = ExperimentConfig.model_json_schema()
    dataset_schema = DatasetConfig.model_json_schema()

    assert scenario_schema["title"] == "ScenarioConfig"
    assert experiment_schema["title"] == "ExperimentConfig"
    assert dataset_schema["title"] == "DatasetConfig"
