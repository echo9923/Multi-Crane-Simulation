from __future__ import annotations

import uuid
import threading
import time
import copy
import inspect
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Optional

from backend.app.core.config_loader import apply_overrides, load_demo_config
from backend.app.core.config_resolver import resolve_config
from backend.app.core.secret_resolver import resolve_provider_secrets
from backend.app.api.desktop_llm_settings import resolve_local_api_key
from backend.app.schemas.enums import LLMProviderName, RuntimeMode
from backend.app.sim.task_generation import TaskGenerationError
from backend.app.schemas.config import DatasetConfig, ExperimentConfig, ScenarioConfig
from backend.app.schemas.recorder import SimFrame
from backend.app.schemas.scheduler import EpisodeStatus

from .config_paths import resolve_config_path_for_request
from .errors import ApiException, config_api_error_from_exception
from .schemas import (
    EpisodeControlResponse,
    EpisodeStartRequest,
    EpisodeStartResponse,
    M_E_CONFIG_INVALID,
    M_E_EPISODE_NOT_FOUND,
    M_E_EPISODE_START_FAILED,
    M_E_INVALID_EPISODE_STATE,
)

RunnerFactory = Callable[..., Any]
DESKTOP_START_PROVIDERS = {
    LLMProviderName.DEEPSEEK,
    LLMProviderName.MINIMAX,
    LLMProviderName.SILICONFLOW,
}


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
    advance_lock: Any = field(default_factory=threading.RLock)
    worker_stop: threading.Event = field(default_factory=threading.Event)
    worker_thread: Optional[threading.Thread] = None


@dataclass(frozen=True)
class EpisodeStateSnapshot:
    episode_id: str
    status: str
    frame_index: int
    time_s: float
    run_dir: Optional[Path]
    last_frame: Optional[SimFrame]
    terminal_reason: Optional[str]


class EpisodeService:
    def __init__(
        self,
        *,
        runner_factory: RunnerFactory,
        project_root: Optional[Path] = None,
        data_root: Optional[Path] = None,
    ) -> None:
        self.runner_factory = runner_factory
        self.project_root = project_root
        self.data_root = data_root or project_root
        self.handles: dict[str, EpisodeHandle] = {}
        self._handles_lock = threading.RLock()

    def start_episode(self, request: EpisodeStartRequest) -> EpisodeStartResponse:
        episode_id = request.episode_id or _new_episode_id()
        _validate_public_start_request(request)
        with self._handles_lock:
            if episode_id in self.handles:
                raise ApiException(
                    status_code=409,
                    code=M_E_INVALID_EPISODE_STATE,
                    message="episode already exists",
                    details={"episode_id": episode_id},
                )

        resolved_config = self._resolve_start_config(request)
        resolved_config = _with_data_root_run_root(resolved_config, self.data_root)
        try:
            factory = _runner_factory_for_request(request, self.runner_factory)
            runner = factory(
                episode_id=episode_id,
                resolved_config=resolved_config,
                **_runner_root_kwargs(
                    factory,
                    project_root=self.project_root,
                    data_root=self.data_root,
                ),
            )
        except TaskGenerationError as exc:
            raise ApiException(
                status_code=422,
                code=M_E_EPISODE_START_FAILED,
                message=str(exc),
                details={
                    "episode_id": episode_id,
                    "exception_type": type(exc).__name__,
                    "config_error_code": exc.error_code,
                    "reason": exc.reason,
                    **exc.details,
                },
            ) from exc
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

        with self._handles_lock:
            if episode_id in self.handles:
                raise ApiException(
                    status_code=409,
                    code=M_E_INVALID_EPISODE_STATE,
                    message="episode already exists",
                    details={"episode_id": episode_id},
                )
            self.handles[episode_id] = handle

        if request.autostart and not _needs_background_worker(request, handle):
            self._advance_handle_once(handle)

        if request.autostart and _needs_background_worker(request, handle):
            self._start_background_worker(handle)
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
        with handle.advance_lock:
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
        with handle.advance_lock:
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
        with handle.advance_lock:
            previous = _display_status(handle)
            if _is_terminal_status(handle.status):
                return EpisodeControlResponse(
                    episode_id=episode_id,
                    previous_status=previous,
                    status=handle.status.value,
                    accepted=False,
                    reason="already_terminal",
                )
            if handle.status is not EpisodeStatus.RUNNING:
                raise _invalid_state(episode_id, "episode cannot be stopped", previous)
            handle.paused = False
        handle.runner.stop("api stop")
        self._advance_handle_once(handle)
        handle.worker_stop.set()
        return EpisodeControlResponse(
            episode_id=episode_id,
            previous_status=previous,
            status=handle.status.value,
            accepted=True,
            reason=handle.terminal_reason,
        )

    def get_handle(self, episode_id: str) -> EpisodeHandle:
        with self._handles_lock:
            try:
                return self.handles[episode_id]
            except KeyError as exc:
                raise ApiException(
                    status_code=404,
                    code=M_E_EPISODE_NOT_FOUND,
                    message="episode not found",
                    details={"episode_id": episode_id},
                ) from exc

    def snapshot_state(self, episode_id: str) -> EpisodeStateSnapshot:
        handle = self.get_handle(episode_id)
        with handle.advance_lock:
            last_frame = _runner_last_frame(handle.runner) or handle.last_frame
            run_dir = _runner_run_dir(handle.runner) or handle.run_dir
            frame_index = handle.frame_index
            time_s = handle.time_s
            if last_frame is not None and frame_index == 0 and time_s == 0.0:
                frame_index = last_frame.frame
                time_s = last_frame.time_s
            return EpisodeStateSnapshot(
                episode_id=episode_id,
                status=_display_status(handle),
                frame_index=frame_index,
                time_s=time_s,
                run_dir=run_dir,
                last_frame=last_frame,
                terminal_reason=handle.terminal_reason,
            )

    def _advance_handle_once(self, handle: EpisodeHandle) -> None:
        with handle.advance_lock:
            result = handle.runner.run_one_frame()
            handle.status = EpisodeStatus(result.status)
            handle.frame_index = result.frame_index
            handle.time_s = result.time_s
            handle.run_dir = _runner_run_dir(handle.runner) or handle.run_dir
            handle.last_frame = _runner_last_frame(handle.runner) or handle.last_frame
            if handle.status is not EpisodeStatus.RUNNING:
                handle.paused = False
                handle.terminal_reason = (
                    getattr(result, "reason", None)
                    or _runner_terminal_reason(handle.runner)
                    or handle.status.value
                )

    def _start_background_worker(self, handle: EpisodeHandle) -> None:
        if handle.worker_thread is not None and handle.worker_thread.is_alive():
            return
        handle.worker_stop.clear()
        handle.worker_thread = threading.Thread(
            target=self._background_worker,
            args=(handle,),
            name=f"episode-worker-{handle.episode_id}",
            daemon=True,
        )
        handle.worker_thread.start()

    def _background_worker(self, handle: EpisodeHandle) -> None:
        while not handle.worker_stop.is_set():
            with handle.advance_lock:
                if handle.status is not EpisodeStatus.RUNNING:
                    break
                paused = handle.paused
            if paused:
                handle.worker_stop.wait(0.1)
                continue

            started_at = time.monotonic()
            try:
                self._advance_handle_once(handle)
            except Exception as exc:
                with handle.advance_lock:
                    handle.status = EpisodeStatus.FAILED_INVALID_STATE
                    handle.paused = False
                    handle.terminal_reason = str(exc)
                    handle.run_dir = _runner_run_dir(handle.runner) or handle.run_dir
                    handle.last_frame = _runner_last_frame(handle.runner) or handle.last_frame
                break

            with handle.advance_lock:
                if handle.status is not EpisodeStatus.RUNNING:
                    break
                delay_base_s = _runner_frame_delay_s(handle.runner)
            elapsed_s = time.monotonic() - started_at
            delay_s = max(0.0, delay_base_s - elapsed_s)
            handle.worker_stop.wait(delay_s)

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

        config_path: Path | str | None = request.config_path
        try:
            overrides = _request_overrides_with_run_mode(request)
            if request.config_path is not None:
                config_path = resolve_config_path_for_request(
                    request.config_path,
                    SimpleNamespace(project_root=self.project_root),
                )
                scenario, experiment, dataset = load_demo_config(
                    config_path,
                    overrides=overrides,
                )
            else:
                config_path = None
                scenario, experiment, dataset = _load_inline_start_config(
                    request,
                    overrides=overrides,
                )
            if experiment is None:
                raise ValueError("episode start config must include experiment section")
            _validate_public_start_experiment(experiment)
            provider_summary = _provider_summary_for_desktop(
                experiment,
                project_root=self.data_root or self.project_root,
                require_start_key=True,
            )
            return resolve_config(
                scenario,
                experiment,
                dataset,
                provider_summary=provider_summary,
            )
        except ApiException:
            raise
        except Exception as exc:
            raise config_api_error_from_exception(
                exc,
                config_kind="scenario",
                source_file=str(config_path) if request.config_path is not None else None,
                field_path="config_path" if request.config_path is not None else None,
                forbidden_secret_values=_inline_secret_values(request.experiment),
            ) from exc


def _new_episode_id() -> str:
    return f"E-{uuid.uuid4().hex[:12]}"


def _validate_public_start_request(request: EpisodeStartRequest) -> None:
    if request.runner not in (None, "production"):
        raise ApiException(
            status_code=422,
            code=M_E_CONFIG_INVALID,
            message="普通启动入口只允许 production runner。",
            details={"field_path": "runner", "runner": request.runner},
        )


def _validate_public_start_experiment(experiment: ExperimentConfig) -> None:
    provider = experiment.llm.provider
    if provider not in DESKTOP_START_PROVIDERS:
        raise ApiException(
            status_code=422,
            code=M_E_CONFIG_INVALID,
            message=(
                f"普通启动入口不允许 provider {provider.value}。"
                "请选择 DeepSeek、MiniMax 或 SiliconFlow 并保存本机 API Key。"
            ),
            details={
                "field_path": "experiment.llm.provider",
                "provider": provider.value,
            },
        )


def _has_inline_start_config(request: EpisodeStartRequest) -> bool:
    return any(
        value is not None
        for value in (request.scenario, request.experiment, request.dataset)
    )


def _load_inline_start_config(
    request: EpisodeStartRequest,
    *,
    overrides: dict[str, Any],
) -> tuple[ScenarioConfig, ExperimentConfig, Optional[DatasetConfig]]:
    if request.scenario is None or request.experiment is None:
        missing = "scenario" if request.scenario is None else "experiment"
        raise ApiException(
            status_code=422,
            code=M_E_EPISODE_START_FAILED,
            message="Inline episode start requires scenario and experiment sections",
            details={"field_path": missing},
        )

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


def _is_terminal_status(status: EpisodeStatus) -> bool:
    return status is not EpisodeStatus.RUNNING


def _invalid_state(episode_id: str, message: str, status: str) -> ApiException:
    return ApiException(
        status_code=409,
        code=M_E_INVALID_EPISODE_STATE,
        message=message,
        details={"episode_id": episode_id, "status": status},
    )


def _needs_background_worker(
    request: EpisodeStartRequest,
    handle: EpisodeHandle,
) -> bool:
    return handle.status is EpisodeStatus.RUNNING and (
        request.run_mode == "interactive_server" or _runner_is_interactive(handle.runner)
    )


def _runner_is_interactive(runner: Any) -> bool:
    inner = getattr(runner, "runner", runner)
    config = getattr(inner, "config", None)
    run_mode = getattr(config, "run_mode", None)
    return run_mode == RuntimeMode.INTERACTIVE_SERVER or run_mode == "interactive_server"


def _runner_frame_delay_s(runner: Any) -> float:
    inner = getattr(runner, "runner", runner)
    config = getattr(inner, "config", None)
    dt_s = getattr(config, "dt_s", None)
    try:
        value = float(dt_s)
    except (TypeError, ValueError):
        return 0.1
    if value <= 0:
        return 0.1
    return min(max(value, 0.02), 1.0)


def _resolved_run_dir(resolved_config: Any) -> Optional[Path]:
    output = getattr(resolved_config, "output", None)
    if output is None:
        return None
    run_root = getattr(output, "run_root", None)
    if run_root is None and isinstance(output, dict):
        run_root = output.get("run_root")
    return Path(run_root) if run_root else None


def _with_data_root_run_root(resolved_config: Any, data_root: Optional[Path]) -> Any:
    if data_root is None:
        return resolved_config
    output = getattr(resolved_config, "output", None)
    if output is None:
        return resolved_config
    run_root = getattr(output, "run_root", None)
    if run_root is None and isinstance(output, dict):
        run_root = output.get("run_root")
    if run_root in (None, ""):
        run_root = "runs"
    path = Path(run_root)
    if path.is_absolute():
        return resolved_config
    resolved_run_root = (Path(data_root).expanduser().resolve() / path).resolve()
    next_output = (
        output.model_copy(update={"run_root": str(resolved_run_root)})
        if hasattr(output, "model_copy")
        else {**dict(output), "run_root": str(resolved_run_root)}
        if isinstance(output, dict)
        else output
    )
    if next_output is output:
        return resolved_config
    return (
        resolved_config.model_copy(update={"output": next_output})
        if hasattr(resolved_config, "model_copy")
        else resolved_config
    )


def _runner_run_dir(runner: Any) -> Optional[Path]:
    recorder = getattr(runner, "recorder", None)
    run_dir = getattr(recorder, "run_dir", None)
    return Path(run_dir) if run_dir is not None else None


def _runner_last_frame(runner: Any) -> Optional[SimFrame]:
    for candidate in (
        runner,
        getattr(runner, "recorder", None),
        getattr(getattr(runner, "recorder", None), "recorder", None),
    ):
        frame = getattr(candidate, "last_frame", None)
        if frame is not None:
            return frame
    return None


def _runner_terminal_reason(runner: Any) -> Optional[str]:
    for candidate in (runner, getattr(runner, "runner", None)):
        value = getattr(candidate, "terminal_reason", None)
        if isinstance(value, str) and value:
            return value
        terminal = getattr(candidate, "terminal_candidate", None)
        reason = getattr(terminal, "reason", None)
        if isinstance(reason, str) and reason:
            return reason
    return None


def _request_overrides_with_run_mode(request: EpisodeStartRequest) -> dict[str, Any]:
    overrides = copy.deepcopy(request.overrides or {})
    if request.run_mode is not None:
        experiment = overrides.setdefault("experiment", {})
        if not isinstance(experiment, dict):
            experiment = {}
            overrides["experiment"] = experiment
        runtime = experiment.setdefault("runtime", {})
        if not isinstance(runtime, dict):
            runtime = {}
            experiment["runtime"] = runtime
        runtime["mode"] = request.run_mode
    return overrides


def default_runner_factory(
    *,
    episode_id: str,
    resolved_config: Any,
    project_root: Optional[Path] = None,
    data_root: Optional[Path] = None,
) -> Any:
    from .production_runner import build_production_episode_runner

    return build_production_episode_runner(
        episode_id=episode_id,
        resolved_config=resolved_config,
        project_root=project_root,
        data_root=data_root,
    )


def _provider_summary_for_desktop(
    experiment: ExperimentConfig,
    *,
    project_root: Optional[Path],
    require_start_key: bool = False,
) -> Any:
    if project_root is None:
        return None
    llm = experiment.llm
    local_api_key = resolve_local_api_key(project_root, provider=llm.provider)
    llm_for_start = llm.model_copy(update={"enabled": True}) if require_start_key else llm
    return resolve_provider_secrets(
        llm_for_start,
        local_api_key=local_api_key,
    ).persisted_summary


def local_runner_factory(
    *,
    episode_id: str,
    resolved_config: Any,
    project_root: Optional[Path] = None,
    data_root: Optional[Path] = None,
) -> Any:
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


def _runner_root_kwargs(
    factory: RunnerFactory,
    *,
    project_root: Optional[Path],
    data_root: Optional[Path],
) -> dict[str, Optional[Path]]:
    try:
        signature = inspect.signature(factory)
    except (TypeError, ValueError):
        return {}
    if any(
        parameter.kind is inspect.Parameter.VAR_KEYWORD
        for parameter in signature.parameters.values()
    ):
        return {"project_root": project_root, "data_root": data_root}
    result: dict[str, Optional[Path]] = {}
    if "project_root" in signature.parameters:
        result["project_root"] = project_root
    if "data_root" in signature.parameters:
        result["data_root"] = data_root
    return result


__all__ = [
    "EpisodeHandle",
    "EpisodeService",
    "default_runner_factory",
    "local_runner_factory",
]
