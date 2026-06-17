from __future__ import annotations

import asyncio
import json

from fastapi.testclient import TestClient

from backend.app.api.episode_service import EpisodeHandle, EpisodeService
from backend.app.main import create_app
from backend.app.schemas.recorder import OfflineFrameLabels, SimFrame, SimFrameWeather
from backend.app.schemas.scheduler import EpisodeStatus


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


def test_websocket_module_does_not_define_duplicate_simframe_schema() -> None:
    from backend.app.api import websocket

    source = websocket.__dict__
    assert "SimFrameCrane" not in source
    assert "SimFramePair" not in source
    assert "SimFrameWeather" not in source
