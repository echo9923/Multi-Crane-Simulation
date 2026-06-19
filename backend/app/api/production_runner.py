from __future__ import annotations

import copy
import math
import random
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Mapping, Optional, Sequence

from backend.app.api.desktop_context import resolve_desktop_project_root
from backend.app.api.desktop_llm_settings import resolve_local_api_key
from backend.app.core.secret_resolver import resolve_provider_secrets
from backend.app.schemas.command import ExecutedCommand, ParsedCommand
from backend.app.schemas.config import (
    ExperimentConfig,
    ForbiddenZonePolicyConfig,
    LLMConfig,
    RiskConfig,
    ScenarioConfig,
)
from backend.app.schemas.crane import CraneConfig
from backend.app.schemas.enums import (
    ForbiddenZonePolicyMode,
    LLMProviderName,
    OperatorAssignmentMode,
    OperatorProfile,
    RiskPromptMode,
    RuntimeMode,
    SafetyMode,
)
from backend.app.schemas.scheduler import (
    EpisodeResult,
    EpisodeStatus,
    SchedulerConfig,
)
from backend.app.schemas.state import CraneState
from backend.app.schemas.task import Task, TaskActionSignal, TaskQueue
from backend.app.schemas.weather import WeatherState, WeatherVisibilityContext
from backend.app.sim.collision import detect_collisions
from backend.app.sim.controller import Controller
from backend.app.sim.llm_provider import (
    LLMProvider,
    ProviderRequest,
    create_llm_provider,
)
from backend.app.sim.observation import build_observations_for_snapshot
from backend.app.sim.operator_decision import OperatorDecisionOrchestrator
from backend.app.sim.physics import initialize_crane_state, step_world
from backend.app.sim.recorder import Recorder
from backend.app.sim.risk import evaluate_online_risk
from backend.app.sim.safety import apply_safety_pipeline
from backend.app.sim.scheduler import (
    EpisodeRunner,
    SchedulerDependencies,
    build_system_neutral_executed_command,
    to_observation_snapshot,
)
from backend.app.sim.task_failure import (
    TaskFailureRuntimeState,
    handle_task_timing_and_failures,
)
from backend.app.sim.task_generation import TaskGenerationError, generate_task_queues
from backend.app.sim.task_observation import build_task_observation_context
from backend.app.sim.task_queue import (
    build_idle_observation_context,
    schedule_task_queues,
)
from backend.app.sim.task_state_machine import (
    TaskRuntimeState,
    step_task_state_machine,
)
from backend.app.sim.weather import WeatherGenerator, build_weather_visibility_context


_PROGRESS_EVENT_TYPES = {
    "task_stage_changed",
    "attach_pending_started",
    "attach_pending_cancelled",
    "load_attached",
    "release_pending_started",
    "release_pending_cancelled",
    "load_released",
    "task_completed",
    "recovery_release_completed",
}

_RELEASE_STAGES = {
    "move_to_dropoff",
    "align_dropoff",
    "lower_for_release",
    "release_pending",
    "recovery_release",
}


def build_production_episode_runner(
    *,
    episode_id: str,
    resolved_config: Any,
    websocket: Any = None,
    project_root: Any = None,
) -> "ProductionEpisodeRunner":
    scenario = scenario_config_from_resolved(resolved_config)
    experiment = ExperimentConfig.model_validate(_mapping_section(resolved_config, "experiment"))
    crane_configs = _crane_configs_from_resolved_config(resolved_config)
    crane_states = [initialize_crane_state(config) for config in crane_configs]
    task_generation = _generate_task_queues_for_production(
        scenario,
        crane_configs,
        seed=int(getattr(resolved_config.seeds, "task")),
    )
    weather = ProductionWeather(resolved_config=resolved_config)
    weather_state, visibility_context = weather.update(0.0)

    llm_config = experiment.llm
    provider = _provider_with_runtime_secret(llm_config, project_root=project_root)
    operator_profiles = _assign_operator_profiles(
        experiment=experiment,
        crane_ids=[config.crane_id for config in crane_configs],
        seed=int(getattr(resolved_config.seeds, "operator_assignment")),
    )
    operator_ids = {crane_id: f"OP_{crane_id}" for crane_id in operator_profiles}

    recorder = ProductionRecorderAdapter(
        Recorder.from_config(resolved_config),
        episode_id=episode_id,
        risk_config=scenario.risk,
        crane_configs=crane_configs,
    )
    scheduler_config = SchedulerConfig.from_config(resolved_config)
    if websocket is not None:
        scheduler_config = scheduler_config.model_copy(
            update={"run_mode": RuntimeMode.INTERACTIVE_SERVER}
        )
    dependencies = SchedulerDependencies(
        weather=weather,
        task_system=ProductionTaskSystem(
            scenario=scenario,
            crane_configs=crane_configs,
        ),
        observation_builder=ProductionObservationBuilder(
            risk_prompt_mode=experiment.risk_prompt_mode,
            operator_profiles=operator_profiles,
            operator_ids=operator_ids,
        ),
        operator=OperatorDecisionOrchestrator(
            config=llm_config,
            provider=provider,
            operator_profiles=operator_profiles,
        ),
        safety=ProductionSafetyAdapter(
            scenario=scenario,
            risk_config=scenario.risk,
            safety_mode=experiment.safety_mode,
            dt_s=scheduler_config.dt_s,
        ),
        controller=Controller.from_config(resolved_config),
        physics=ProductionPhysicsAdapter(),
        risk=ProductionRiskAdapter(
            risk_config=scenario.risk,
            crane_configs=crane_configs,
            weather_state=weather_state,
        ),
        collision=ProductionCollisionAdapter(
            risk_config=scenario.risk,
            crane_configs=crane_configs,
        ),
        recorder=recorder,
        websocket=websocket,
    )
    runner = EpisodeRunner(
        config=scheduler_config,
        dependencies=dependencies,
        episode_id=episode_id,
        crane_configs=crane_configs,
        crane_states=crane_states,
        weather_state=weather_state,
        visibility_context=visibility_context,
        tasks=task_generation.tasks,
        task_queues=task_generation.queues,
        task_contexts=_task_contexts(
            states=crane_states,
            queues=task_generation.queues,
            time_s=0.0,
            recent_events={},
            crane_configs_by_id={config.crane_id: config for config in crane_configs},
            state_machine_config=scenario.tasks.state_machine,
        ),
    )
    return ProductionEpisodeRunner(runner=runner, recorder=recorder)


@dataclass
class ProductionEpisodeRunner:
    runner: EpisodeRunner
    recorder: "ProductionRecorderAdapter"

    @property
    def episode_status(self) -> Any:
        return self.runner.episode_status

    def run_one_frame(self) -> Any:
        result = self.runner.run_one_frame()
        if result.status is not EpisodeStatus.RUNNING:
            if self.recorder.run_dir is None:
                self.runner._record_initial_frame()
            self.recorder.finalize(episode_status=result.status)
        return result

    def run_episode(self) -> EpisodeResult:
        result = self.runner.run_episode()
        self.recorder.finalize(episode_status=result.status)
        return result

    def stop(self, reason: str = "stopped_by_user") -> None:
        self.runner.stop(reason)


class ProductionWeather:
    def __init__(self, *, resolved_config: Any) -> None:
        self.seed = int(getattr(resolved_config.seeds, "weather"))
        self.generator = WeatherGenerator.from_resolved_config(resolved_config)

    def update(self, time_s: float) -> tuple[WeatherState, WeatherVisibilityContext]:
        result = self.generator.update(time_s)
        if result.weather_state is None:
            failure = result.failure_request or {}
            raise RuntimeError(failure.get("reason") or "weather update failed")
        visibility_context = build_weather_visibility_context(
            result.weather_state,
            weather_seed=self.seed,
            decision_time_bucket=result.weather_state.generation_step,
        )
        return result.weather_state, visibility_context


class ProductionTaskSystem:
    def __init__(
        self,
        *,
        scenario: ScenarioConfig,
        crane_configs: Sequence[CraneConfig],
    ) -> None:
        self.scenario = scenario
        self.crane_configs = {config.crane_id: config for config in crane_configs}
        self.state_machine_runtime: dict[str, TaskRuntimeState] = {}
        self.failure_runtime: dict[str, TaskFailureRuntimeState] = {}
        self._last_progress_signature: dict[
            str,
            tuple[str, tuple[float, float, float]],
        ] = {}
        self._recent_events: dict[str, list[Any]] = {}

    def activate_due_tasks(
        self,
        *,
        time_s: float,
        states: Sequence[CraneState],
        task_queues: Sequence[TaskQueue],
    ) -> SimpleNamespace:
        state_by_id = {state.crane_id: state for state in states}
        result = schedule_task_queues(task_queues, state_by_id, time_s=time_s)
        next_states = _apply_state_patches(states, result.state_patches)
        events = list(result.events)
        self._record_recent_events(events)
        return SimpleNamespace(
            queues=list(result.queues),
            states=next_states,
            events=events,
            task_contexts=_task_contexts(
                states=next_states,
                queues=result.queues,
                time_s=time_s,
                recent_events=self._recent_events,
                crane_configs_by_id=self.crane_configs,
                state_machine_config=self.scenario.tasks.state_machine,
            ),
        )

    def update_after_physics(
        self,
        *,
        states: Sequence[CraneState],
        commands: Mapping[str, ExecutedCommand],
        time_s: float,
        task_queues: Sequence[TaskQueue],
    ) -> SimpleNamespace:
        states_by_id = {state.crane_id: state for state in states}
        next_states_by_id = dict(states_by_id)
        next_queues = [copy.deepcopy(queue) for queue in task_queues]
        queue_by_crane = {queue.crane_id: queue for queue in next_queues}
        events: list[Any] = []

        for queue in list(next_queues):
            active_task = _active_task(queue)
            if active_task is None:
                continue
            state = next_states_by_id[queue.crane_id]
            command = commands.get(queue.crane_id)
            signal = _task_action_signal(
                state=state,
                command=command,
                time_s=time_s,
            )
            task_runtime = self.state_machine_runtime.get(
                active_task.task_id,
                TaskRuntimeState(),
            )
            sm_result = step_task_state_machine(
                active_task,
                self.crane_configs[queue.crane_id],
                state,
                signal,
                time_s=time_s,
                config=self.scenario.tasks.state_machine,
                runtime=task_runtime,
                attach_delay_s=self.scenario.tasks.attach_delay_s[0],
                release_delay_s=self.scenario.tasks.release_delay_s[0],
            )
            self.state_machine_runtime[sm_result.task.task_id] = sm_result.runtime
            next_state = sm_result.state
            next_queue = _replace_task_in_queue(queue, sm_result.task)
            if sm_result.task.status == "completed":
                next_queue = next_queue.model_copy(update={"active_task_id": None})
            failure_runtime = self.failure_runtime.get(
                sm_result.task.task_id,
                TaskFailureRuntimeState(last_progress_at_s=sm_result.task.started_at_s),
            )
            failure_runtime = self._advance_failure_runtime_for_progress(
                task_id=sm_result.task.task_id,
                state=next_state,
                runtime=failure_runtime,
                events=sm_result.events,
                time_s=time_s,
            )
            failure_result = handle_task_timing_and_failures(
                sm_result.task,
                next_state,
                self.scenario,
                self.crane_configs[queue.crane_id],
                time_s=time_s,
                runtime=failure_runtime,
                queue=next_queue,
            )
            self.failure_runtime[failure_result.task.task_id] = failure_result.runtime
            next_state = failure_result.state
            next_queue = _replace_task_in_queue(
                failure_result.queue or next_queue,
                failure_result.task,
            )
            if failure_result.recovery_task is not None:
                next_queue = next_queue.model_copy(
                    update={
                        "tasks": [*next_queue.tasks, failure_result.recovery_task],
                        "active_task_id": failure_result.recovery_task.task_id,
                    }
                )
            queue_by_crane[queue.crane_id] = next_queue
            next_states_by_id[queue.crane_id] = next_state
            events.extend(sm_result.events)
            events.extend(failure_result.events)

        ordered_queues = [queue_by_crane[queue.crane_id] for queue in next_queues]
        ordered_states = [
            next_states_by_id[state.crane_id]
            for state in states
        ]
        self._record_recent_events(events)
        return SimpleNamespace(
            queues=ordered_queues,
            states=ordered_states,
            events=events,
            task_contexts=_task_contexts(
                states=ordered_states,
                queues=ordered_queues,
                time_s=time_s,
                recent_events=self._recent_events,
                crane_configs_by_id=self.crane_configs,
                state_machine_config=self.scenario.tasks.state_machine,
            ),
        )

    def _record_recent_events(self, events: Sequence[Any]) -> None:
        for event in events:
            crane_id = getattr(event, "crane_id", None)
            if crane_id is None:
                continue
            bucket = self._recent_events.setdefault(str(crane_id), [])
            bucket.append(event)
            del bucket[:-12]

    def _advance_failure_runtime_for_progress(
        self,
        *,
        task_id: str,
        state: CraneState,
        runtime: TaskFailureRuntimeState,
        events: Sequence[Any],
        time_s: float,
    ) -> TaskFailureRuntimeState:
        update: dict[str, float] = {}
        if any(_event_type(event) in _PROGRESS_EVENT_TYPES for event in events):
            update["last_progress_at_s"] = time_s
        if (
            state.task_stage in _RELEASE_STAGES
            and runtime.release_stage_started_at_s is None
        ):
            update["release_stage_started_at_s"] = time_s
        if self._hook_progressed(task_id, state):
            update["last_progress_at_s"] = time_s
        if not update:
            return runtime
        return runtime.model_copy(update=update)

    def _hook_progressed(self, task_id: str, state: CraneState) -> bool:
        signature = (
            state.task_stage,
            (
                float(state.hook_position[0]),
                float(state.hook_position[1]),
                float(state.hook_position[2]),
            ),
        )
        previous = self._last_progress_signature.get(task_id)
        self._last_progress_signature[task_id] = signature
        if previous is None:
            return False
        previous_stage, previous_position = previous
        if previous_stage != state.task_stage:
            return False
        epsilon = self.scenario.tasks.state_machine.no_progress_xy_epsilon_m
        return math.dist(signature[1], previous_position) >= epsilon


class ProductionObservationBuilder:
    def __init__(
        self,
        *,
        risk_prompt_mode: RiskPromptMode,
        operator_profiles: Mapping[str, OperatorProfile],
        operator_ids: Mapping[str, str],
    ) -> None:
        self.risk_prompt_mode = RiskPromptMode(risk_prompt_mode)
        self.operator_profiles = dict(operator_profiles)
        self.operator_ids = dict(operator_ids)

    def build_batch(
        self,
        *,
        snapshot: Any,
        crane_ids: Sequence[str],
        risk_hints: Mapping[str, Any],
    ) -> list[Any]:
        observation_snapshot = to_observation_snapshot(
            snapshot,
            neighbor_map=_neighbor_map(snapshot.crane_states),
        )
        return build_observations_for_snapshot(
            snapshot=observation_snapshot,
            crane_ids=list(crane_ids),
            risk_prompt_mode=self.risk_prompt_mode,
            operator_profiles=self.operator_profiles,
            online_risks=dict(risk_hints),
            operator_ids=self.operator_ids,
        )


class ProductionSafetyAdapter:
    def __init__(
        self,
        *,
        scenario: ScenarioConfig,
        risk_config: RiskConfig,
        safety_mode: SafetyMode,
        dt_s: float,
    ) -> None:
        self.risk_config = risk_config
        self.safety_mode = SafetyMode(safety_mode)
        self.forbidden_zones = list(scenario.site.forbidden_zones)
        self.forbidden_zone_policy = _hard_or_default_policy(
            scenario.site.forbidden_zone_policy
        )
        self.dt_s = dt_s
        self.last_result: Any = None

    def apply_pipeline(
        self,
        parsed_commands: Sequence[ParsedCommand],
        *,
        snapshot: Any,
    ) -> list[ExecutedCommand]:
        result = apply_safety_pipeline(
            commands=list(parsed_commands),
            crane_states=list(snapshot.crane_states),
            crane_configs=list(snapshot.crane_configs),
            risk_config=self.risk_config,
            weather_state=snapshot.weather_state,
            safety_mode=self.safety_mode,
            forbidden_zones=self.forbidden_zones,
            forbidden_zone_policy=self.forbidden_zone_policy,
            source_snapshot_id=snapshot.snapshot_id,
            time_s=snapshot.time_s,
            dt_s=self.dt_s,
        )
        self.last_result = result
        return list(result.executed_commands)


class ProductionRiskAdapter:
    def __init__(
        self,
        *,
        risk_config: RiskConfig,
        crane_configs: Sequence[CraneConfig],
        weather_state: WeatherState,
    ) -> None:
        self.risk_config = risk_config
        self.crane_configs = [copy.deepcopy(config) for config in crane_configs]
        self.weather_state = copy.deepcopy(weather_state)

    def evaluate_predecision(
        self,
        *,
        snapshot: Any,
        commands: Mapping[str, ExecutedCommand],
    ) -> SimpleNamespace:
        self.weather_state = copy.deepcopy(snapshot.weather_state)
        online_risk = _evaluate_risk_with_complete_commands(
            states=list(snapshot.crane_states),
            configs=list(snapshot.crane_configs),
            commands=commands,
            risk_config=self.risk_config,
            weather_state=snapshot.weather_state,
            source_snapshot_id=snapshot.snapshot_id,
            time_s=snapshot.time_s,
        )
        return SimpleNamespace(hints=dict(online_risk.hint_by_crane), online_risk=online_risk)

    def evaluate_after_physics(
        self,
        *,
        states: Sequence[CraneState],
        commands: Mapping[str, ExecutedCommand],
        time_s: float,
    ) -> Any:
        return _evaluate_risk_with_complete_commands(
            states=list(states),
            configs=self.crane_configs,
            commands=commands,
            risk_config=self.risk_config,
            weather_state=self.weather_state.model_copy(update={"time_s": time_s}),
            source_snapshot_id=_source_snapshot_id(commands, time_s),
            time_s=time_s,
        )


class ProductionCollisionAdapter:
    def __init__(
        self,
        *,
        risk_config: RiskConfig,
        crane_configs: Sequence[CraneConfig],
    ) -> None:
        self.risk_config = risk_config
        self.crane_configs = [copy.deepcopy(config) for config in crane_configs]

    def detect(
        self,
        *,
        states: Sequence[CraneState],
        risk: Any,
        time_s: float,
    ) -> list[Any]:
        event = detect_collisions(
            crane_states=list(states),
            crane_configs=self.crane_configs,
            risk_config=self.risk_config,
            source_snapshot_id=getattr(risk, "source_snapshot_id", f"RISK_{time_s:.3f}"),
            time_s=time_s,
        )
        return [event] if event is not None else []


class ProductionPhysicsAdapter:
    def step_world(
        self,
        *,
        crane_configs: Sequence[CraneConfig],
        previous_states: Sequence[CraneState],
        control_targets: Sequence[Any],
        dt: float,
    ) -> list[CraneState]:
        return step_world(
            crane_configs,
            previous_states,
            control_targets,
            dt=dt,
        )


class ProductionRecorderAdapter:
    def __init__(
        self,
        recorder: Recorder,
        *,
        episode_id: str | None = None,
        risk_config: RiskConfig | None = None,
        crane_configs: Sequence[CraneConfig] = (),
    ) -> None:
        self.recorder = recorder
        self.episode_id = episode_id
        self.risk_config = risk_config
        self.crane_configs = [copy.deepcopy(config) for config in crane_configs]
        self._finalized = False
        self.last_frame: Any = None

    @property
    def layout(self) -> Any:
        return self.recorder.layout

    @property
    def run_dir(self) -> Optional[Path]:
        layout = self.recorder.layout
        if layout is not None:
            return layout.run_root
        if self.episode_id is None:
            return None
        output = getattr(self.recorder.resolved_config, "output", None)
        run_root = getattr(output, "run_root", None)
        return Path(run_root) / self.episode_id if run_root else None

    def record_initial_frame(self, **kwargs: Any) -> Any:
        if "online_risk" not in kwargs and self.risk_config is not None:
            kwargs["online_risk"] = _evaluate_risk_with_complete_commands(
                states=list(kwargs.get("states", [])),
                configs=self.crane_configs,
                commands=dict(kwargs.get("commands") or {}),
                risk_config=self.risk_config,
                weather_state=kwargs["weather_state"],
                source_snapshot_id=f"SNAP_{kwargs['episode_id']}_000000",
                time_s=float(kwargs.get("time_s", 0.0)),
            )
        frame = self.recorder.record_initial_frame(**kwargs)
        self.last_frame = frame
        return frame

    def record_step(self, **kwargs: Any) -> Any:
        frame = self.recorder.record_step(**kwargs)
        self.last_frame = frame
        return frame

    def finalize(self, *, episode_status: Any) -> Any:
        if self._finalized:
            return None
        self._finalized = True
        return self.recorder.finalize(episode_status=episode_status)

class RuntimeSecretProvider:
    def __init__(self, provider: LLMProvider, runtime_secret: Any) -> None:
        self.provider = provider
        self.provider_name = provider.provider_name
        self.runtime_secret = runtime_secret

    def generate(self, request: ProviderRequest) -> Any:
        return self.provider.generate(
            request.model_copy(update={"runtime_secret": self.runtime_secret})
        )


def _provider_with_runtime_secret(
    llm_config: LLMConfig,
    *,
    project_root: Any = None,
) -> LLMProvider:
    provider = create_llm_provider(llm_config)
    if llm_config.provider not in {
        LLMProviderName.DEEPSEEK,
        LLMProviderName.MINIMAX,
        LLMProviderName.SILICONFLOW,
    }:
        return provider
    secret_resolution = resolve_provider_secrets(
        llm_config,
        local_api_key=resolve_local_api_key(
            resolve_desktop_project_root(SimpleNamespace(project_root=project_root))
            if project_root is not None
            else resolve_desktop_project_root(SimpleNamespace()),
            provider=llm_config.provider,
        ),
    )
    return RuntimeSecretProvider(provider, secret_resolution.runtime_secret)


def _generate_task_queues_for_production(
    scenario: ScenarioConfig,
    crane_configs: Sequence[CraneConfig],
    *,
    seed: int,
) -> Any:
    result = generate_task_queues(scenario, crane_configs, seed=seed)
    if not result.tasks:
        raise TaskGenerationError(
            "task generation produced zero tasks",
            error_code="TASK_E_001",
            reason="no_tasks_generated",
            details={"num_cranes": len(crane_configs)},
        )
    return result


def _assign_operator_profiles(
    *,
    experiment: ExperimentConfig,
    crane_ids: Sequence[str],
    seed: int,
) -> dict[str, OperatorProfile]:
    assignment = experiment.operators
    distribution = dict(assignment.profile_distribution)
    if assignment.assignment_mode is OperatorAssignmentMode.MANUAL:
        profile = next(iter(distribution), OperatorProfile.NORMAL)
        return {crane_id: OperatorProfile(profile) for crane_id in crane_ids}
    rng = random.Random(seed)
    result: dict[str, OperatorProfile] = {}
    items = list(distribution.items())
    for crane_id in sorted(crane_ids):
        draw = rng.random()
        cumulative = 0.0
        chosen = items[-1][0] if items else OperatorProfile.NORMAL
        for profile, weight in items:
            cumulative += weight
            if draw <= cumulative:
                chosen = profile
                break
        result[crane_id] = OperatorProfile(chosen)
    return result


def _task_contexts(
    *,
    states: Sequence[CraneState],
    queues: Sequence[TaskQueue],
    time_s: float,
    recent_events: Mapping[str, Sequence[Any]],
    crane_configs_by_id: Mapping[str, CraneConfig] | None = None,
    state_machine_config: Any = None,
) -> dict[str, Any]:
    states_by_id = {state.crane_id: state for state in states}
    contexts: dict[str, Any] = {}
    for queue in queues:
        state = states_by_id[queue.crane_id]
        active_task = _active_task(queue)
        events = list(recent_events.get(queue.crane_id, []))
        if active_task is None:
            contexts[queue.crane_id] = build_idle_observation_context(
                queue,
                state,
                time_s=time_s,
            )
        else:
            contexts[queue.crane_id] = build_task_observation_context(
                queue.crane_id,
                state,
                active_task=active_task,
                time_s=time_s,
                recent_events=events,
                crane_config=(
                    crane_configs_by_id.get(queue.crane_id)
                    if crane_configs_by_id is not None
                    else None
                ),
                state_machine_config=state_machine_config,
            )
    return contexts


def _active_task(queue: TaskQueue) -> Task | None:
    if queue.active_task_id is None:
        return None
    for task in queue.tasks:
        if task.task_id == queue.active_task_id:
            return task
    return None


def _replace_task_in_queue(queue: TaskQueue, task: Task) -> TaskQueue:
    tasks = [task if current.task_id == task.task_id else current for current in queue.tasks]
    return queue.model_copy(update={"tasks": tasks})


def _apply_state_patches(
    states: Sequence[CraneState],
    patches: Mapping[str, Mapping[str, Any]],
) -> list[CraneState]:
    return [
        state.model_copy(update=dict(patches[state.crane_id]))
        if state.crane_id in patches
        else state
        for state in states
    ]


def _task_action_signal(
    *,
    state: CraneState,
    command: ExecutedCommand | None,
    time_s: float,
) -> TaskActionSignal:
    if command is None:
        return TaskActionSignal(crane_id=state.crane_id, time_s=time_s)
    return TaskActionSignal(
        crane_id=state.crane_id,
        command_id=command.command_id,
        time_s=time_s,
        task_action=command.task_action,
        motion_is_non_neutral=not _command_is_neutral(command),
    )


def _command_is_neutral(command: ExecutedCommand) -> bool:
    return (
        command.left_joystick.slew.direction == "neutral"
        and command.left_joystick.trolley.direction == "neutral"
        and command.right_joystick.hoist.direction == "neutral"
    )


def _neighbor_map(states: Sequence[CraneState]) -> dict[str, list[str]]:
    ids = [state.crane_id for state in states]
    return {crane_id: [other for other in ids if other != crane_id] for crane_id in ids}


def _event_type(event: Any) -> str | None:
    if isinstance(event, Mapping):
        value = event.get("event_type")
    else:
        value = getattr(event, "event_type", None)
    return str(value) if value is not None else None


def _evaluate_risk_with_complete_commands(
    *,
    states: list[CraneState],
    configs: list[CraneConfig],
    commands: Mapping[str, ExecutedCommand],
    risk_config: RiskConfig,
    weather_state: WeatherState,
    source_snapshot_id: str,
    time_s: float,
) -> Any:
    complete_commands = dict(commands)
    for state in states:
        if state.crane_id not in complete_commands:
            complete_commands[state.crane_id] = build_system_neutral_executed_command(
                crane_id=state.crane_id,
                operator_id=f"OP_{state.crane_id}",
                time_s=time_s,
                source_snapshot_id=source_snapshot_id,
                observation_id=f"OBS_RISK_{state.crane_id}_{time_s:.3f}",
                reason="risk adapter neutral fill",
            )
    return evaluate_online_risk(
        crane_states=states,
        crane_configs=configs,
        risk_config=risk_config,
        weather_state=weather_state,
        proposed_commands=complete_commands,
    )


def _source_snapshot_id(commands: Mapping[str, ExecutedCommand], time_s: float) -> str:
    for command in commands.values():
        return command.source_snapshot_id
    return f"RISK_{time_s:.3f}"


def _hard_or_default_policy(
    policy: ForbiddenZonePolicyConfig,
) -> ForbiddenZonePolicyConfig:
    # H's safety pipeline currently accepts hard/soft policy modes; task_only is
    # a scenario-level generation policy, so runtime movement safety uses record-only.
    if policy.mode.value == "task_only":
        return policy.model_copy(update={"mode": ForbiddenZonePolicyMode.HARD})
    return policy


def _crane_configs_from_resolved_config(resolved_config: Any) -> list[CraneConfig]:
    layout = getattr(resolved_config, "layout", None)
    cranes = getattr(layout, "resolved_cranes", None) if layout is not None else None
    if cranes is None and isinstance(layout, Mapping):
        cranes = layout.get("resolved_cranes")
    if not cranes:
        raise ValueError("resolved config does not include layout.resolved_cranes")
    return [CraneConfig.model_validate(crane) for crane in cranes]


def _mapping_section(resolved_config: Any, name: str) -> dict[str, Any]:
    section = getattr(resolved_config, name, None)
    if section is None:
        raise ValueError(f"resolved config missing {name}")
    if hasattr(section, "model_dump"):
        return section.model_dump(mode="python")
    return dict(section)


def scenario_config_from_resolved(resolved_config: Any) -> ScenarioConfig:
    payload = copy.deepcopy(_mapping_section(resolved_config, "scenario"))
    visibility = payload.get("weather", {}).get("visibility")
    if isinstance(visibility, dict) and isinstance(visibility.get("levels"), dict):
        visibility["levels"] = None
    return ScenarioConfig.model_validate(payload)


__all__ = [
    "ProductionCollisionAdapter",
    "ProductionObservationBuilder",
    "ProductionRecorderAdapter",
    "ProductionRiskAdapter",
    "ProductionSafetyAdapter",
    "ProductionTaskSystem",
    "build_production_episode_runner",
    "scenario_config_from_resolved",
]
