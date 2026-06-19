from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Request

from backend.app.core.config_loader import load_demo_config
from backend.app.core.config_resolver import resolve_config
from backend.app.schemas.config import DatasetConfig, ExperimentConfig, ScenarioConfig
from backend.app.schemas.crane import CraneConfig
from backend.app.schemas.errors import ConfigError
from backend.app.api.production_runner import scenario_config_from_resolved
from backend.app.sim.task_generation import TaskGenerationError, generate_task_queues

from .config_paths import resolve_config_path_for_request
from .errors import (
    ConfigValidationApiError,
    config_api_error_from_config_error,
    config_api_error_from_exception,
)
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
def validate_scenario(http_request: Request, request: ScenarioValidateRequest) -> ApiResponse:
    resolved = _resolve_request_config(request, http_request.app)
    _validate_task_generation(resolved)
    result = ScenarioValidateResult(
        valid=True,
        resolved_config_hash=resolved.resolved_config_hash,
    )
    return ApiResponse(data=result.model_dump(mode="json"))


def _resolve_request_config(request: ScenarioValidateRequest, app: Any = None) -> Any:
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
        return _resolve_config_path(request, app)
    if request.scenario is not None:
        return _resolve_inline_config(request)
    raise ConfigValidationApiError(
        "either config_path or scenario must be provided",
        details={"config_kind": "scenario", "field_path": "scenario"},
    )


def _resolve_config_path(request: ScenarioValidateRequest, app: Any = None) -> Any:
    config_path = request.config_path
    try:
        if app is not None:
            config_path = resolve_config_path_for_request(request.config_path, app)
        scenario, experiment, dataset = load_demo_config(
            config_path,
            overrides=request.overrides,
        )
        if experiment is None:
            raise ValueError("demo config must include experiment section")
        return resolve_config(scenario, experiment, dataset)
    except Exception as exc:
        raise config_api_error_from_exception(
            exc,
            config_kind="scenario",
            source_file=str(config_path),
            field_path="config_path",
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


def _validate_task_generation(resolved_config: Any) -> None:
    try:
        scenario = scenario_config_from_resolved(resolved_config)
        if scenario.tasks.generation_mode.value != "manual":
            return
        crane_configs = [
            CraneConfig.model_validate(crane)
            for crane in resolved_config.layout.resolved_cranes
        ]
        result = generate_task_queues(
            scenario,
            crane_configs,
            seed=int(resolved_config.seeds.task),
        )
        if not result.tasks:
            raise TaskGenerationError(
                "task generation produced zero tasks",
                error_code="TASK_E_001",
                reason="no_tasks_generated",
                details={"num_cranes": len(crane_configs)},
            )
    except TaskGenerationError as exc:
        raise config_api_error_from_config_error(
            ConfigError(
                error_code=exc.error_code,
                message=str(exc),
                field_path="scenario.tasks",
                source_file=None,
                hint="Fix task zones, load types, crane reach, or manual_tasks before startup.",
                details={
                    "config_kind": "scenario",
                    "reason": exc.reason,
                    **exc.details,
                },
            )
        ) from exc


__all__ = ["router"]
