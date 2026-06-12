from __future__ import annotations

import json
import math
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError
import pyarrow.parquet as pq

from backend.app.core.config_resolver import resolve_config
from backend.app.schemas.recorder import (
    RECORDER_SCHEMA_VERSION,
    CommandLogEntry,
    DataExportWarning,
    EpisodeSummary,
    EventLogEntry,
    GraphEdgeRow,
    OfflineFrameLabels,
    PairRiskRow,
    SimFrame,
    SimFrameCrane,
    SimFramePair,
    SimFrameWeather,
    TaskParquetRow,
    TrajectoryRow,
    WeatherParquetRow,
)
from backend.app.sim.recorder import (
    DataExportError,
    RecorderParquetWriters,
    init_run_directory,
)
from backend.app.tests.test_config_schema import load_fixture


def _sim_frame_payload(**overrides):
    payload = {
        "episode_id": "episode-001",
        "scenario_id": "scenario-001",
        "frame": 3,
        "time_s": 1.5,
        "episode_status": "running",
        "cranes": [
            {
                "crane_id": "C1",
                "base": [0.0, 0.0, 0.0],
                "root": [0.0, 0.0, 45.0],
                "tip": [42.0, 18.0, 45.0],
                "hook": [20.0, 8.0, 25.0],
                "theta_rad": 0.4,
                "trolley_r_m": 22.0,
                "hook_h_m": 25.0,
                "load_attached": False,
                "load_type": "rebar_bundle",
                "load_size_m": [6.0, 1.0, 1.0],
                "task_id": "T1",
                "task_stage": "move_to_pickup",
                "pickup_zone_id": "yard",
                "dropoff_zone_id": "workface",
                "operator_profile": "aggressive",
                "current_command": {
                    "left_joystick": {
                        "slew": {"direction": "right", "gear": 2},
                        "trolley": {"direction": "out", "gear": 1},
                    },
                    "right_joystick": {
                        "hoist": {"direction": "neutral", "gear": 0}
                    },
                },
            }
        ],
        "pairs": [
            {
                "crane_i": "C1",
                "crane_j": "C2",
                "distance_min_raw_now_m": 6.0,
                "clearance_min_now_m": 4.5,
                "risk_level_now": "medium",
            }
        ],
        "tasks": [{"task_id": "T1", "status": "active"}],
        "weather": {
            "wind_speed_m_s": 8.0,
            "wind_gust_m_s": 10.0,
            "wind_direction_deg": 90.0,
            "visibility": "medium",
            "rain_level": "none",
            "fog_level": "none",
        },
        "events": [{"event_type": "risk_entered"}],
    }
    payload.update(overrides)
    return payload


def _trajectory_row_payload(**overrides):
    payload = {
        "episode_id": "episode-001",
        "scenario_id": "scenario-001",
        "frame": 1,
        "time_s": 0.5,
        "crane_id": "C1",
        "base_x": 0.0,
        "base_y": 0.0,
        "base_z": 0.0,
        "mast_height_m": 45.0,
        "jib_length_m": 55.0,
        "theta_rad": 0.1,
        "theta_sin": math.sin(0.1),
        "theta_cos": math.cos(0.1),
        "theta_dot_rad_s": 0.0,
        "theta_ddot_rad_s2": 0.0,
        "trolley_r_m": 20.0,
        "trolley_v_m_s": 0.0,
        "hook_h_m": 30.0,
        "hoist_v_m_s": 0.0,
        "root_x": 0.0,
        "root_y": 0.0,
        "root_z": 45.0,
        "tip_x": 54.7,
        "tip_y": 5.5,
        "tip_z": 45.0,
        "hook_x": 19.9,
        "hook_y": 2.0,
        "hook_z": 30.0,
        "load_attached": True,
        "load_type": "steel",
        "load_weight_t": 1.2,
        "load_size_x_m": 2.0,
        "load_size_y_m": 1.0,
        "load_size_z_m": 1.0,
        "task_id": "T1",
        "task_stage": "move_to_pickup",
        "pickup_zone_id": "yard",
        "dropoff_zone_id": "workface",
        "operator_mode": "llm",
        "operator_profile": "aggressive",
        "executed_slew_direction": "right",
        "executed_slew_gear": 2,
        "executed_trolley_direction": "out",
        "executed_trolley_gear": 1,
        "executed_hoist_direction": "neutral",
        "executed_hoist_gear": 0,
        "executed_deadman_pressed": True,
        "executed_emergency_stop": False,
        "executed_task_action": "none",
        "wind_speed_m_s": 8.0,
        "wind_gust_m_s": 10.0,
        "wind_direction_deg": 90.0,
        "visibility_level": "medium",
    }
    payload.update(overrides)
    return payload


def _episode_summary_payload(**overrides):
    payload = {
        "episode_id": "episode-001",
        "scenario_id": "scenario-001",
        "episode_status": "completed",
        "duration_s": 12.0,
        "num_cranes": 2,
        "num_tasks_total": 4,
        "num_tasks_completed": 3,
        "num_tasks_failed": 1,
        "task_completion_rate": 0.75,
        "mean_task_duration_s": 4.0,
        "deadline_missed_count": 1,
        "overtime_mean_s": 0.5,
        "risk_frame_ratio_by_level": {"safe": 0.5, "high": 0.5},
        "near_miss_count": 2,
        "collision_count": 0,
        "min_clearance_over_episode": 1.25,
        "high_risk_duration_s": 3.0,
        "num_llm_calls": 5,
        "llm_invalid_output_count": 1,
        "llm_timeout_count": 1,
        "mean_latency_ms": 820.0,
        "cache_hit_count": 2,
        "operator_profile_distribution": {"aggressive": 1, "cautious": 1},
        "ignored_risk_hint_count": 1,
        "emergency_stop_count": 0,
        "forbidden_zone_violation_count": 0,
        "overlap_zone_shared_count": 1,
        "has_nan": True,
        "has_inf": False,
        "max_state_jump": 0.4,
        "replay_available": False,
        "warnings": [
            {
                "warning_id": "warning-001",
                "warning_type": "nan_to_null",
                "message": "converted NaN to null",
            }
        ],
    }
    payload.update(overrides)
    return payload


def _resolved_config(tmp_path: Path):
    resolved = resolve_config(
        load_fixture("scenario_valid.yaml"),
        load_fixture("experiment_valid.yaml"),
    )
    return resolved.model_copy(
        update={
            "output": resolved.output.model_copy(
                update={"run_root": str(tmp_path)}
            )
        }
    )


def test_sim_frame_schema_serializes_frontend_payload() -> None:
    frame = SimFrame.model_validate(_sim_frame_payload())

    dumped = frame.model_dump(mode="json")

    assert frame.schema_version == RECORDER_SCHEMA_VERSION
    assert dumped["type"] == "sim_frame"
    assert dumped["frame"] == 3
    assert dumped["cranes"][0]["hook"] == [20.0, 8.0, 25.0]
    assert dumped["pairs"][0]["risk_level_now"] == "medium"
    json.dumps(dumped, ensure_ascii=False)


def test_sim_frame_rejects_extra_fields_and_non_finite_values() -> None:
    with pytest.raises(ValidationError):
        SimFrame.model_validate(_sim_frame_payload(unexpected=True))

    payload = _sim_frame_payload()
    payload["cranes"][0]["theta_rad"] = math.nan
    with pytest.raises(ValidationError):
        SimFrame.model_validate(payload)


def test_realtime_sim_frame_rejects_offline_labels() -> None:
    offline_labels = OfflineFrameLabels(
        pair_labels=[
            {
                "crane_i": "C1",
                "crane_j": "C2",
                "min_clearance_future_5s_m": 1.0,
            }
        ]
    )
    offline_frame = SimFrame.model_validate(
        _sim_frame_payload(offline_labels=offline_labels.model_dump(mode="json"))
    )

    assert offline_frame.offline_labels is not None

    with pytest.raises(ValidationError):
        SimFrame.realtime(**_sim_frame_payload(offline_labels=offline_labels))


def test_parquet_row_schemas_cover_required_columns() -> None:
    trajectory = TrajectoryRow.model_validate(_trajectory_row_payload())
    pair = PairRiskRow(
        episode_id="episode-001",
        scenario_id="scenario-001",
        frame=1,
        time_s=0.5,
        crane_i="C1",
        crane_j="C2",
        distance_min_raw_now_m=6.0,
        clearance_min_now_m=4.5,
        min_clearance_future_5s_m=2.0,
        min_clearance_future_10s_m=1.0,
        min_clearance_future_15s_m=0.5,
        ttc_5s_s=4.0,
        ttc_10s_s=4.0,
        ttc_15s_s=4.0,
        risk_level_now="medium",
        risk_level_5s="high",
        risk_level_10s="high",
        risk_level_15s="near_miss",
        collision_label_5s=0,
        collision_label_10s=0,
        collision_label_15s=0,
    )
    edge = GraphEdgeRow(
        episode_id="episode-001",
        frame=1,
        time_s=0.5,
        src_crane_id="C1",
        dst_crane_id="C2",
        edge_distance_m=6.0,
        edge_overlap_ratio=0.25,
        edge_delta_height_m=5.0,
        edge_delta_theta_rad=0.2,
        edge_delta_theta_dot_rad_s=0.0,
        edge_ttc_s=4.0,
        edge_risk_level="medium",
        edge_weight_physics_prior=0.7,
    )

    assert trajectory.schema_version == RECORDER_SCHEMA_VERSION
    assert pair.schema_version == RECORDER_SCHEMA_VERSION
    assert edge.schema_version == RECORDER_SCHEMA_VERSION
    assert "executed_slew_direction" in trajectory.model_dump(mode="json")
    assert "min_clearance_future_15s_m" in pair.model_dump(mode="json")
    assert "edge_weight_physics_prior" in edge.model_dump(mode="json")


def test_task_weather_command_event_and_summary_schemas_are_strict() -> None:
    task = TaskParquetRow(
        episode_id="episode-001",
        scenario_id="scenario-001",
        task_id="T1",
        crane_id="C1",
        task_type="easy_task",
        status="completed",
        failure_reason=None,
        pickup_x=0.0,
        pickup_y=1.0,
        pickup_z=0.0,
        dropoff_x=10.0,
        dropoff_y=11.0,
        dropoff_z=0.0,
        pickup_zone_id="yard",
        dropoff_zone_id="workface",
        load_type="steel",
        load_weight_t=1.2,
        load_size_x_m=2.0,
        load_size_y_m=1.0,
        load_size_z_m=1.0,
        planned_start_s=None,
        actual_start_s=1.0,
        completed_time_s=5.0,
        deadline_s=10.0,
        deadline_missed=False,
        overtime_s=0.0,
    )
    weather = WeatherParquetRow(
        episode_id="episode-001",
        scenario_id="scenario-001",
        frame=1,
        time_s=0.5,
        wind_speed_m_s=8.0,
        wind_gust_m_s=10.0,
        wind_direction_deg=90.0,
        visibility_level="medium",
        rain_level="none",
    )
    command = CommandLogEntry(
        episode_id="episode-001",
        time_s=1.0,
        decision_index=2,
        crane_id="C1",
        operator_id="OP_C1",
        operator_profile="aggressive",
        operator_mode="llm",
        observation_id="OBS1",
        provider="deepseek",
        model="deepseek-chat",
        raw_llm_response="{...}",
        parsed_command={"command_id": "raw"},
        executed_command={"command_id": "exec"},
        modified_by_intervention=False,
        modified_by_mechanical_safety=False,
        latency_ms=820.0,
        token_usage={"prompt_tokens": 10, "completion_tokens": 2},
        retry_count=0,
        validation_errors=[],
        cache_hit=False,
    )
    event = EventLogEntry(
        event_id="EVT1",
        event_type="near_miss",
        episode_id="episode-001",
        scenario_id="scenario-001",
        frame=1,
        time_s=0.5,
        crane_ids=["C1", "C2"],
        risk_level="high",
        distance_min_raw_now_m=2.0,
        clearance_min_now_m=0.8,
        details={"nearest_object_type": "jib-hook"},
    )
    summary = EpisodeSummary.model_validate(_episode_summary_payload())

    assert task.schema_version == RECORDER_SCHEMA_VERSION
    assert weather.schema_version == RECORDER_SCHEMA_VERSION
    assert command.schema_version == RECORDER_SCHEMA_VERSION
    assert event.schema_version == RECORDER_SCHEMA_VERSION
    assert summary.task_completion_rate == 0.75

    with pytest.raises(ValidationError):
        EventLogEntry.model_validate(event.model_dump(mode="json") | {"extra": True})


def test_data_export_warning_rejects_non_finite_values() -> None:
    warning = DataExportWarning(
        warning_id="warning-001",
        episode_id="episode-001",
        frame=1,
        time_s=0.5,
        file_name="data/trajectories.parquet",
        field_path="theta_rad",
        warning_type="nan_to_null",
        message="converted NaN to null",
    )

    assert warning.schema_version == RECORDER_SCHEMA_VERSION

    with pytest.raises(ValidationError):
        SimFrameCrane(
            crane_id="C1",
            base=[0.0, 0.0, 0.0],
            root=[0.0, 0.0, 45.0],
            tip=[1.0, 0.0, 45.0],
            hook=[1.0, 0.0, 20.0],
            theta_rad=math.inf,
            trolley_r_m=1.0,
            hook_h_m=20.0,
            load_attached=False,
            task_stage="idle",
        )

    assert SimFramePair(crane_i="C1", crane_j="C2").schema_version
    assert SimFrameWeather(wind_speed_m_s=1.0, visibility="good").schema_version


def test_init_run_directory_creates_module_l_layout_and_metadata(tmp_path: Path) -> None:
    resolved = _resolved_config(tmp_path)

    layout = init_run_directory(
        config=resolved,
        episode_id="episode-001",
        scenario_id="scenario-001",
    )

    for directory in [
        layout.config_dir,
        layout.metadata_dir,
        layout.logs_dir,
        layout.data_dir,
        layout.replay_dir,
        layout.visual_dir,
    ]:
        assert directory.is_dir()

    resolved_yaml = yaml.safe_load(
        layout.resolved_config_path.read_text(encoding="utf-8")
    )
    metadata = json.loads(layout.episode_metadata_path.read_text(encoding="utf-8"))

    assert resolved_yaml["resolved_config_hash"] == resolved.resolved_config_hash
    assert metadata["schema_version"] == RECORDER_SCHEMA_VERSION
    assert metadata["episode_id"] == "episode-001"
    assert metadata["scenario_id"] == "scenario-001"
    assert metadata["episode_status"] == "running"
    assert metadata["files"]["trajectories"] == "data/trajectories.parquet"
    assert layout.frames_jsonl_path == layout.visual_dir / "frames.jsonl"
    assert layout.commands_path == layout.logs_dir / "commands.jsonl"


def test_init_run_directory_is_idempotent_and_does_not_persist_full_secret(
    tmp_path: Path,
) -> None:
    experiment = load_fixture("experiment_valid.yaml")
    experiment["llm"]["api_key"] = "sk-inline-secret-123456"
    resolved = resolve_config(load_fixture("scenario_valid.yaml"), experiment)
    resolved = resolved.model_copy(
        update={
            "output": resolved.output.model_copy(
                update={"run_root": str(tmp_path)}
            )
        }
    )

    first = init_run_directory(config=resolved, episode_id="episode-001")
    second = init_run_directory(config=resolved, episode_id="episode-001")

    assert first.run_root == second.run_root
    combined = "\n".join(
        [
            first.resolved_config_path.read_text(encoding="utf-8"),
            first.episode_metadata_path.read_text(encoding="utf-8"),
        ]
    )
    assert "sk-inline-secret-123456" not in combined
    assert "sk-i****3456" in combined


def test_init_run_directory_maps_filesystem_errors_to_data_export_error(
    tmp_path: Path,
) -> None:
    run_root_file = tmp_path / "not-a-directory"
    run_root_file.write_text("occupied", encoding="utf-8")
    resolved = _resolved_config(run_root_file)

    with pytest.raises(DataExportError) as exc_info:
        init_run_directory(config=resolved, episode_id="episode-001")

    assert exc_info.value.category == "data_export_error"
    assert exc_info.value.file_path is not None


def test_parquet_writers_append_and_flush_all_tables(tmp_path: Path) -> None:
    layout = init_run_directory(
        config=_resolved_config(tmp_path),
        episode_id="episode-001",
        scenario_id="scenario-001",
    )
    writers = RecorderParquetWriters.from_layout(layout)

    writers.write_trajectories(
        [
            _trajectory_row_payload(frame=0, time_s=0.0),
            _trajectory_row_payload(frame=1, time_s=0.5),
        ]
    )
    writers.write_trajectories([_trajectory_row_payload(frame=2, time_s=1.0)])
    writers.write_pair_risks(
        [
            {
                "episode_id": "episode-001",
                "scenario_id": "scenario-001",
                "frame": 1,
                "time_s": 0.5,
                "crane_i": "C1",
                "crane_j": "C2",
                "clearance_min_now_m": 4.5,
                "risk_level_now": "medium",
            }
        ]
    )
    writers.write_graph_edges(
        [
            {
                "episode_id": "episode-001",
                "frame": 1,
                "time_s": 0.5,
                "src_crane_id": "C1",
                "dst_crane_id": "C2",
                "edge_distance_m": 6.0,
                "edge_overlap_ratio": 0.25,
            }
        ]
    )
    writers.write_tasks(
        [
            {
                "episode_id": "episode-001",
                "scenario_id": "scenario-001",
                "task_id": "T1",
                "crane_id": "C1",
                "task_type": "easy_task",
                "status": "completed",
                "pickup_x": 0.0,
                "pickup_y": 1.0,
                "pickup_z": 0.0,
                "dropoff_x": 10.0,
                "dropoff_y": 11.0,
                "dropoff_z": 0.0,
                "pickup_zone_id": "yard",
                "dropoff_zone_id": "workface",
                "load_type": "steel",
                "load_weight_t": 1.2,
                "load_size_x_m": 2.0,
                "load_size_y_m": 1.0,
                "load_size_z_m": 1.0,
                "deadline_missed": False,
                "overtime_s": 0.0,
            }
        ]
    )
    writers.write_weather(
        [
            {
                "episode_id": "episode-001",
                "scenario_id": "scenario-001",
                "frame": 1,
                "time_s": 0.5,
                "wind_speed_m_s": 8.0,
                "wind_gust_m_s": 10.0,
                "wind_direction_deg": 90.0,
                "visibility_level": "medium",
                "rain_level": "none",
            }
        ]
    )
    writers.flush_all()

    trajectories = pq.read_table(layout.trajectories_path)
    pair_risks = pq.read_table(layout.pair_risks_path)
    graph_edges = pq.read_table(layout.graph_edges_path)
    tasks = pq.read_table(layout.tasks_path)
    weather = pq.read_table(layout.weather_path)

    assert trajectories.num_rows == 3
    assert pair_risks.num_rows == 1
    assert graph_edges.num_rows == 1
    assert tasks.num_rows == 1
    assert weather.num_rows == 1
    for table in [trajectories, pair_risks, graph_edges, tasks, weather]:
        assert "schema_version" in table.column_names


def test_parquet_writer_converts_non_finite_values_to_null_and_records_warning(
    tmp_path: Path,
) -> None:
    layout = init_run_directory(
        config=_resolved_config(tmp_path),
        episode_id="episode-001",
        scenario_id="scenario-001",
    )
    writers = RecorderParquetWriters.from_layout(layout)

    writers.write_pair_risks(
        [
            {
                "episode_id": "episode-001",
                "scenario_id": "scenario-001",
                "frame": 1,
                "time_s": 0.5,
                "crane_i": "C1",
                "crane_j": "C2",
                "clearance_min_now_m": math.nan,
                "ttc_5s_s": math.inf,
                "risk_level_now": "medium",
            }
        ]
    )
    writers.flush_all()

    table = pq.read_table(layout.pair_risks_path)
    data = table.to_pylist()[0]

    assert data["clearance_min_now_m"] is None
    assert data["ttc_5s_s"] is None
    assert {warning.warning_type for warning in writers.warnings} == {
        "nan_to_null",
        "inf_to_null",
    }


def test_parquet_writer_rejects_extra_fields_without_authoritative_file(
    tmp_path: Path,
) -> None:
    layout = init_run_directory(
        config=_resolved_config(tmp_path),
        episode_id="episode-001",
        scenario_id="scenario-001",
    )
    writers = RecorderParquetWriters.from_layout(layout)

    with pytest.raises(DataExportError):
        writers.write_trajectories(
            [_trajectory_row_payload(extra_training_hint="not allowed")]
        )

    assert not layout.trajectories_path.exists()
