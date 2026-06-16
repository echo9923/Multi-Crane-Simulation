from __future__ import annotations

from pathlib import Path
from typing import Callable, TypeVar

import yaml
from fastapi import APIRouter, Request

from .desktop_service import (
    apply_config_patch,
    environment_report,
    list_desktop_templates,
    list_recent_experiments,
    list_run_files,
    list_runs,
    render_template_yaml,
    save_experiment_draft,
)
from .errors import ApiException
from .schemas import (
    ApiResponse,
    DesktopConfigPatchRequest,
    DesktopConfigRenderRequest,
    DesktopConfigTextResponse,
    DesktopExperimentDraftRequest,
    DesktopRecentExperimentsResponse,
    DesktopRunFilesResponse,
    DesktopRunsResponse,
    DesktopTemplatesResponse,
    M_E_CONFIG_INVALID,
    M_E_EPISODE_NOT_FOUND,
)

router = APIRouter(prefix="/desktop")

_T = TypeVar("_T")


@router.get("/templates", response_model=ApiResponse)
def get_desktop_templates(request: Request) -> ApiResponse:
    templates = _translate_config_errors(
        lambda: list_desktop_templates(project_root=_project_root(request))
    )
    response = DesktopTemplatesResponse(items=templates)
    return ApiResponse(data=response.model_dump(mode="json"))


@router.post("/config/render", response_model=ApiResponse)
def render_desktop_config(
    request: Request, payload: DesktopConfigRenderRequest
) -> ApiResponse:
    yaml_text = _translate_config_errors(
        lambda: render_template_yaml(
            project_root=_project_root(request),
            template_id=payload.template_id,
            core_overrides=payload.core_overrides,
        )
    )
    response = DesktopConfigTextResponse(yaml_text=yaml_text)
    return ApiResponse(data=response.model_dump(mode="json"))


@router.post("/config/patch", response_model=ApiResponse)
def patch_desktop_config(payload: DesktopConfigPatchRequest) -> ApiResponse:
    yaml_text = _translate_config_errors(
        lambda: apply_config_patch(
            yaml_text=payload.yaml_text,
            patches=payload.patches,
        )
    )
    response = DesktopConfigTextResponse(yaml_text=yaml_text)
    return ApiResponse(data=response.model_dump(mode="json"))


@router.post("/experiments/draft", response_model=ApiResponse)
def save_desktop_experiment_draft(
    request: Request, payload: DesktopExperimentDraftRequest
) -> ApiResponse:
    response = _translate_config_errors(
        lambda: save_experiment_draft(
            project_root=_project_root(request),
            experiment_id=payload.experiment_id,
            yaml_text=payload.yaml_text,
            metadata=payload.metadata,
        )
    )
    return ApiResponse(data=response.model_dump(mode="json"))


@router.get("/experiments/recent", response_model=ApiResponse)
def get_recent_desktop_experiments(request: Request) -> ApiResponse:
    experiments = list_recent_experiments(project_root=_project_root(request))
    response = DesktopRecentExperimentsResponse(items=experiments)
    return ApiResponse(data=response.model_dump(mode="json"))


@router.get("/runs", response_model=ApiResponse)
def get_desktop_runs(request: Request) -> ApiResponse:
    runs = list_runs(project_root=_project_root(request))
    response = DesktopRunsResponse(items=runs)
    return ApiResponse(data=response.model_dump(mode="json"))


@router.get("/runs/{episode_id}/files", response_model=ApiResponse)
def get_desktop_run_files(request: Request, episode_id: str) -> ApiResponse:
    project_root = _project_root(request)
    run = _find_run_dir(project_root, episode_id)
    try:
        files = list_run_files(run, project_root=project_root)
    except ValueError as exc:
        raise _run_not_found(episode_id) from exc
    response = DesktopRunFilesResponse(episode_id=episode_id, files=files)
    return ApiResponse(data=response.model_dump(mode="json"))


@router.get("/environment", response_model=ApiResponse)
def get_desktop_environment(request: Request) -> ApiResponse:
    response = environment_report(
        project_root=_project_root(request),
        backend_port=_backend_port(request),
    )
    return ApiResponse(data=response.model_dump(mode="json"))


def _project_root(request: Request) -> Path:
    root = getattr(request.app.state, "project_root", None)
    if root is None:
        return Path.cwd().resolve()
    return Path(root).expanduser().resolve()


def _backend_port(request: Request) -> int | None:
    port = getattr(request.app.state, "backend_port", None)
    return port if isinstance(port, int) else None


def _find_run_dir(project_root: Path, episode_id: str) -> Path:
    if "/" in episode_id or "\\" in episode_id or episode_id in {"", ".", ".."}:
        raise _run_not_found(episode_id)
    for run in list_runs(project_root=project_root):
        if run.episode_id == episode_id:
            return Path(run.path)
    raise _run_not_found(episode_id)


def _translate_config_errors(action: Callable[[], _T]) -> _T:
    try:
        return action()
    except yaml.YAMLError as exc:
        raise ApiException(
            status_code=400,
            code=M_E_CONFIG_INVALID,
            message="invalid desktop configuration",
            details={
                "error": str(exc),
                "exception_type": type(exc).__name__,
            },
        ) from exc
    except FileNotFoundError as exc:
        raise ApiException(
            status_code=404,
            code=M_E_CONFIG_INVALID,
            message=str(exc),
            details={"exception_type": type(exc).__name__},
        ) from exc
    except ValueError as exc:
        raise ApiException(
            status_code=400,
            code=M_E_CONFIG_INVALID,
            message=str(exc),
            details={"exception_type": type(exc).__name__},
        ) from exc


def _run_not_found(episode_id: str) -> ApiException:
    return ApiException(
        status_code=404,
        code=M_E_EPISODE_NOT_FOUND,
        message="run not found",
        details={"episode_id": episode_id},
    )


__all__ = ["router"]
