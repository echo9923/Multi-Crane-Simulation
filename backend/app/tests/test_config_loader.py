from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from backend.app.core.config_loader import (
    ConfigLoadError,
    ConfigSourceMetadata,
    PathSecurityError,
    apply_overrides,
    get_config_source_metadata,
    load_dataset_config,
    load_demo_config,
    load_experiment_config,
    load_scenario_config,
)
from backend.app.core.path_utils import normalize_path_under_root
from backend.app.schemas.config import (
    DatasetConfig,
    ExperimentConfig,
    ScenarioConfig,
)


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "configs"


def test_loads_separate_scenario_experiment_and_dataset_configs() -> None:
    scenario = load_scenario_config(FIXTURE_DIR / "scenario_valid.yaml")
    experiment = load_experiment_config(FIXTURE_DIR / "experiment_valid.yaml")
    dataset = load_dataset_config(FIXTURE_DIR / "dataset_valid.yaml")

    assert isinstance(scenario, ScenarioConfig)
    assert isinstance(experiment, ExperimentConfig)
    assert isinstance(dataset, DatasetConfig)
    assert scenario.scenario_id == "site_001"
    assert experiment.experiment_id == "exp_2026_001"
    assert dataset.dataset_id == "tower_crane_llm_dataset_v1"


def test_loader_attaches_source_metadata_without_dumping_it() -> None:
    scenario_path = FIXTURE_DIR / "scenario_valid.yaml"
    scenario = load_scenario_config(scenario_path)

    metadata = get_config_source_metadata(scenario)

    assert metadata == ConfigSourceMetadata(
        source_file=str(scenario_path.resolve()), config_kind="scenario"
    )
    assert "source_file" not in scenario.model_dump()


def test_demo_config_is_split_into_typed_configs() -> None:
    scenario, experiment, dataset = load_demo_config(FIXTURE_DIR / "demo_valid.yaml")

    assert isinstance(scenario, ScenarioConfig)
    assert isinstance(experiment, ExperimentConfig)
    assert isinstance(dataset, DatasetConfig)
    assert not isinstance(scenario, dict)
    assert get_config_source_metadata(experiment).config_kind == "experiment"


def test_demo_config_may_omit_experiment_and_dataset(tmp_path: Path) -> None:
    with (FIXTURE_DIR / "demo_valid.yaml").open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    raw.pop("experiment")
    raw.pop("dataset")
    demo_path = tmp_path / "demo_scenario_only.yaml"
    demo_path.write_text(yaml.safe_dump(raw), encoding="utf-8")

    scenario, experiment, dataset = load_demo_config(demo_path)

    assert isinstance(scenario, ScenarioConfig)
    assert experiment is None
    assert dataset is None


def test_demo_config_without_scenario_fails(tmp_path: Path) -> None:
    demo_path = tmp_path / "demo_missing_scenario.yaml"
    demo_path.write_text("experiment: {}\n", encoding="utf-8")

    with pytest.raises(ConfigLoadError) as exc_info:
        load_demo_config(demo_path)

    assert str(demo_path) in str(exc_info.value)
    assert exc_info.value.config_kind == "scenario"


def test_cli_override_can_update_experiment_duration() -> None:
    experiment = load_experiment_config(
        FIXTURE_DIR / "experiment_valid.yaml",
        overrides={"sim.duration_s": 900},
    )

    assert experiment.sim.duration_s == 900


def test_none_override_values_are_ignored() -> None:
    experiment = load_experiment_config(
        FIXTURE_DIR / "experiment_valid.yaml",
        overrides={"sim.duration_s": None},
    )

    assert experiment.sim.duration_s == 600


def test_override_still_goes_through_schema_validation() -> None:
    with pytest.raises(ValidationError) as exc_info:
        load_experiment_config(
            FIXTURE_DIR / "experiment_valid.yaml",
            overrides={"sim.duration_s": -1},
        )

    assert ("sim", "duration_s") in [error["loc"] for error in exc_info.value.errors()]


def test_same_yaml_and_override_produce_same_typed_config() -> None:
    first = load_experiment_config(
        FIXTURE_DIR / "experiment_valid.yaml",
        overrides={"sim.duration_s": 900},
    )
    second = load_experiment_config(
        FIXTURE_DIR / "experiment_valid.yaml",
        overrides={"sim.duration_s": 900},
    )

    assert first == second


def test_apply_overrides_supports_nested_dict_format() -> None:
    raw = {"sim": {"duration_s": 600, "dt": 0.05}}

    merged = apply_overrides(raw, {"sim": {"duration_s": 900}})

    assert merged == {"sim": {"duration_s": 900, "dt": 0.05}}
    assert raw["sim"]["duration_s"] == 600


def test_path_traversal_is_rejected() -> None:
    with pytest.raises(PathSecurityError):
        normalize_path_under_root("../outside.yaml", root=FIXTURE_DIR)


def test_yaml_syntax_error_includes_source_file(tmp_path: Path) -> None:
    bad_yaml = tmp_path / "bad.yaml"
    bad_yaml.write_text("schema_version: [unterminated\n", encoding="utf-8")

    with pytest.raises(ConfigLoadError) as exc_info:
        load_scenario_config(bad_yaml)

    assert str(bad_yaml) in str(exc_info.value)
    assert exc_info.value.source_file == str(bad_yaml.resolve())
