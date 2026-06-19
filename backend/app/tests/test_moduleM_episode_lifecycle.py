from __future__ import annotations

import json
import threading
import time
import shutil
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from backend.app.main import create_app
from backend.app.schemas.enums import RuntimeMode
from backend.app.schemas.scheduler import EpisodeStatus, FrameStepResult
from backend.app.tests.test_config_schema import FIXTURE_DIR, load_fixture


@pytest.fixture(autouse=True)
def _deepseek_env_for_demo_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test-secret-123456")


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
                "resolved_config": resolved_config,
                "resolved_config_hash": resolved_config.resolved_config_hash,
                "runner": runner,
            }
        )
        return runner


class RootAwareRunnerFactory(FakeRunnerFactory):
    def __call__(
        self,
        *,
        episode_id: str,
        resolved_config: Any,
        project_root: Path | None = None,
        data_root: Path | None = None,
    ) -> FakeRunner:
        runner = FakeRunner()
        self.created.append(
            {
                "episode_id": episode_id,
                "resolved_config": resolved_config,
                "project_root": project_root,
                "data_root": data_root,
                "runner": runner,
            }
        )
        return runner


class BlockingFirstFrameRunner(FakeRunner):
    def __init__(self) -> None:
        super().__init__()
        self.entered_first_frame = threading.Event()
        self.release_first_frame = threading.Event()

    def run_one_frame(self) -> FrameStepResult:
        if self.run_one_frame_calls == 0:
            self.entered_first_frame.set()
            if not self.release_first_frame.wait(2.0):
                raise RuntimeError("first frame was not released")
        return super().run_one_frame()


class BlockingRunnerFactory(FakeRunnerFactory):
    def __call__(self, *, episode_id: str, resolved_config: Any) -> BlockingFirstFrameRunner:
        runner = BlockingFirstFrameRunner()
        self.created.append(
            {
                "episode_id": episode_id,
                "resolved_config": resolved_config,
                "resolved_config_hash": resolved_config.resolved_config_hash,
                "runner": runner,
            }
        )
        return runner


class InteractiveBlockingRunnerFactory(BlockingRunnerFactory):
    def __call__(self, *, episode_id: str, resolved_config: Any) -> BlockingFirstFrameRunner:
        runner = super().__call__(
            episode_id=episode_id,
            resolved_config=resolved_config,
        )
        runner.runner = SimpleNamespace(
            config=SimpleNamespace(run_mode=RuntimeMode.INTERACTIVE_SERVER)
        )
        return runner


def _client_with_factory(
    factory: FakeRunnerFactory,
    *,
    project_root: Path | None = None,
    data_root: Path | None = None,
) -> TestClient:
    app = create_app()
    app.state.runner_factory = factory
    if project_root is not None:
        app.state.project_root = project_root
    if data_root is not None:
        app.state.data_root = data_root
    return TestClient(app)


def _start_payload(episode_id: str = "E-life", *, autostart: bool = False) -> dict[str, Any]:
    return {
        "config_path": str(FIXTURE_DIR / "demo_valid.yaml"),
        "episode_id": episode_id,
        "autostart": autostart,
    }


def _inline_payload(
    episode_id: str = "E-inline",
    *,
    autostart: bool = False,
) -> dict[str, Any]:
    raw = load_fixture("demo_valid.yaml")
    return {
        "scenario": raw["scenario"],
        "experiment": raw["experiment"],
        "dataset": raw.get("dataset"),
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


def test_start_episode_resolves_relative_config_path_from_project_root(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    data_root = tmp_path / "data"
    configs = project_root / "configs"
    configs.mkdir(parents=True)
    shutil.copyfile(FIXTURE_DIR / "demo_valid.yaml", configs / "demo_valid.yaml")
    factory = FakeRunnerFactory()
    client = _client_with_factory(
        factory,
        project_root=project_root,
        data_root=data_root,
    )

    response = client.post(
        "/episodes/start",
        json={
            "config_path": "configs/demo_valid.yaml",
            "episode_id": "E-relative-path",
            "autostart": False,
            "overrides": {
                "scenario": {
                    "layout": {"mode": "manual", "num_cranes": 1},
                    "cranes": [
                        {
                            "crane_id": "C1",
                            "model_id": "generic_flat_top_55m",
                            "base": [-60.0, -60.0, 0.0],
                            "mast_height_m": 45.0,
                            "theta_init_deg": 0.0,
                            "slew": {"mode": "continuous"},
                        }
                    ],
                }
            },
        },
    )

    assert response.status_code == 200, response.text
    assert response.json()["data"]["episode_id"] == "E-relative-path"
    assert factory.created[0]["resolved_config_hash"]
    assert Path(response.json()["data"]["run_dir"]).is_relative_to(data_root)


def test_start_episode_rejects_relative_config_path_escape(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    data_root = tmp_path / "data"
    outside = tmp_path / "outside"
    project_root.mkdir()
    outside.mkdir()
    shutil.copyfile(FIXTURE_DIR / "demo_valid.yaml", outside / "demo_valid.yaml")
    factory = FakeRunnerFactory()
    client = _client_with_factory(
        factory,
        project_root=project_root,
        data_root=data_root,
    )

    response = client.post(
        "/episodes/start",
        json={
            "config_path": "../outside/demo_valid.yaml",
            "episode_id": "E-escape",
            "autostart": False,
        },
    )

    assert response.status_code == 422
    payload = response.json()
    assert payload["code"] == "M_E_CONFIG_INVALID"
    assert payload["data"] is None
    assert payload["details"]["field_path"] == "config_path"
    assert payload["details"]["source_file"] == "../outside/demo_valid.yaml"
    assert factory.created == []
    assert not hasattr(client.app.state, "episode_service") or (
        "E-escape" not in client.app.state.episode_service.handles
    )


def test_start_episode_passes_project_and_data_roots_to_root_aware_runner_factory(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    data_root = tmp_path / "data"
    project_root.mkdir()
    data_root.mkdir()
    factory = RootAwareRunnerFactory()
    client = _client_with_factory(
        factory,
        project_root=project_root,
        data_root=data_root,
    )

    response = client.post(
        "/episodes/start",
        json={
            **_inline_payload("E-roots"),
            "overrides": {
                "scenario": {
                    "layout": {"mode": "manual", "num_cranes": 1},
                    "cranes": [
                        {
                            "crane_id": "C1",
                            "model_id": "generic_flat_top_55m",
                            "base": [-60.0, -60.0, 0.0],
                            "mast_height_m": 45.0,
                            "theta_init_deg": 0.0,
                            "slew": {"mode": "continuous"},
                        }
                    ],
                }
            },
        },
    )

    assert response.status_code == 200, response.text
    assert factory.created[0]["project_root"] == project_root
    assert factory.created[0]["data_root"] == data_root


def test_start_episode_accepts_inline_config_payload() -> None:
    factory = FakeRunnerFactory()
    client = _client_with_factory(factory)

    response = client.post("/episodes/start", json=_inline_payload())

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["code"] == 0
    assert payload["data"]["episode_id"] == "E-inline"
    assert payload["data"]["status"] == "running"
    assert payload["data"]["resolved_config_hash"]
    assert factory.created[0]["episode_id"] == "E-inline"


def test_start_episode_pydantic_error_redacts_inline_secret_input() -> None:
    factory = FakeRunnerFactory()
    client = _client_with_factory(factory)
    payload = _inline_payload("E-secret-redaction")
    secret = "sk-inline-secret-123456"
    payload["experiment"]["llm"]["api_key"] = secret
    payload["experiment"]["llm"]["api_key_env"] = None
    payload["experiment"]["llm"].pop("model")

    response = client.post("/episodes/start", json=payload)

    assert response.status_code == 422
    assert secret not in response.text
    assert response.json()["code"] == "M_E_CONFIG_INVALID"
    assert factory.created == []


def test_start_episode_uses_desktop_local_llm_secret_summary(tmp_path: Path) -> None:
    from backend.app.api.desktop_llm_settings import save_provider_secret
    from backend.app.schemas.enums import LLMProviderName

    save_provider_secret(
        tmp_path,
        provider=LLMProviderName.SILICONFLOW,
        api_key="sf-local-secret-123456",
    )
    factory = FakeRunnerFactory()
    client = _client_with_factory(factory, project_root=tmp_path)
    payload = _inline_payload("E-local-secret")
    payload["experiment"]["llm"].update(
        {
            "provider": "siliconflow",
            "model": "deepseek-ai/DeepSeek-V4-Flash",
            "api_key": None,
            "api_key_env": "SILICONFLOW_API_KEY",
            "base_url": "https://api.siliconflow.cn/v1",
        }
    )

    response = client.post("/episodes/start", json=payload)

    assert response.status_code == 200, response.text
    provider = factory.created[0]["resolved_config"].provider
    assert provider.provider == "siliconflow"
    assert provider.key_source == "local_settings"
    assert provider.key_env_name is None
    assert provider.key_masked == "sf-l****3456"
    assert "sf-local-secret-123456" not in json.dumps(
        factory.created[0]["resolved_config"].model_dump(mode="json"),
        sort_keys=True,
    )


def test_start_episode_uses_cwd_local_llm_secret_when_project_root_state_is_missing(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from backend.app.api.desktop_llm_settings import save_provider_secret
    from backend.app.schemas.enums import LLMProviderName

    monkeypatch.chdir(tmp_path)
    save_provider_secret(
        tmp_path,
        provider=LLMProviderName.SILICONFLOW,
        api_key="sf-cwd-secret-123456",
    )
    factory = FakeRunnerFactory()
    client = _client_with_factory(factory)
    payload = _inline_payload("E-cwd-secret")
    payload["experiment"]["llm"].update(
        {
            "provider": "siliconflow",
            "model": "deepseek-ai/DeepSeek-V4-Flash",
            "api_key": None,
            "api_key_env": "SILICONFLOW_API_KEY",
            "base_url": "https://api.siliconflow.cn/v1",
        }
    )

    response = client.post("/episodes/start", json=payload)

    assert response.status_code == 200, response.text
    provider = factory.created[0]["resolved_config"].provider
    assert provider.key_source == "local_settings"
    assert provider.key_masked == "sf-c****3456"


def test_start_episode_rejects_ambiguous_config_sources() -> None:
    factory = FakeRunnerFactory()
    client = _client_with_factory(factory)

    response = client.post(
        "/episodes/start",
        json={
            **_inline_payload("E-ambiguous"),
            "config_path": str(FIXTURE_DIR / "demo_valid.yaml"),
        },
    )

    assert response.status_code == 422
    payload = response.json()
    assert payload["code"] == "M_E_EPISODE_START_FAILED"
    assert payload["data"] is None
    assert payload["details"]["field_path"] == "config_path"
    assert factory.created == []


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
            "runner": "local",
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


def test_default_runner_stop_before_autostart_writes_terminal_summary(
    tmp_path: Path,
) -> None:
    client = TestClient(create_app())
    response = client.post(
        "/episodes/start",
        json={
            **_start_payload("E-stop-cold", autostart=False),
            "runner": "local",
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

    stop = client.post("/episodes/E-stop-cold/stop")

    assert stop.status_code == 200
    assert stop.json()["data"]["status"] == "stopped_by_user"
    run_dir = Path(client.app.state.episode_service.get_handle("E-stop-cold").run_dir)
    summary_path = run_dir / "metadata" / "episode_summary.json"
    assert summary_path.is_file()
    assert json.loads(summary_path.read_text(encoding="utf-8"))["episode_status"] == (
        "stopped_by_user"
    )


def test_production_runner_stop_before_first_frame_writes_terminal_summary(
    tmp_path: Path,
) -> None:
    client = TestClient(create_app(), raise_server_exceptions=False)
    response = client.post(
        "/episodes/start",
        json={
            **_start_payload("E-production-stop-cold", autostart=False),
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
        },
    )
    assert response.status_code == 200, response.text

    stop = client.post("/episodes/E-production-stop-cold/stop")

    assert stop.status_code == 200, stop.text
    assert stop.json()["data"]["status"] == "stopped_by_user"
    run_dir = Path(response.json()["data"]["run_dir"])
    summary_path = run_dir / "metadata" / "episode_summary.json"
    assert summary_path.is_file()
    assert json.loads(summary_path.read_text(encoding="utf-8"))["episode_status"] == (
        "stopped_by_user"
    )


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


def test_interactive_server_autostart_returns_before_first_frame_then_advances() -> None:
    factory = BlockingRunnerFactory()
    client = _client_with_factory(factory)

    response = client.post(
        "/episodes/start",
        json={**_start_payload(autostart=True), "run_mode": "interactive_server"},
    )

    assert response.status_code == 200
    runner = factory.created[0]["runner"]
    assert runner.run_one_frame_calls == 0
    assert runner.entered_first_frame.wait(1.0)
    runner.release_first_frame.set()
    deadline = time.monotonic() + 1.5
    while time.monotonic() < deadline and runner.run_one_frame_calls < 2:
        time.sleep(0.02)
    handle = client.app.state.episode_service.get_handle("E-life")
    handle.worker_stop.set()
    assert runner.run_one_frame_calls >= 2
    assert handle.frame_index >= 2


def test_autostart_uses_background_worker_for_runner_interactive_mode() -> None:
    factory = InteractiveBlockingRunnerFactory()
    client = _client_with_factory(factory)

    response = client.post("/episodes/start", json=_start_payload(autostart=True))

    assert response.status_code == 200
    runner = factory.created[0]["runner"]
    assert runner.run_one_frame_calls == 0
    assert runner.entered_first_frame.wait(1.0)
    handle = client.app.state.episode_service.get_handle("E-life")
    handle.worker_stop.set()
    runner.release_first_frame.set()
    handle.worker_thread.join(timeout=1.0)
    assert runner.run_one_frame_calls >= 1


def test_pause_stops_background_advancement_until_resume() -> None:
    factory = FakeRunnerFactory()
    client = _client_with_factory(factory)
    client.post(
        "/episodes/start",
        json={**_start_payload(autostart=True), "run_mode": "interactive_server"},
    )
    runner = factory.created[0]["runner"]
    handle = client.app.state.episode_service.get_handle("E-life")

    deadline = time.monotonic() + 1.5
    while time.monotonic() < deadline and runner.run_one_frame_calls < 2:
        time.sleep(0.02)

    pause = client.post("/episodes/E-life/pause")
    assert pause.status_code == 200
    paused_calls = runner.run_one_frame_calls
    time.sleep(0.25)
    assert runner.run_one_frame_calls == paused_calls

    resume = client.post("/episodes/E-life/resume")
    assert resume.status_code == 200
    deadline = time.monotonic() + 1.5
    while time.monotonic() < deadline and runner.run_one_frame_calls == paused_calls:
        time.sleep(0.02)
    handle.worker_stop.set()
    assert runner.run_one_frame_calls > paused_calls


def test_pause_resume_stop_lifecycle_flow() -> None:
    factory = FakeRunnerFactory()
    client = _client_with_factory(factory)
    client.post("/episodes/start", json=_start_payload())

    pause = client.post("/episodes/E-life/pause")
    assert pause.status_code == 200
    assert pause.json()["data"]["accepted"] is True
    assert pause.json()["data"]["status"] == "paused"
    assert client.app.state.episode_service.get_handle("E-life").paused is True
    state = client.get("/episodes/E-life/state")
    assert state.status_code == 200
    assert state.json()["data"]["status"] == "paused"

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


def test_terminal_episode_stop_is_idempotent_noop() -> None:
    factory = FakeRunnerFactory()
    client = _client_with_factory(factory)
    client.post("/episodes/start", json=_start_payload())
    handle = client.app.state.episode_service.get_handle("E-life")
    handle.status = EpisodeStatus.COMPLETED

    stop = client.post("/episodes/E-life/stop")

    assert stop.status_code == 200
    assert stop.json()["data"]["accepted"] is False
    assert stop.json()["data"]["status"] == "completed"
    assert stop.json()["data"]["reason"] == "already_terminal"


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


def test_task_generation_failure_returns_config_start_error_without_registering_episode() -> None:
    from backend.app.sim.task_generation import TaskGenerationError

    class TaskGenerationFailureFactory(FakeRunnerFactory):
        def __call__(self, *, episode_id: str, resolved_config: Any) -> FakeRunner:
            raise TaskGenerationError(
                "task point hook target height is unreachable",
                error_code="TASK_E_001",
                reason="point_height_unreachable",
                details={"task_id": "T_TOO_HIGH", "zone_id": "roof_dropoff"},
            )

    client = _client_with_factory(TaskGenerationFailureFactory())

    response = client.post("/episodes/start", json=_start_payload())

    assert response.status_code == 422
    payload = response.json()
    assert payload["code"] == "M_E_EPISODE_START_FAILED"
    assert payload["details"]["config_error_code"] == "TASK_E_001"
    assert payload["details"]["reason"] == "point_height_unreachable"
    assert payload["details"]["task_id"] == "T_TOO_HIGH"
    assert "E-life" not in client.app.state.episode_service.handles
