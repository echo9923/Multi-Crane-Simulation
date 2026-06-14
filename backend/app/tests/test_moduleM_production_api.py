from __future__ import annotations

import io
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.main import create_app
from backend.app.tests.test_config_schema import FIXTURE_DIR


def _short_payload(tmp_path: Path, *, runner: str | None = None) -> dict:
    payload = {
        "config_path": str(FIXTURE_DIR / "demo_valid.yaml"),
        "episode_id": f"E-api-{runner or 'default'}",
        "autostart": True,
        "overrides": {
            "scenario": {
                "layout": {"num_cranes": 2},
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
                    "duration_s": 0.3,
                    "min_duration_s": 0.0,
                    "stop_when_all_tasks_done": False,
                    "completion_cooldown_s": 0.0,
                    "llm_decision_interval_s": 0.2,
                },
                "llm": {
                    "provider": "mock",
                    "model": "mock-api",
                    "api_key_env": None,
                    "api_key": None,
                    "timeout_s": 1,
                    "max_retries": 0,
                    "context": {"history_mode": "none", "recent_decisions_full": 0},
                },
                "output": {"run_root": str(tmp_path)},
            },
        },
    }
    if runner is not None:
        payload["runner"] = runner
    return payload


def test_start_episode_defaults_to_production_runner_and_downloads_full_archive(
    tmp_path: Path,
) -> None:
    client = TestClient(create_app())

    response = client.post("/episodes/start", json=_short_payload(tmp_path))

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    run_dir = Path(data["run_dir"])
    assert run_dir.name == "E-api-default"
    assert (run_dir / "data" / "trajectories.parquet").is_file()
    assert (run_dir / "logs" / "commands.jsonl").is_file()
    assert (run_dir / "metadata" / "episode_metadata.json").is_file()
    assert (run_dir / "visual" / "frames.jsonl").is_file()

    archive = client.get("/episodes/E-api-default/download")

    assert archive.status_code == 200
    with zipfile.ZipFile(io.BytesIO(archive.content)) as zf:
        names = set(zf.namelist())
    assert "visual/frames.jsonl" in names
    assert "metadata/episode_metadata.json" in names
    assert "logs/commands.jsonl" in names
    assert "data/trajectories.parquet" in names


def test_start_episode_runner_local_keeps_fast_smoke_runner(tmp_path: Path) -> None:
    client = TestClient(create_app())

    response = client.post("/episodes/start", json=_short_payload(tmp_path, runner="local"))

    assert response.status_code == 200, response.text
    run_dir = Path(response.json()["data"]["run_dir"])
    assert (run_dir / "visual" / "frames.jsonl").is_file()
    assert not (run_dir / "data" / "trajectories.parquet").is_file()


def test_start_episode_default_production_broadcasts_live_sim_frame(
    tmp_path: Path,
) -> None:
    client = TestClient(create_app())
    manager = client.app.state.websocket_manager
    capture = _CaptureWebSocket()

    response = client.post("/episodes/start", json=_short_payload(tmp_path))

    assert response.status_code == 200, response.text
    episode_id = response.json()["data"]["episode_id"]

    import asyncio

    async def scenario() -> None:
        await manager.connect(episode_id, capture)
        service = client.app.state.episode_service
        handle = service.get_handle(episode_id)
        service._advance_handle_once(handle)

    asyncio.run(scenario())

    assert capture.sent
    assert capture.sent[0]["type"] == "sim_frame"
    assert capture.sent[0]["data"]["episode_id"] == episode_id
    assert capture.sent[0]["data"].get("offline_labels") is None


class _CaptureWebSocket:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def accept(self) -> None:
        return None

    async def send_json(self, payload: dict) -> None:
        self.sent.append(payload)
