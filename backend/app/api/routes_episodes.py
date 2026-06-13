from __future__ import annotations

from fastapi import APIRouter, Request

from .episode_service import EpisodeService, default_runner_factory
from .schemas import ApiResponse, EpisodeStartRequest

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


def _episode_service(request: Request) -> EpisodeService:
    state = request.app.state
    if not hasattr(state, "episode_service"):
        runner_factory = getattr(state, "runner_factory", default_runner_factory)
        state.episode_service = EpisodeService(runner_factory=runner_factory)
    return state.episode_service


__all__ = ["router"]
