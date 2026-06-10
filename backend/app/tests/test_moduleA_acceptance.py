from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from backend.app.core.config_errors import config_error_from_exception
from backend.app.core.config_hash import ConfigHashError
from backend.app.core.config_loader import load_demo_config
from backend.app.core.config_resolver import resolve_config
from backend.app.core.run_workspace import create_run_workspace
from backend.app.core.secret_resolver import resolve_provider_secrets
from backend.app.schemas.config import ExperimentConfig, ScenarioConfig
from backend.app.tests.test_config_schema import FIXTURE_DIR, load_fixture


REPO_ROOT = Path(__file__).resolve().parents[3]


def test_module_a_end_to_end_acceptance_flow(tmp_path: Path) -> None:
    scenario, experiment, dataset = load_demo_config(
        FIXTURE_DIR / "demo_valid.yaml",
        overrides={"experiment": {"llm": {"provider": "mock", "api_key_env": None}}},
    )
    provider_resolution = resolve_provider_secrets(experiment.llm)
    resolved = resolve_config(
        scenario,
        experiment,
        dataset,
        provider_summary=provider_resolution.persisted_summary,
    )
    workspace = create_run_workspace(
        resolved,
        run_root=tmp_path,
        forbidden_secret_values=[provider_resolution.runtime_secret.full_api_key],
    )

    assert resolved.resolved_config_hash
    assert resolved.layout.auto_params["num_cranes"] >= 3
    assert resolved.tasks.generation["num_tasks_per_crane"] >= 5
    assert workspace.path.exists()
    assert provider_resolution.persisted_summary.provider == "mock"


def test_module_a_supports_manual_and_auto_layout_config_only() -> None:
    auto = ScenarioConfig.model_validate(load_fixture("scenario_valid.yaml"))
    manual_raw = load_fixture("scenario_valid.yaml")
    manual_raw["layout"]["mode"] = "manual"
    manual_raw["cranes"] = [
        {
            "crane_id": "C1",
            "model_id": "generic_flat_top_55m",
            "base": [999, 999, 0],
            "mast_height_m": 45,
            "theta_init_deg": 20,
            "slew": {"mode": "continuous"},
        }
    ]
    manual = ScenarioConfig.model_validate(manual_raw)

    assert auto.cranes is None
    assert manual.cranes[0].base == [999.0, 999.0, 0.0]


def test_module_a_provider_config_supports_four_provider_names() -> None:
    for provider in ["deepseek", "minimax", "mock", "replay"]:
        raw = load_fixture("experiment_valid.yaml")
        raw["llm"]["provider"] = provider
        raw["llm"]["model"] = f"{provider}-model"
        if provider in {"mock", "replay"}:
            raw["llm"]["api_key_env"] = None
        config = ExperimentConfig.model_validate(raw)
        assert config.llm.provider.value == provider


def test_sample_resolved_config_and_metadata_do_not_persist_full_key(tmp_path: Path) -> None:
    scenario = load_fixture("scenario_valid.yaml")
    experiment = load_fixture("experiment_valid.yaml")
    experiment["llm"]["api_key"] = "sk-inline-secret-123456"
    experiment_config = ExperimentConfig.model_validate(experiment)
    provider_resolution = resolve_provider_secrets(experiment_config.llm)
    resolved = resolve_config(
        scenario,
        experiment_config,
        provider_summary=provider_resolution.persisted_summary,
    )
    workspace = create_run_workspace(
        resolved,
        run_root=tmp_path,
        forbidden_secret_values=[provider_resolution.runtime_secret.full_api_key],
    )
    persisted = "\n".join(path.read_text(encoding="utf-8") for path in workspace.created_files)

    assert "sk-inline-secret-123456" not in persisted
    assert "key_masked" in persisted


def test_required_config_error_codes_are_covered() -> None:
    scenario_error = config_error_from_exception(
        ValueError("scenario bad"), config_kind="scenario", source_file="scenario.yaml"
    )
    experiment_error = config_error_from_exception(
        ValueError("experiment bad"), config_kind="experiment", source_file="experiment.yaml"
    )
    hash_error = config_error_from_exception(
        ConfigHashError("hash bad"), config_kind="resolved", source_file="resolved"
    )

    assert {scenario_error.error_code, experiment_error.error_code, hash_error.error_code} == {
        "CFG_E_001",
        "CFG_E_002",
        "CFG_E_003",
    }


def test_module_a_docs_expected_readme_files_exist() -> None:
    docs = _module_a_docs_from_index()

    assert len(docs) == 8
    assert docs[0] == REPO_ROOT / "docs" / "moduleA" / "README.md"
    assert all(path.exists() for path in docs)
    assert [path.stem for path in docs[1:]] == [
        "task01_config_schema",
        "task02_config_loading",
        "task03_resolved_config",
        "task04_run_workspace",
        "task05_secret_governance",
        "task06_validation_errors",
        "task07_tests_and_acceptance",
    ]


def test_module_a_docs_contain_key_contract_terms() -> None:
    combined = "\n".join(
        path.read_text(encoding="utf-8") for path in _module_a_docs_from_index()
    )

    for term in [
        "ScenarioConfig",
        "ExperimentConfig",
        "DatasetConfig",
        "ResolvedConfig",
        "resolved_config_hash",
        "api_key",
        "key_masked",
        "CFG_E_001",
        "CFG_E_002",
        "CFG_E_003",
    ]:
        assert term in combined


def test_module_a_implementation_does_not_import_runtime_modules() -> None:
    module_a_files = list((REPO_ROOT / "backend" / "app" / "core").glob("*.py")) + list(
        (REPO_ROOT / "backend" / "app" / "schemas").glob("*.py")
    )
    combined = "\n".join(path.read_text(encoding="utf-8") for path in module_a_files)

    forbidden_imports = [
        "backend.app.physics",
        "backend.app.llm",
        "backend.app.risk",
        "backend.app.tasks",
        "backend.app.layout",
    ]
    for forbidden in forbidden_imports:
        assert forbidden not in combined


def _module_a_docs_from_index() -> list[Path]:
    docs_root = REPO_ROOT / "docs" / "moduleA"
    index_path = docs_root / "README.md"
    index_text = index_path.read_text(encoding="utf-8")
    linked_docs = [
        (docs_root / match).resolve()
        for match in re.findall(r"\]\((task\d+_[^)]+(?:\.md|/README\.md))\)", index_text)
    ]
    return [index_path] + linked_docs
