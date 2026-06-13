from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter

from backend.app.core.config_loader import load_demo_config
from backend.app.core.config_resolver import resolve_config
from backend.app.schemas.config import DatasetConfig, ExperimentConfig, ScenarioConfig

from .errors import ConfigValidationApiError, config_api_error_from_exception
from .schemas import (
    API_SCHEMA_VERSION,
    ApiResponse,
    ScenarioValidateRequest,
    ScenarioValidateResult,
)

router = APIRouter()


@router.get("/health", response_model=ApiResponse)
def health() -> ApiResponse:
    return ApiResponse(
        data={
            "status": "ok",
            "api_schema_version": API_SCHEMA_VERSION,
            "modules": {
                "api": "available",
                "config": "available",
                "scheduler": "available",
                "recorder": "available",
            },
        }
    )


@router.post("/scenarios/validate", response_model=ApiResponse)
def validate_scenario(request: ScenarioValidateRequest) -> ApiResponse:
    resolved = _resolve_request_config(request)
    result = ScenarioValidateResult(
        valid=True,
        resolved_config_hash=resolved.resolved_config_hash,
    )
    return ApiResponse(data=result.model_dump(mode="json"))


def _resolve_request_config(request: ScenarioValidateRequest) -> Any:
    has_inline = any(
        value is not None
        for value in (request.scenario, request.experiment, request.dataset)
    )
    if request.config_path and has_inline:
        raise ConfigValidationApiError(
            "config_path cannot be combined with inline config payload",
            details={
                "config_kind": "scenario",
                "field_path": "config_path",
                "source_file": request.config_path,
            },
            status_code=400,
        )
    if request.config_path:
        return _resolve_config_path(request)
    if request.scenario is not None:
        return _resolve_inline_config(request)
    raise ConfigValidationApiError(
        "either config_path or scenario must be provided",
        details={"config_kind": "scenario", "field_path": "scenario"},
    )


def _resolve_config_path(request: ScenarioValidateRequest) -> Any:
    try:
        scenario, experiment, dataset = load_demo_config(
            request.config_path,
            overrides=request.overrides,
        )
        if experiment is None:
            raise ValueError("demo config must include experiment section")
        return resolve_config(scenario, experiment, dataset)
    except Exception as exc:
        raise config_api_error_from_exception(
            exc,
            config_kind="scenario",
            source_file=request.config_path,
        ) from exc


def _resolve_inline_config(request: ScenarioValidateRequest) -> Any:
    forbidden_secret_values = _inline_secret_values(request.experiment)
    try:
        scenario = ScenarioConfig.model_validate(request.scenario)
        if request.experiment is None:
            raise ValueError("inline config must include experiment")
        experiment = ExperimentConfig.model_validate(request.experiment)
        dataset = (
            DatasetConfig.model_validate(request.dataset)
            if request.dataset is not None
            else None
        )
        return resolve_config(scenario, experiment, dataset)
    except Exception as exc:
        raise config_api_error_from_exception(
            exc,
            config_kind="scenario",
            forbidden_secret_values=forbidden_secret_values,
        ) from exc


def _inline_secret_values(experiment: Optional[dict[str, Any]]) -> list[str]:
    if not isinstance(experiment, dict):
        return []
    llm = experiment.get("llm")
    if not isinstance(llm, dict):
        return []
    value = llm.get("api_key")
    return [value] if isinstance(value, str) and value else []


__all__ = ["router"]
