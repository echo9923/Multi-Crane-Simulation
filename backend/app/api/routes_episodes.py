from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import Response

from .episode_service import EpisodeService, default_runner_factory
from backend.app.schemas.recorder import EpisodeSummary, SimFrame

from .errors import ApiException
from .schemas import (
    ApiResponse,
    EpisodeStartRequest,
    EpisodeStateResponse,
    M_E_DOWNLOAD_FAILED,
    M_E_SUMMARY_NOT_FOUND,
)

router = APIRouter()


@router.post("/episodes/start", response_model=ApiResponse)
def start_episode(request: Request, payload: EpisodeStartRequest) -> ApiResponse:
    service = _episode_service(request)
    result = service.start_episode(payload)
    return ApiResponse(data=result.model_dump(mode="json"))


@router.post("/episodes/{episode_id}/pause", response_model=ApiResponse)
def pause_episode(request: Request, episode_id: str) -> ApiResponse:
    service = _episode_service(request)
    result = service.pause_episode(episode_id)
    return ApiResponse(data=result.model_dump(mode="json"))


@router.post("/episodes/{episode_id}/resume", response_model=ApiResponse)
def resume_episode(request: Request, episode_id: str) -> ApiResponse:
    service = _episode_service(request)
    result = service.resume_episode(episode_id)
    return ApiResponse(data=result.model_dump(mode="json"))


@router.post("/episodes/{episode_id}/stop", response_model=ApiResponse)
def stop_episode(request: Request, episode_id: str) -> ApiResponse:
    service = _episode_service(request)
    result = service.stop_episode(episode_id)
    return ApiResponse(data=result.model_dump(mode="json"))


@router.get("/episodes/{episode_id}/state", response_model=ApiResponse)
def get_episode_state(request: Request, episode_id: str) -> ApiResponse:
    handle = _episode_service(request).get_handle(episode_id)
    last_frame = handle.last_frame or _read_last_frame(handle.run_dir)
    frame_index = handle.frame_index
    time_s = handle.time_s
    if last_frame is not None and frame_index == 0 and time_s == 0.0:
        frame_index = last_frame.frame
        time_s = last_frame.time_s
    result = EpisodeStateResponse(
        episode_id=episode_id,
        status=handle.status.value,
        frame_index=frame_index,
        time_s=time_s,
        run_dir=str(handle.run_dir) if handle.run_dir is not None else None,
        last_frame=last_frame,
        terminal_reason=handle.terminal_reason,
    )
    return ApiResponse(data=result.model_dump(mode="json"))


@router.get("/episodes/{episode_id}/summary", response_model=ApiResponse)
def get_episode_summary(request: Request, episode_id: str) -> ApiResponse:
    handle = _episode_service(request).get_handle(episode_id)
    summary = _read_episode_summary(handle.run_dir, episode_id)
    return ApiResponse(data=summary.model_dump(mode="json"))


@router.get("/episodes/{episode_id}/download")
def download_episode(
    request: Request,
    episode_id: str,
    include_logs: bool = True,
    include_data: bool = True,
    include_visual: bool = True,
) -> Response:
    handle = _episode_service(request).get_handle(episode_id)
    archive = _build_run_archive(
        run_dir=handle.run_dir,
        episode_id=episode_id,
        include_logs=include_logs,
        include_data=include_data,
        include_visual=include_visual,
    )
    return Response(
        content=archive,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{episode_id}.zip"',
        },
    )


def _episode_service(request: Request) -> EpisodeService:
    state = request.app.state
    if not hasattr(state, "episode_service"):
        runner_factory = getattr(state, "runner_factory", default_runner_factory)
        state.episode_service = EpisodeService(runner_factory=runner_factory)
    return state.episode_service


def _read_episode_summary(run_dir: Path | None, episode_id: str) -> EpisodeSummary:
    if run_dir is None:
        raise _summary_not_found(episode_id)
    path = run_dir / "metadata" / "episode_summary.json"
    if not path.is_file():
        raise _summary_not_found(episode_id)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return EpisodeSummary.model_validate(payload)
    except ApiException:
        raise
    except Exception as exc:
        raise ApiException(
            status_code=500,
            code=M_E_SUMMARY_NOT_FOUND,
            message="failed to read episode summary",
            details={
                "episode_id": episode_id,
                "path": str(path),
                "exception_type": type(exc).__name__,
            },
        ) from exc


def _summary_not_found(episode_id: str) -> ApiException:
    return ApiException(
        status_code=404,
        code=M_E_SUMMARY_NOT_FOUND,
        message="episode summary not found",
        details={"episode_id": episode_id},
    )


def _read_last_frame(run_dir: Path | None) -> SimFrame | None:
    if run_dir is None:
        return None
    path = run_dir / "visual" / "frames.jsonl"
    if not path.is_file():
        return None
    last_line = ""
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            last_line = line
    if not last_line:
        return None
    return SimFrame.model_validate(json.loads(last_line))


def _build_run_archive(
    *,
    run_dir: Path | None,
    episode_id: str,
    include_logs: bool,
    include_data: bool,
    include_visual: bool,
) -> bytes:
    if run_dir is None or not run_dir.is_dir():
        raise ApiException(
            status_code=404,
            code=M_E_DOWNLOAD_FAILED,
            message="episode run directory not found",
            details={"episode_id": episode_id},
        )
    allowed_dirs = {"config", "metadata", "replay"}
    if include_logs:
        allowed_dirs.add("logs")
    if include_data:
        allowed_dirs.add("data")
    if include_visual:
        allowed_dirs.add("visual")

    try:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
            for file_path in sorted(path for path in run_dir.rglob("*") if path.is_file()):
                relative = file_path.relative_to(run_dir)
                if not relative.parts or relative.parts[0] not in allowed_dirs:
                    continue
                if _excluded_archive_path(relative):
                    continue
                archive.write(file_path, relative.as_posix())
        return buffer.getvalue()
    except ApiException:
        raise
    except Exception as exc:
        raise ApiException(
            status_code=500,
            code=M_E_DOWNLOAD_FAILED,
            message="failed to build episode download",
            details={
                "episode_id": episode_id,
                "exception_type": type(exc).__name__,
            },
        ) from exc


def _excluded_archive_path(path: Path) -> bool:
    parts = set(path.parts)
    name = path.name
    return (
        "__pycache__" in parts
        or name == ".DS_Store"
        or name.endswith(".tmp")
        or name.endswith(".partial")
    )


__all__ = ["router"]
