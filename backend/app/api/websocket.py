from __future__ import annotations

import asyncio
import concurrent.futures
import threading
import time
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from backend.app.schemas.recorder import SimFrame
from backend.app.sim.recorder import build_sim_frame

from .desktop_context import resolve_desktop_data_root, resolve_desktop_project_root
from .episode_service import EpisodeHandle, EpisodeService, default_runner_factory
from .schemas import (
    ApiError,
    API_SCHEMA_VERSION,
    M_E_EPISODE_NOT_FOUND,
    M_E_WEBSOCKET_CLOSED,
)

router = APIRouter()


class WebSocketConnectionManager:
    def __init__(self, *, send_timeout_s: float = 0.5) -> None:
        self.connections: dict[str, set[Any]] = {}
        self.send_timeout_s = send_timeout_s
        self._loop: asyncio.AbstractEventLoop | None = None
        self._loop_lock = threading.Lock()

    async def connect(self, episode_id: str, websocket: WebSocket) -> None:
        self._remember_loop(asyncio.get_running_loop())
        await websocket.accept()
        self.connections.setdefault(episode_id, set()).add(websocket)

    def disconnect(self, episode_id: str, websocket: WebSocket) -> None:
        clients = self.connections.get(episode_id)
        if not clients:
            return
        clients.discard(websocket)
        if not clients:
            self.connections.pop(episode_id, None)

    async def broadcast_sim_frame(self, episode_id: str, frame: SimFrame) -> None:
        if frame.offline_labels is not None:
            await self.broadcast_error(
                episode_id,
                ApiError(
                    code=M_E_WEBSOCKET_CLOSED,
                    message="realtime websocket frame cannot include offline labels",
                    details={"episode_id": episode_id, "frame": frame.frame},
                ),
            )
            return
        payload = {"type": "sim_frame", "data": frame.model_dump(mode="json")}
        await self._broadcast(episode_id, payload)

    async def broadcast_error(self, episode_id: str, error: ApiError) -> None:
        await self._broadcast(
            episode_id,
            {"type": "error", "data": error.model_dump(mode="json")},
        )

    async def broadcast_heartbeat(self, episode_id: str, *, server_time_s: float) -> None:
        await self._broadcast(
            episode_id,
            {"type": "heartbeat", "data": {"server_time_s": server_time_s}},
        )

    def submit_broadcast_sim_frame(
        self,
        episode_id: str,
        frame: SimFrame,
    ) -> concurrent.futures.Future[Any] | None:
        loop = self._get_loop()
        if loop is None or loop.is_closed() or not loop.is_running():
            return None
        return asyncio.run_coroutine_threadsafe(
            self.broadcast_sim_frame(episode_id, frame),
            loop,
        )

    async def send_initial_frame(
        self,
        episode_id: str,
        websocket: WebSocket,
        handle: EpisodeHandle,
    ) -> None:
        frame = _runner_last_frame(handle.runner) or handle.last_frame
        if frame is None:
            return
        if frame.offline_labels is not None:
            return
        await self._send_one(
            episode_id,
            websocket,
            {"type": "sim_frame", "data": frame.model_dump(mode="json")},
        )

    async def _broadcast(self, episode_id: str, payload: dict[str, Any]) -> None:
        clients = list(self.connections.get(episode_id, set()))
        if not clients:
            return
        await asyncio.gather(
            *[self._send_one(episode_id, websocket, payload) for websocket in clients],
            return_exceptions=True,
        )

    async def _send_one(
        self,
        episode_id: str,
        websocket: WebSocket,
        payload: dict[str, Any],
    ) -> None:
        try:
            await asyncio.wait_for(
                websocket.send_json(payload),
                timeout=self.send_timeout_s,
            )
        except Exception:
            self.disconnect(episode_id, websocket)

    def _remember_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        with self._loop_lock:
            if self._loop is None or self._loop.is_closed():
                self._loop = loop

    def _get_loop(self) -> asyncio.AbstractEventLoop | None:
        with self._loop_lock:
            return self._loop

    def owns_loop(self, loop: asyncio.AbstractEventLoop) -> bool:
        return self._get_loop() is loop


@router.websocket("/ws/episodes/{episode_id}")
async def episode_websocket(websocket: WebSocket, episode_id: str) -> None:
    service = _episode_service(websocket)
    manager = _websocket_manager(websocket)
    try:
        handle = service.get_handle(episode_id)
    except Exception:
        await websocket.accept()
        error = ApiError(
            code=M_E_EPISODE_NOT_FOUND,
            message="episode not found",
            details={"episode_id": episode_id},
        )
        await websocket.send_json({"type": "error", "data": error.model_dump(mode="json")})
        await websocket.close()
        return

    await manager.connect(episode_id, websocket)
    await manager.send_initial_frame(episode_id, websocket, handle)
    heartbeat = asyncio.create_task(_heartbeat_loop(manager, episode_id, websocket))
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(episode_id, websocket)
    finally:
        heartbeat.cancel()
        try:
            await heartbeat
        except asyncio.CancelledError:
            pass


async def _heartbeat_loop(
    manager: WebSocketConnectionManager,
    episode_id: str,
    websocket: WebSocket,
) -> None:
    while True:
        await asyncio.sleep(5.0)
        await manager._send_one(
            episode_id,
            websocket,
            {"type": "heartbeat", "data": {"server_time_s": time.time()}},
        )


def _episode_service(websocket: WebSocket) -> EpisodeService:
    state = websocket.app.state
    if not hasattr(state, "episode_service"):
        runner_factory = getattr(state, "runner_factory", default_runner_factory)
        state.episode_service = EpisodeService(
            runner_factory=runner_factory,
            project_root=resolve_desktop_project_root(websocket.app),
            data_root=resolve_desktop_data_root(websocket.app),
        )
    return state.episode_service


def _runner_last_frame(runner: Any) -> SimFrame | None:
    for candidate in (
        runner,
        getattr(runner, "recorder", None),
        getattr(getattr(runner, "recorder", None), "recorder", None),
    ):
        frame = getattr(candidate, "last_frame", None)
        if frame is not None:
            return frame
    return None


def _websocket_manager(websocket: WebSocket) -> WebSocketConnectionManager:
    state = websocket.app.state
    if not hasattr(state, "websocket_manager"):
        state.websocket_manager = WebSocketConnectionManager()
    return state.websocket_manager


class ApiWebSocketAdapter:
    def __init__(self, manager: WebSocketConnectionManager) -> None:
        self.manager = manager

    def broadcast_sim_frame_if_enabled(
        self,
        *,
        episode_id: str,
        frame: SimFrame | None = None,
        **kwargs: Any,
    ) -> None:
        sim_frame = frame or build_sim_frame(
            episode_id=episode_id,
            scenario_id=None,
            frame_index=kwargs["frame_index"],
            time_s=kwargs["time_s"],
            episode_status=kwargs.get("status", "running"),
            states=kwargs.get("states", []),
            weather_state=kwargs["weather_state"],
            commands=kwargs.get("commands"),
            pairs=[],
            tasks=[],
            task_queues=kwargs.get("task_queues", []),
            site=kwargs.get("site"),
            events=kwargs.get("events", []),
            for_realtime=True,
        )
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            future = self.manager.submit_broadcast_sim_frame(episode_id, sim_frame)
            if future is None:
                asyncio.run(self.manager.broadcast_sim_frame(episode_id, sim_frame))
            return
        if self.manager.owns_loop(loop):
            loop.create_task(self.manager.broadcast_sim_frame(episode_id, sim_frame))
            return
        future = self.manager.submit_broadcast_sim_frame(episode_id, sim_frame)
        if future is None:
            loop.create_task(self.manager.broadcast_sim_frame(episode_id, sim_frame))


__all__ = [
    "ApiWebSocketAdapter",
    "WebSocketConnectionManager",
    "router",
]
