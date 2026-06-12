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
from backend.app.sim.crane_model import build_crane_model_library
from backend.app.sim.layout import build_crane_configs
from backend.app.sim.physics import initialize_crane_state
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
