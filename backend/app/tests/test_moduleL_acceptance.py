from __future__ import annotations

import json
from types import SimpleNamespace

import pyarrow.parquet as pq
import pytest

from backend.app.core.config_resolver import resolve_config
from backend.app.schemas.command import ExecutedCommand, ParsedCommand
from backend.app.schemas.enums import LLMProviderName, SafetyMode
from backend.app.schemas.risk import InterventionRecord, OnlineRisk, RiskPairResult
from backend.app.schemas.recorder import (
    EventLogEntry,
    ObservationLogEntry,
    SimFrame,
)
from backend.app.sim.recorder import DataExportError, Recorder
from backend.app.sim.scheduler import SchedulerDependencies
from backend.app.sim.physics import initialize_crane_state
from backend.app.tests.test_config_schema import load_fixture
from backend.app.tests.test_moduleJ_acceptance import (
    FakeCollision,
    FakeController,
    FakeObservationBuilder,
    FakeOperator,
    FakePhysics,
    FakeRisk,
    FakeSafety,
    FakeTaskSystem,
    FakeWeather,
    _crane_configs,
    _runner,
    _scheduler_config,
)


def _resolved_config(tmp_path):
    resolved = resolve_config(
        load_fixture("scenario_valid.yaml"),
        load_fixture("experiment_valid.yaml"),
    )
    return resolved.model_copy(
        update={
            "output": resolved.output.model_copy(update={"run_root": str(tmp_path)})
        }
    )


def _parsed_command(*, crane_id: str = "C1") -> ParsedCommand:
    return ParsedCommand(
        command_id=f"CMD-{crane_id}",
        response_id=f"RESP-{crane_id}",
        observation_id=f"OBS-{crane_id}",
        source_snapshot_id="SNAP-001",
        operator_id=f"OP-{crane_id}",
        crane_id=crane_id,
        time_s=0.5,
        left_joystick={
            "slew": {"direction": "neutral", "gear": 0},
            "trolley": {"direction": "neutral", "gear": 0},
        },
        right_joystick={"hoist": {"direction": "neutral", "gear": 0}},
        deadman_pressed=True,
        emergency_stop=False,
        horn=False,
        command_duration_s=1.0,
        task_action="none",
        attention_target="module_l_acceptance",
        confidence=0.8,
        reason="acceptance fixture",
    )


def _executed_command(*, crane_id: str = "C1") -> ExecutedCommand:
    return ExecutedCommand.from_raw(
        command_id=f"EXEC-{crane_id}",
        raw_command=_parsed_command(crane_id=crane_id),
        interventions=[
            InterventionRecord(
                intervention_id=f"INT-{crane_id}",
                crane_id=crane_id,
                safety_mode=SafetyMode.S2,
                risk_level="high",
                action="limit_speed_on_high_risk",
                modified=True,
                reason="near neighbor",
                pair_ids=["C1-C2"],
            )
        ],
        modification_reasons=["risk_intervention"],
    )


def _online_risk() -> OnlineRisk:
    return OnlineRisk(
        risk_id="RISK-001",
        source_snapshot_id="SNAP-001",
        time_s=0.5,
        pairs=[
            RiskPairResult(
                pair_id="C1-C2",
                crane_id_a="C1",
                crane_id_b="C2",
                time_s=0.5,
                d_min_online_m=3.0,
                d_hat_min_m=1.5,
                ttc_hat_s=4.0,
                d_safe_effective_m=5.0,
                base_threshold_m=4.0,
                wind_extra_m=1.0,
                risk_level="high",
                nearest_object_a="hook",
                nearest_object_b="jib",
                relative_motion="closing",
                confidence=0.75,
                reasons=["acceptance fixture"],
            )
        ],
        global_risk_level="high",
        nearest_pair_id="C1-C2",
        nearest_neighbor_by_crane={"C1": "C2", "C2": "C1"},
    )


def _llm_call_record(*, crane_id: str = "C1") -> SimpleNamespace:
    command = _parsed_command(crane_id=crane_id)
    return SimpleNamespace(
        call_id=f"CALL-{crane_id}",
        provider=LLMProviderName.MOCK,
        model="mock-command-v1",
        latency_ms=120.0,
        token_usage={"prompt_tokens": 20, "completion_tokens": 8},
        attempt_index=1,
        raw_response={
            "response_id": f"RESP-{crane_id}",
            "content": "{}",
            "provider": "mock",
            "model": "mock-command-v1",
        },
        parsed_command=command,
        validation_errors=[],
    )


def _observation(*, crane_id: str = "C1") -> SimpleNamespace:
    return SimpleNamespace(
        observation_id=f"OBS-{crane_id}",
        episode_id="EPL",
        time_s=0.5,
        crane_id=crane_id,
        risk_prompt_mode="R1",
        observation={"self": {"crane_id": crane_id}, "risk": "high"},
        source_snapshot_id="SNAP-001",
    )


def test_module_l_schema_acceptance_surface_is_available() -> None:
    frame = SimFrame(
        episode_id="episode-001",
        scenario_id="scenario-001",
        frame=0,
        time_s=0.0,
        episode_status="running",
        cranes=[],
        pairs=[],
        tasks=[],
        weather={"wind_speed_m_s": 0.0, "visibility": "good"},
        events=[],
    )

    assert frame.type == "sim_frame"
    assert frame.schema_version == "1.0"


def test_module_l_observation_log_does_not_include_offline_truth() -> None:
    observation = ObservationLogEntry(
        observation_id="OBS-001",
        episode_id="episode-001",
        time_s=0.0,
        crane_id="C1",
        risk_prompt_mode="R1",
        observation={"self": {"crane_id": "C1"}},
        source_snapshot_id="SNAP-001",
    )

    dumped = observation.model_dump(mode="json")

    assert "offline_label" not in dumped
    assert "future_min_distance" not in dumped
    assert "future_ttc" not in dumped


def test_module_l_event_log_supports_mvp_event_catalog() -> None:
    assert len(EventLogEntry.supported_mvp_event_types) >= 25
    assert "near_miss" in EventLogEntry.supported_mvp_event_types
    assert "llm_invalid_output" in EventLogEntry.supported_mvp_event_types


def test_episode_runner_records_complete_episode_with_real_recorder(tmp_path) -> None:
    log: list[str] = []
    recorder = Recorder.from_config(_resolved_config(tmp_path))
    dependencies = SchedulerDependencies(
        weather=FakeWeather(log),
        task_system=FakeTaskSystem(log),
        observation_builder=FakeObservationBuilder(log),
        operator=FakeOperator(log),
        safety=FakeSafety(log),
        controller=FakeController(log),
        physics=FakePhysics(log),
        risk=FakeRisk(log),
        collision=FakeCollision(log),
        recorder=recorder,
    )
    runner = _runner(
        log,
        config=_scheduler_config(duration_s=1.0, dt_s=0.5),
        dependencies=dependencies,
    )
    dependencies.risk.evaluate_after_physics = (
        lambda *, states, commands, time_s: _online_risk()
    )

    result = runner.run_episode()
    summary = recorder.finalize(episode_status=result.status)

    assert result.final_frame_index == 2
    assert summary.episode_status == "timeout"

    layout = recorder.layout
    assert layout is not None
    frames = [
        json.loads(line)
        for line in layout.frames_jsonl_path.read_text(encoding="utf-8").splitlines()
    ]
    manifest = json.loads(layout.episode_manifest_path.read_text(encoding="utf-8"))
    trajectories = pq.read_table(layout.trajectories_path)
    weather = pq.read_table(layout.weather_path)
    pair_risks = pq.read_table(layout.pair_risks_path)
    graph_edges = pq.read_table(layout.graph_edges_path)

    assert [frame["frame"] for frame in frames] == [0, 1, 2]
    assert all("offline_labels" not in frame or frame["offline_labels"] is None for frame in frames)
    assert manifest["frame_count"] == 3
    assert trajectories.num_rows == 6
    assert weather.num_rows == 3
    assert pair_risks.num_rows == 2
    assert graph_edges.num_rows == 4
    assert summary.risk_frame_ratio_by_level == {"high": pytest.approx(1.0)}
    assert "collision.detect:1.0" in log


def test_recorder_records_step_full_export_surface_and_summary(tmp_path) -> None:
    recorder = Recorder.from_config(_resolved_config(tmp_path))
    configs = _crane_configs(2)
    states = [initialize_crane_state(config) for config in configs]
    weather = FakeWeather([]).update(0.0)[0]

    recorder.record_initial_frame(
        episode_id="EPL",
        frame_index=0,
        time_s=0.0,
        states=states,
        weather_state=weather,
        status="running",
    )
    recorder.record_step(
        episode_id="EPL",
        frame_index=1,
        time_s=0.5,
        states=states,
        weather_state=FakeWeather([]).update(0.5)[0],
        commands={state.crane_id: _executed_command(crane_id=state.crane_id) for state in states},
        observations=[_observation(crane_id=state.crane_id) for state in states],
        llm_calls=[_llm_call_record(crane_id=state.crane_id) for state in states],
        interventions=[
            InterventionRecord(
                intervention_id="INT-GLOBAL",
                crane_id="C1",
                safety_mode=SafetyMode.S2,
                risk_level="high",
                action="limit_speed_on_high_risk",
                modified=True,
                reason="global acceptance intervention",
                pair_ids=["C1-C2"],
            )
        ],
        online_risk=_online_risk(),
        events=[
            {
                "event_id": "EVT-L-001",
                "event_type": "near_miss",
                "episode_id": "EPL",
                "frame": 1,
                "time_s": 0.5,
                "crane_ids": ["C1", "C2"],
                "risk_level": "high",
                "clearance_min_now_m": 1.5,
            }
        ],
        status="running",
        snapshot_id="SNAP-001",
    )
    summary = recorder.finalize(episode_status="completed")

    layout = recorder.layout
    assert layout is not None
    observations = [
        json.loads(line)
        for line in layout.observations_path.read_text(encoding="utf-8").splitlines()
    ]
    decisions = [
        json.loads(line)
        for line in layout.decisions_path.read_text(encoding="utf-8").splitlines()
    ]
    commands = [
        json.loads(line)
        for line in layout.commands_path.read_text(encoding="utf-8").splitlines()
    ]
    interventions = [
        json.loads(line)
        for line in layout.interventions_path.read_text(encoding="utf-8").splitlines()
    ]
    pair_risks = pq.read_table(layout.pair_risks_path)
    graph_edges = pq.read_table(layout.graph_edges_path)

    assert len(observations) == 2
    assert len(decisions) == 2
    assert len(commands) == 2
    assert len(interventions) == 3
    assert pair_risks.num_rows == 1
    assert graph_edges.num_rows == 2
    assert summary.num_llm_calls == 2
    assert summary.mean_latency_ms == pytest.approx(120.0)
    assert summary.near_miss_count == 1
    assert summary.risk_frame_ratio_by_level == {"high": pytest.approx(1.0)}


def test_high_frequency_recorder_writes_many_frames_without_offline_leak(tmp_path) -> None:
    recorder = Recorder.from_config(_resolved_config(tmp_path))
    config = _crane_configs(1)[0]
    state = initialize_crane_state(config)

    recorder.record_initial_frame(
        episode_id="EPL",
        frame_index=0,
        time_s=0.0,
        states=[state],
        weather_state=FakeWeather([]).update(0.0)[0],
        status="running",
    )
    for index in range(1, 51):
        recorder.record_step(
            episode_id="EPL",
            frame_index=index,
            time_s=index * 0.02,
            states=[state],
            weather_state=FakeWeather([]).update(index * 0.02)[0],
            status="running",
        )
    recorder.finalize(episode_status="completed")

    layout = recorder.layout
    assert layout is not None
    frames = [
        json.loads(line)
        for line in layout.frames_jsonl_path.read_text(encoding="utf-8").splitlines()
    ]
    trajectories = pq.read_table(layout.trajectories_path)

    assert len(frames) == 51
    assert trajectories.num_rows == 51
    assert frames[-1]["time_s"] == pytest.approx(1.0)
    assert all(frame.get("offline_labels") is None for frame in frames)


def test_recorder_write_failure_raises_data_export_error_without_authoritative_file(
    tmp_path,
    monkeypatch,
) -> None:
    recorder = Recorder.from_config(_resolved_config(tmp_path))
    config = _crane_configs(1)[0]
    state = initialize_crane_state(config)
    recorder.record_initial_frame(
        episode_id="EPL",
        frame_index=0,
        time_s=0.0,
        states=[state],
        weather_state=FakeWeather([]).update(0.0)[0],
        status="running",
    )
    layout = recorder.layout
    assert layout is not None

    def fail_write_table(*args, **kwargs):
        raise OSError("simulated disk full")

    monkeypatch.setattr("backend.app.sim.recorder.pq.write_table", fail_write_table)

    with pytest.raises(DataExportError) as exc_info:
        recorder.finalize(episode_status="failed_invalid_state")

    assert exc_info.value.error_code == "RECORDER_E_PARQUET_WRITE"
    assert not layout.trajectories_path.exists()
