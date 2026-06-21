from __future__ import annotations

import asyncio
import io
import json
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app.api.desktop_llm_settings import save_provider_secret
from backend.app.main import create_app
from backend.app.schemas.enums import LLMProviderName
from backend.app.schemas.scheduler import EpisodeStatus
from backend.app.tests.test_config_schema import FIXTURE_DIR


@pytest.fixture(autouse=True)
def _local_deepseek_secret_and_fake_provider(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.app.sim.llm_provider import DeepSeekProvider

    monkeypatch.chdir(tmp_path)
    save_provider_secret(
        tmp_path,
        provider=LLMProviderName.DEEPSEEK,
        api_key="sk-test-secret-123456",
    )

    def fake_init(self, *, http_client=None):
        self._http_client = http_client or _FakeChatHTTPClient()

    monkeypatch.setattr(DeepSeekProvider, "__init__", fake_init)


class _FakeChatHTTPResponse:
    status_code = 200

    def json(self) -> dict:
        return {
            "id": "fake-chat-response",
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "left_joystick": {
                                    "slew": {"direction": "left", "gear": 1},
                                    "trolley": {"direction": "out", "gear": 1},
                                },
                                "right_joystick": {
                                    "hoist": {"direction": "neutral", "gear": 0}
                                },
                                "deadman_pressed": True,
                                "emergency_stop": False,
                                "horn": False,
                                "command_duration_s": 1.0,
                                "task_action": "none",
                                "attention_target": "current_target",
                                "confidence": 0.75,
                                "reason": "test fake provider command",
                            },
                            ensure_ascii=False,
                        )
                    }
                }
            ],
            "usage": {
                "prompt_tokens": 1,
                "completion_tokens": 1,
                "total_tokens": 2,
            },
        }


class _FakeChatHTTPClient:
    def post(self, url: str, *, headers: dict, json: dict, timeout: float):
        assert headers.get("Authorization") == "Bearer sk-test-secret-123456"
        return _FakeChatHTTPResponse()


def _short_payload(
    tmp_path: Path,
    *,
    runner: str | None = None,
    autostart: bool = True,
) -> dict:
    payload = {
        "config_path": str(FIXTURE_DIR / "demo_valid.yaml"),
        "episode_id": f"E-api-{runner or 'default'}",
        "autostart": autostart,
        "overrides": {
            "scenario": {
                "layout": {
                    "num_cranes": 2,
                    "overlap_level": "high",
                    "coverage_target": "dense_overlap",
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
                    "duration_s": 0.3,
                    "min_duration_s": 0.0,
                    "stop_when_all_tasks_done": False,
                    "completion_cooldown_s": 0.0,
                    "llm_decision_interval_s": 0.2,
                },
                "llm": {
                    "provider": "deepseek",
                    "model": "deepseek-chat",
                    "base_url": "https://api.deepseek.com/v1",
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
    service = client.app.state.episode_service
    handle = service.get_handle("E-api-default")
    while handle.status is EpisodeStatus.RUNNING:
        service._advance_handle_once(handle)
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


def test_start_episode_runner_local_is_rejected_for_public_api(tmp_path: Path) -> None:
    client = TestClient(create_app())

    response = client.post("/episodes/start", json=_short_payload(tmp_path, runner="local"))

    assert response.status_code == 422
    payload = response.json()
    assert payload["code"] == "M_E_CONFIG_INVALID"
    assert "production" in payload["message"]


def test_start_episode_runner_local_never_records_site_payload_via_public_api(
    tmp_path: Path,
) -> None:
    client = TestClient(create_app())

    response = client.post("/episodes/start", json=_short_payload(tmp_path, runner="local"))

    assert response.status_code == 422
    assert not (tmp_path / "E-api-local").exists()


def test_start_episode_default_production_broadcasts_live_sim_frame(
    tmp_path: Path,
) -> None:
    client = TestClient(create_app())
    manager = client.app.state.websocket_manager
    capture = _CaptureWebSocket()

    response = client.post(
        "/episodes/start",
        json=_short_payload(tmp_path, autostart=False),
    )

    assert response.status_code == 200, response.text
    episode_id = response.json()["data"]["episode_id"]

    async def scenario() -> None:
        await manager.connect(episode_id, capture)
        service = client.app.state.episode_service
        handle = service.get_handle(episode_id)
        handle.worker_stop.set()
        service._advance_handle_once(handle)
        deadline = asyncio.get_running_loop().time() + 1.0
        while not capture.sent and asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(0.01)

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
