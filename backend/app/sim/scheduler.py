from __future__ import annotations

import copy
import math
from dataclasses import dataclass
from typing import Any, Collection, Literal, Mapping, Optional, Sequence

from backend.app.schemas.command import ExecutedCommand, build_neutral_stop_command
from backend.app.schemas.control import ControlTarget
from backend.app.schemas.crane import CraneConfig
from backend.app.schemas.enums import RuntimeMode
from backend.app.schemas.scheduler import (
    SCH_E_COMMAND_STORE,
    SCH_E_FRAME_LOOP,
    SCH_E_INVALID_SNAPSHOT,
    CommandStoreSnapshot,
    EpisodeResult,
    EpisodeStatus,
    FrameStepResult,
    SchedulerConfig,
    SchedulerError,
    StoredCommand,
    TerminalStatusCandidate,
    WorldSnapshot,
)
from backend.app.schemas.state import CraneState
from backend.app.schemas.task import Task, TaskQueue
from backend.app.schemas.weather import WeatherState, WeatherVisibilityContext
from backend.app.sim.observation import ObservationWorldSnapshot
from backend.app.sim.task_queue import all_ordinary_tasks_terminal

CommandReplacementSource = Literal["decision", "replay"]


@dataclass
class SchedulerDependencies:
    weather: Any
    task_system: Any
    observation_builder: Any
    operator: Any
    safety: Any
    controller: Any
    physics: Any
    risk: Any
    collision: Any
    recorder: Any
    websocket: Any = None
    replay: Any = None


class EpisodeRunner:
    def __init__(
        self,
        *,
        config: SchedulerConfig,
        dependencies: SchedulerDependencies,
        episode_id: str,
        crane_configs: Sequence[CraneConfig],
        crane_states: Sequence[CraneState],
        weather_state: WeatherState,
        visibility_context: WeatherVisibilityContext,
        tasks: Sequence[Task] = (),
        task_queues: Sequence[TaskQueue] = (),
        task_contexts: Optional[Mapping[str, Any]] = None,
        current_commands: Optional[Mapping[str, ExecutedCommand]] = None,
        current_control_targets: Optional[Mapping[str, ControlTarget]] = None,
    ) -> None:
        self.config = config
        self.dependencies = dependencies
        self.episode_id = episode_id
        self.crane_configs = tuple(copy.deepcopy(list(crane_configs)))
        self.crane_states = list(copy.deepcopy(list(crane_states)))
        self.weather_state = copy.deepcopy(weather_state)
        self.visibility_context = copy.deepcopy(visibility_context)
        self.tasks = tuple(copy.deepcopy(list(tasks)))
        self.task_queues = list(copy.deepcopy(list(task_queues)))
        self.task_contexts = copy.deepcopy(dict(task_contexts or {}))
        self.current_control_targets = copy.deepcopy(
            dict(current_control_targets or {})
        )
        self.crane_ids = tuple(config.crane_id for config in self.crane_configs)
        self.time_s = 0.0
        self.frame_index = 0
        self.episode_status = EpisodeStatus.RUNNING
        self._terminal_candidate: TerminalStatusCandidate | None = None
        self._all_tasks_done_since_s: float | None = None
        self._stop_requested = False
        self._stop_reason = "stopped_by_user"
        self._initial_recorded = False
        self._recent_decisions: dict[str, list[dict[str, Any]]] = {}
        self._recent_events: dict[str, list[dict[str, Any]]] = {}
        self.decision_clock = DecisionClock(
            crane_ids=self.crane_ids,
            llm_decision_interval_s=config.llm_decision_interval_s,
        )
        self.command_store = CommandStore.with_startup_neutral(
            crane_ids=self.crane_ids,
            time_s=0.0,
        )
        if current_commands:
            self.command_store.replace_current_commands(
                list(current_commands.values()),
                sim_time=0.0,
            )

    @classmethod
    def from_config(
        cls,
        config: object,
        *,
        dependencies: SchedulerDependencies | None = None,
        **kwargs: Any,
    ) -> "EpisodeRunner":
        if dependencies is None:
            raise SchedulerError(
                "EpisodeRunner.from_config requires scheduler dependencies",
                error_code=SCH_E_FRAME_LOOP,
            )
        scheduler_config = (
            config
            if isinstance(config, SchedulerConfig)
            else SchedulerConfig.from_config(config)
        )
        return cls(config=scheduler_config, dependencies=dependencies, **kwargs)

    def run_episode(self) -> EpisodeResult:
        while not should_stop(
            episode_status=self.episode_status,
            sim_time=self.time_s,
            config=self.config,
            all_tasks_done_since_s=self._all_tasks_done_since_s,
        ):
            self.run_one_frame()
        return EpisodeResult(
            episode_id=self.episode_id,
            status=self.episode_status,
            final_time_s=self.time_s,
            final_frame_index=self.frame_index,
            reason=self._terminal_candidate.reason if self._terminal_candidate else None,
            terminal_candidate=self._terminal_candidate,
            metrics={"frames": self.frame_index},
        )

    def run_one_frame(self) -> FrameStepResult:
        if self.episode_status is not EpisodeStatus.RUNNING:
            return FrameStepResult(
                frame_index=self.frame_index,
                time_s=self.time_s,
                status=self.episode_status,
                events=[],
            )
        if self._stop_requested:
            self.episode_status = EpisodeStatus.STOPPED_BY_USER
            self._terminal_candidate = TerminalStatusCandidate(
                status=EpisodeStatus.STOPPED_BY_USER,
                source_module="J",
                reason=self._stop_reason,
                time_s=self.time_s,
                frame_index=self.frame_index,
            )
            return FrameStepResult(
                frame_index=self.frame_index,
                time_s=self.time_s,
                status=self.episode_status,
                events=[self._terminal_candidate.model_dump(mode="json")],
            )

        try:
            return self._run_one_frame()
        except SchedulerError as exc:
            self.episode_status = exc.episode_status
            self._terminal_candidate = TerminalStatusCandidate(
                status=exc.episode_status,
                source_module=exc.source_module,
                reason=str(exc),
                time_s=self.time_s,
                frame_index=self.frame_index,
                details=exc.details,
            )
        except Exception as exc:
            self.episode_status = EpisodeStatus.FAILED_INVALID_STATE
            self._terminal_candidate = TerminalStatusCandidate(
                status=EpisodeStatus.FAILED_INVALID_STATE,
                source_module="J",
                reason=str(exc),
                time_s=self.time_s,
                frame_index=self.frame_index,
                details={"exception_type": type(exc).__name__},
            )
        return FrameStepResult(
            frame_index=self.frame_index,
            time_s=self.time_s,
            status=self.episode_status,
            events=[self._terminal_candidate.model_dump(mode="json")]
            if self._terminal_candidate
            else [],
        )

    def stop(self, reason: str = "stopped_by_user") -> None:
        self._stop_requested = True
        self._stop_reason = reason

    def _run_one_frame(self) -> FrameStepResult:
        if not self._initial_recorded:
            self._record_initial_frame()

        sim_time = self.time_s
        frame_index = self.frame_index
        weather_state, visibility_context = self._update_weather(sim_time)
        self.weather_state = weather_state
        self.visibility_context = visibility_context

        task_activation = self.dependencies.task_system.activate_due_tasks(
            time_s=sim_time,
            states=self.crane_states,
            task_queues=self.task_queues,
        )
        activation_events = self._apply_task_result(task_activation)

        decision_cranes = self.decision_clock.cranes_due_for_decision(
            sim_time=sim_time,
            include_idle=True,
        )
        snapshot: WorldSnapshot | None = None
        decision_results: list[Any] = []
        if decision_cranes:
            snapshot = self._freeze_snapshot(frame_index=frame_index, time_s=sim_time)
            executed_commands, decision_results = self._decide_and_execute(
                snapshot=snapshot,
                decision_cranes=decision_cranes,
            )
            self.command_store.replace_current_commands(
                executed_commands,
                sim_time=sim_time,
                source=(
                    "replay"
                    if self.config.run_mode is RuntimeMode.OFFLINE_REPLAY
                    else "decision"
                ),
            )
            self.decision_clock.mark_decided(
                decision_cranes,
                decision_time_s=sim_time,
            )

        current_commands, expiry_events = self.command_store.expire_or_neutral_stop(
            sim_time=sim_time
        )
        control_targets, controller_diagnostics = (
            self.dependencies.controller.compute_batch(
                commands=self._commands_in_crane_order(current_commands),
                states=self.crane_states,
                models=self._models_by_crane_id(),
                dt_s=self.config.dt_s,
                now_s=sim_time,
            )
        )
        self.current_control_targets = {
            target.crane_id: copy.deepcopy(target) for target in control_targets
        }

        next_states = self.dependencies.physics.step_world(
            crane_configs=self.crane_configs,
            previous_states=self.crane_states,
            control_targets=control_targets,
            dt=self.config.dt_s,
        )
        next_time_s = sim_time + self.config.dt_s

        task_update = self.dependencies.task_system.update_after_physics(
            states=next_states,
            commands=current_commands,
            time_s=next_time_s,
            task_queues=self.task_queues,
        )
        task_events = self._apply_task_result(task_update, states=next_states)
        next_states = self.crane_states

        risk_now = self.dependencies.risk.evaluate_after_physics(
            states=next_states,
            commands=current_commands,
            time_s=next_time_s,
        )
        collision_events = self.dependencies.collision.detect(
            states=next_states,
            risk=risk_now,
            time_s=next_time_s,
        )

        status_or_candidate = update_terminal_status(
            current_status=self.episode_status,
            sim_time=next_time_s,
            frame_index=frame_index + 1,
            states=next_states,
            task_queues=self.task_queues,
            task_events=task_events,
            collision_events=collision_events,
            llm_results=decision_results,
            replay_mismatch=None,
            config=self.config,
        )
        self._apply_terminal_status(status_or_candidate, next_time_s, frame_index + 1)
        self._promote_completed_if_cooldown_met(next_time_s, frame_index + 1)

        frame_events = [
            *_events_to_dicts(activation_events),
            *expiry_events,
            *_events_to_dicts(task_events),
            *_events_to_dicts(collision_events),
        ]
        if self._terminal_candidate is not None:
            frame_events.append(self._terminal_candidate.model_dump(mode="json"))

        self.dependencies.recorder.record_step(
            episode_id=self.episode_id,
            frame_index=frame_index + 1,
            time_s=next_time_s,
            states=copy.deepcopy(next_states),
            weather_state=copy.deepcopy(weather_state),
            visibility_context=copy.deepcopy(visibility_context),
            commands=copy.deepcopy(current_commands),
            control_targets=copy.deepcopy(control_targets),
            controller_diagnostics=copy.deepcopy(controller_diagnostics),
            task_queues=copy.deepcopy(self.task_queues),
            events=copy.deepcopy(frame_events),
            status=self.episode_status,
            snapshot_id=snapshot.snapshot_id if snapshot is not None else None,
            online_risk=copy.deepcopy(risk_now),
            observations=copy.deepcopy(_observations_from_decision_results(decision_results)),
            llm_calls=copy.deepcopy(_llm_calls_from_decision_results(decision_results)),
        )
        if (
            self.config.run_mode is RuntimeMode.INTERACTIVE_SERVER
            and self.dependencies.websocket is not None
        ):
            self.dependencies.websocket.broadcast_sim_frame_if_enabled(
                episode_id=self.episode_id,
                frame_index=frame_index + 1,
                time_s=next_time_s,
                states=copy.deepcopy(next_states),
                events=copy.deepcopy(frame_events),
                status=self.episode_status,
            )

        self.frame_index = frame_index + 1
        self.time_s = next_time_s
        self.crane_states = list(copy.deepcopy(next_states))
        return FrameStepResult(
            frame_index=self.frame_index,
            time_s=self.time_s,
            status=self.episode_status,
            snapshot_id=snapshot.snapshot_id if snapshot is not None else None,
            events=frame_events,
        )

    def _record_initial_frame(self) -> None:
        weather_state, visibility_context = self._update_weather(0.0)
        self.weather_state = weather_state
        self.visibility_context = visibility_context
        self.dependencies.recorder.record_initial_frame(
            episode_id=self.episode_id,
            frame_index=0,
            time_s=0.0,
            states=copy.deepcopy(self.crane_states),
            weather_state=copy.deepcopy(weather_state),
            visibility_context=copy.deepcopy(visibility_context),
            task_queues=copy.deepcopy(self.task_queues),
            commands=copy.deepcopy(self.command_store.get_current_commands()),
            status=self.episode_status,
        )
        self._initial_recorded = True

    def _update_weather(
        self,
        time_s: float,
    ) -> tuple[WeatherState, WeatherVisibilityContext]:
        result = self.dependencies.weather.update(time_s)
        if isinstance(result, tuple) and len(result) == 2:
            return result
        return result.weather_state, result.visibility_context

    def _freeze_snapshot(self, *, frame_index: int, time_s: float) -> WorldSnapshot:
        return freeze_world_snapshot(
            episode_id=self.episode_id,
            frame_index=frame_index,
            time_s=time_s,
            llm_decision_interval_s=self.config.llm_decision_interval_s,
            crane_states=self.crane_states,
            crane_configs=self.crane_configs,
            weather_state=self.weather_state,
            visibility_context=self.visibility_context,
            tasks=self.tasks,
            task_queues=self.task_queues,
            task_contexts=self.task_contexts,
            current_commands=self.command_store.get_current_commands(),
            current_control_targets=self.current_control_targets,
            recent_decisions=self._recent_decisions,
            recent_events=self._recent_events,
        )

    def _decide_and_execute(
        self,
        *,
        snapshot: WorldSnapshot,
        decision_cranes: Sequence[str],
    ) -> tuple[list[ExecutedCommand], list[Any]]:
        predecision_risk = self.dependencies.risk.evaluate_predecision(
            snapshot=snapshot,
            commands=self.command_store.get_current_commands(),
        )
        observations = self.dependencies.observation_builder.build_batch(
            snapshot=snapshot,
            crane_ids=list(decision_cranes),
            risk_hints=getattr(predecision_risk, "hints", {}),
        )
        if self.config.run_mode is RuntimeMode.OFFLINE_REPLAY:
            if self.dependencies.replay is None:
                raise SchedulerError(
                    "offline_replay requires a replay command source",
                    error_code=SCH_E_FRAME_LOOP,
                    episode_status=EpisodeStatus.FAILED_REPLAY_MISMATCH,
                )
            commands = list(
                self.dependencies.replay.commands_for_decision(
                    snapshot=snapshot,
                    crane_ids=list(decision_cranes),
                    decision_indices={
                        crane_id: self.decision_clock.decision_index(crane_id)
                        for crane_id in decision_cranes
                    },
                )
            )
            self._validate_replay_commands(
                commands,
                snapshot=snapshot,
                expected_crane_ids=decision_cranes,
            )
            return commands, []

        decision_results = list(
            self.dependencies.operator.decide(
                observations,
                llm_decision_interval_s=self.config.llm_decision_interval_s,
            )
        )
        parsed_commands = [result.parsed_command for result in decision_results]
        self._validate_decision_commands(
            parsed_commands,
            snapshot=snapshot,
            expected_crane_ids=decision_cranes,
        )
        executed = self.dependencies.safety.apply_pipeline(
            parsed_commands,
            snapshot=snapshot,
        )
        return list(executed), decision_results

    def _validate_decision_commands(
        self,
        commands: Sequence[Any],
        *,
        snapshot: WorldSnapshot,
        expected_crane_ids: Sequence[str],
    ) -> None:
        expected = set(expected_crane_ids)
        actual = {command.crane_id for command in commands}
        if actual != expected:
            raise SchedulerError(
                "decision batch crane ids do not match due cranes",
                error_code=SCH_E_FRAME_LOOP,
                details={
                    "expected_crane_ids": sorted(expected),
                    "actual_crane_ids": sorted(actual),
                },
            )
        for command in commands:
            if command.source_snapshot_id != snapshot.snapshot_id:
                raise SchedulerError(
                    "decision command source_snapshot_id must match current snapshot",
                    error_code=SCH_E_FRAME_LOOP,
                    details={
                        "command_id": command.command_id,
                        "source_snapshot_id": command.source_snapshot_id,
                        "snapshot_id": snapshot.snapshot_id,
                    },
                )

    def _validate_replay_commands(
        self,
        commands: Sequence[ExecutedCommand],
        *,
        snapshot: WorldSnapshot,
        expected_crane_ids: Sequence[str],
    ) -> None:
        seen: set[str] = set()
        duplicates: set[str] = set()
        for command in commands:
            if command.crane_id in seen:
                duplicates.add(command.crane_id)
            seen.add(command.crane_id)
            if command.source_snapshot_id != snapshot.snapshot_id:
                raise SchedulerError(
                    "replay command source_snapshot_id must match current snapshot",
                    error_code=SCH_E_FRAME_LOOP,
                    episode_status=EpisodeStatus.FAILED_REPLAY_MISMATCH,
                    details={
                        "command_id": command.command_id,
                        "source_snapshot_id": command.source_snapshot_id,
                        "snapshot_id": snapshot.snapshot_id,
                    },
                )
        expected = set(expected_crane_ids)
        if seen != expected or duplicates:
            raise SchedulerError(
                "replay command batch must uniquely match due cranes",
                error_code=SCH_E_FRAME_LOOP,
                episode_status=EpisodeStatus.FAILED_REPLAY_MISMATCH,
                details={
                    "expected_crane_ids": sorted(expected),
                    "actual_crane_ids": sorted(seen),
                    "duplicate_crane_ids": sorted(duplicates),
                },
            )

    def _apply_task_result(self, result: Any, *, states: Any = None) -> list[Any]:
        self.task_queues = list(
            copy.deepcopy(getattr(result, "queues", self.task_queues))
        )
        result_states = getattr(result, "states", states)
        if result_states is not None:
            self.crane_states = list(copy.deepcopy(result_states))
        task_contexts = getattr(result, "task_contexts", None)
        if task_contexts is not None:
            self.task_contexts = copy.deepcopy(dict(task_contexts))
        events = list(getattr(result, "events", []))
        self._append_recent_events(events)
        return events

    def _append_recent_events(self, events: Sequence[Any]) -> None:
        for event in events:
            crane_id = _event_field(event, "crane_id")
            if crane_id is None:
                continue
            self._recent_events.setdefault(str(crane_id), []).append(
                _event_to_dict(event)
            )

    def _apply_terminal_status(
        self,
        status_or_candidate: EpisodeStatus | TerminalStatusCandidate,
        sim_time: float,
        frame_index: int,
    ) -> None:
        if isinstance(status_or_candidate, TerminalStatusCandidate):
            self.episode_status = status_or_candidate.status
            self._terminal_candidate = status_or_candidate
            return
        self.episode_status = EpisodeStatus(status_or_candidate)
        if self.episode_status is not EpisodeStatus.RUNNING:
            self._terminal_candidate = TerminalStatusCandidate(
                status=self.episode_status,
                source_module="J",
                reason=self.episode_status.value,
                time_s=sim_time,
                frame_index=frame_index,
            )
        if all_ordinary_tasks_terminal(self.task_queues):
            if self._all_tasks_done_since_s is None:
                self._all_tasks_done_since_s = sim_time
        else:
            self._all_tasks_done_since_s = None

    def _promote_completed_if_cooldown_met(
        self,
        sim_time: float,
        frame_index: int,
    ) -> None:
        if self.episode_status is not EpisodeStatus.RUNNING:
            return
        if not self.config.stop_when_all_tasks_done:
            return
        if self._all_tasks_done_since_s is None:
            return
        if sim_time < self.config.min_duration_s:
            return
        if (
            sim_time - self._all_tasks_done_since_s + 1.0e-9
            < self.config.completion_cooldown_s
        ):
            return
        self.episode_status = EpisodeStatus.COMPLETED
        self._terminal_candidate = TerminalStatusCandidate(
            status=EpisodeStatus.COMPLETED,
            source_module="J",
            reason="completed",
            time_s=sim_time,
            frame_index=frame_index,
        )

    def _commands_in_crane_order(
        self,
        commands: Mapping[str, ExecutedCommand],
    ) -> list[ExecutedCommand]:
        return [copy.deepcopy(commands[crane_id]) for crane_id in self.crane_ids]

    def _models_by_crane_id(self) -> dict[str, Any]:
        return {config.crane_id: config.model for config in self.crane_configs}


class DecisionClock:
    def __init__(
        self,
        *,
        crane_ids: Sequence[str],
        llm_decision_interval_s: float,
        epsilon_s: float = 1.0e-9,
    ) -> None:
        self._crane_ids = _validate_decision_crane_ids(crane_ids)
        if not math.isfinite(llm_decision_interval_s) or llm_decision_interval_s <= 0:
            raise SchedulerError(
                "llm_decision_interval_s must be finite and positive",
                error_code=SCH_E_FRAME_LOOP,
                details={"llm_decision_interval_s": llm_decision_interval_s},
            )
        if not math.isfinite(epsilon_s) or epsilon_s < 0:
            raise SchedulerError(
                "epsilon_s must be finite and non-negative",
                error_code=SCH_E_FRAME_LOOP,
                details={"epsilon_s": epsilon_s},
            )
        self._llm_decision_interval_s = llm_decision_interval_s
        self._epsilon_s = epsilon_s
        self._last_decision_time_s: dict[str, float | None] = {
            crane_id: None for crane_id in self._crane_ids
        }
        self._decision_indices: dict[str, int] = {
            crane_id: 0 for crane_id in self._crane_ids
        }

    def cranes_due_for_decision(
        self,
        *,
        sim_time: float,
        include_idle: bool = True,
        active_crane_ids: Collection[str] | None = None,
    ) -> list[str]:
        _validate_decision_time(sim_time, field_name="sim_time")
        if active_crane_ids is not None:
            _validate_known_decision_cranes(
                active_crane_ids,
                known_crane_ids=self._crane_ids,
                field_name="active_crane_ids",
            )
        active_ids = set(active_crane_ids or ())

        candidates = (
            self._crane_ids
            if include_idle
            else tuple(crane_id for crane_id in self._crane_ids if crane_id in active_ids)
        )
        due: list[str] = []
        for crane_id in candidates:
            last_time = self._last_decision_time_s[crane_id]
            if last_time is None:
                due.append(crane_id)
                continue
            if sim_time + self._epsilon_s < last_time:
                raise SchedulerError(
                    "sim_time must not go backward before last decision time",
                    error_code=SCH_E_FRAME_LOOP,
                    details={
                        "crane_id": crane_id,
                        "sim_time": sim_time,
                        "last_decision_time_s": last_time,
                    },
                )
            if (
                sim_time - last_time + self._epsilon_s
                >= self._llm_decision_interval_s
            ):
                due.append(crane_id)
        return due

    def mark_decided(
        self,
        crane_ids: Sequence[str],
        *,
        decision_time_s: float,
    ) -> None:
        _validate_decision_time(decision_time_s, field_name="decision_time_s")
        _validate_known_decision_cranes(
            crane_ids,
            known_crane_ids=self._crane_ids,
            field_name="crane_ids",
        )
        ids = tuple(crane_ids)
        for crane_id in ids:
            last_time = self._last_decision_time_s[crane_id]
            if last_time is not None and decision_time_s + self._epsilon_s < last_time:
                raise SchedulerError(
                    "decision_time_s must not go backward",
                    error_code=SCH_E_FRAME_LOOP,
                    details={
                        "crane_id": crane_id,
                        "decision_time_s": decision_time_s,
                        "last_decision_time_s": last_time,
                    },
                )
        for crane_id in ids:
            self._last_decision_time_s[crane_id] = decision_time_s
            self._decision_indices[crane_id] += 1

    def decision_index(self, crane_id: str) -> int:
        self._validate_known_crane_id(crane_id)
        return self._decision_indices[crane_id]

    def last_decision_time(self, crane_id: str) -> float | None:
        self._validate_known_crane_id(crane_id)
        return self._last_decision_time_s[crane_id]

    def _validate_known_crane_id(self, crane_id: str) -> None:
        if crane_id not in self._decision_indices:
            raise SchedulerError(
                "unknown crane_id",
                error_code=SCH_E_FRAME_LOOP,
                details={"crane_id": crane_id},
            )


def freeze_world_snapshot(
    *,
    episode_id: str,
    frame_index: int,
    time_s: float,
    llm_decision_interval_s: float,
    crane_states: Sequence[CraneState],
    crane_configs: Sequence[CraneConfig],
    weather_state: WeatherState,
    visibility_context: WeatherVisibilityContext,
    tasks: Sequence[Task] = (),
    task_queues: Sequence[TaskQueue] = (),
    task_contexts: Optional[Mapping[str, Any]] = None,
    current_commands: Optional[Mapping[str, ExecutedCommand]] = None,
    current_control_targets: Optional[Mapping[str, ControlTarget]] = None,
    recent_decisions: Optional[Mapping[str, Sequence[Mapping[str, Any]]]] = None,
    recent_events: Optional[Mapping[str, Sequence[Mapping[str, Any]]]] = None,
) -> WorldSnapshot:
    _validate_snapshot_time_inputs(
        time_s=time_s,
        llm_decision_interval_s=llm_decision_interval_s,
    )
    try:
        return WorldSnapshot(
            snapshot_id=_snapshot_id(episode_id=episode_id, frame_index=frame_index),
            episode_id=episode_id,
            frame_index=frame_index,
            time_s=time_s,
            decision_time_bucket=_decision_time_bucket(
                time_s=time_s,
                llm_decision_interval_s=llm_decision_interval_s,
            ),
            crane_states=tuple(copy.deepcopy(list(crane_states))),
            crane_configs=tuple(copy.deepcopy(list(crane_configs))),
            weather_state=copy.deepcopy(weather_state),
            visibility_context=copy.deepcopy(visibility_context),
            tasks=tuple(copy.deepcopy(list(tasks))),
            task_queues=tuple(copy.deepcopy(list(task_queues))),
            task_contexts=copy.deepcopy(dict(task_contexts or {})),
            current_commands=copy.deepcopy(dict(current_commands or {})),
            current_control_targets=copy.deepcopy(dict(current_control_targets or {})),
            recent_decisions=_copy_recent_mapping(recent_decisions),
            recent_events=_copy_recent_mapping(recent_events),
        )
    except Exception as exc:
        if isinstance(exc, SchedulerError):
            raise
        raise SchedulerError(
            "failed to freeze world snapshot",
            error_code=SCH_E_INVALID_SNAPSHOT,
            details={"reason": str(exc)},
        ) from exc


def to_observation_snapshot(
    snapshot: WorldSnapshot,
    *,
    neighbor_map: Optional[Mapping[str, Sequence[str]]] = None,
) -> ObservationWorldSnapshot:
    return ObservationWorldSnapshot(
        snapshot_id=snapshot.snapshot_id,
        time_s=snapshot.time_s,
        decision_time_bucket=snapshot.decision_time_bucket,
        crane_states=list(copy.deepcopy(snapshot.crane_states)),
        crane_configs=list(copy.deepcopy(snapshot.crane_configs)),
        weather_state=copy.deepcopy(snapshot.weather_state),
        visibility_context=copy.deepcopy(snapshot.visibility_context),
        neighbor_map={
            crane_id: list(neighbor_ids)
            for crane_id, neighbor_ids in dict(neighbor_map or {}).items()
        },
        task_contexts=copy.deepcopy(snapshot.task_contexts),
        current_commands=copy.deepcopy(snapshot.current_control_targets),
        recent_decisions=copy.deepcopy(snapshot.recent_decisions),
        recent_events=copy.deepcopy(snapshot.recent_events),
    )


def update_terminal_status(
    *,
    current_status: EpisodeStatus,
    sim_time: float,
    frame_index: int,
    states: Sequence[CraneState],
    task_queues: Sequence[TaskQueue],
    task_events: Sequence[Any],
    collision_events: Sequence[Any],
    llm_results: Sequence[Any] = (),
    replay_mismatch: TerminalStatusCandidate | None = None,
    config: SchedulerConfig,
) -> EpisodeStatus | TerminalStatusCandidate:
    if current_status is not EpisodeStatus.RUNNING:
        return current_status
    if replay_mismatch is not None:
        return replay_mismatch
    if collision_events:
        return TerminalStatusCandidate(
            status=EpisodeStatus.FAILED_COLLISION,
            source_module="K",
            reason="collision detected",
            time_s=sim_time,
            frame_index=frame_index,
            details={"collision_count": len(collision_events)},
        )
    non_finite_path = _find_non_finite_in_object(states)
    if non_finite_path is not None:
        return TerminalStatusCandidate(
            status=EpisodeStatus.FAILED_INVALID_STATE,
            source_module="J",
            reason="non-finite crane state",
            time_s=sim_time,
            frame_index=frame_index,
            details={"field_path": non_finite_path},
        )
    for result in llm_results:
        if getattr(result, "episode_failure_reason", None) == "llm_failed":
            return TerminalStatusCandidate(
                status=EpisodeStatus.LLM_FAILED,
                source_module="G",
                reason="llm_failed",
                time_s=sim_time,
                frame_index=frame_index,
            )
    for event in task_events:
        failure_request = _event_field(event, "episode_failure_request") or _event_field(
            event, "reason"
        )
        if failure_request == EpisodeStatus.FAILED_RECOVERY_BLOCKED.value:
            return TerminalStatusCandidate(
                status=EpisodeStatus.FAILED_RECOVERY_BLOCKED,
                source_module="D",
                reason=EpisodeStatus.FAILED_RECOVERY_BLOCKED.value,
                time_s=sim_time,
                frame_index=frame_index,
            )
        if failure_request == EpisodeStatus.FAILED_RECOVERY_TIMEOUT.value:
            return TerminalStatusCandidate(
                status=EpisodeStatus.FAILED_RECOVERY_TIMEOUT,
                source_module="D",
                reason=EpisodeStatus.FAILED_RECOVERY_TIMEOUT.value,
                time_s=sim_time,
                frame_index=frame_index,
            )
    if (
        config.stop_when_all_tasks_done
        and sim_time >= config.min_duration_s
        and config.completion_cooldown_s <= 0
        and all_ordinary_tasks_terminal(task_queues)
    ):
        return EpisodeStatus.COMPLETED
    if sim_time >= config.duration_s:
        return EpisodeStatus.TIMEOUT
    return EpisodeStatus.RUNNING


def should_stop(
    *,
    episode_status: EpisodeStatus,
    sim_time: float,
    config: SchedulerConfig,
    all_tasks_done_since_s: float | None = None,
) -> bool:
    if episode_status is not EpisodeStatus.RUNNING:
        return True
    if sim_time >= config.duration_s:
        return True
    if (
        config.stop_when_all_tasks_done
        and all_tasks_done_since_s is not None
        and sim_time >= config.min_duration_s
        and sim_time - all_tasks_done_since_s + 1.0e-9
        >= config.completion_cooldown_s
    ):
        return True
    return False


class CommandStore:
    def __init__(
        self,
        *,
        crane_ids: Sequence[str],
        default_operator_ids: Optional[Mapping[str, str]] = None,
        default_command_duration_s: float = 1.0,
    ) -> None:
        self._crane_ids = _validate_crane_ids(crane_ids)
        self._default_operator_ids = {
            crane_id: (default_operator_ids or {}).get(crane_id, f"OP_{crane_id}")
            for crane_id in self._crane_ids
        }
        _validate_positive_duration(default_command_duration_s)
        self._default_command_duration_s = default_command_duration_s
        self._commands: dict[str, StoredCommand] = {}

    @classmethod
    def with_startup_neutral(
        cls,
        *,
        crane_ids: Sequence[str],
        time_s: float = 0.0,
        default_operator_ids: Optional[Mapping[str, str]] = None,
        command_duration_s: float = 1.0,
    ) -> "CommandStore":
        store = cls(
            crane_ids=crane_ids,
            default_operator_ids=default_operator_ids,
            default_command_duration_s=command_duration_s,
        )
        _validate_finite_non_negative_time(time_s, field_name="time_s")
        for crane_id in store._crane_ids:
            command = build_system_neutral_executed_command(
                crane_id=crane_id,
                operator_id=store._default_operator_ids[crane_id],
                time_s=time_s,
                source_snapshot_id=f"SNAP_STARTUP_{crane_id}",
                observation_id=f"OBS_STARTUP_{crane_id}",
                reason="startup neutral_stop",
                command_duration_s=command_duration_s,
                command_id=f"cmd-neutral-startup-{crane_id}-{_time_token(time_s)}",
            )
            store._commands[crane_id] = _stored_command(
                command=command,
                applied_at_s=time_s,
                source="startup_neutral_stop",
            )
        return store

    def replace_current_commands(
        self,
        executed_commands: Sequence[ExecutedCommand],
        *,
        sim_time: float,
        source: CommandReplacementSource = "decision",
    ) -> CommandStoreSnapshot:
        _validate_finite_non_negative_time(sim_time, field_name="sim_time")
        if source not in {"decision", "replay"}:
            raise SchedulerError(
                "command replacement source must be decision or replay",
                error_code=SCH_E_COMMAND_STORE,
                details={"source": source},
            )
        replacements = self._validated_replacements(
            executed_commands,
            sim_time=sim_time,
            source=source,
        )
        self._commands.update(replacements)
        return self.snapshot(time_s=sim_time)

    def expire_or_neutral_stop(
        self,
        *,
        sim_time: float,
        command_duration_s: Optional[float] = None,
    ) -> tuple[dict[str, ExecutedCommand], list[dict[str, Any]]]:
        _validate_finite_non_negative_time(sim_time, field_name="sim_time")
        duration = (
            self._default_command_duration_s
            if command_duration_s is None
            else command_duration_s
        )
        _validate_positive_duration(duration)
        events: list[dict[str, Any]] = []
        for crane_id in self._crane_ids:
            stored = self._commands[crane_id]
            if sim_time + 1.0e-9 < stored.expires_at_s:
                continue
            expired_command = stored.command
            neutral = build_system_neutral_executed_command(
                crane_id=crane_id,
                operator_id=expired_command.operator_id,
                time_s=sim_time,
                source_snapshot_id=expired_command.source_snapshot_id,
                observation_id=expired_command.observation_id,
                reason=f"command {expired_command.command_id} expired; neutral_stop",
                command_duration_s=duration,
                command_id=(
                    f"cmd-neutral-expired-{crane_id}-{_time_token(sim_time)}"
                ),
            )
            self._commands[crane_id] = _stored_command(
                command=neutral,
                applied_at_s=sim_time,
                source="expired_neutral_stop",
            )
            events.append(
                {
                    "event_type": "command_expired_neutral_stop",
                    "time_s": sim_time,
                    "crane_id": crane_id,
                    "expired_command_id": expired_command.command_id,
                }
            )
        return self.get_current_commands(), events

    def get_current_commands(self) -> dict[str, ExecutedCommand]:
        return {
            crane_id: copy.deepcopy(stored.command)
            for crane_id, stored in self._commands.items()
        }

    def snapshot(self, *, time_s: float) -> CommandStoreSnapshot:
        _validate_finite_non_negative_time(time_s, field_name="time_s")
        return CommandStoreSnapshot(
            time_s=time_s,
            commands=copy.deepcopy(self._commands),
        )

    def _validated_replacements(
        self,
        executed_commands: Sequence[ExecutedCommand],
        *,
        sim_time: float,
        source: CommandReplacementSource,
    ) -> dict[str, StoredCommand]:
        seen: set[str] = set()
        replacements: dict[str, StoredCommand] = {}
        for command in executed_commands:
            if command.crane_id in seen:
                raise SchedulerError(
                    "duplicate command crane_id in replacement batch",
                    error_code=SCH_E_COMMAND_STORE,
                    details={"crane_id": command.crane_id},
                )
            seen.add(command.crane_id)
            if command.crane_id not in self._crane_ids:
                raise SchedulerError(
                    "command crane_id is not managed by this store",
                    error_code=SCH_E_COMMAND_STORE,
                    details={"crane_id": command.crane_id},
                )
            if not math.isclose(command.time_s, sim_time, rel_tol=0.0, abs_tol=1.0e-9):
                raise SchedulerError(
                    "command time_s must match replacement sim_time",
                    error_code=SCH_E_COMMAND_STORE,
                    details={
                        "crane_id": command.crane_id,
                        "command_time_s": command.time_s,
                        "sim_time": sim_time,
                    },
                )
            replacements[command.crane_id] = _stored_command(
                command=command,
                applied_at_s=sim_time,
                source=source,
            )
        return replacements


def build_system_neutral_executed_command(
    *,
    crane_id: str,
    operator_id: str,
    time_s: float,
    source_snapshot_id: str,
    observation_id: str,
    reason: str,
    command_duration_s: float = 1.0,
    command_id: Optional[str] = None,
) -> ExecutedCommand:
    _validate_finite_non_negative_time(time_s, field_name="time_s")
    _validate_positive_duration(command_duration_s)
    raw = build_neutral_stop_command(
        observation_id=observation_id,
        source_snapshot_id=source_snapshot_id,
        operator_id=operator_id,
        crane_id=crane_id,
        time_s=time_s,
        command_id=command_id or f"cmd-neutral-{crane_id}-{_time_token(time_s)}",
        response_id=None,
        command_duration_s=command_duration_s,
        reason=reason,
    )
    return ExecutedCommand.from_raw(
        command_id=f"EXEC_{raw.command_id}",
        raw_command=raw,
    )


def _validate_snapshot_time_inputs(
    *,
    time_s: float,
    llm_decision_interval_s: float,
) -> None:
    if not math.isfinite(time_s) or time_s < 0:
        raise SchedulerError(
            "time_s must be finite and non-negative",
            error_code=SCH_E_INVALID_SNAPSHOT,
            details={"time_s": time_s},
        )
    if not math.isfinite(llm_decision_interval_s) or llm_decision_interval_s <= 0:
        raise SchedulerError(
            "llm_decision_interval_s must be finite and positive",
            error_code=SCH_E_INVALID_SNAPSHOT,
            details={"llm_decision_interval_s": llm_decision_interval_s},
        )


def _validate_finite_non_negative_time(value: float, *, field_name: str) -> None:
    if not math.isfinite(value) or value < 0:
        raise SchedulerError(
            f"{field_name} must be finite and non-negative",
            error_code=SCH_E_COMMAND_STORE,
            details={field_name: value},
        )


def _validate_positive_duration(value: float) -> None:
    if not math.isfinite(value) or value <= 0:
        raise SchedulerError(
            "command duration must be finite and positive",
            error_code=SCH_E_COMMAND_STORE,
            details={"command_duration_s": value},
        )


def _validate_decision_time(value: float, *, field_name: str) -> None:
    if not math.isfinite(value) or value < 0:
        raise SchedulerError(
            f"{field_name} must be finite and non-negative",
            error_code=SCH_E_FRAME_LOOP,
            details={field_name: value},
        )


def _validate_crane_ids(crane_ids: Sequence[str]) -> tuple[str, ...]:
    ids = tuple(crane_ids)
    if not ids:
        raise SchedulerError(
            "command store requires at least one crane",
            error_code=SCH_E_COMMAND_STORE,
        )
    if len(set(ids)) != len(ids):
        raise SchedulerError(
            "command store crane_ids must be unique",
            error_code=SCH_E_COMMAND_STORE,
            details={"crane_ids": list(ids)},
        )
    return ids


def _validate_decision_crane_ids(crane_ids: Sequence[str]) -> tuple[str, ...]:
    ids = tuple(crane_ids)
    if not ids:
        raise SchedulerError(
            "decision clock requires at least one crane",
            error_code=SCH_E_FRAME_LOOP,
        )
    if len(set(ids)) != len(ids):
        raise SchedulerError(
            "decision clock crane_ids must be unique",
            error_code=SCH_E_FRAME_LOOP,
            details={"crane_ids": list(ids)},
        )
    return ids


def _validate_known_decision_cranes(
    crane_ids: Collection[str],
    *,
    known_crane_ids: Sequence[str],
    field_name: str,
) -> None:
    known = set(known_crane_ids)
    ids = tuple(crane_ids)
    if len(set(ids)) != len(ids):
        raise SchedulerError(
            f"{field_name} must be unique",
            error_code=SCH_E_FRAME_LOOP,
            details={field_name: list(ids)},
        )
    unknown = sorted(set(ids) - known)
    if unknown:
        raise SchedulerError(
            f"{field_name} contains unknown crane ids",
            error_code=SCH_E_FRAME_LOOP,
            details={"unknown_crane_ids": unknown},
        )


def _event_to_dict(event: Any) -> dict[str, Any]:
    if hasattr(event, "model_dump"):
        return event.model_dump(mode="json")
    if isinstance(event, Mapping):
        return dict(event)
    if hasattr(event, "__dict__"):
        return dict(vars(event))
    return {"value": event}


def _events_to_dicts(events: Sequence[Any]) -> list[dict[str, Any]]:
    return [_event_to_dict(event) for event in events]


def _observations_from_decision_results(results: Sequence[Any]) -> list[Any]:
    observations = []
    for result in results:
        observation = getattr(result, "observation", None)
        if observation is not None:
            observations.append(observation)
    return observations


def _llm_calls_from_decision_results(results: Sequence[Any]) -> list[Any]:
    calls = []
    for result in results:
        calls.extend(list(getattr(result, "call_records", []) or []))
    return calls


def _event_field(event: Any, field_name: str) -> Any:
    if isinstance(event, Mapping):
        if field_name in event:
            return event[field_name]
        details = event.get("details")
        if isinstance(details, Mapping):
            return details.get(field_name)
        return None
    if hasattr(event, field_name):
        return getattr(event, field_name)
    details = getattr(event, "details", None)
    if isinstance(details, Mapping):
        return details.get(field_name)
    return None


def _find_non_finite_in_object(value: Any, path: str = "") -> str | None:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="python")
    if isinstance(value, float):
        if not math.isfinite(value):
            return path or "<root>"
        return None
    if isinstance(value, Mapping):
        for key, child in value.items():
            child_path = f"{path}.{key}" if path else str(key)
            found = _find_non_finite_in_object(child, child_path)
            if found is not None:
                return found
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            found = _find_non_finite_in_object(child, f"{path}[{index}]")
            if found is not None:
                return found
    return None


def _stored_command(
    *,
    command: ExecutedCommand,
    applied_at_s: float,
    source: str,
) -> StoredCommand:
    return StoredCommand(
        crane_id=command.crane_id,
        command=copy.deepcopy(command),
        applied_at_s=applied_at_s,
        expires_at_s=command.time_s + command.command_duration_s,
        source=source,
    )


def _snapshot_id(*, episode_id: str, frame_index: int) -> str:
    return f"SNAP_{episode_id}_{frame_index:06d}"


def _decision_time_bucket(
    *,
    time_s: float,
    llm_decision_interval_s: float,
) -> int:
    return int(round((time_s + 1.0e-9) / llm_decision_interval_s))


def _time_token(time_s: float) -> str:
    return f"{time_s:.9f}".rstrip("0").rstrip(".").replace(".", "p")


def _copy_recent_mapping(
    value: Optional[Mapping[str, Sequence[Mapping[str, Any]]]]
) -> dict[str, list[dict[str, Any]]]:
    return {
        key: [dict(item) for item in sequence]
        for key, sequence in copy.deepcopy(dict(value or {})).items()
    }
