from __future__ import annotations

import json
import math
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from backend.app.core.config_loader import load_demo_config
from backend.app.core.config_resolver import resolve_config
from backend.app.schemas.crane import CraneConfig
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
        for line in (run_dir / "logs" / "llm_observations.jsonl").read_text(encoding="utf-8").splitlines()
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


def test_production_runner_exposes_episode_run_dir_before_first_frame(
    tmp_path: Path,
) -> None:
    from backend.app.api.production_runner import build_production_episode_runner

    runner = build_production_episode_runner(
        episode_id="E-start-path",
        resolved_config=_production_smoke_config(tmp_path),
    )

    assert runner.recorder.run_dir == tmp_path / "E-start-path"
    assert runner.recorder.layout is None


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


def test_production_runner_runtime_secret_prefers_data_root_over_project_root(
    tmp_path: Path,
) -> None:
    from backend.app.api.desktop_llm_settings import save_provider_secret
    from backend.app.api.production_runner import (
        RuntimeSecretProvider,
        build_production_episode_runner,
    )
    from backend.app.schemas.enums import LLMProviderName

    project_root = tmp_path / "project"
    data_root = tmp_path / "data"
    project_root.mkdir()
    data_root.mkdir()
    save_provider_secret(
        data_root,
        provider=LLMProviderName.SILICONFLOW,
        api_key="sf-data-root-secret-123456",
    )
    resolved = _production_smoke_config(tmp_path / "runs")
    llm = dict(resolved.experiment["llm"])
    llm.update(
        {
            "provider": "siliconflow",
            "model": "deepseek-ai/DeepSeek-V4-Flash",
            "api_key": None,
            "api_key_env": "SILICONFLOW_API_KEY",
            "base_url": "https://api.siliconflow.cn/v1",
        }
    )
    resolved = resolved.model_copy(
        update={"experiment": {**resolved.experiment, "llm": llm}}
    )

    runner = build_production_episode_runner(
        episode_id="E-data-root-secret",
        resolved_config=resolved,
        project_root=project_root,
        data_root=data_root,
    )

    provider = runner.runner.dependencies.operator.provider
    assert isinstance(provider, RuntimeSecretProvider)
    assert provider.runtime_secret.full_api_key == "sf-data-root-secret-123456"


def test_production_runner_rejects_unreachable_manual_tasks_instead_of_empty_queues(
    tmp_path: Path,
) -> None:
    from backend.app.api.production_runner import build_production_episode_runner
    from backend.app.sim.task_generation import TaskGenerationError

    scenario, experiment, dataset = load_demo_config(
        FIXTURE_DIR / "demo_valid.yaml",
        overrides={
            "scenario": {
                "layout": {"mode": "manual", "num_cranes": 1},
                "cranes": [
                    {
                        "crane_id": "C1",
                        "model_id": "generic_flat_top_55m",
                        "base": [0, 0, 0],
                        "mast_height_m": 40,
                        "theta_init_deg": 0,
                        "slew": {"mode": "continuous"},
                    },
                ],
                "site": {
                    "boundary": {
                        "x_min": -100,
                        "x_max": 100,
                        "y_min": -100,
                        "y_max": 100,
                        "z_min": 0,
                        "z_max": 80,
                    },
                    "forbidden_zones": [],
                    "material_zones": [
                        {
                            "zone_id": "ground",
                            "type": "box",
                            "center": [12, 0, 0],
                            "size": [6, 6, 0.4],
                            "surface_z_m": 0,
                            "load_types": ["rebar_bundle"],
                        }
                    ],
                    "work_zones": [
                        {
                            "zone_id": "too_high_floor",
                            "type": "box",
                            "center": [18, 0, 39],
                            "size": [6, 6, 0.4],
                            "surface_z_m": 39,
                            "accepted_load_types": ["rebar_bundle"],
                        }
                    ],
                },
                "tasks": {
                    "generation_mode": "manual",
                    "manual_tasks": [
                        {
                            "task_id": "T_TOO_HIGH",
                            "crane_id": "C1",
                            "task_type": "easy_task",
                            "pickup_zone_id": "ground",
                            "dropoff_zone_id": "too_high_floor",
                            "load_type": "rebar_bundle",
                            "priority": "medium",
                        }
                    ],
                    "num_tasks_per_crane": 1,
                },
            },
            "experiment": {
                "llm": {
                    "provider": "mock",
                    "model": "mock-production",
                    "api_key_env": None,
                    "api_key": None,
                },
                "output": {"run_root": str(tmp_path)},
            },
        },
    )
    assert experiment is not None
    resolved = resolve_config(scenario, experiment, dataset)

    with pytest.raises(TaskGenerationError) as exc_info:
        build_production_episode_runner(
            episode_id="E-unreachable",
            resolved_config=resolved,
        )

    assert exc_info.value.reason == "point_height_unreachable"
    assert exc_info.value.details["task_id"] == "T_TOO_HIGH"


def test_multifloor_construction_demo_generates_visible_reachable_tasks() -> None:
    from backend.app.api.production_runner import scenario_config_from_resolved
    from backend.app.sim.layout_geometry import horizontal_distance
    from backend.app.sim.task_generation import generate_task_queues

    scenario, experiment, dataset = load_demo_config(
        Path("configs/multifloor_construction_demo.yaml")
    )
    assert experiment is not None
    resolved = resolve_config(scenario, experiment, dataset)
    resolved_scenario = scenario_config_from_resolved(resolved)
    cranes = [
        CraneConfig.model_validate(crane)
        for crane in resolved.layout.resolved_cranes
    ]

    result = generate_task_queues(
        resolved_scenario,
        cranes,
        seed=int(resolved.seeds.task),
    )

    assert len(result.tasks) >= 8
    assert {queue.crane_id: len(queue.tasks) for queue in result.queues} == {
        "C1": 2,
        "C2": 2,
        "C3": 2,
        "C4": 2,
    }
    crane_by_id = {crane.crane_id: crane for crane in cranes}
    assert {
        task.dropoff.floor_id
        for task in result.tasks
        if task.dropoff.floor_id is not None
    } >= {"floor_03", "floor_05", "roof"}
    visible_slew_deltas: list[float] = []
    for task in result.tasks:
        crane = crane_by_id[task.crane_id]
        for point in (task.pickup, task.dropoff):
            radius = horizontal_distance(crane.base, point.as_xyz())
            assert crane.trolley_r_min_m <= radius <= crane.trolley_r_max_m
            assert crane.hook_h_min_world_m <= point.hook_target_z_m <= crane.hook_h_max_world_m
        pickup_angle = math.atan2(
            task.pickup.y - crane.base[1],
            task.pickup.x - crane.base[0],
        )
        dropoff_angle = math.atan2(
            task.dropoff.y - crane.base[1],
            task.dropoff.x - crane.base[0],
        )
        visible_slew_deltas.append(
            abs(math.atan2(math.sin(dropoff_angle - pickup_angle), math.cos(dropoff_angle - pickup_angle)))
        )
    assert max(visible_slew_deltas) >= math.radians(35)


def test_production_runner_multifloor_demo_records_task_payloads(tmp_path: Path) -> None:
    from backend.app.api.production_runner import build_production_episode_runner

    scenario, experiment, dataset = load_demo_config(
        Path("configs/multifloor_construction_demo.yaml"),
        overrides={
            "experiment": {
                "sim": {
                    "duration_s": 8.0,
                    "min_duration_s": 0.0,
                    "stop_when_all_tasks_done": False,
                    "llm_decision_interval_s": 0.5,
                },
                "llm": {
                    "provider": "mock",
                    "model": "mock-multifloor",
                    "api_key_env": None,
                    "api_key": None,
                    "timeout_s": 1,
                    "max_retries": 0,
                },
                "output": {"run_root": str(tmp_path)},
            },
        },
    )
    assert experiment is not None
    resolved = resolve_config(scenario, experiment, dataset)
    runner = build_production_episode_runner(
        episode_id="E-multifloor",
        resolved_config=resolved,
    )

    for _ in range(3):
        result = runner.run_one_frame()
        assert result.status is EpisodeStatus.RUNNING

    runner.stop("test complete")
    runner.run_one_frame()

    run_dir = tmp_path / "E-multifloor"
    summary = json.loads((run_dir / "metadata" / "episode_summary.json").read_text(encoding="utf-8"))
    assert summary["num_tasks_total"] >= 8
    frames = [
        json.loads(line)
        for line in (run_dir / "visual" / "frames.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert frames
    assert any(frame["tasks"] for frame in frames)
    manifest = json.loads((run_dir / "visual" / "episode_manifest.json").read_text(encoding="utf-8"))
    assert manifest["site"]["buildings"]
    assert len(manifest["material_zones"]) >= 2
    assert len(manifest["work_zones"]) >= 3


def test_production_runner_warm_stop_records_and_broadcasts_terminal_frame(
    tmp_path: Path,
) -> None:
    from backend.app.api.production_runner import build_production_episode_runner

    class RecordingWebSocket:
        def __init__(self) -> None:
            self.frames: list[Any] = []

        def broadcast_sim_frame_if_enabled(self, *, episode_id: str, frame: Any) -> None:
            self.frames.append(frame)

    websocket = RecordingWebSocket()
    runner = build_production_episode_runner(
        episode_id="E-warm-stop",
        resolved_config=_production_smoke_config(tmp_path),
        websocket=websocket,
    )
    first = runner.run_one_frame()
    assert first.status is EpisodeStatus.RUNNING

    runner.stop("api stop")
    stopped = runner.run_one_frame()

    assert stopped.status is EpisodeStatus.STOPPED_BY_USER
    run_dir = tmp_path / "E-warm-stop"
    frames = [
        json.loads(line)
        for line in (run_dir / "visual" / "frames.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert frames[-1]["episode_status"] == "stopped_by_user"
    assert websocket.frames[-1].episode_status == "stopped_by_user"
