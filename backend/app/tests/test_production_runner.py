from __future__ import annotations

import json
from pathlib import Path

import pyarrow.parquet as pq

from backend.app.core.config_loader import load_demo_config
from backend.app.core.config_resolver import resolve_config
from backend.app.schemas.scheduler import EpisodeStatus
from backend.app.tests.test_config_schema import FIXTURE_DIR


def _production_smoke_config(tmp_path: Path):
    scenario, experiment, dataset = load_demo_config(
        FIXTURE_DIR / "demo_valid.yaml",
        overrides={
            "scenario": {
                "layout": {"mode": "manual", "num_cranes": 2},
                "cranes": [
                    {
                        "crane_id": "C1",
                        "model_id": "generic_flat_top_55m",
                        "base": [-22, 0, 0],
                        "mast_height_m": 50,
                        "theta_init_deg": 30,
                        "slew": {"mode": "continuous"},
                    },
                    {
                        "crane_id": "C2",
                        "model_id": "generic_flat_top_55m",
                        "base": [-34, 0, 0],
                        "mast_height_m": 54,
                        "theta_init_deg": 30,
                        "slew": {"mode": "continuous"},
                    },
                ],
                "site": {
                    "material_zones": [
                        {
                            "zone_id": "mat",
                            "type": "box",
                            "center": [-35, -10, 1],
                            "size": [10, 10, 2],
                            "z_range_m": [0.5, 1.5],
                            "load_types": ["rebar_bundle"],
                        }
                    ],
                    "work_zones": [
                        {
                            "zone_id": "work",
                            "type": "box",
                            "center": [5, 10, 20],
                            "size": [10, 10, 4],
                            "z_range_m": [18, 22],
                            "accepted_load_types": ["rebar_bundle"],
                        }
                    ],
                },
                "tasks": {
                    "num_tasks_per_crane": 1,
                    "queue_policy": {
                        "start_mode": "simultaneous",
                        "initial_start_jitter_s": [0, 0],
                        "inter_task_delay_s": [0, 0],
                    },
                    "task_type_distribution": {
                        "easy_task": 1.0,
                        "overlap_task": 0.0,
                        "stress_task": 0.0,
                    },
                },
            },
            "experiment": {
                "sim": {
                    "dt": 0.1,
                    "duration_s": 0.4,
                    "min_duration_s": 0.0,
                    "stop_when_all_tasks_done": False,
                    "completion_cooldown_s": 0.0,
                    "llm_decision_interval_s": 0.2,
                },
                "llm": {
                    "provider": "mock",
                    "model": "mock-production",
                    "api_key_env": None,
                    "api_key": None,
                    "timeout_s": 1,
                    "max_retries": 0,
                    "context": {"history_mode": "none", "recent_decisions_full": 0},
                },
                "output": {"run_root": str(tmp_path)},
            },
        },
    )
    assert experiment is not None
    return resolve_config(scenario, experiment, dataset)


def test_production_runner_uses_tasks_observations_llm_safety_and_recorder(
    tmp_path: Path,
) -> None:
    from backend.app.api.production_runner import build_production_episode_runner

    runner = build_production_episode_runner(
        episode_id="E-production",
        resolved_config=_production_smoke_config(tmp_path),
    )

    result = runner.run_episode()

    assert result.status in {EpisodeStatus.TIMEOUT, EpisodeStatus.COMPLETED}
    run_dir = runner.recorder.run_dir
    assert run_dir == tmp_path / "E-production"

    summary = json.loads((run_dir / "metadata" / "episode_summary.json").read_text())
    assert summary["num_llm_calls"] > 0
    assert summary["llm_invalid_output_count"] == 0

    commands = [
        json.loads(line)
        for line in (run_dir / "logs" / "commands.jsonl").read_text().splitlines()
        if line.strip()
    ]
    assert commands
    assert any(row["provider"] == "mock" for row in commands)
    assert any(
        row["parsed_command"]["attention_target"] == "current_target"
        for row in commands
        if row.get("parsed_command")
    )

    observations = [
        json.loads(line)
        for line in (run_dir / "logs" / "llm_observations.jsonl").read_text().splitlines()
        if line.strip()
    ]
    assert observations
    assert any(row["observation"]["task"]["has_active_task"] for row in observations)
    assert any(
        row["observation"]["task"].get("control_hint")
        for row in observations
        if row["observation"]["task"]["has_active_task"]
    )

    events = [
        json.loads(line)
        for line in (run_dir / "logs" / "events.jsonl").read_text().splitlines()
        if line.strip()
    ]
    assert any(row["event_type"] == "task_started" for row in events)

    trajectories = pq.read_table(run_dir / "data" / "trajectories.parquet").to_pylist()
    assert trajectories
    assert any(row["task_id"] for row in trajectories)
    assert (run_dir / "data" / "pair_risks.parquet").is_file()
    assert (run_dir / "visual" / "frames.jsonl").is_file()
    assert (run_dir / "visual" / "episode_manifest.json").is_file()


def test_production_runner_wraps_siliconflow_provider_with_runtime_secret(
    tmp_path: Path,
) -> None:
    from backend.app.api.desktop_llm_settings import save_provider_secret
    from backend.app.api.production_runner import RuntimeSecretProvider, _provider_with_runtime_secret
    from backend.app.schemas.config import ExperimentConfig

    experiment = load_demo_config(FIXTURE_DIR / "demo_valid.yaml")[1]
    assert experiment is not None
    payload = experiment.model_dump(mode="json")
    payload["llm"].update(
        {
            "provider": "siliconflow",
            "model": "deepseek-ai/DeepSeek-V4-Flash",
            "api_key": None,
            "api_key_env": "SILICONFLOW_API_KEY",
            "base_url": "https://api.siliconflow.cn/v1",
        }
    )
    experiment = ExperimentConfig.model_validate(payload)
    save_provider_secret(
        tmp_path,
        provider=experiment.llm.provider,
        api_key="sf-local-secret-123456",
    )

    provider = _provider_with_runtime_secret(experiment.llm, project_root=tmp_path)

    assert isinstance(provider, RuntimeSecretProvider)
    assert provider.provider_name.value == "siliconflow"
    assert provider.runtime_secret.full_api_key == "sf-local-secret-123456"


def test_production_runner_runtime_secret_falls_back_to_cwd_project_root(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from backend.app.api.desktop_llm_settings import save_provider_secret
    from backend.app.api.production_runner import RuntimeSecretProvider, _provider_with_runtime_secret
    from backend.app.schemas.config import ExperimentConfig

    monkeypatch.chdir(tmp_path)
    experiment = load_demo_config(FIXTURE_DIR / "demo_valid.yaml")[1]
    assert experiment is not None
    payload = experiment.model_dump(mode="json")
    payload["llm"].update(
        {
            "provider": "siliconflow",
            "model": "deepseek-ai/DeepSeek-V4-Flash",
            "api_key": None,
            "api_key_env": "SILICONFLOW_API_KEY",
            "base_url": "https://api.siliconflow.cn/v1",
        }
    )
    experiment = ExperimentConfig.model_validate(payload)
    save_provider_secret(
        tmp_path,
        provider=experiment.llm.provider,
        api_key="sf-cwd-secret-123456",
    )

    provider = _provider_with_runtime_secret(experiment.llm)

    assert isinstance(provider, RuntimeSecretProvider)
    assert provider.runtime_secret.full_api_key == "sf-cwd-secret-123456"
