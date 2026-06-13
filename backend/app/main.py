from __future__ import annotations

from fastapi import FastAPI

from backend.app.api.errors import register_exception_handlers
from backend.app.api.routes_datasets import router as datasets_router
from backend.app.api.routes_episodes import router as episodes_router
from backend.app.api.routes_health import router as health_router
from backend.app.api.websocket import router as websocket_router


def create_app() -> FastAPI:
    app = FastAPI(
        title="Multi Crane Simulation API",
        version="1.0.0",
    )
    register_exception_handlers(app)
    app.include_router(health_router)
    app.include_router(episodes_router)
    app.include_router(datasets_router)
    app.include_router(websocket_router)
    return app


app = create_app()


__all__ = ["app", "create_app"]
