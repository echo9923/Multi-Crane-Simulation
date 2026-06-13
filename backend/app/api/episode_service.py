from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

from backend.app.core.config_loader import load_demo_config
from backend.app.core.config_resolver import resolve_config
from backend.app.schemas.recorder import SimFrame
from backend.app.schemas.scheduler import EpisodeStatus

from .errors import ApiException, config_api_error_from_exception
from .schemas import (
    EpisodeControlResponse,
    EpisodeStartRequest,
    EpisodeStartResponse,
    M_E_EPISODE_NOT_FOUND,
    M_E_EPISODE_START_FAILED,
    M_E_INVALID_EPISODE_STATE,
)

RunnerFactory = Callable[..., Any]


@dataclass
class EpisodeHandle:
    episode_id: str
    runner: Any
    run_dir: Optional[Path]
    status: EpisodeStatus
    frame_index: int = 0
    time_s: float = 0.0
    paused: bool = False
    last_frame: Optional[SimFrame] = None
    terminal_reason: Optional[str] = None


class EpisodeService:
    def __init__(self, *, runner_factory: RunnerFactory) -> None:
        self.runner_factory = runner_factory
        self.handles: dict[str, EpisodeHandle] = {}

    def start_episode(self, request: EpisodeStartRequest) -> EpisodeStartResponse:
        episode_id = request.episode_id or _new_episode_id()
        if episode_id in self.handles:
            raise ApiException(
                status_code=409,
                code=M_E_INVALID_EPISODE_STATE,
                message="episode already exists",
                details={"episode_id": episode_id},
            )

        resolved_config = self._resolve_start_config(request)
        try:
            runner = self.runner_factory(
                episode_id=episode_id,
                resolved_config=resolved_config,
            )
        except Exception as exc:
            raise ApiException(
                status_code=500,
                code=M_E_EPISODE_START_FAILED,
                message=str(exc),
                details={
                    "episode_id": episode_id,
                    "exception_type": type(exc).__name__,
                },
            ) from exc

        handle = EpisodeHandle(
            episode_id=episode_id,
            runner=runner,
            run_dir=_resolved_run_dir(resolved_config),
            status=_runner_status(runner),
        )

        if request.autostart:
            self._advance_handle_once(handle)

        self.handles[episode_id] = handle
        return EpisodeStartResponse(
            episode_id=episode_id,
            run_id=getattr(resolved_config, "run_id", None),
            run_dir=str(handle.run_dir) if handle.run_dir is not None else None,
            status=handle.status.value,
            resolved_config_hash=getattr(
                resolved_config,
                "resolved_config_hash",
                None,
            ),
            websocket_url=f"/ws/episodes/{episode_id}",
        )

    def pause_episode(self, episode_id: str) -> EpisodeControlResponse:
        handle = self.get_handle(episode_id)
        previous = _display_status(handle)
        if handle.status is not EpisodeStatus.RUNNING or handle.paused:
            raise _invalid_state(episode_id, "episode cannot be paused", previous)
        handle.paused = True
        return EpisodeControlResponse(
            episode_id=episode_id,
            previous_status=previous,
            status="paused",
            accepted=True,
        )

    def resume_episode(self, episode_id: str) -> EpisodeControlResponse:
        handle = self.get_handle(episode_id)
        previous = _display_status(handle)
        if handle.status is not EpisodeStatus.RUNNING or not handle.paused:
            raise _invalid_state(episode_id, "episode cannot be resumed", previous)
        handle.paused = False
        return EpisodeControlResponse(
            episode_id=episode_id,
            previous_status=previous,
            status=handle.status.value,
            accepted=True,
        )

    def stop_episode(self, episode_id: str) -> EpisodeControlResponse:
        handle = self.get_handle(episode_id)
        previous = _display_status(handle)
        if handle.status is not EpisodeStatus.RUNNING:
            raise _invalid_state(episode_id, "episode cannot be stopped", previous)
        handle.runner.stop("api stop")
        self._advance_handle_once(handle)
        return EpisodeControlResponse(
            episode_id=episode_id,
            previous_status=previous,
            status=handle.status.value,
            accepted=True,
            reason=handle.terminal_reason,
        )

    def get_handle(self, episode_id: str) -> EpisodeHandle:
        try:
            return self.handles[episode_id]
        except KeyError as exc:
            raise ApiException(
                status_code=404,
                code=M_E_EPISODE_NOT_FOUND,
                message="episode not found",
                details={"episode_id": episode_id},
            ) from exc

    def _advance_handle_once(self, handle: EpisodeHandle) -> None:
        result = handle.runner.run_one_frame()
        handle.status = EpisodeStatus(result.status)
        handle.frame_index = result.frame_index
        handle.time_s = result.time_s
        if handle.status is not EpisodeStatus.RUNNING:
            handle.paused = False
            handle.terminal_reason = getattr(result, "reason", None) or handle.status.value

    def _resolve_start_config(self, request: EpisodeStartRequest) -> Any:
        if request.config_path is None:
            raise ApiException(
                status_code=422,
                code=M_E_EPISODE_START_FAILED,
                message="Episode start currently requires config_path",
                details={"field_path": "config_path"},
            )
        try:
            scenario, experiment, dataset = load_demo_config(
                request.config_path,
                overrides=request.overrides,
            )
            if experiment is None:
                raise ValueError("demo config must include experiment section")
            return resolve_config(scenario, experiment, dataset)
        except ApiException:
            raise
        except Exception as exc:
            raise config_api_error_from_exception(
                exc,
                config_kind="scenario",
                source_file=request.config_path,
            ) from exc


def _new_episode_id() -> str:
    return f"E-{uuid.uuid4().hex[:12]}"


def _runner_status(runner: Any) -> EpisodeStatus:
    return EpisodeStatus(getattr(runner, "episode_status", EpisodeStatus.RUNNING))


def _display_status(handle: EpisodeHandle) -> str:
    if handle.paused and handle.status is EpisodeStatus.RUNNING:
        return "paused"
    return handle.status.value


def _invalid_state(episode_id: str, message: str, status: str) -> ApiException:
    return ApiException(
        status_code=409,
        code=M_E_INVALID_EPISODE_STATE,
        message=message,
        details={"episode_id": episode_id, "status": status},
    )


def _resolved_run_dir(resolved_config: Any) -> Optional[Path]:
    output = getattr(resolved_config, "output", None)
    if output is None:
        return None
    run_root = getattr(output, "run_root", None)
    if run_root is None and isinstance(output, dict):
        run_root = output.get("run_root")
    return Path(run_root) if run_root else None


def default_runner_factory(*, episode_id: str, resolved_config: Any) -> Any:
    raise NotImplementedError(
        "real EpisodeRunner dependency assembly is implemented in later Module M tasks"
    )


__all__ = [
    "EpisodeHandle",
    "EpisodeService",
    "default_runner_factory",
]
