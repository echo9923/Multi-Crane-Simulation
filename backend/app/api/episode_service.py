from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

from backend.app.core.config_loader import apply_overrides, load_demo_config
from backend.app.core.config_resolver import resolve_config
from backend.app.core.secret_resolver import resolve_provider_secrets
from backend.app.api.desktop_llm_settings import resolve_local_api_key
from backend.app.schemas.config import DatasetConfig, ExperimentConfig, ScenarioConfig
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
    def __init__(
        self,
        *,
        runner_factory: RunnerFactory,
        project_root: Optional[Path] = None,
    ) -> None:
        self.runner_factory = runner_factory
        self.project_root = project_root
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
            factory = _runner_factory_for_request(request, self.runner_factory)
            runner = factory(
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
            run_dir=_runner_run_dir(runner) or _resolved_run_dir(resolved_config),
            status=_runner_status(runner),
        )

        if request.autostart:
            self._advance_handle_once(handle)
            handle.run_dir = _runner_run_dir(runner) or handle.run_dir

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
        handle.run_dir = _runner_run_dir(handle.runner) or handle.run_dir
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
        has_inline = _has_inline_start_config(request)
        if request.config_path is not None and has_inline:
            raise ApiException(
                status_code=422,
                code=M_E_EPISODE_START_FAILED,
                message="Episode start cannot combine config_path with inline config payload",
                details={
                    "field_path": "config_path",
                    "source_file": request.config_path,
                },
            )
        if request.config_path is None and not has_inline:
            raise ApiException(
                status_code=422,
                code=M_E_EPISODE_START_FAILED,
                message=(
                    "Episode start requires either config_path or inline "
                    "scenario and experiment sections"
                ),
                details={"field_path": "scenario"},
            )

        try:
            if request.config_path is not None:
                scenario, experiment, dataset = load_demo_config(
                    request.config_path,
                    overrides=request.overrides,
                )
            else:
                scenario, experiment, dataset = _load_inline_start_config(request)
            if experiment is None:
                raise ValueError("episode start config must include experiment section")
            return resolve_config(
                scenario,
                experiment,
                dataset,
                provider_summary=_provider_summary_for_desktop(
                    experiment,
                    project_root=self.project_root,
                ),
            )
        except ApiException:
            raise
        except Exception as exc:
            raise config_api_error_from_exception(
                exc,
                config_kind="scenario",
                source_file=request.config_path,
                forbidden_secret_values=_inline_secret_values(request.experiment),
            ) from exc


def _new_episode_id() -> str:
    return f"E-{uuid.uuid4().hex[:12]}"


def _has_inline_start_config(request: EpisodeStartRequest) -> bool:
    return any(
        value is not None
        for value in (request.scenario, request.experiment, request.dataset)
    )


def _load_inline_start_config(
    request: EpisodeStartRequest,
) -> tuple[ScenarioConfig, ExperimentConfig, Optional[DatasetConfig]]:
    if request.scenario is None or request.experiment is None:
        missing = "scenario" if request.scenario is None else "experiment"
        raise ApiException(
            status_code=422,
            code=M_E_EPISODE_START_FAILED,
            message="Inline episode start requires scenario and experiment sections",
            details={"field_path": missing},
        )

    overrides = request.overrides or {}
    forbidden_secret_values = _inline_secret_values(request.experiment)
    scenario = _validate_inline_section(
        request.scenario,
        overrides.get("scenario"),
        ScenarioConfig,
        "scenario",
        forbidden_secret_values=forbidden_secret_values,
    )
    experiment = _validate_inline_section(
        request.experiment,
        overrides.get("experiment"),
        ExperimentConfig,
        "experiment",
        forbidden_secret_values=forbidden_secret_values,
    )
    dataset = (
        _validate_inline_section(
            request.dataset,
            overrides.get("dataset"),
            DatasetConfig,
            "dataset",
            forbidden_secret_values=forbidden_secret_values,
        )
        if request.dataset is not None
        else None
    )
    return scenario, experiment, dataset


def _validate_inline_section(
    raw: dict[str, Any],
    overrides: Any,
    model_class: type[Any],
    config_kind: str,
    *,
    forbidden_secret_values: list[str],
) -> Any:
    try:
        merged = apply_overrides(raw, overrides)
        return model_class.model_validate(merged)
    except Exception as exc:
        raise config_api_error_from_exception(
            exc,
            config_kind=config_kind,
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


def _runner_run_dir(runner: Any) -> Optional[Path]:
    recorder = getattr(runner, "recorder", None)
    run_dir = getattr(recorder, "run_dir", None)
    return Path(run_dir) if run_dir is not None else None


def default_runner_factory(*, episode_id: str, resolved_config: Any) -> Any:
    from .production_runner import build_production_episode_runner

    return build_production_episode_runner(
        episode_id=episode_id,
        resolved_config=resolved_config,
    )


def _provider_summary_for_desktop(
    experiment: ExperimentConfig,
    *,
    project_root: Optional[Path],
) -> Any:
    if project_root is None:
        return None
    llm = experiment.llm
    local_api_key = resolve_local_api_key(project_root, provider=llm.provider)
    return resolve_provider_secrets(llm, local_api_key=local_api_key).persisted_summary


def local_runner_factory(*, episode_id: str, resolved_config: Any) -> Any:
    from .local_runner import build_local_episode_runner

    return build_local_episode_runner(
        episode_id=episode_id,
        resolved_config=resolved_config,
    )


def _runner_factory_for_request(
    request: EpisodeStartRequest,
    fallback: RunnerFactory,
) -> RunnerFactory:
    if request.runner is None or request.runner == "production":
        return fallback
    if request.runner == "local":
        return local_runner_factory
    return fallback


__all__ = [
    "EpisodeHandle",
    "EpisodeService",
    "default_runner_factory",
    "local_runner_factory",
]
