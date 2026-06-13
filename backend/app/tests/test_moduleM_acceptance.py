from __future__ import annotations

import asyncio
import json
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from backend.app.api.episode_service import EpisodeHandle, EpisodeService
from backend.app.api.websocket import WebSocketConnectionManager
from backend.app.main import create_app
from backend.app.schemas.recorder import EpisodeSummary, SimFrame, SimFrameWeather
from backend.app.schemas.scheduler import EpisodeStatus, FrameStepResult
from backend.app.tests.test_config_schema import FIXTURE_DIR


@dataclass
class AcceptanceRunner:
    episode_status: EpisodeStatus = EpisodeStatus.RUNNING
    frame_index: int = 0
    time_s: float = 0.0
    stop_reason: str | None = None

    def run_one_frame(self) -> FrameStepResult:
        if self.stop_reason is not None:
            self.episode_status = EpisodeStatus.STOPPED_BY_USER
        elif self.episode_status is EpisodeStatus.RUNNING:
            self.frame_index += 1
            self.time_s += 0.5
        return FrameStepResult(
            frame_index=self.frame_index,
            time_s=self.time_s,
            status=self.episode_status,
        )

    def stop(self, reason: str = "stopped_by_user") -> None:
        self.stop_reason = reason


class CaptureWebSocket:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def accept(self) -> None:
        pass

    async def send_json(self, payload: dict) -> None:
        self.sent.append(payload)


def _frame() -> SimFrame:
    return SimFrame(
        episode_id="E-accept",
        frame=1,
        time_s=0.5,
        episode_status="running",
        cranes=[],
        pairs=[],
        tasks=[],
        weather=SimFrameWeather(wind_speed_m_s=1.0, visibility="good"),
        events=[],
    )


def _summary_payload() -> dict[str, Any]:
    return EpisodeSummary(
        episode_id="E-accept",
        scenario_id=None,
        episode_status="completed",
        duration_s=1.0,
        num_cranes=2,
        num_tasks_total=1,
        num_tasks_completed=1,
        num_tasks_failed=0,
        task_completion_rate=1.0,
        deadline_missed_count=0,
        overtime_mean_s=0.0,
        risk_frame_ratio_by_level={"safe": 1.0},
        near_miss_count=0,
        collision_count=0,
        high_risk_duration_s=0.0,
        num_llm_calls=0,
        llm_invalid_output_count=0,
        llm_timeout_count=0,
        cache_hit_count=0,
        operator_profile_distribution={},
        ignored_risk_hint_count=0,
        emergency_stop_count=0,
        forbidden_zone_violation_count=0,
        overlap_zone_shared_count=0,
        has_nan=False,
        has_inf=False,
        replay_available=False,
    ).model_dump(mode="json")


def _run_dir(tmp_path: Path) -> Path:
    run_dir = tmp_path / "runs" / "E-accept"
    for name in ["config", "metadata", "logs", "data", "visual", "replay"]:
        (run_dir / name).mkdir(parents=True)
    (run_dir / "metadata" / "episode_summary.json").write_text(
        json.dumps(_summary_payload()),
        encoding="utf-8",
    )
    (run_dir / "visual" / "episode_manifest.json").write_text(
        json.dumps({"episode_id": "E-accept"}),
        encoding="utf-8",
    )
    (run_dir / "visual" / "frames.jsonl").write_text(
        json.dumps(_frame().model_dump(mode="json")) + "\n",
        encoding="utf-8",
    )
    return run_dir


def _client(tmp_path: Path) -> tuple[TestClient, list[AcceptanceRunner]]:
    runners: list[AcceptanceRunner] = []

    def factory(**kwargs: Any) -> AcceptanceRunner:
        runner = AcceptanceRunner()
        runners.append(runner)
        return runner

    app = create_app()
    app.state.runner_factory = factory
    app.state.dataset_root = tmp_path / "datasets"
    return TestClient(app), runners


def test_openapi_contains_all_module_m_rest_paths(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)

    paths = client.get("/openapi.json").json()["paths"]

    for path in [
        "/health",
        "/scenarios/validate",
        "/episodes/start",
        "/episodes/{episode_id}/pause",
        "/episodes/{episode_id}/resume",
        "/episodes/{episode_id}/stop",
        "/episodes/{episode_id}/state",
        "/episodes/{episode_id}/summary",
        "/episodes/{episode_id}/download",
        "/datasets",
        "/datasets/{dataset_id}/summary",
    ]:
        assert path in paths


def test_api_to_runner_to_query_and_download_flow(tmp_path: Path) -> None:
    client, runners = _client(tmp_path)
    response = client.post(
        "/episodes/start",
        json={
            "config_path": str(FIXTURE_DIR / "demo_valid.yaml"),
            "episode_id": "E-accept",
            "autostart": True,
        },
    )

    assert response.status_code == 200
    assert runners[0].frame_index == 1

    service = client.app.state.episode_service
    handle = service.get_handle("E-accept")
    handle.run_dir = _run_dir(tmp_path)
    handle.last_frame = _frame()

    state = client.get("/episodes/E-accept/state").json()["data"]
    assert state["frame_index"] == 1
    assert SimFrame.model_validate(state["last_frame"]).episode_id == "E-accept"

    summary = client.get("/episodes/E-accept/summary")
    assert summary.status_code == 200
    assert summary.json()["data"]["episode_status"] == "completed"

    download = client.get("/episodes/E-accept/download")
    assert download.status_code == 200
    archive_path = tmp_path / "download.zip"
    archive_path.write_bytes(download.content)
    with zipfile.ZipFile(archive_path) as archive:
        assert "metadata/episode_summary.json" in archive.namelist()


def test_websocket_manager_multi_client_and_schema_contract() -> None:
    manager = WebSocketConnectionManager()
    first = CaptureWebSocket()
    second = CaptureWebSocket()

    async def scenario() -> None:
        await manager.connect("E-accept", first)
        await manager.connect("E-accept", second)
        await manager.broadcast_sim_frame("E-accept", _frame())

    asyncio.run(scenario())

    assert first.sent == second.sent
    payload = first.sent[0]
    assert payload["type"] == "sim_frame"
    assert SimFrame.model_validate(payload["data"]).offline_labels is None


def test_repeated_state_requests_do_not_advance_runner(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    service = EpisodeService(runner_factory=lambda **kwargs: AcceptanceRunner())
    runner = AcceptanceRunner()
    service.handles["E-accept"] = EpisodeHandle(
        episode_id="E-accept",
        runner=runner,
        run_dir=None,
        status=EpisodeStatus.RUNNING,
        frame_index=3,
        time_s=1.5,
    )
    client.app.state.episode_service = service

    for _ in range(20):
        response = client.get("/episodes/E-accept/state")
        assert response.status_code == 200

    assert runner.frame_index == 0


def test_acceptance_error_paths_are_uniform(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)

    responses = [
        client.get("/episodes/missing/state"),
        client.get("/datasets/missing/summary"),
        client.post("/scenarios/validate", json={"config_path": "missing.yaml"}),
    ]

    for response in responses:
        assert response.status_code in {404, 422}
        payload = response.json()
        assert payload["code"] != 0
        assert payload["data"] is None
        assert payload["message"]
        assert isinstance(payload["details"], dict)
