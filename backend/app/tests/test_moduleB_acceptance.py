from __future__ import annotations

import re
from pathlib import Path

from backend.app.core.config_resolver import resolve_config
from backend.app.sim.auto_layout import AutoLayoutError
from backend.app.sim.crane_model import CraneModelLibraryError
from backend.app.sim.layout import LayoutResolutionError
from backend.app.tests.test_config_schema import load_fixture


REPO_ROOT = Path(__file__).resolve().parents[3]


def test_module_b_docs_expected_files_exist() -> None:
    docs_root = REPO_ROOT / "docs" / "moduleB"
    docs = [docs_root / "README.md"] + [
        docs_root / f"task{index:02d}_{name}.md"
        for index, name in [
            (1, "crane_model_spec"),
            (2, "manual_layout_validation"),
            (3, "crane_config_resolution"),
            (4, "auto_layout_generator"),
            (5, "task_reachability_precheck"),
            (6, "tests_and_acceptance"),
        ]
    ]

    assert all(path.exists() for path in docs)


def test_module_b_docs_contain_key_contract_terms() -> None:
    combined = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (REPO_ROOT / "docs" / "moduleB").glob("*.md")
    )

    for term in [
        "CraneModelSpec",
        "CraneConfig",
        "capacity_at_radius",
        "LAY_E_001",
        "LAY_E_002",
        "LAY_E_003",
        "resolved_cranes",
        "layout_diagnostics",
        "model_library_snapshot",
        "overlap_ratio",
        "quality_score",
    ]:
        assert term in combined


def test_module_b_resolved_auto_layout_demo_has_cranes_and_diagnostics() -> None:
    resolved = resolve_config(
        load_fixture("scenario_valid.yaml"),
        load_fixture("experiment_valid.yaml"),
    )

    assert len(resolved.layout.resolved_cranes) == 4
    assert resolved.layout.layout_diagnostics["mode"] == "auto"
    assert resolved.layout.layout_diagnostics["pair_diagnostics"]
    assert resolved.layout.layout_diagnostics["quality_score"] is not None


def test_module_b_error_code_classes_are_distinct() -> None:
    assert AutoLayoutError(
        "auto failed",
        max_sampling_attempts=1,
        attempts=1,
        last_failure_reason="base_out_of_boundary",
        failure_counts_by_reason={"base_out_of_boundary": 1},
        layout_params={},
        seed=1,
    ).error_code == "LAY_E_001"
    assert LayoutResolutionError(
        "manual failed",
        reason="base_out_of_boundary",
    ).reason == "base_out_of_boundary"
    assert CraneModelLibraryError(
        "model failed",
        model_id="bad",
        reason="invalid_crane_model",
    ).reason == "invalid_crane_model"


def test_module_b_implementation_does_not_import_runtime_modules() -> None:
    files = list((REPO_ROOT / "backend" / "app" / "sim").glob("*.py"))
    combined = "\n".join(path.read_text(encoding="utf-8") for path in files)

    forbidden_imports = [
        "backend.app.physics",
        "backend.app.llm",
        "backend.app.risk",
        "backend.app.tasks",
        "backend.app.recorder",
    ]
    for forbidden in forbidden_imports:
        assert forbidden not in combined
