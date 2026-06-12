from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.app.schemas.command import ExecutedCommand, ParsedCommand
from backend.app.schemas.config import ScenarioConfig
from backend.app.schemas.control import ControlTarget
from backend.app.schemas.risk import CollisionEvent
from backend.app.schemas.scheduler import EpisodeStatus, SchedulerConfig
from backend.app.schemas.weather import WeatherState, WeatherVisibilityContext
from backend.app.sim.crane_model import build_crane_model_library
from backend.app.sim.layout import build_crane_configs
from backend.app.sim.physics import initialize_crane_state
from backend.app.sim.scheduler import EpisodeRunner, SchedulerDependencies
from backend.app.tests.test_config_schema import load_fixture


def _scheduler_config(
    *,
    mode: str = "offline_batch",
    dt_s: float = 0.5,
    duration_s: float = 3.0,
    llm_decision_interval_s: float = 1.0,
    min_duration_s: float = 0.0,
    stop_when_all_tasks_done: bool = False,
    completion_cooldown_s: float = 0.0,
) -> SchedulerConfig:
    return SchedulerConfig.model_validate(
        {
            "dt_s": dt_s,
            "duration_s": duration_s,
            "min_duration_s": min_duration_s,
            "stop_when_all_tasks_done": stop_when_all_tasks_done,
            "completion_cooldown_s": completion_cooldown_s,
            "controller_hz": 20.0,
            "llm_decision_interval_s": llm_decision_interval_s,
            "run_mode": mode,
        }
    )


def _crane_configs(count: int = 2):
    raw = load_fixture("scenario_valid.yaml")
    raw["layout"]["mode"] = "manual"
    raw["layout"]["num_cranes"] = count
    raw["cranes"] = [
        {
            "crane_id": f"C{index + 1}",
            "model_id": "generic_flat_top_55m",
            "base": [index * 40.0, 0.0, 0.0],
            "mast_height_m": 45.0 + index * 5.0,
            "theta_init_deg": 15.0 + index * 45.0,
            "slew": {"mode": "continuous"},
        }
        for index in range(count)
    ]
    scenario = ScenarioConfig.model_validate(raw)
    library = build_crane_model_library(scenario.crane_models)
    return build_crane_configs(scenario.cranes, library, scenario, source="manual")


def _weather_state(time_s: float = 0.0) -> WeatherState:
    return WeatherState(
        time_s=time_s,
        mode="constant",
        wind_speed_m_s=4.0,
        wind_gust_m_s=6.0,
        wind_direction_deg=90.0,
        visibility_level="good",
        rain_level="none",
        fog_level="none",
        source_segment_id="constant",
        generation_seed=303,
        generation_step=0,
    )


def _visibility_context(time_s: float = 0.0) -> WeatherVisibilityContext:
    return WeatherVisibilityContext(
        time_s=time_s,
        visibility_level="good",
        neighbor_visibility_radius_m=120.0,
        distance_noise_m=0.5,
        hide_hook_prob=0.0,
        visibility_confidence=1.0,
        distance_precision_m=0.5,
        noise_seed=303,
        profile_source="default",
    )


def _task_contexts_for(crane_ids: list[str], time_s: float) -> dict[str, dict]:
    return {
        crane_id: {
            "crane_id": crane_id,
            "time_s": time_s,
            "has_active_task": False,
            "task_stage": "idle",
        }
        for crane_id in crane_ids
    }


def _parsed_command(
    *,
    crane_id: str,
    snapshot_id: str,
    observation_id: str,
    time_s: float,
    command_duration_s: float = 1.0,
) -> ParsedCommand:
    return ParsedCommand(
        command_id=f"cmd-{crane_id}-{time_s:.1f}".replace(".", "p"),
        response_id=f"resp-{crane_id}-{time_s:.1f}".replace(".", "p"),
        observation_id=observation_id,
        source_snapshot_id=snapshot_id,
        operator_id=f"OP_{crane_id}",
        crane_id=crane_id,
        time_s=time_s,
        left_joystick={
            "slew": {"direction": "neutral", "gear": 0},
            "trolley": {"direction": "neutral", "gear": 0},
        },
        right_joystick={"hoist": {"direction": "neutral", "gear": 0}},
        deadman_pressed=True,
        emergency_stop=False,
        horn=False,
        command_duration_s=command_duration_s,
        task_action="none",
        attention_target="module_j_acceptance",
        confidence=0.9,
        reason="fake operator command",
    )


class FakeWeather:
    def __init__(self, log: list[str]) -> None:
        self.log = log

    def update(self, time_s: float):
        self.log.append(f"weather.update:{time_s:.1f}")
        return _weather_state(time_s), _visibility_context(time_s)


class FakeTaskSystem:
    def __init__(self, log: list[str]) -> None:
        self.log = log

    def activate_due_tasks(self, *, time_s, states, task_queues):
        self.log.append(f"task.activate:{time_s:.1f}")
        return SimpleNamespace(
            queues=list(task_queues),
            states=list(states),
            events=[],
            task_contexts=_task_contexts_for(
                [state.crane_id for state in states],
                time_s,
            ),
        )

    def update_after_physics(self, *, states, commands, time_s, task_queues):
        self.log.append(f"task.update_after_physics:{time_s:.1f}")
        return SimpleNamespace(
            queues=list(task_queues),
            states=list(states),
            events=[],
            task_contexts=_task_contexts_for(
                [state.crane_id for state in states],
                time_s,
            ),
        )


class FakeRisk:
    def __init__(self, log: list[str]) -> None:
        self.log = log

    def evaluate_predecision(self, *, snapshot, commands):
        self.log.append(f"risk.predecision:{snapshot.snapshot_id}")
        return SimpleNamespace(hints={})

    def evaluate_after_physics(self, *, states, commands, time_s):
        self.log.append(f"risk.after_physics:{time_s:.1f}")
        return SimpleNamespace(events=[])


class FakeObservationBuilder:
    def __init__(self, log: list[str]) -> None:
        self.log = log
        self.snapshot_ids: list[str] = []

    def build_batch(self, *, snapshot, crane_ids, risk_hints):
        self.snapshot_ids.append(snapshot.snapshot_id)
        self.log.append(
            f"observation.build:{snapshot.snapshot_id}:{','.join(crane_ids)}"
        )
        return [
            SimpleNamespace(
                observation_id=f"OBS_{snapshot.snapshot_id}_{crane_id}",
                source_snapshot_id=snapshot.snapshot_id,
                operator_id=f"OP_{crane_id}",
                crane_id=crane_id,
                time_s=snapshot.time_s,
            )
            for crane_id in crane_ids
        ]


class FakeOperator:
    def __init__(self, log: list[str]) -> None:
        self.log = log
        self.calls: list[list[SimpleNamespace]] = []
        self.episode_failure_reason: str | None = None

    def decide(self, observations, *, llm_decision_interval_s):
        observations = list(observations)
        self.calls.append(observations)
        snapshot_id = observations[0].source_snapshot_id
        self.log.append(f"operator.decide:{snapshot_id}")
        return [
            SimpleNamespace(
                parsed_command=_parsed_command(
                    crane_id=observation.crane_id,
                    snapshot_id=observation.source_snapshot_id,
                    observation_id=observation.observation_id,
                    time_s=observation.time_s,
                ),
                episode_failure_reason=self.episode_failure_reason,
            )
            for observation in observations
        ]


class FakeSafety:
    def __init__(self, log: list[str]) -> None:
        self.log = log
        self.batch_sizes: list[int] = []

    def apply_pipeline(self, parsed_commands, *, snapshot):
        parsed_commands = list(parsed_commands)
        self.batch_sizes.append(len(parsed_commands))
        self.log.append(
            "safety.apply:"
            + ",".join(command.command_id for command in parsed_commands)
        )
        return [
            ExecutedCommand.from_raw(
                command_id=f"EXEC_{command.command_id}",
                raw_command=command,
            )
            for command in parsed_commands
        ]


class FakeController:
    def __init__(self, log: list[str]) -> None:
        self.log = log
        self.command_batches: list[list[ExecutedCommand]] = []

    def compute_batch(self, *, commands, states, models, dt_s, now_s):
        commands = list(commands)
        self.command_batches.append(commands)
        self.log.append(f"controller.compute:{now_s:.1f}")
        return [
            ControlTarget(
                crane_id=command.crane_id,
                target_slew_velocity_rad_s=0.0,
                target_trolley_velocity_m_s=0.0,
                target_hoist_velocity_m_s=0.0,
                source_command_id=command.command_id,
            )
            for command in commands
        ], []


class FakePhysics:
    def __init__(self, log: list[str]) -> None:
        self.log = log
        self.nan_after_step = False

    def step_world(self, *, crane_configs, previous_states, control_targets, dt):
        self.log.append("physics.step")
        if self.nan_after_step:
            return [
                previous_states[0].model_copy(update={"theta_rad": float("nan")}),
                *list(previous_states[1:]),
            ]
        return list(previous_states)


class FakeCollision:
    def __init__(self, log: list[str]) -> None:
        self.log = log
        self.events: list[CollisionEvent] = []

    def detect(self, *, states, risk, time_s):
        self.log.append(f"collision.detect:{time_s:.1f}")
        return list(self.events)


class FakeRecorder:
    def __init__(self, log: list[str]) -> None:
        self.log = log
        self.initial_calls: list[dict] = []
        self.step_calls: list[dict] = []

    def record_initial_frame(self, **kwargs) -> None:
        self.initial_calls.append(kwargs)
        self.log.append(f"recorder.initial:{kwargs['time_s']:.1f}")

    def record_step(self, **kwargs) -> None:
        self.step_calls.append(kwargs)
        self.log.append(f"recorder.step:{kwargs['time_s']:.1f}")


class FakeWebSocket:
    def __init__(self, log: list[str]) -> None:
        self.log = log
        self.calls: list[dict] = []

    def broadcast_sim_frame_if_enabled(self, **kwargs) -> None:
        self.calls.append(kwargs)
        self.log.append(f"websocket.broadcast:{kwargs['time_s']:.1f}")


class FakeReplaySource:
    def __init__(self, commands: list[ExecutedCommand]) -> None:
        self.commands = commands
        self.calls: list[dict] = []

    def commands_for_decision(self, *, snapshot, crane_ids, decision_indices):
        self.calls.append(
            {
                "snapshot_id": snapshot.snapshot_id,
                "crane_ids": list(crane_ids),
                "decision_indices": dict(decision_indices),
            }
        )
        return list(self.commands)


def _dependencies(
    log: list[str],
    *,
    websocket: FakeWebSocket | None = None,
    replay: FakeReplaySource | None = None,
) -> SchedulerDependencies:
    return SchedulerDependencies(
        weather=FakeWeather(log),
        task_system=FakeTaskSystem(log),
        observation_builder=FakeObservationBuilder(log),
        operator=FakeOperator(log),
        safety=FakeSafety(log),
        controller=FakeController(log),
        physics=FakePhysics(log),
        risk=FakeRisk(log),
        collision=FakeCollision(log),
        recorder=FakeRecorder(log),
        websocket=websocket,
        replay=replay,
    )


def _runner(
    log: list[str],
    *,
    config: SchedulerConfig | None = None,
    dependencies: SchedulerDependencies | None = None,
) -> EpisodeRunner:
    configs = _crane_configs(2)
    states = [initialize_crane_state(config) for config in configs]
    return EpisodeRunner(
        config=config or _scheduler_config(),
        dependencies=dependencies or _dependencies(log),
        episode_id="EPJ",
        crane_configs=configs,
        crane_states=states,
        weather_state=_weather_state(0.0),
        visibility_context=_visibility_context(0.0),
        task_queues=[],
        task_contexts=_task_contexts_for([config.crane_id for config in configs], 0.0),
    )


def test_episode_runner_run_one_frame_follows_fixed_lifecycle_order() -> None:
    log: list[str] = []
    runner = _runner(log)

    result = runner.run_one_frame()

    assert result.status is EpisodeStatus.RUNNING
    assert result.frame_index == 1
    assert result.time_s == pytest.approx(0.5)
    assert result.snapshot_id == "SNAP_EPJ_000000"
    assert log == [
        "weather.update:0.0",
        "recorder.initial:0.0",
        "weather.update:0.0",
        "task.activate:0.0",
        "risk.predecision:SNAP_EPJ_000000",
        "observation.build:SNAP_EPJ_000000:C1,C2",
        "operator.decide:SNAP_EPJ_000000",
        "safety.apply:cmd-C1-0p0,cmd-C2-0p0",
        "controller.compute:0.0",
        "physics.step",
        "task.update_after_physics:0.5",
        "risk.after_physics:0.5",
        "collision.detect:0.5",
        "recorder.step:0.5",
    ]
    assert runner.dependencies.observation_builder.snapshot_ids == [
        "SNAP_EPJ_000000"
    ]
    assert runner.dependencies.safety.batch_sizes == [2]
    assert len(runner.dependencies.recorder.initial_calls) == 1
    assert len(runner.dependencies.recorder.step_calls) == 1


def test_episode_runner_maps_operator_episode_failure_to_llm_failed() -> None:
    log: list[str] = []
    dependencies = _dependencies(log)
    dependencies.operator.episode_failure_reason = "llm_failed"
    runner = _runner(log, dependencies=dependencies)

    result = runner.run_one_frame()

    assert result.status is EpisodeStatus.LLM_FAILED
    assert runner.episode_status is EpisodeStatus.LLM_FAILED
    assert runner.dependencies.recorder.step_calls[-1]["status"] is EpisodeStatus.LLM_FAILED


def test_episode_runner_run_episode_completes_after_cooldown() -> None:
    log: list[str] = []
    runner = _runner(
        log,
        config=_scheduler_config(
            duration_s=5.0,
            stop_when_all_tasks_done=True,
            completion_cooldown_s=0.5,
        ),
    )

    result = runner.run_episode()

    assert result.status is EpisodeStatus.COMPLETED
    assert result.final_time_s == pytest.approx(1.0)
    assert runner.dependencies.recorder.step_calls[-1]["status"] is EpisodeStatus.COMPLETED


def test_episode_runner_skips_decision_until_interval_and_expires_stale_command() -> None:
    log: list[str] = []
    runner = _runner(
        log,
        config=_scheduler_config(llm_decision_interval_s=2.0),
    )

    first = runner.run_one_frame()
    second = runner.run_one_frame()
    third = runner.run_one_frame()

    assert first.snapshot_id == "SNAP_EPJ_000000"
    assert second.snapshot_id is None
    assert third.snapshot_id is None
    assert len(runner.dependencies.operator.calls) == 1
    assert runner.dependencies.safety.batch_sizes == [2]
    second_commands = runner.dependencies.controller.command_batches[1]
    assert all(command.command_id.startswith("EXEC_cmd-C") for command in second_commands)
    third_commands = runner.dependencies.controller.command_batches[2]
    assert all(
        command.command_id.startswith("EXEC_cmd-neutral-expired-")
        for command in third_commands
    )


def test_interactive_runner_broadcasts_frame_when_websocket_present() -> None:
    log: list[str] = []
    websocket = FakeWebSocket(log)
    runner = _runner(
        log,
        config=_scheduler_config(mode="interactive_server"),
        dependencies=_dependencies(log, websocket=websocket),
    )

    result = runner.run_one_frame()

    assert result.status is EpisodeStatus.RUNNING
    assert len(websocket.calls) == 1
    assert websocket.calls[0]["frame_index"] == 1
    assert "websocket.broadcast:0.5" in log


def test_offline_replay_uses_historical_commands_without_operator_or_safety() -> None:
    log: list[str] = []
    configs = _crane_configs(2)
    replay_commands = [
        ExecutedCommand.from_raw(
            command_id="EXEC_REPLAY_C1",
            raw_command=_parsed_command(
                crane_id="C1",
                snapshot_id="SNAP_EPJ_000000",
                observation_id="OBS_REPLAY_C1",
                time_s=0.0,
            ),
        ),
        ExecutedCommand.from_raw(
            command_id="EXEC_REPLAY_C2",
            raw_command=_parsed_command(
                crane_id="C2",
                snapshot_id="SNAP_EPJ_000000",
                observation_id="OBS_REPLAY_C2",
                time_s=0.0,
            ),
        ),
    ]
    replay = FakeReplaySource(replay_commands)
    dependencies = _dependencies(log, replay=replay)
    runner = EpisodeRunner(
        config=_scheduler_config(mode="offline_replay"),
        dependencies=dependencies,
        episode_id="EPJ",
        crane_configs=configs,
        crane_states=[initialize_crane_state(config) for config in configs],
        weather_state=_weather_state(0.0),
        visibility_context=_visibility_context(0.0),
        task_queues=[],
        task_contexts=_task_contexts_for([config.crane_id for config in configs], 0.0),
    )

    result = runner.run_one_frame()

    assert result.status is EpisodeStatus.RUNNING
    assert replay.calls == [
        {
            "snapshot_id": "SNAP_EPJ_000000",
            "crane_ids": ["C1", "C2"],
            "decision_indices": {"C1": 0, "C2": 0},
        }
    ]
    assert dependencies.operator.calls == []
    assert dependencies.safety.batch_sizes == []
    assert [
        command.command_id
        for command in dependencies.controller.command_batches[-1]
    ] == ["EXEC_REPLAY_C1", "EXEC_REPLAY_C2"]


def test_offline_replay_missing_command_maps_failed_replay_mismatch() -> None:
    log: list[str] = []
    configs = _crane_configs(2)
    replay = FakeReplaySource(
        [
            ExecutedCommand.from_raw(
                command_id="EXEC_REPLAY_C1",
                raw_command=_parsed_command(
                    crane_id="C1",
                    snapshot_id="SNAP_EPJ_000000",
                    observation_id="OBS_REPLAY_C1",
                    time_s=0.0,
                ),
            )
        ]
    )
    dependencies = _dependencies(log, replay=replay)
    runner = EpisodeRunner(
        config=_scheduler_config(mode="offline_replay"),
        dependencies=dependencies,
        episode_id="EPJ",
        crane_configs=configs,
        crane_states=[initialize_crane_state(config) for config in configs],
        weather_state=_weather_state(0.0),
        visibility_context=_visibility_context(0.0),
        task_queues=[],
        task_contexts=_task_contexts_for([config.crane_id for config in configs], 0.0),
    )

    result = runner.run_one_frame()

    assert result.status is EpisodeStatus.FAILED_REPLAY_MISMATCH
    assert runner.episode_status is EpisodeStatus.FAILED_REPLAY_MISMATCH
    assert dependencies.operator.calls == []
    assert dependencies.safety.batch_sizes == []


def test_episode_runner_records_collision_terminal_frame() -> None:
    log: list[str] = []
    dependencies = _dependencies(log)
    dependencies.collision.events = [
        CollisionEvent(
            event_id="COLLISION_1",
            source_snapshot_id="SNAP_EPJ_000000",
            time_s=0.5,
            crane_id_a="C1",
            crane_id_b="C2",
            object_a="hook",
            object_b="hook",
            distance_m=0.0,
            reason="test collision",
        )
    ]
    runner = _runner(log, dependencies=dependencies)

    result = runner.run_one_frame()

    assert result.status is EpisodeStatus.FAILED_COLLISION
    assert runner.episode_status is EpisodeStatus.FAILED_COLLISION
    assert runner.dependencies.recorder.step_calls[-1]["status"] is EpisodeStatus.FAILED_COLLISION


def test_episode_runner_times_out_at_duration_boundary() -> None:
    log: list[str] = []
    runner = _runner(
        log,
        config=_scheduler_config(dt_s=0.5, duration_s=0.5),
    )

    result = runner.run_episode()

    assert result.status is EpisodeStatus.TIMEOUT
    assert result.final_time_s == pytest.approx(0.5)
    assert runner.dependencies.recorder.step_calls[-1]["status"] is EpisodeStatus.TIMEOUT


def test_episode_runner_maps_non_finite_state_to_failed_invalid_state() -> None:
    log: list[str] = []
    dependencies = _dependencies(log)
    dependencies.physics.nan_after_step = True
    runner = _runner(log, dependencies=dependencies)

    result = runner.run_one_frame()

    assert result.status is EpisodeStatus.FAILED_INVALID_STATE
    assert runner.episode_status is EpisodeStatus.FAILED_INVALID_STATE
    assert runner.dependencies.recorder.step_calls[-1]["status"] is EpisodeStatus.FAILED_INVALID_STATE
