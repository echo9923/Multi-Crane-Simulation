from __future__ import annotations

import json
import os
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from backend.app.api.production_runner import build_production_episode_runner
from backend.app.core.config_loader import load_demo_config
from backend.app.core.config_resolver import resolve_config
from backend.app.tests.test_config_schema import FIXTURE_DIR


def _load_env_local() -> None:
    env_path = Path(__file__).resolve().parents[3] / ".env.local"
    if not env_path.is_file():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'\"")
        if key and key not in os.environ:
            os.environ[key] = value


def _deepseek_config(tmp_path: Path):
    _load_env_local()
    if not os.environ.get("DEEPSEEK_API_KEY"):
        pytest.fail(
            "DEEPSEEK_API_KEY is required for external DeepSeek production "
            "acceptance. Set it in .env.local or the environment."
        )

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
                    "fallback_dropoff_z_range_m": [18, 22],
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
                    "duration_s": 0.6,
                    "min_duration_s": 0.0,
                    "stop_when_all_tasks_done": False,
                    "completion_cooldown_s": 0.0,
                    "llm_decision_interval_s": 0.6,
                },
                "llm": {
                    "provider": "deepseek",
                    "model": "deepseek-v4-flash",
                    "base_url": "https://api.deepseek.com/v1",
                    "api_key_env": "DEEPSEEK_API_KEY",
                    "api_key": None,
                    "timeout_s": 20,
                    "max_retries": 1,
                    "context": {
                        "history_mode": "none",
                        "recent_decisions_full": 0,
                        "summarizer": {"mode": "none"},
                    },
                },
                "output": {"run_root": str(tmp_path)},
            },
        },
    )
    assert experiment is not None
    return resolve_config(scenario, experiment, dataset)


def test_external_deepseek_v4_flash_production_generates_motion(
    tmp_path: Path,
) -> None:
    runner = build_production_episode_runner(
        episode_id="E-deepseek-v4-flash-production",
        resolved_config=_deepseek_config(tmp_path),
    )

    result = runner.run_episode()

    run_dir = runner.recorder.run_dir
    assert run_dir is not None
    summary = json.loads((run_dir / "metadata" / "episode_summary.json").read_text())
    assert result.status.value in {"timeout", "completed"}
    assert summary["num_llm_calls"] > 0
    assert summary["llm_invalid_output_count"] == 0

    rows = pq.read_table(run_dir / "data" / "trajectories.parquet").to_pylist()
    assert rows
    by_crane: dict[str, list[dict]] = {}
    for row in rows:
        by_crane.setdefault(row["crane_id"], []).append(row)
    assert any(_has_motion(crane_rows) for crane_rows in by_crane.values())


def _has_motion(rows: list[dict]) -> bool:
    ordered = sorted(rows, key=lambda row: row["frame"])
    first = ordered[0]
    return any(
        abs(row["theta_rad"] - first["theta_rad"]) > 1.0e-6
        or abs(row["trolley_r_m"] - first["trolley_r_m"]) > 1.0e-6
        or abs(row["hook_h_m"] - first["hook_h_m"]) > 1.0e-6
        for row in ordered[1:]
    )
