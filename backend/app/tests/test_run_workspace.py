from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from backend.app.core.config_resolver import resolve_config
from backend.app.core.run_workspace import (
    RunWorkspaceError,
    create_run_workspace,
)
from backend.app.tests.test_config_schema import load_fixture


def _resolved_config_with_inline_key():
    experiment = load_fixture("experiment_valid.yaml")
    experiment["llm"]["api_key"] = "sk-inline-secret-123456"
    return resolve_config(load_fixture("scenario_valid.yaml"), experiment)


def test_creates_standard_run_workspace_structure(tmp_path: Path) -> None:
    resolved = resolve_config(load_fixture("scenario_valid.yaml"), load_fixture("experiment_valid.yaml"))

    workspace = create_run_workspace(resolved, run_root=tmp_path)

    assert workspace.path.exists()
    assert (workspace.path / "config").is_dir()
    assert (workspace.path / "metadata").is_dir()
    assert (workspace.path / "logs").is_dir()
    assert (workspace.path / "data").is_dir()
    assert (workspace.path / "visual").is_dir()
    assert (workspace.path / "replay").is_dir()


def test_writes_resolved_config_yaml_and_metadata_json(tmp_path: Path) -> None:
    resolved = resolve_config(load_fixture("scenario_valid.yaml"), load_fixture("experiment_valid.yaml"))

    workspace = create_run_workspace(resolved, run_root=tmp_path, run_id="E0001")

    resolved_yaml = yaml.safe_load(
        (workspace.path / "config" / "resolved_config.yaml").read_text(encoding="utf-8")
    )
    metadata = json.loads(
        (workspace.path / "metadata" / "run_metadata.json").read_text(encoding="utf-8")
    )

    assert resolved_yaml["resolved_config_hash"] == resolved.resolved_config_hash
    assert metadata["experiment_id"] == "exp_2026_001"
    assert metadata["scenario_id"] == "site_001"
    assert metadata["run_id"] == "E0001"
    assert metadata["resolved_config_hash"] == resolved.resolved_config_hash
    assert "git_commit" in metadata
    assert "git_dirty" in metadata
    assert "python_version" in metadata
    assert "package_summary" in metadata


def test_consecutive_runs_do_not_overwrite_existing_directory(tmp_path: Path) -> None:
    resolved = resolve_config(load_fixture("scenario_valid.yaml"), load_fixture("experiment_valid.yaml"))

    first = create_run_workspace(resolved, run_root=tmp_path, run_id="E0001")
    second = create_run_workspace(resolved, run_root=tmp_path, run_id="E0001")

    assert first.path != second.path
    assert first.path.exists()
    assert second.path.exists()


def test_custom_run_root_must_stay_under_allowed_root(tmp_path: Path) -> None:
    resolved = resolve_config(load_fixture("scenario_valid.yaml"), load_fixture("experiment_valid.yaml"))

    with pytest.raises(RunWorkspaceError):
        create_run_workspace(
            resolved,
            run_root="../outside",
            allowed_root=tmp_path,
        )


def test_workspace_outputs_do_not_contain_full_api_key(tmp_path: Path) -> None:
    resolved = _resolved_config_with_inline_key()

    workspace = create_run_workspace(resolved, run_root=tmp_path)
    combined = "\n".join(
        path.read_text(encoding="utf-8")
        for path in [
            workspace.path / "config" / "resolved_config.yaml",
            workspace.path / "metadata" / "run_metadata.json",
        ]
    )

    assert "sk-inline-secret-123456" not in combined
    assert "sk-i****3456" in combined


def test_refuses_to_persist_payload_that_contains_full_api_key(tmp_path: Path) -> None:
    resolved = _resolved_config_with_inline_key()
    unsafe = resolved.model_copy(
        update={
            "scenario": {
                **resolved.scenario,
                "unsafe_note": "sk-inline-secret-123456",
            }
        }
    )

    with pytest.raises(RunWorkspaceError) as exc_info:
        create_run_workspace(
            unsafe,
            run_root=tmp_path,
            forbidden_secret_values=["sk-inline-secret-123456"],
        )

    assert "secret" in str(exc_info.value).lower()


def test_all_output_paths_are_inside_workspace(tmp_path: Path) -> None:
    resolved = resolve_config(load_fixture("scenario_valid.yaml"), load_fixture("experiment_valid.yaml"))

    workspace = create_run_workspace(resolved, run_root=tmp_path)

    for output_path in workspace.created_files:
        assert workspace.path in output_path.resolve().parents
