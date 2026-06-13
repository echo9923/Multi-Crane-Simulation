from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from backend.app.api.episode_service import EpisodeHandle, EpisodeService
from backend.app.main import create_app
from backend.app.schemas.recorder import EpisodeSummary, SimFrame, SimFrameWeather
from backend.app.schemas.scheduler import EpisodeStatus


class NoopRunner:
    episode_status = EpisodeStatus.RUNNING

    def run_one_frame(self):
        raise AssertionError("query tests must not advance the runner")

    def stop(self, reason: str = "stopped_by_user") -> None:
        raise AssertionError("query tests must not stop the runner")


def _client_with_service(service: EpisodeService) -> TestClient:
    app = create_app()
    app.state.episode_service = service
    return TestClient(app)


def _service() -> EpisodeService:
    return EpisodeService(runner_factory=lambda **kwargs: NoopRunner())


def _frame(frame_index: int = 2) -> SimFrame:
    return SimFrame(
        episode_id="E-query",
        scenario_id="scenario-a",
        frame=frame_index,
        time_s=float(frame_index) * 0.5,
        episode_status="running",
        cranes=[],
        pairs=[],
        tasks=[],
        weather=SimFrameWeather(wind_speed_m_s=1.0, visibility="good"),
        events=[],
    )


def _summary_payload(**overrides: Any) -> dict[str, Any]:
    payload = {
        "episode_id": "E-query",
        "scenario_id": "scenario-a",
        "episode_status": "completed",
        "duration_s": 1.0,
        "num_cranes": 2,
        "num_tasks_total": 1,
        "num_tasks_completed": 1,
        "num_tasks_failed": 0,
        "task_completion_rate": 1.0,
        "deadline_missed_count": 0,
        "overtime_mean_s": 0.0,
        "risk_frame_ratio_by_level": {"safe": 1.0},
        "near_miss_count": 0,
        "collision_count": 0,
        "high_risk_duration_s": 0.0,
        "num_llm_calls": 0,
        "llm_invalid_output_count": 0,
        "llm_timeout_count": 0,
        "cache_hit_count": 0,
        "operator_profile_distribution": {},
        "ignored_risk_hint_count": 0,
        "emergency_stop_count": 0,
        "forbidden_zone_violation_count": 0,
        "overlap_zone_shared_count": 0,
        "has_nan": False,
        "has_inf": False,
        "replay_available": False,
    }
    payload.update(overrides)
    return EpisodeSummary.model_validate(payload).model_dump(mode="json")


def _run_dir(tmp_path: Path) -> Path:
    run_dir = tmp_path / "runs" / "E-query"
    for child in ["config", "metadata", "logs", "data", "visual", "replay"]:
        (run_dir / child).mkdir(parents=True, exist_ok=True)
    (run_dir / "metadata" / "episode_summary.json").write_text(
        json.dumps(_summary_payload()),
        encoding="utf-8",
    )
    (run_dir / "visual" / "episode_manifest.json").write_text(
        json.dumps({"episode_id": "E-query", "frame_count": 2}),
        encoding="utf-8",
    )
    (run_dir / "visual" / "frames.jsonl").write_text(
        "\n".join(
            [
                json.dumps(_frame(1).model_dump(mode="json")),
                json.dumps(_frame(2).model_dump(mode="json")),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (run_dir / "logs" / "events.jsonl").write_text("{}", encoding="utf-8")
    (run_dir / "data" / "placeholder.txt").write_text("data", encoding="utf-8")
    return run_dir


def test_get_state_returns_registry_runtime_fields(tmp_path: Path) -> None:
    service = _service()
    service.handles["E-query"] = EpisodeHandle(
        episode_id="E-query",
        runner=NoopRunner(),
        run_dir=tmp_path,
        status=EpisodeStatus.RUNNING,
        frame_index=2,
        time_s=1.0,
        last_frame=_frame(2),
    )
    client = _client_with_service(service)

    response = client.get("/episodes/E-query/state")

    assert response.status_code == 200
    payload = response.json()
    assert payload["code"] == 0
    assert payload["data"]["episode_id"] == "E-query"
    assert payload["data"]["frame_index"] == 2
    assert payload["data"]["time_s"] == 1.0
    assert SimFrame.model_validate(payload["data"]["last_frame"]).frame == 2


def test_get_state_missing_episode_uses_uniform_error() -> None:
    client = _client_with_service(_service())

    response = client.get("/episodes/missing/state")

    assert response.status_code == 404
    assert response.json()["code"] == "M_E_EPISODE_NOT_FOUND"


def test_get_summary_reads_episode_summary_file(tmp_path: Path) -> None:
    run_dir = _run_dir(tmp_path)
    service = _service()
    service.handles["E-query"] = EpisodeHandle(
        episode_id="E-query",
        runner=NoopRunner(),
        run_dir=run_dir,
        status=EpisodeStatus.COMPLETED,
    )
    client = _client_with_service(service)

    response = client.get("/episodes/E-query/summary")

    assert response.status_code == 200
    payload = response.json()
    assert payload["code"] == 0
    assert payload["data"]["episode_id"] == "E-query"
    assert payload["data"]["episode_status"] == "completed"


def test_get_summary_missing_file_returns_uniform_error(tmp_path: Path) -> None:
    run_dir = _run_dir(tmp_path)
    (run_dir / "metadata" / "episode_summary.json").unlink()
    service = _service()
    service.handles["E-query"] = EpisodeHandle(
        episode_id="E-query",
        runner=NoopRunner(),
        run_dir=run_dir,
        status=EpisodeStatus.COMPLETED,
    )
    client = _client_with_service(service)

    response = client.get("/episodes/E-query/summary")

    assert response.status_code == 404
    assert response.json()["code"] == "M_E_SUMMARY_NOT_FOUND"


def test_get_state_falls_back_to_last_frame_from_run_dir(tmp_path: Path) -> None:
    run_dir = _run_dir(tmp_path)
    service = _service()
    service.handles["E-query"] = EpisodeHandle(
        episode_id="E-query",
        runner=NoopRunner(),
        run_dir=run_dir,
        status=EpisodeStatus.COMPLETED,
    )
    client = _client_with_service(service)

    response = client.get("/episodes/E-query/state")

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["frame_index"] == 2
    assert payload["time_s"] == 1.0
    assert payload["last_frame"]["frame"] == 2


def test_download_returns_zip_and_honors_include_logs_false(tmp_path: Path) -> None:
    run_dir = _run_dir(tmp_path)
    service = _service()
    service.handles["E-query"] = EpisodeHandle(
        episode_id="E-query",
        runner=NoopRunner(),
        run_dir=run_dir,
        status=EpisodeStatus.COMPLETED,
    )
    client = _client_with_service(service)

    response = client.get("/episodes/E-query/download?include_logs=false")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    archive_path = tmp_path / "download.zip"
    archive_path.write_bytes(response.content)
    with zipfile.ZipFile(archive_path) as archive:
        names = set(archive.namelist())

    assert "metadata/episode_summary.json" in names
    assert "visual/episode_manifest.json" in names
    assert "data/placeholder.txt" in names
    assert "logs/events.jsonl" not in names
    assert all(not name.startswith("/") and ".." not in Path(name).parts for name in names)
