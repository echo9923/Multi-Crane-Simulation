from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from backend.app.api.desktop_service import (
    apply_config_patch,
    list_desktop_templates,
    list_recent_experiments,
    list_run_files,
    list_runs,
    render_template_yaml,
    save_experiment_draft,
    scrub_secret_values,
)


def test_list_desktop_templates_reads_yaml_files(tmp_path: Path) -> None:
    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    (config_dir / "demo.yaml").write_text(
        "scenario:\n  scenario_id: demo\nexperiment:\n  experiment_id: demo_exp\n",
        encoding="utf-8",
    )

    templates = list_desktop_templates(project_root=tmp_path, template_dirs=[config_dir])

    assert len(templates) == 1
    assert templates[0].template_id == "demo"
    assert templates[0].name == "demo"
    assert templates[0].scenario_id == "demo"
    assert templates[0].experiment_id == "demo_exp"


def test_render_template_yaml_applies_core_overrides(tmp_path: Path) -> None:
    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    (config_dir / "demo.yaml").write_text(
        "\n".join(
            [
                "scenario:",
                "  scenario_id: demo",
                "  layout:",
                "    num_cranes: 4",
                "experiment:",
                "  experiment_id: demo_exp",
                "  sim:",
                "    duration_s: 100",
                "  llm:",
                "    provider: deepseek",
            ]
        ),
        encoding="utf-8",
    )

    text = render_template_yaml(
        project_root=tmp_path,
        template_id="demo",
        core_overrides={
            "scenario.layout.num_cranes": 6,
            "experiment.sim.duration_s": 240,
            "experiment.llm.provider": "openai_compatible",
        },
        template_dirs=[config_dir],
    )
    parsed = yaml.safe_load(text)

    assert parsed["scenario"]["layout"]["num_cranes"] == 6
    assert parsed["experiment"]["sim"]["duration_s"] == 240
    assert parsed["experiment"]["llm"]["provider"] == "openai_compatible"


def test_render_template_yaml_does_not_scrub_token_count_fields(tmp_path: Path) -> None:
    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    (config_dir / "demo.yaml").write_text(
        "\n".join(
            [
                "experiment:",
                "  llm:",
                "    api_key: sk-real",
                "    context:",
                "      summarizer:",
                "        trigger:",
                "          context_over_tokens: 12000",
                "    token_env: TOKEN_SECRET",
            ]
        ),
        encoding="utf-8",
    )

    text = render_template_yaml(
        project_root=tmp_path,
        template_id="demo",
        core_overrides={},
        template_dirs=[config_dir],
    )
    parsed = yaml.safe_load(text)
    llm = parsed["experiment"]["llm"]

    assert llm["api_key"] == "***"
    assert llm["token_env"] == "***"
    assert llm["context"]["summarizer"]["trigger"]["context_over_tokens"] == 12000


def test_apply_config_patch_preserves_unmapped_yaml_fields() -> None:
    text = "scenario:\n  scenario_id: x\n  custom_field: keep\nexperiment:\n  sim:\n    duration_s: 10\n"

    patched = apply_config_patch(text, {"experiment.sim.duration_s": 20})
    parsed = yaml.safe_load(patched)

    assert parsed["scenario"]["custom_field"] == "keep"
    assert parsed["experiment"]["sim"]["duration_s"] == 20


def test_scrub_secret_values_masks_nested_api_keys() -> None:
    cleaned = scrub_secret_values(
        {
            "experiment": {
                "llm": {
                    "api_key": "sk-real",
                    "api_key_env": "DEEPSEEK_API_KEY",
                    "authorization_env": "AUTH_HEADER",
                    "model": "m",
                    "password_env": "PASSWORD",
                    "secret_env": "SECRET",
                    "token_env": "TOKEN",
                    "context_over_tokens": 12000,
                    "prompt_tokens": 12,
                }
            }
        }
    )

    llm = cleaned["experiment"]["llm"]
    assert llm["api_key"] == "***"
    assert llm["api_key_env"] == "DEEPSEEK_API_KEY"
    assert llm["authorization_env"] == "***"
    assert llm["model"] == "m"
    assert llm["password_env"] == "***"
    assert llm["secret_env"] == "***"
    assert llm["token_env"] == "***"
    assert llm["context_over_tokens"] == 12000
    assert llm["prompt_tokens"] == 12


def test_save_experiment_draft_never_writes_raw_secret(tmp_path: Path) -> None:
    draft_dir = tmp_path / ".desktop" / "experiments"
    result = save_experiment_draft(
        project_root=tmp_path,
        experiment_id="exp1",
        yaml_text="experiment:\n  llm:\n    api_key: sk-real\n    model: m\n",
        metadata={"template_id": "demo", "last_validation_hash": "abc"},
        draft_root=draft_dir,
    )

    yaml_text = Path(result.yaml_path).read_text(encoding="utf-8")
    meta = json.loads(Path(result.metadata_path).read_text(encoding="utf-8"))

    assert result.metadata_path.endswith("draft.meta.json")
    assert "sk-real" not in yaml_text
    assert "***" in yaml_text
    assert meta["experiment_id"] == "exp1"
    assert meta["template_id"] == "demo"


def test_save_experiment_draft_rejects_non_mapping_yaml(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="YAML mapping"):
        save_experiment_draft(
            project_root=tmp_path,
            experiment_id="exp1",
            yaml_text="- item\n",
            metadata={},
            draft_root=tmp_path / ".desktop" / "experiments",
        )


def test_list_recent_experiments_ignores_tampered_metadata_paths(tmp_path: Path) -> None:
    draft_dir = tmp_path / ".desktop" / "experiments"
    exp_dir = draft_dir / "exp1"
    exp_dir.mkdir(parents=True)
    (exp_dir / "draft.yaml").write_text("experiment: {}\n", encoding="utf-8")
    (exp_dir / "draft.meta.json").write_text(
        json.dumps(
            {
                "experiment_id": "../unsafe",
                "yaml_path": "/etc/passwd",
                "metadata_path": "/etc/shadow",
                "template_id": "demo",
            }
        ),
        encoding="utf-8",
    )

    items = list_recent_experiments(project_root=tmp_path, draft_root=draft_dir)

    assert len(items) == 1
    assert items[0].experiment_id == "exp1"
    assert Path(items[0].yaml_path).resolve() == (exp_dir / "draft.yaml").resolve()
    assert Path(items[0].metadata_path).resolve() == (exp_dir / "draft.meta.json").resolve()


def test_list_runs_reads_episode_summaries(tmp_path: Path) -> None:
    run = tmp_path / "runs" / "exp" / "episode-1"
    (run / "metadata").mkdir(parents=True)
    (run / "metadata" / "episode_summary.json").write_text(
        json.dumps({"episode_id": "episode-1", "status": "completed", "duration_s": 12}),
        encoding="utf-8",
    )

    runs = list_runs(project_root=tmp_path, run_roots=[tmp_path / "runs"])

    assert len(runs) == 1
    assert runs[0].episode_id == "episode-1"
    assert runs[0].summary_available is True
    assert runs[0].path.endswith("episode-1")


def test_list_run_files_keeps_known_artifacts_only(tmp_path: Path) -> None:
    run = tmp_path / "runs" / "episode-1"
    for rel in [
        "metadata/episode_summary.json",
        "visual/frames.jsonl",
        "data/trajectories.parquet",
        "logs/commands.jsonl",
        "tmp/debug.tmp",
    ]:
        path = run / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x", encoding="utf-8")

    files = list_run_files(run)
    names = {item.relative_path for item in files}

    assert "metadata/episode_summary.json" in names
    assert "visual/frames.jsonl" in names
    assert "data/trajectories.parquet" in names
    assert "logs/commands.jsonl" in names
    assert "tmp/debug.tmp" not in names


def test_list_run_files_rejects_paths_outside_safe_run_roots(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    run_root = project_root / "runs"
    outside = tmp_path / "outside" / "episode-1"
    for run_dir in [run_root / "episode-1", outside]:
        path = run_dir / "metadata" / "episode_summary.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}", encoding="utf-8")

    with pytest.raises(ValueError, match="run_dir"):
        list_run_files(outside, project_root=project_root, run_roots=["runs"])

    with pytest.raises(ValueError, match="run_dir"):
        list_run_files("../outside/episode-1", project_root=project_root, run_roots=["runs"])
