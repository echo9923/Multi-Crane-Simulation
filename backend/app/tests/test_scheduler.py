from __future__ import annotations

import json
import math

import pytest
from pydantic import ValidationError

from backend.app.schemas.command import (
    ExecutedCommand,
    ExecutedAxisCommand,
    ExecutedLeftJoystickCommand,
    ExecutedRightJoystickCommand,
    ParsedCommand,
)
from backend.app.schemas.config import ScenarioConfig
from backend.app.schemas.control import ControlTarget
from backend.app.schemas.enums import LLMSchedulingMode, RuntimeMode
from backend.app.schemas.scheduler import (
    SCHEDULER_SCHEMA_VERSION,
    CommandStoreSnapshot,
    EpisodeResult,
    EpisodeStatus,
    FrameStepResult,
    ReplayValidationConfig,
    SchedulerConfig,
    SchedulerError,
    StoredCommand,
    TerminalStatusCandidate,
    WorldSnapshot,
)
from backend.app.schemas.task import Task, TaskPoint, TaskQueue
from backend.app.schemas.weather import WeatherState, WeatherVisibilityContext
from backend.app.sim.observation import build_observations_for_snapshot
from backend.app.sim.crane_model import build_crane_model_library
from backend.app.sim.layout import build_crane_configs
from backend.app.sim.physics import initialize_crane_state
from backend.app.sim.scheduler import (
    CommandStore,
    DecisionClock,
    freeze_world_snapshot,
    should_stop,
    to_observation_snapshot,
    update_terminal_status,
)
from backend.app.sim.task_observation import TaskObservationContext
from backend.app.sim.task_queue import IdleObservationContext
from backend.app.tests.test_config_schema import load_fixture


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


def _task(crane_id: str = "C1") -> Task:
    pickup = TaskPoint(
        x=10.0,
        y=0.0,
        z=1.0,
        zone_id="material_zone",
        zone_type="material",
    )
    dropoff = TaskPoint(
        x=30.0,
        y=10.0,
        z=20.0,
        zone_id="work_zone",
        zone_type="work",
    )
    return Task(
        task_id=f"T_{crane_id}_001",
        crane_id=crane_id,
        task_type="easy_task",
        pickup=pickup,
        dropoff=dropoff,
        pickup_zone_id=pickup.zone_id,
        dropoff_zone_id=dropoff.zone_id,
        planned_start_s=0.0,
        load_type="rebar_bundle",
        load_weight_t=2.0,
        load_size_m=[6.0, 1.0, 1.0],
        priority="medium",
        deadline_s=180.0,
        generation_seed=1,
        generation_attempt=0,
    )


def _raw_command(
    *,
    crane_id: str = "C1",
    snapshot_id: str = "SNAP_EP_000001",
    command_id: str = "cmd-001",
    time_s: float = 1.0,
    command_duration_s: float = 1.5,
) -> ParsedCommand:
    return ParsedCommand(
        command_id=command_id,
        response_id=f"resp-{command_id}",
        observation_id=f"obs-{command_id}",
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
        attention_target="scheduler_fixture",
        confidence=0.8,
        reason="scheduler test fixture",
    )


def _executed_command(
    *,
    crane_id: str = "C1",
    snapshot_id: str = "SNAP_EP_000001",
    command_id: str = "cmd-001",
    time_s: float = 1.0,
    command_duration_s: float = 1.5,
) -> ExecutedCommand:
    raw = _raw_command(
        crane_id=crane_id,
        snapshot_id=snapshot_id,
        command_id=command_id,
        time_s=time_s,
        command_duration_s=max(command_duration_s, 0.5),
    )
    return ExecutedCommand(
        command_id=f"EXEC_{command_id}",
        raw_command_id=raw.command_id,
        observation_id=raw.observation_id,
        source_snapshot_id=raw.source_snapshot_id,
        operator_id=raw.operator_id,
        crane_id=raw.crane_id,
        time_s=time_s,
        raw_command=raw,
        left_joystick=ExecutedLeftJoystickCommand(
            slew=ExecutedAxisCommand(direction="neutral", gear=0, source="raw"),
            trolley=ExecutedAxisCommand(direction="neutral", gear=0, source="raw"),
        ),
        right_joystick=ExecutedRightJoystickCommand(
            hoist=ExecutedAxisCommand(direction="neutral", gear=0, source="raw")
        ),
        deadman_pressed=True,
        emergency_stop=False,
        horn=False,
        command_duration_s=command_duration_s,
        task_action="none",
        modified=False,
    )


def _world_snapshot_payload() -> dict:
    configs = _crane_configs(2)
    states = [initialize_crane_state(config) for config in configs]
    return {
        "snapshot_id": "SNAP_EP_000001",
        "episode_id": "EP",
        "frame_index": 1,
        "time_s": 1.0,
        "decision_time_bucket": 2,
        "crane_states": states,
        "crane_configs": configs,
        "weather_state": _weather_state(1.0),
        "visibility_context": _visibility_context(1.0),
        "tasks": [_task("C1")],
        "task_queues": [TaskQueue(crane_id="C1", tasks=[_task("C1")])],
        "current_commands": {
            "C1": _executed_command(crane_id="C1", command_id="cmd-c1"),
            "C2": _executed_command(crane_id="C2", command_id="cmd-c2"),
        },
        "current_control_targets": {
            "C1": ControlTarget(
                crane_id="C1",
                target_slew_velocity_rad_s=0.0,
                target_trolley_velocity_m_s=0.0,
                target_hoist_velocity_m_s=0.0,
            )
        },
        "recent_decisions": {"C1": [{"time_s": 0.5, "command_summary": "neutral"}]},
        "recent_events": {"C1": [{"event_type": "task_started", "time_s": 0.0}]},
    }


def _task_contexts(time_s: float = 1.0) -> dict:
    return {
        "C1": TaskObservationContext(
            crane_id="C1",
            time_s=time_s,
            has_active_task=True,
            task_id="T_C1_001",
            task_type="easy_task",
            task_stage="move_to_pickup",
            priority="medium",
            deadline_s=180.0,
            deadline_missed=False,
            overtime_s=0.0,
            pickup=TaskPoint(
                x=10.0,
                y=0.0,
                z=1.0,
                zone_id="material_zone",
                zone_type="material",
            ),
            dropoff=TaskPoint(
                x=30.0,
                y=10.0,
                z=20.0,
                zone_id="work_zone",
                zone_type="work",
            ),
            current_target=TaskPoint(
                x=10.0,
                y=0.0,
                z=1.0,
                zone_id="material_zone",
                zone_type="material",
            ),
            load_type="rebar_bundle",
            load_weight_t=2.0,
            load_size_m=[6.0, 1.0, 1.0],
            load_attached=False,
            ground_signal_hint="吊钩在目标点附近，请微调。",
        ),
        "C2": IdleObservationContext(
            crane_id="C2",
            time_s=time_s,
            has_active_task=False,
            task_id=None,
            task_stage="idle",
            current_target=None,
            ground_signal_hint="当前无任务，请保持塔吊安全静止并观察现场。",
        ),
    }


def test_scheduler_config_from_dict_extracts_runtime_and_llm_scheduling() -> None:
    config = SchedulerConfig.from_config(
        {
            "sim": {
                "dt": 0.1,
                "duration_s": 60.0,
                "min_duration_s": 5.0,
                "stop_when_all_tasks_done": True,
                "completion_cooldown_s": 2.0,
                "controller_hz": 20.0,
                "llm_decision_interval_s": 1.0,
            },
            "runtime": {
                "mode": "offline_batch",
                "replay_file": "runs/ep/replay/command_replay.jsonl",
            },
            "llm": {
                "max_consecutive_failures": 3,
                "scheduling": {
                    "mode": "realtime_stale",
                    "stale_command_max_hold_s": 0.5,
                },
            },
        }
    )

    assert config.schema_version == SCHEDULER_SCHEMA_VERSION
    assert config.dt_s == 0.1
    assert config.duration_s == 60.0
    assert config.min_duration_s == 5.0
    assert config.completion_cooldown_s == 2.0
    assert config.controller_hz == 20.0
    assert config.llm_decision_interval_s == 1.0
    assert config.run_mode is RuntimeMode.OFFLINE_BATCH
    assert config.llm_scheduling_mode is LLMSchedulingMode.REALTIME_STALE
    assert config.max_consecutive_llm_failures == 3
    assert config.replay is not None
    assert config.replay.replay_file == "runs/ep/replay/command_replay.jsonl"


def test_scheduler_config_from_resolved_like_runtime_shape() -> None:
    config = SchedulerConfig.from_config(
        {
            "runtime": {
                "runtime": {"mode": "interactive_server"},
                "sim": {
                    "dt": 0.05,
                    "duration_s": 20.0,
                    "min_duration_s": 0.0,
                    "stop_when_all_tasks_done": False,
                    "completion_cooldown_s": 0.0,
                    "controller_hz": 40.0,
                    "llm_decision_interval_s": 0.5,
                },
            },
            "experiment": {
                "llm": {
                    "scheduling": {"mode": "offline_wait"},
                    "max_consecutive_failures": 5,
                }
            },
        }
    )

    assert config.run_mode is RuntimeMode.INTERACTIVE_SERVER
    assert config.llm_scheduling_mode is LLMSchedulingMode.OFFLINE_WAIT
    assert config.max_consecutive_llm_failures == 5
    assert config.stop_when_all_tasks_done is False


@pytest.mark.parametrize(
    "payload",
    [
        {"dt_s": 0.0, "duration_s": 1.0, "controller_hz": 20.0, "llm_decision_interval_s": 1.0, "run_mode": "offline_batch"},
        {"dt_s": 0.1, "duration_s": 0.0, "controller_hz": 20.0, "llm_decision_interval_s": 1.0, "run_mode": "offline_batch"},
        {"dt_s": 0.1, "duration_s": 1.0, "controller_hz": 0.0, "llm_decision_interval_s": 1.0, "run_mode": "offline_batch"},
        {"dt_s": 0.1, "duration_s": 1.0, "controller_hz": 20.0, "llm_decision_interval_s": -1.0, "run_mode": "offline_batch"},
        {"dt_s": math.nan, "duration_s": 1.0, "controller_hz": 20.0, "llm_decision_interval_s": 1.0, "run_mode": "offline_batch"},
        {"dt_s": 0.1, "duration_s": 1.0, "controller_hz": 20.0, "llm_decision_interval_s": 1.0, "run_mode": "offline_wait"},
    ],
)
def test_scheduler_config_rejects_invalid_values(payload: dict) -> None:
    with pytest.raises(ValidationError):
        SchedulerConfig.model_validate(payload)


def test_episode_status_covers_required_terminal_values() -> None:
    assert {status.value for status in EpisodeStatus} >= {
        "running",
        "completed",
        "timeout",
        "failed_collision",
        "failed_invalid_state",
        "llm_failed",
        "failed_replay_mismatch",
        "failed_recovery_blocked",
        "failed_recovery_timeout",
        "stopped_by_user",
    }


def test_world_snapshot_accepts_complete_payload_and_serializes() -> None:
    snapshot = WorldSnapshot.model_validate(_world_snapshot_payload())

    assert snapshot.schema_version == SCHEDULER_SCHEMA_VERSION
    assert snapshot.snapshot_id == "SNAP_EP_000001"
    assert [state.crane_id for state in snapshot.crane_states] == ["C1", "C2"]
    payload = snapshot.model_dump(mode="json")
    json.dumps(payload, ensure_ascii=False)
    assert payload["current_commands"]["C1"]["crane_id"] == "C1"


def test_world_snapshot_forbids_extra_and_future_fields() -> None:
    payload = _world_snapshot_payload()
    payload["offline_risk_label"] = {"future_min_distance_m": 0.1}

    with pytest.raises(ValidationError):
        WorldSnapshot.model_validate(payload)

    payload = _world_snapshot_payload()
    payload["recent_decisions"]["C1"][0]["llm_reason"] = "hidden chain"

    with pytest.raises(ValidationError):
        WorldSnapshot.model_validate(payload)


def test_world_snapshot_rejects_duplicate_and_missing_crane_identity() -> None:
    payload = _world_snapshot_payload()
    payload["crane_states"] = [payload["crane_states"][0], payload["crane_states"][0]]

    with pytest.raises(ValidationError):
        WorldSnapshot.model_validate(payload)

    payload = _world_snapshot_payload()
    payload["crane_configs"] = payload["crane_configs"][:1]

    with pytest.raises(ValidationError):
        WorldSnapshot.model_validate(payload)


def test_world_snapshot_rejects_non_finite_nested_state_values() -> None:
    payload = _world_snapshot_payload()
    bad_state = payload["crane_states"][0].model_copy(update={"theta_rad": math.nan})
    payload["crane_states"] = [bad_state, payload["crane_states"][1]]

    with pytest.raises(ValidationError):
        WorldSnapshot.model_validate(payload)


def test_world_snapshot_validates_current_command_and_target_keys() -> None:
    payload = _world_snapshot_payload()
    payload["current_commands"] = {"C2": _executed_command(crane_id="C1")}

    with pytest.raises(ValidationError):
        WorldSnapshot.model_validate(payload)

    payload = _world_snapshot_payload()
    payload["current_control_targets"] = {
        "C2": ControlTarget(
            crane_id="C1",
            target_slew_velocity_rad_s=0.0,
            target_trolley_velocity_m_s=0.0,
            target_hoist_velocity_m_s=0.0,
        )
    }

    with pytest.raises(ValidationError):
        WorldSnapshot.model_validate(payload)


def test_stored_command_and_command_store_snapshot_validate_identity_and_expiry() -> None:
    command = _executed_command(command_id="cmd-store", time_s=4.0, command_duration_s=1.25)
    stored = StoredCommand(
        crane_id="C1",
        command=command,
        applied_at_s=4.0,
        expires_at_s=5.25,
        source="decision",
    )
    snapshot = CommandStoreSnapshot(time_s=4.0, commands={"C1": stored})

    assert stored.expires_at_s == pytest.approx(
        command.time_s + command.command_duration_s
    )
    json.dumps(snapshot.model_dump(mode="json"), ensure_ascii=False)

    with pytest.raises(ValidationError):
        StoredCommand(
            crane_id="C2",
            command=command,
            applied_at_s=4.0,
            expires_at_s=5.25,
            source="decision",
        )

    with pytest.raises(ValidationError):
        CommandStoreSnapshot(time_s=4.0, commands={"C2": stored})


def test_terminal_and_episode_results_are_json_serializable() -> None:
    candidate = TerminalStatusCandidate(
        status="failed_collision",
        source_module="K",
        reason="collision detected",
        time_s=6.0,
        frame_index=60,
        details={"pair_id": "C1-C2"},
    )
    frame = FrameStepResult(
        frame_index=60,
        time_s=6.0,
        status="failed_collision",
        snapshot_id="SNAP_EP_000060",
        events=[{"event_type": "collision"}],
    )
    episode = EpisodeResult(
        episode_id="EP",
        status="failed_collision",
        final_time_s=6.0,
        final_frame_index=60,
        reason="collision detected",
        terminal_candidate=candidate,
        metrics={"frames": 60},
    )

    assert frame.status is EpisodeStatus.FAILED_COLLISION
    assert episode.terminal_candidate == candidate
    json.dumps(candidate.model_dump(mode="json"), ensure_ascii=False)
    json.dumps(frame.model_dump(mode="json"), ensure_ascii=False)
    json.dumps(episode.model_dump(mode="json"), ensure_ascii=False)


def test_scheduler_error_carries_status_and_details() -> None:
    error = SchedulerError(
        "replay mismatch",
        error_code="SCH_E_REPLAY_MISMATCH",
        episode_status=EpisodeStatus.FAILED_REPLAY_MISMATCH,
        source_module="J",
        details={"command_id": "exec-001"},
    )

    assert str(error) == "replay mismatch"
    assert error.error_code == "SCH_E_REPLAY_MISMATCH"
    assert error.episode_status is EpisodeStatus.FAILED_REPLAY_MISMATCH
    assert error.details == {"command_id": "exec-001"}


def test_replay_validation_config_has_strict_defaults() -> None:
    replay = ReplayValidationConfig()

    assert replay.strict is True
    assert replay.require_resolved_config_hash_match is True
    assert replay.position_tolerance_m == pytest.approx(1.0e-5)
    assert replay.angle_tolerance_rad == pytest.approx(1.0e-7)
    assert replay.velocity_tolerance == pytest.approx(1.0e-6)


def test_freeze_world_snapshot_is_stable_and_detached_from_inputs() -> None:
    configs = _crane_configs(2)
    states = [initialize_crane_state(config) for config in configs]
    tasks = [_task("C1")]
    queues = [TaskQueue(crane_id="C1", tasks=tasks)]
    control_targets = {
        "C1": ControlTarget(
            crane_id="C1",
            target_slew_velocity_rad_s=0.1,
            target_trolley_velocity_m_s=0.0,
            target_hoist_velocity_m_s=0.0,
        )
    }

    snapshot = freeze_world_snapshot(
        episode_id="EP",
        frame_index=3,
        time_s=0.30000000000000004,
        llm_decision_interval_s=0.1,
        crane_states=states,
        crane_configs=configs,
        weather_state=_weather_state(0.3),
        visibility_context=_visibility_context(0.3),
        tasks=tasks,
        task_queues=queues,
        task_contexts=_task_contexts(0.3),
        current_commands={"C1": _executed_command(crane_id="C1")},
        current_control_targets=control_targets,
        recent_decisions={"C1": [{"time_s": 0.2, "command_summary": "neutral"}]},
        recent_events={"C1": [{"event_type": "task_started", "time_s": 0.0}]},
    )
    repeated = freeze_world_snapshot(
        episode_id="EP",
        frame_index=3,
        time_s=0.30000000000000004,
        llm_decision_interval_s=0.1,
        crane_states=states,
        crane_configs=configs,
        weather_state=_weather_state(0.3),
        visibility_context=_visibility_context(0.3),
        tasks=tasks,
        task_queues=queues,
        task_contexts=_task_contexts(0.3),
        current_commands={"C1": _executed_command(crane_id="C1")},
        current_control_targets=control_targets,
        recent_decisions={"C1": [{"time_s": 0.2, "command_summary": "neutral"}]},
        recent_events={"C1": [{"event_type": "task_started", "time_s": 0.0}]},
    )

    assert snapshot.snapshot_id == "SNAP_EP_000003"
    assert snapshot.decision_time_bucket == 3
    assert snapshot.model_dump(mode="json") == repeated.model_dump(mode="json")

    states[0] = states[0].model_copy(update={"theta_rad": 99.0})
    tasks[0] = tasks[0].model_copy(update={"status": "completed"})
    control_targets["C1"] = control_targets["C1"].model_copy(
        update={"target_slew_velocity_rad_s": 9.9}
    )

    assert snapshot.crane_states[0].theta_rad != 99.0
    assert snapshot.tasks[0].status == "pending"
    assert (
        snapshot.current_control_targets["C1"].target_slew_velocity_rad_s
        == pytest.approx(0.1)
    )


def test_to_observation_snapshot_uses_same_snapshot_id_and_control_targets() -> None:
    configs = _crane_configs(2)
    states = [initialize_crane_state(config) for config in configs]
    snapshot = freeze_world_snapshot(
        episode_id="EP",
        frame_index=42,
        time_s=4.2,
        llm_decision_interval_s=0.1,
        crane_states=states,
        crane_configs=configs,
        weather_state=_weather_state(4.2),
        visibility_context=_visibility_context(4.2),
        tasks=[_task("C1")],
        task_queues=[TaskQueue(crane_id="C1", tasks=[_task("C1")])],
        task_contexts=_task_contexts(4.2),
        current_commands={"C1": _executed_command(crane_id="C1")},
        current_control_targets={
            "C1": ControlTarget(
                crane_id="C1",
                target_slew_velocity_rad_s=-0.1,
                target_trolley_velocity_m_s=0.2,
                target_hoist_velocity_m_s=0.0,
            )
        },
        recent_decisions={"C1": [{"time_s": 4.0, "command_summary": "slew left"}]},
        recent_events={"C1": [{"event_type": "task_started", "time_s": 4.0}]},
    )

    observation_snapshot = to_observation_snapshot(
        snapshot,
        neighbor_map={"C1": ["C2"], "C2": ["C1"]},
    )
    observations = build_observations_for_snapshot(
        snapshot=observation_snapshot,
        crane_ids=["C1", "C2"],
        risk_prompt_mode="R0",
        operator_profiles={"C1": "normal", "C2": "conservative"},
    )

    assert observation_snapshot.snapshot_id == snapshot.snapshot_id
    assert set(observation_snapshot.current_commands) == {"C1"}
    assert observation_snapshot.current_commands["C1"].crane_id == "C1"
    assert observation_snapshot.current_commands["C1"].source_command_id is None
    assert {observation.source_snapshot_id for observation in observations} == {
        snapshot.snapshot_id
    }


@pytest.mark.parametrize(
    ("time_s", "interval"),
    [
        (-0.1, 0.1),
        (0.0, 0.0),
        (math.nan, 0.1),
        (0.0, math.inf),
    ],
)
def test_freeze_world_snapshot_rejects_invalid_time_inputs(
    time_s: float, interval: float
) -> None:
    configs = _crane_configs(2)
    states = [initialize_crane_state(config) for config in configs]

    with pytest.raises(SchedulerError):
        freeze_world_snapshot(
            episode_id="EP",
            frame_index=0,
            time_s=time_s,
            llm_decision_interval_s=interval,
            crane_states=states,
            crane_configs=configs,
            weather_state=_weather_state(0.0),
            visibility_context=_visibility_context(0.0),
        )


def test_freeze_world_snapshot_rejects_recent_decision_leaks() -> None:
    configs = _crane_configs(2)
    states = [initialize_crane_state(config) for config in configs]

    with pytest.raises(SchedulerError):
        freeze_world_snapshot(
            episode_id="EP",
            frame_index=1,
            time_s=1.0,
            llm_decision_interval_s=0.5,
            crane_states=states,
            crane_configs=configs,
            weather_state=_weather_state(1.0),
            visibility_context=_visibility_context(1.0),
            recent_decisions={
                "C1": [
                    {
                        "time_s": 0.5,
                        "command_summary": "neutral",
                        "future_min_distance_m": 0.1,
                    }
                ]
            },
        )


def test_command_store_initializes_startup_neutral_for_each_crane() -> None:
    store = CommandStore.with_startup_neutral(
        crane_ids=["C1", "C2"],
        time_s=0.0,
        default_operator_ids={"C1": "OP_A", "C2": "OP_B"},
        command_duration_s=1.0,
    )

    commands = store.get_current_commands()

    assert set(commands) == {"C1", "C2"}
    assert commands["C1"].operator_id == "OP_A"
    assert commands["C2"].operator_id == "OP_B"
    for command in commands.values():
        assert command.left_joystick.slew.direction == "neutral"
        assert command.left_joystick.trolley.gear == 0
        assert command.right_joystick.hoist.direction == "neutral"
        assert command.deadman_pressed is True
        assert command.emergency_stop is False
        assert command.task_action == "none"


def test_command_store_replaces_due_commands_atomically() -> None:
    store = CommandStore.with_startup_neutral(crane_ids=["C1", "C2"])
    old_commands = store.get_current_commands()
    c1 = _executed_command(
        crane_id="C1",
        command_id="cmd-new-c1",
        time_s=2.0,
        command_duration_s=1.0,
    )
    c2 = _executed_command(
        crane_id="C2",
        command_id="cmd-new-c2",
        time_s=2.0,
        command_duration_s=1.0,
    )

    snapshot = store.replace_current_commands([c1, c2], sim_time=2.0)

    assert store.get_current_commands()["C1"].command_id == c1.command_id
    assert store.get_current_commands()["C2"].command_id == c2.command_id
    assert snapshot.commands["C1"].source == "decision"
    assert snapshot.commands["C1"].expires_at_s == pytest.approx(3.0)
    assert old_commands["C1"].command_id != c1.command_id


def test_command_store_rejects_invalid_batch_without_partial_update() -> None:
    store = CommandStore.with_startup_neutral(crane_ids=["C1", "C2"])
    before = store.get_current_commands()
    valid = _executed_command(crane_id="C1", command_id="cmd-valid", time_s=2.0)
    unknown = _executed_command(crane_id="C9", command_id="cmd-unknown", time_s=2.0)

    with pytest.raises(SchedulerError):
        store.replace_current_commands([valid, unknown], sim_time=2.0)

    assert store.get_current_commands() == before

    duplicate = _executed_command(crane_id="C1", command_id="cmd-dup", time_s=2.0)
    with pytest.raises(SchedulerError):
        store.replace_current_commands([valid, duplicate], sim_time=2.0)

    assert store.get_current_commands() == before


def test_command_store_expires_only_commands_at_or_past_boundary() -> None:
    store = CommandStore.with_startup_neutral(crane_ids=["C1", "C2"])
    c1 = _executed_command(
        crane_id="C1",
        command_id="cmd-c1",
        time_s=2.0,
        command_duration_s=1.0,
    )
    c2 = _executed_command(
        crane_id="C2",
        command_id="cmd-c2",
        time_s=2.0,
        command_duration_s=2.0,
    )
    store.replace_current_commands([c1, c2], sim_time=2.0)

    commands, events = store.expire_or_neutral_stop(
        sim_time=2.99,
        command_duration_s=1.25,
    )
    assert commands["C1"].command_id == c1.command_id
    assert events == []

    commands, events = store.expire_or_neutral_stop(
        sim_time=3.0,
        command_duration_s=1.25,
    )

    assert commands["C1"].command_id.startswith("EXEC_cmd-neutral-expired-C1-")
    assert commands["C1"].time_s == pytest.approx(3.0)
    assert commands["C1"].command_duration_s == pytest.approx(1.25)
    assert commands["C1"].left_joystick.slew.direction == "neutral"
    assert commands["C1"].right_joystick.hoist.gear == 0
    assert commands["C1"].task_action == "none"
    assert commands["C2"].command_id == c2.command_id
    assert events == [
        {
            "event_type": "command_expired_neutral_stop",
            "time_s": 3.0,
            "crane_id": "C1",
            "expired_command_id": c1.command_id,
        }
    ]


def test_command_store_accepts_replay_source_and_serializes_snapshot() -> None:
    store = CommandStore.with_startup_neutral(crane_ids=["C1"])
    command = _executed_command(
        crane_id="C1",
        command_id="cmd-replay",
        time_s=5.0,
        command_duration_s=0.0,
    )

    snapshot = store.replace_current_commands(
        [command],
        sim_time=5.0,
        source="replay",
    )

    assert snapshot.commands["C1"].source == "replay"
    assert snapshot.commands["C1"].expires_at_s == pytest.approx(5.0)
    json.dumps(store.snapshot(time_s=5.0).model_dump(mode="json"), ensure_ascii=False)


def test_command_store_rejects_non_finite_time() -> None:
    store = CommandStore.with_startup_neutral(crane_ids=["C1"])

    with pytest.raises(SchedulerError):
        store.replace_current_commands(
            [_executed_command(crane_id="C1", command_id="cmd-c1", time_s=1.0)],
            sim_time=math.nan,
        )

    with pytest.raises(SchedulerError):
        store.expire_or_neutral_stop(sim_time=math.inf)


def test_decision_clock_first_frame_marks_all_cranes_due_in_order() -> None:
    clock = DecisionClock(
        crane_ids=["C2", "C1", "C3"],
        llm_decision_interval_s=0.5,
    )

    assert clock.cranes_due_for_decision(sim_time=0.0) == ["C2", "C1", "C3"]
    assert clock.decision_index("C2") == 0
    assert clock.last_decision_time("C2") is None


def test_decision_clock_respects_interval_and_updates_indices() -> None:
    clock = DecisionClock(crane_ids=["C1", "C2"], llm_decision_interval_s=0.5)

    clock.mark_decided(["C1", "C2"], decision_time_s=0.0)

    assert clock.cranes_due_for_decision(sim_time=0.49) == []
    assert clock.cranes_due_for_decision(sim_time=0.5) == ["C1", "C2"]

    clock.mark_decided(["C1", "C2"], decision_time_s=0.5)

    assert clock.decision_index("C1") == 2
    assert clock.decision_index("C2") == 2
    assert clock.last_decision_time("C1") == pytest.approx(0.5)


def test_decision_clock_can_mark_subset_and_return_only_remaining_due() -> None:
    clock = DecisionClock(crane_ids=["C1", "C2", "C3"], llm_decision_interval_s=1.0)

    clock.mark_decided(["C1", "C3"], decision_time_s=0.0)

    assert clock.cranes_due_for_decision(sim_time=0.2) == ["C2"]
    assert clock.decision_index("C1") == 1
    assert clock.decision_index("C2") == 0
    assert clock.decision_index("C3") == 1


def test_decision_clock_include_idle_false_filters_to_active_cranes() -> None:
    clock = DecisionClock(crane_ids=["C1", "C2", "C3"], llm_decision_interval_s=1.0)

    clock.mark_decided(["C1", "C2", "C3"], decision_time_s=0.0)

    assert clock.cranes_due_for_decision(
        sim_time=1.0,
        include_idle=True,
        active_crane_ids=["C2"],
    ) == ["C1", "C2", "C3"]
    assert clock.cranes_due_for_decision(
        sim_time=1.0,
        include_idle=False,
        active_crane_ids=["C2"],
    ) == ["C2"]
    assert clock.cranes_due_for_decision(
        sim_time=1.0,
        include_idle=False,
        active_crane_ids=[],
    ) == []


def test_decision_clock_handles_float_boundary() -> None:
    clock = DecisionClock(crane_ids=["C1"], llm_decision_interval_s=0.1)

    clock.mark_decided(["C1"], decision_time_s=0.2)

    assert clock.cranes_due_for_decision(sim_time=0.30000000000000004) == ["C1"]


def test_decision_clock_uses_same_due_list_for_all_driver_types() -> None:
    clock = DecisionClock(crane_ids=["C1", "C2"], llm_decision_interval_s=0.5)

    clock.mark_decided(["C1", "C2"], decision_time_s=0.0)
    due_by_driver = {
        driver_type: clock.cranes_due_for_decision(sim_time=0.5)
        for driver_type in ("rule", "llm", "mock", "replay")
    }

    assert due_by_driver == {
        "rule": ["C1", "C2"],
        "llm": ["C1", "C2"],
        "mock": ["C1", "C2"],
        "replay": ["C1", "C2"],
    }


def test_decision_clock_rejects_invalid_inputs() -> None:
    with pytest.raises(SchedulerError):
        DecisionClock(crane_ids=["C1", "C1"], llm_decision_interval_s=0.5)

    with pytest.raises(SchedulerError):
        DecisionClock(crane_ids=["C1"], llm_decision_interval_s=0.0)

    clock = DecisionClock(crane_ids=["C1"], llm_decision_interval_s=0.5)

    with pytest.raises(SchedulerError):
        clock.mark_decided(["C2"], decision_time_s=0.0)

    with pytest.raises(SchedulerError):
        clock.mark_decided(["C1"], decision_time_s=math.nan)

    clock.mark_decided(["C1"], decision_time_s=1.0)

    with pytest.raises(SchedulerError):
        clock.cranes_due_for_decision(sim_time=0.9)


def test_update_terminal_status_maps_recovery_failures() -> None:
    config = SchedulerConfig(
        dt_s=0.5,
        duration_s=10.0,
        controller_hz=20.0,
        llm_decision_interval_s=1.0,
        run_mode="offline_batch",
    )
    states = [initialize_crane_state(config_item) for config_item in _crane_configs(1)]

    blocked = update_terminal_status(
        current_status=EpisodeStatus.RUNNING,
        sim_time=1.0,
        frame_index=2,
        states=states,
        task_queues=[],
        task_events=[{"reason": "failed_recovery_blocked"}],
        collision_events=[],
        config=config,
    )
    timeout = update_terminal_status(
        current_status=EpisodeStatus.RUNNING,
        sim_time=1.0,
        frame_index=2,
        states=states,
        task_queues=[],
        task_events=[{"details": {"episode_failure_request": "failed_recovery_timeout"}}],
        collision_events=[],
        config=config,
    )

    assert isinstance(blocked, TerminalStatusCandidate)
    assert blocked.status is EpisodeStatus.FAILED_RECOVERY_BLOCKED
    assert isinstance(timeout, TerminalStatusCandidate)
    assert timeout.status is EpisodeStatus.FAILED_RECOVERY_TIMEOUT


def test_should_stop_covers_terminal_timeout_and_completion_cooldown() -> None:
    config = SchedulerConfig(
        dt_s=0.5,
        duration_s=2.0,
        controller_hz=20.0,
        llm_decision_interval_s=1.0,
        run_mode="offline_batch",
        stop_when_all_tasks_done=True,
        completion_cooldown_s=0.5,
    )

    assert should_stop(
        episode_status=EpisodeStatus.FAILED_COLLISION,
        sim_time=0.5,
        config=config,
    )
    assert should_stop(
        episode_status=EpisodeStatus.RUNNING,
        sim_time=2.0,
        config=config,
    )
    assert not should_stop(
        episode_status=EpisodeStatus.RUNNING,
        sim_time=0.75,
        config=config,
        all_tasks_done_since_s=0.5,
    )
    assert should_stop(
        episode_status=EpisodeStatus.RUNNING,
        sim_time=1.0,
        config=config,
        all_tasks_done_since_s=0.5,
    )
