from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from backend.app.api.episode_service import EpisodeHandle, EpisodeService
from backend.app.main import create_app
from backend.app.schemas.recorder import OfflineFrameLabels, SimFrame, SimFrameWeather
from backend.app.schemas.scheduler import EpisodeStatus
from backend.app.schemas.task import Task, TaskPoint, TaskQueue
from backend.app.schemas.state import CraneState
from backend.app.schemas.weather import WeatherState


class NoopRunner:
    episode_status = EpisodeStatus.RUNNING


class FakeWebSocket:
    def __init__(self, *, fail_send: bool = False, delay_s: float = 0.0) -> None:
        self.accepted = False
        self.sent: list[dict] = []
        self.closed = False
        self.fail_send = fail_send
        self.delay_s = delay_s

    async def accept(self) -> None:
        self.accepted = True

    async def send_json(self, payload: dict) -> None:
        if self.delay_s:
            await asyncio.sleep(self.delay_s)
        if self.fail_send:
            raise RuntimeError("send failed")
        self.sent.append(payload)

    async def close(self) -> None:
        self.closed = True


class LoopBoundFakeWebSocket(FakeWebSocket):
    def __init__(self) -> None:
        super().__init__()
        self.accept_loop: asyncio.AbstractEventLoop | None = None
        self.send_loops: list[asyncio.AbstractEventLoop] = []

    async def accept(self) -> None:
        self.accept_loop = asyncio.get_running_loop()
        await super().accept()

    async def send_json(self, payload: dict) -> None:
        loop = asyncio.get_running_loop()
        self.send_loops.append(loop)
        if loop is not self.accept_loop:
            raise RuntimeError("send_json called from wrong event loop")
        await super().send_json(payload)


def _frame() -> SimFrame:
    return SimFrame(
        episode_id="E-ws",
        scenario_id="scenario-a",
        frame=1,
        time_s=0.5,
        episode_status="running",
        cranes=[],
        pairs=[],
        tasks=[],
        weather=SimFrameWeather(wind_speed_m_s=1.0, visibility="good"),
        events=[],
    )


def _crane_state(crane_id: str = "C1") -> CraneState:
    return CraneState(
        crane_id=crane_id,
        theta_rad=0.0,
        theta_sin=0.0,
        theta_cos=1.0,
        trolley_r_m=20.0,
        hook_h_m=12.0,
        root_position=[0.0, 0.0, 45.0],
        tip_position=[55.0, 0.0, 45.0],
        hook_position=[20.0, 0.0, 12.0],
        cable_length_m=33.0,
        load_attached=False,
        load_type="rebar_bundle",
        load_weight_t=1.0,
        load_size_m=[6.0, 1.0, 1.0],
        task_id="T_C1_001",
        task_stage="move_to_pickup",
    )


def _weather_state() -> WeatherState:
    return WeatherState(
        time_s=1.0,
        mode="constant",
        wind_speed_m_s=1.0,
        wind_gust_m_s=2.0,
        wind_direction_deg=90.0,
        visibility_level="good",
        rain_level="none",
        fog_level="none",
        source_segment_id="constant",
        generation_seed=1,
        generation_step=0,
    )


def _task_queue() -> TaskQueue:
    pickup = TaskPoint(x=10.0, y=0.0, z=1.0, zone_id="material_zone", zone_type="material")
    dropoff = TaskPoint(x=30.0, y=10.0, z=20.0, zone_id="work_zone", zone_type="work")
    task = Task(
        task_id="T_C1_001",
        crane_id="C1",
        task_type="easy_task",
        pickup=pickup,
        dropoff=dropoff,
        pickup_zone_id=pickup.zone_id,
        dropoff_zone_id=dropoff.zone_id,
        planned_start_s=0.0,
        load_type="rebar_bundle",
        load_weight_t=2.0,
        load_size_m=[6.0, 1.0, 1.0],
        priority="medium",
        deadline_s=180.0,
        generation_seed=1,
        generation_attempt=0,
    )
    return TaskQueue(
        crane_id="C1",
        tasks=[task],
        active_task_id="T_C1_001",
        next_task_index=1,
    )


def _service_with_episode() -> EpisodeService:
    service = EpisodeService(runner_factory=lambda **kwargs: NoopRunner())
    service.handles["E-ws"] = EpisodeHandle(
        episode_id="E-ws",
        runner=NoopRunner(),
        run_dir=None,
        status=EpisodeStatus.RUNNING,
        last_frame=_frame(),
    )
    return service


def _client_with_service(service: EpisodeService) -> TestClient:
    app = create_app()
    app.state.episode_service = service
    return TestClient(app)


def test_websocket_missing_episode_sends_uniform_error_and_closes() -> None:
    client = _client_with_service(EpisodeService(runner_factory=lambda **kwargs: NoopRunner()))

    with client.websocket_connect("/ws/episodes/missing") as websocket:
        message = websocket.receive_json()

    assert message["type"] == "error"
    assert message["data"]["code"] == "M_E_EPISODE_NOT_FOUND"
    assert message["data"]["details"]["episode_id"] == "missing"


def test_websocket_existing_episode_connects_successfully() -> None:
    client = _client_with_service(_service_with_episode())

    with client.websocket_connect("/ws/episodes/E-ws") as websocket:
        websocket.send_text("client-ready")


def test_manager_broadcasts_recorder_sim_frame_to_all_clients() -> None:
    from backend.app.api.websocket import WebSocketConnectionManager

    manager = WebSocketConnectionManager()
    first = FakeWebSocket()
    second = FakeWebSocket()
    frame = _frame()

    async def scenario() -> None:
        await manager.connect("E-ws", first)
        await manager.connect("E-ws", second)
        await manager.broadcast_sim_frame("E-ws", frame)

    asyncio.run(scenario())

    assert first.accepted is True
    assert second.accepted is True
    assert len(first.sent) == 1
    assert len(second.sent) == 1
    assert first.sent[0]["type"] == "sim_frame"
    assert SimFrame.model_validate(first.sent[0]["data"]).frame == 1
    assert first.sent[0] == second.sent[0]


def test_manager_can_broadcast_ten_frames_for_realtime_rate() -> None:
    from backend.app.api.websocket import WebSocketConnectionManager

    manager = WebSocketConnectionManager()
    websocket = FakeWebSocket()

    async def scenario() -> None:
        await manager.connect("E-ws", websocket)
        for index in range(10):
            await manager.broadcast_sim_frame("E-ws", _frame().model_copy(update={"frame": index}))

    asyncio.run(scenario())

    assert len(websocket.sent) == 10
    assert all(message["type"] == "sim_frame" for message in websocket.sent)
    assert [message["data"]["frame"] for message in websocket.sent] == list(range(10))


def test_manager_broadcast_no_clients_is_noop() -> None:
    from backend.app.api.websocket import WebSocketConnectionManager

    manager = WebSocketConnectionManager()

    asyncio.run(manager.broadcast_sim_frame("E-ws", _frame()))


def test_manager_rejects_realtime_frame_with_offline_labels() -> None:
    from backend.app.api.websocket import WebSocketConnectionManager

    manager = WebSocketConnectionManager()
    websocket = FakeWebSocket()
    frame = _frame().model_copy(
        update={
            "offline_labels": OfflineFrameLabels(
                pair_labels=[{"crane_i": "C1", "crane_j": "C2"}]
            )
        }
    )

    async def scenario() -> None:
        await manager.connect("E-ws", websocket)
        await manager.broadcast_sim_frame("E-ws", frame)

    asyncio.run(scenario())

    assert websocket.sent[0]["type"] == "error"
    assert websocket.sent[0]["data"]["code"] == "M_E_WEBSOCKET_CLOSED"


def test_manager_can_emit_heartbeat() -> None:
    from backend.app.api.websocket import WebSocketConnectionManager

    manager = WebSocketConnectionManager()
    websocket = FakeWebSocket()

    async def scenario() -> None:
        await manager.connect("E-ws", websocket)
        await manager.broadcast_heartbeat("E-ws", server_time_s=1.25)

    asyncio.run(scenario())

    assert websocket.sent == [
        {"type": "heartbeat", "data": {"server_time_s": 1.25}}
    ]


def test_manager_disconnects_failing_clients_without_blocking_others() -> None:
    from backend.app.api.websocket import WebSocketConnectionManager

    manager = WebSocketConnectionManager(send_timeout_s=0.01)
    good = FakeWebSocket()
    failing = FakeWebSocket(fail_send=True)

    async def scenario() -> None:
        await manager.connect("E-ws", good)
        await manager.connect("E-ws", failing)
        await manager.broadcast_sim_frame("E-ws", _frame())

    asyncio.run(scenario())

    assert len(good.sent) == 1
    assert good in manager.connections["E-ws"]
    assert failing not in manager.connections["E-ws"]


def test_manager_sends_last_frame_to_new_connection() -> None:
    from backend.app.api.websocket import WebSocketConnectionManager

    manager = WebSocketConnectionManager()
    websocket = FakeWebSocket()
    handle = _service_with_episode().get_handle("E-ws")

    async def scenario() -> None:
        await manager.connect("E-ws", websocket)
        await manager.send_initial_frame("E-ws", websocket, handle)

    asyncio.run(scenario())

    assert websocket.sent[0]["type"] == "sim_frame"
    assert websocket.sent[0]["data"]["episode_id"] == "E-ws"
    assert websocket.sent[0]["data"]["frame"] == 1


def test_manager_sends_runner_recorder_frame_when_handle_frame_not_synced() -> None:
    from backend.app.api.websocket import WebSocketConnectionManager

    manager = WebSocketConnectionManager()
    websocket = FakeWebSocket()
    handle = EpisodeHandle(
        episode_id="E-ws",
        runner=SimpleNamespace(recorder=SimpleNamespace(last_frame=_frame())),
        run_dir=None,
        status=EpisodeStatus.RUNNING,
        last_frame=None,
    )

    async def scenario() -> None:
        await manager.connect("E-ws", websocket)
        await manager.send_initial_frame("E-ws", websocket, handle)

    asyncio.run(scenario())

    assert websocket.sent[0]["type"] == "sim_frame"
    assert websocket.sent[0]["data"]["frame"] == 1


def test_websocket_lazy_episode_service_preserves_desktop_roots(
    tmp_path: Path,
) -> None:
    app = create_app()
    project_root = tmp_path / "project"
    data_root = tmp_path / "data"
    app.state.project_root = project_root
    app.state.data_root = data_root
    client = TestClient(app)

    with client.websocket_connect("/ws/episodes/missing") as websocket:
        message = websocket.receive_json()

    assert message["type"] == "error"
    service = client.app.state.episode_service
    assert service.project_root == project_root.resolve()
    assert service.data_root == data_root.resolve()


def test_adapter_includes_task_queues_when_building_realtime_frame() -> None:
    from backend.app.api.websocket import ApiWebSocketAdapter, WebSocketConnectionManager

    manager = WebSocketConnectionManager()
    websocket = FakeWebSocket()
    adapter = ApiWebSocketAdapter(manager)

    async def scenario() -> None:
        await manager.connect("E-ws", websocket)
        adapter.broadcast_sim_frame_if_enabled(
            episode_id="E-ws",
            frame_index=2,
            time_s=1.0,
            states=[_crane_state("C1")],
            weather_state=_weather_state(),
            task_queues=[_task_queue()],
            status="running",
        )
        await asyncio.sleep(0)

    asyncio.run(scenario())

    assert websocket.sent[0]["type"] == "sim_frame"
    payload = websocket.sent[0]["data"]
    assert payload["offline_labels"] is None
    assert payload["tasks"][0]["active_task_id"] == "T_C1_001"
    assert payload["tasks"][0]["tasks"][0]["task_id"] == "T_C1_001"


def test_adapter_hands_worker_thread_broadcast_to_connection_loop() -> None:
    from backend.app.api.websocket import ApiWebSocketAdapter, WebSocketConnectionManager

    manager = WebSocketConnectionManager()
    websocket = LoopBoundFakeWebSocket()
    adapter = ApiWebSocketAdapter(manager)

    async def scenario() -> None:
        await manager.connect("E-ws", websocket)

        worker = threading.Thread(
            target=adapter.broadcast_sim_frame_if_enabled,
            kwargs={"episode_id": "E-ws", "frame": _frame()},
        )
        worker.start()
        worker.join(timeout=1.0)

        deadline = asyncio.get_running_loop().time() + 1.0
        while not websocket.sent and asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(0.01)

    asyncio.run(scenario())

    assert websocket.sent[0]["type"] == "sim_frame"
    assert websocket.send_loops == [websocket.accept_loop]
    assert websocket in manager.connections["E-ws"]


def test_websocket_module_does_not_define_duplicate_simframe_schema() -> None:
    from backend.app.api import websocket

    source = websocket.__dict__
    assert "SimFrameCrane" not in source
    assert "SimFramePair" not in source
    assert "SimFrameWeather" not in source
