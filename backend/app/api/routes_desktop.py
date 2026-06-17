from __future__ import annotations

from pathlib import Path
from typing import Callable, TypeVar

import yaml
from fastapi import APIRouter, Request

from .desktop_context import resolve_desktop_project_root
from .desktop_service import (
    apply_config_patch,
    environment_report,
    load_latest_experiment_draft,
    list_desktop_templates,
    list_recent_experiments,
    list_run_files,
    list_runs,
    render_template_yaml,
    save_experiment_draft,
)
from .desktop_llm_settings import (
    DesktopLLMSettingsError,
    delete_provider_secret,
    list_provider_summaries,
    provider_from_path,
    save_provider_secret,
    test_provider_connectivity,
)
from .errors import ApiException
from .schemas import (
    ApiResponse,
    DesktopConfigPatchRequest,
    DesktopConfigRenderRequest,
    DesktopConfigTextResponse,
    DesktopExperimentDraftLatestResponse,
    DesktopExperimentDraftRequest,
    DesktopLLMConnectivityTestRequest,
    DesktopLLMConnectivityTestResponse,
    DesktopLLMProviderSummary,
    DesktopLLMProvidersResponse,
    DesktopLLMSecretSaveRequest,
    DesktopRecentExperimentsResponse,
    DesktopRunFilesResponse,
    DesktopRunsResponse,
    DesktopTemplatesResponse,
    M_E_CONFIG_INVALID,
    M_E_EPISODE_NOT_FOUND,
    M_E_LLM_SETTINGS_INVALID,
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


@router.get("/experiments/draft/latest", response_model=ApiResponse)
def get_latest_desktop_experiment_draft(request: Request) -> ApiResponse:
    draft = _translate_config_errors(
        lambda: load_latest_experiment_draft(project_root=_project_root(request))
    )
    response = DesktopExperimentDraftLatestResponse(
        experiment_id=draft.experiment_id if draft is not None else None,
        yaml_text=draft.yaml_text if draft is not None else None,
        metadata=draft.metadata if draft is not None else None,
        updated_at=draft.updated_at if draft is not None else None,
    )
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


@router.get("/llm/providers", response_model=ApiResponse)
def get_desktop_llm_providers(request: Request) -> ApiResponse:
    summaries = list_provider_summaries(project_root=_project_root(request))
    response = DesktopLLMProvidersResponse(
        items=[DesktopLLMProviderSummary(**summary.__dict__) for summary in summaries]
    )
    return ApiResponse(data=response.model_dump(mode="json"))


@router.post("/llm/providers/{provider}/secret", response_model=ApiResponse)
def save_desktop_llm_provider_secret(
    request: Request,
    provider: str,
    payload: DesktopLLMSecretSaveRequest,
) -> ApiResponse:
    summary = _translate_llm_settings_errors(
        lambda: save_provider_secret(
            project_root=_project_root(request),
            provider=provider_from_path(provider),
            api_key=payload.api_key,
            base_url=payload.base_url,
            model=payload.model,
        )
    )
    response = DesktopLLMProviderSummary(**summary.__dict__)
    return ApiResponse(data=response.model_dump(mode="json"))


@router.delete("/llm/providers/{provider}/secret", response_model=ApiResponse)
def delete_desktop_llm_provider_secret(request: Request, provider: str) -> ApiResponse:
    summary = _translate_llm_settings_errors(
        lambda: delete_provider_secret(
            project_root=_project_root(request),
            provider=provider_from_path(provider),
        )
    )
    response = DesktopLLMProviderSummary(**summary.__dict__)
    return ApiResponse(data=response.model_dump(mode="json"))


@router.post("/llm/providers/{provider}/test", response_model=ApiResponse)
def test_desktop_llm_provider(
    request: Request,
    provider: str,
    payload: DesktopLLMConnectivityTestRequest,
) -> ApiResponse:
    result = _translate_llm_settings_errors(
        lambda: test_provider_connectivity(
            project_root=_project_root(request),
            provider=provider_from_path(provider),
            api_key=payload.api_key,
            base_url=payload.base_url,
            model=payload.model,
        )
    )
    response = DesktopLLMConnectivityTestResponse(**result.__dict__)
    return ApiResponse(data=response.model_dump(mode="json"))


def _project_root(request: Request) -> Path:
    return resolve_desktop_project_root(request.app)


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


def _translate_llm_settings_errors(action: Callable[[], _T]) -> _T:
    try:
        return action()
    except (DesktopLLMSettingsError, ValueError) as exc:
        raise ApiException(
            status_code=400,
            code=M_E_LLM_SETTINGS_INVALID,
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
