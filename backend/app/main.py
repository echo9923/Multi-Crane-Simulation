from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app.api.desktop_context import (
    resolve_desktop_data_root,
    resolve_desktop_project_root,
)
from backend.app.api.errors import register_exception_handlers
from backend.app.api.routes_desktop import router as desktop_router
from backend.app.api.routes_datasets import router as datasets_router
from backend.app.api.routes_episodes import router as episodes_router
from backend.app.api.routes_health import router as health_router
from backend.app.api.websocket import (
    ApiWebSocketAdapter,
    WebSocketConnectionManager,
    router as websocket_router,
)


def create_app() -> FastAPI:
    app = FastAPI(
        title="Multi Crane Simulation API",
        version="1.0.0",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1):\d+$",
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["content-type"],
    )
    register_exception_handlers(app)
    app.state.project_root = _path_from_env("MULTI_CRANE_PROJECT_ROOT")
    app.state.data_root = _path_from_env("MULTI_CRANE_DATA_ROOT")
    app.state.backend_port = _backend_port_from_env()
    app.state.websocket_manager = WebSocketConnectionManager()
    app.state.runner_factory = _production_runner_factory(app)
    app.include_router(health_router)
    app.include_router(desktop_router)
    app.include_router(episodes_router)
    app.include_router(datasets_router)
    app.include_router(websocket_router)
    return app


def _backend_port_from_env() -> int | None:
    port = os.environ.get("MULTI_CRANE_BACKEND_PORT")
    if port is None:
        return None
    try:
        parsed = int(port)
    except ValueError:
        return None
    return parsed if 1 <= parsed <= 65535 else None


def _path_from_env(name: str):
    value = os.environ.get(name)
    return value if value else None


def _production_runner_factory(app: FastAPI):
    def factory(
        *,
        episode_id: str,
        resolved_config,
        project_root=None,
        data_root=None,
    ):
        from backend.app.api.production_runner import build_production_episode_runner

        return build_production_episode_runner(
            episode_id=episode_id,
            resolved_config=resolved_config,
            websocket=ApiWebSocketAdapter(app.state.websocket_manager),
            project_root=project_root or resolve_desktop_project_root(app),
            data_root=data_root or resolve_desktop_data_root(app),
        )

    return factory


app = create_app()


__all__ = ["app", "create_app"]
