from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from fastapi.testclient import TestClient

from backend.app.main import create_app
from backend.app.schemas.scheduler import EpisodeStatus, FrameStepResult
from backend.app.tests.test_config_schema import FIXTURE_DIR


@dataclass
class FakeRunner:
    status: EpisodeStatus = EpisodeStatus.RUNNING
    frame_index: int = 0
    time_s: float = 0.0
    stop_reason: str | None = None
    run_one_frame_calls: int = 0

    @property
    def episode_status(self) -> EpisodeStatus:
        return self.status

    def run_one_frame(self) -> FrameStepResult:
        self.run_one_frame_calls += 1
        if self.stop_reason is not None:
            self.status = EpisodeStatus.STOPPED_BY_USER
        elif self.status is EpisodeStatus.RUNNING:
            self.frame_index += 1
            self.time_s += 0.5
        return FrameStepResult(
            frame_index=self.frame_index,
            time_s=self.time_s,
            status=self.status,
        )

    def stop(self, reason: str = "stopped_by_user") -> None:
        self.stop_reason = reason


class FakeRunnerWithRunDir(FakeRunner):
    def __init__(self, run_dir: Path) -> None:
        super().__init__()
        self.recorder = SimpleNamespace(run_dir=run_dir)


class FakeRunnerFactory:
    def __init__(self) -> None:
        self.created: list[dict[str, Any]] = []
        self.fail_next = False

    def __call__(self, *, episode_id: str, resolved_config: Any) -> FakeRunner:
        if self.fail_next:
            raise RuntimeError("runner boom")
        runner = FakeRunner()
        self.created.append(
            {
                "episode_id": episode_id,
                "resolved_config_hash": resolved_config.resolved_config_hash,
                "runner": runner,
            }
        )
        return runner


def _client_with_factory(factory: FakeRunnerFactory) -> TestClient:
    app = create_app()
    app.state.runner_factory = factory
    return TestClient(app)


def _start_payload(episode_id: str = "E-life", *, autostart: bool = False) -> dict[str, Any]:
    return {
        "config_path": str(FIXTURE_DIR / "demo_valid.yaml"),
        "episode_id": episode_id,
        "autostart": autostart,
    }


def test_start_episode_creates_registry_handle_with_explicit_id() -> None:
    factory = FakeRunnerFactory()
    client = _client_with_factory(factory)

    response = client.post("/episodes/start", json=_start_payload())

    assert response.status_code == 200
    payload = response.json()
    assert payload["code"] == 0
    assert payload["data"]["episode_id"] == "E-life"
    assert payload["data"]["status"] == "running"
    assert factory.created[0]["episode_id"] == "E-life"

    service = client.app.state.episode_service
    handle = service.get_handle("E-life")
    assert handle.episode_id == "E-life"
    assert handle.runner is factory.created[0]["runner"]


def test_start_episode_prefers_runner_reported_run_dir(tmp_path: Path) -> None:
    actual_run_dir = tmp_path / "runs" / "E-life"

    def factory(**kwargs: Any) -> FakeRunnerWithRunDir:
        return FakeRunnerWithRunDir(actual_run_dir)

    app = create_app()
    app.state.runner_factory = factory
    client = TestClient(app)

    response = client.post("/episodes/start", json=_start_payload())

    assert response.status_code == 200
    assert response.json()["data"]["run_dir"] == str(actual_run_dir)
    handle = client.app.state.episode_service.get_handle("E-life")
    assert handle.run_dir == actual_run_dir


def test_start_episode_default_runner_autostart_exposes_run_dir_and_frame(
    tmp_path: Path,
) -> None:
    client = TestClient(create_app())

    response = client.post(
        "/episodes/start",
        json={
            **_start_payload("E-default", autostart=True),
            "overrides": {
                "experiment": {
                    "output": {
                        "run_root": str(tmp_path),
                    },
                },
            },
        },
    )

    assert response.status_code == 200
    data = response.json()["data"]
    run_dir = Path(data["run_dir"])
    assert run_dir.name == "E-default"
    frame_path = run_dir / "visual" / "frames.jsonl"
    assert frame_path.is_file()

    state = client.get("/episodes/E-default/state")
    assert state.status_code == 200
    assert state.json()["data"]["last_frame"]["type"] == "sim_frame"


def test_autostart_false_does_not_advance_runner() -> None:
    factory = FakeRunnerFactory()
    client = _client_with_factory(factory)

    response = client.post("/episodes/start", json=_start_payload(autostart=False))

    assert response.status_code == 200
    runner = factory.created[0]["runner"]
    assert runner.run_one_frame_calls == 0


def test_autostart_true_advances_runner_once() -> None:
    factory = FakeRunnerFactory()
    client = _client_with_factory(factory)

    response = client.post("/episodes/start", json=_start_payload(autostart=True))

    assert response.status_code == 200
    runner = factory.created[0]["runner"]
    assert runner.run_one_frame_calls == 1
    handle = client.app.state.episode_service.get_handle("E-life")
    assert handle.frame_index == 1
    assert handle.time_s == 0.5


def test_pause_resume_stop_lifecycle_flow() -> None:
    factory = FakeRunnerFactory()
    client = _client_with_factory(factory)
    client.post("/episodes/start", json=_start_payload())

    pause = client.post("/episodes/E-life/pause")
    assert pause.status_code == 200
    assert pause.json()["data"]["accepted"] is True
    assert pause.json()["data"]["status"] == "paused"
    assert client.app.state.episode_service.get_handle("E-life").paused is True

    resume = client.post("/episodes/E-life/resume")
    assert resume.status_code == 200
    assert resume.json()["data"]["previous_status"] == "paused"
    assert resume.json()["data"]["status"] == "running"
    assert client.app.state.episode_service.get_handle("E-life").paused is False

    stop = client.post("/episodes/E-life/stop")
    assert stop.status_code == 200
    assert stop.json()["data"]["status"] == "stopped_by_user"
    assert factory.created[0]["runner"].stop_reason == "api stop"


def test_lifecycle_returns_not_found_for_missing_episode() -> None:
    client = _client_with_factory(FakeRunnerFactory())

    response = client.post("/episodes/missing/pause")

    assert response.status_code == 404
    assert response.json()["code"] == "M_E_EPISODE_NOT_FOUND"


def test_terminal_episode_rejects_pause_and_resume() -> None:
    factory = FakeRunnerFactory()
    client = _client_with_factory(factory)
    client.post("/episodes/start", json=_start_payload())
    handle = client.app.state.episode_service.get_handle("E-life")
    handle.status = EpisodeStatus.COMPLETED

    pause = client.post("/episodes/E-life/pause")
    resume = client.post("/episodes/E-life/resume")

    assert pause.status_code == 409
    assert pause.json()["code"] == "M_E_INVALID_EPISODE_STATE"
    assert resume.status_code == 409
    assert resume.json()["code"] == "M_E_INVALID_EPISODE_STATE"


def test_duplicate_episode_id_is_conflict_and_does_not_overwrite_handle() -> None:
    factory = FakeRunnerFactory()
    client = _client_with_factory(factory)
    client.post("/episodes/start", json=_start_payload())
    first_handle = client.app.state.episode_service.get_handle("E-life")

    response = client.post("/episodes/start", json=_start_payload())

    assert response.status_code == 409
    assert response.json()["code"] == "M_E_INVALID_EPISODE_STATE"
    assert client.app.state.episode_service.get_handle("E-life") is first_handle
    assert len(factory.created) == 1


def test_runner_factory_failure_does_not_register_episode() -> None:
    factory = FakeRunnerFactory()
    factory.fail_next = True
    client = _client_with_factory(factory)

    response = client.post("/episodes/start", json=_start_payload())

    assert response.status_code == 500
    assert response.json()["code"] == "M_E_EPISODE_START_FAILED"
    assert "E-life" not in client.app.state.episode_service.handles
