from __future__ import annotations

import json
import math
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError
import pyarrow.parquet as pq

from backend.app.core.config_resolver import resolve_config
from backend.app.schemas.risk import OfflineRiskLabel
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
from backend.app.schemas.state import CraneState
from backend.app.schemas.task import Task, TaskPoint, TaskQueue
from backend.app.schemas.weather import WeatherState
from backend.app.sim.recorder import (
    DataExportError,
    Recorder,
    RecorderJsonlWriters,
    RecorderParquetWriters,
    VisualFrameWriter,
    build_episode_manifest,
    build_episode_summary,
    build_sim_frame,
    init_run_directory,
    write_episode_summary,
    _replace_file_with_fallback,
)
from backend.app.api.production_runner import ProductionRecorderAdapter
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


def _crane_state(crane_id: str = "C1") -> CraneState:
    return CraneState(
        crane_id=crane_id,
        theta_rad=0.4,
        theta_sin=math.sin(0.4),
        theta_cos=math.cos(0.4),
        trolley_r_m=22.0,
        hook_h_m=25.0,
        root_position=[0.0, 0.0, 45.0],
        tip_position=[42.0, 18.0, 45.0],
        hook_position=[20.0, 8.0, 25.0],
        cable_length_m=20.0,
        load_attached=False,
        load_type="rebar_bundle",
        load_weight_t=1.0,
        load_size_m=[6.0, 1.0, 1.0],
        task_id="T1",
        task_stage="move_to_pickup",
    )


def _weather_state() -> WeatherState:
    return WeatherState(
        time_s=1.0,
        mode="constant",
        wind_speed_m_s=8.0,
        wind_gust_m_s=10.0,
        wind_direction_deg=90.0,
        visibility_level="medium",
        rain_level="none",
        fog_level="none",
        source_segment_id="constant",
        generation_seed=303,
        generation_step=0,
    )


def _task(crane_id: str = "C1") -> Task:
    pickup = TaskPoint(
        x=10.0,
        y=0.0,
        z=1.8,
        zone_id="material_zone",
        zone_type="material",
        surface_z_m=0.0,
        load_center_z_m=0.5,
        hook_target_z_m=1.8,
        approach_z_m=5.0,
        zone_role="ground_yard",
    )
    dropoff = TaskPoint(
        x=30.0,
        y=10.0,
        z=21.8,
        zone_id="work_zone",
        zone_type="work",
        surface_z_m=20.0,
        load_center_z_m=20.5,
        hook_target_z_m=21.8,
        approach_z_m=25.0,
        floor_id="floor_06",
        building_id="tower_a",
        zone_role="floor_slab",
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


def _offline_label() -> OfflineRiskLabel:
    return OfflineRiskLabel.model_validate(
        {
            "episode_id": "episode-001",
            "scenario_id": "scenario-001",
            "frame": 2,
            "time_s": 1.0,
            "crane_i": "C1",
            "crane_j": "C2",
            "pair_id": "C1-C2",
            "distance_min_raw_now_m": 5.0,
            "clearance_min_now_m": 4.0,
            "distance_jib_jib_raw_now_m": 10.0,
            "clearance_jib_jib_now_m": 9.0,
            "distance_jib_i_hook_j_raw_now_m": 5.0,
            "clearance_jib_i_hook_j_now_m": 4.0,
            "distance_jib_j_hook_i_raw_now_m": 8.0,
            "clearance_jib_j_hook_i_now_m": 7.0,
            "distance_hook_hook_raw_now_m": 12.0,
            "clearance_hook_hook_now_m": 11.0,
            "min_clearance_future_5s_m": 2.0,
            "min_clearance_future_10s_m": 1.0,
            "ttc_5s_s": 4.0,
            "ttc_10s_s": 4.0,
            "risk_level_5s": "high",
            "risk_level_10s": "high",
            "collision_label_5s": 0,
            "collision_label_10s": 0,
            "future_window_labels": {
                "5s": {
                    "window_s": 5.0,
                    "min_clearance_future_m": 2.0,
                    "ttc_s": 4.0,
                    "risk_level": "high",
                    "collision_label": 0,
                    "used_future_truth": True,
                },
                "10s": {
                    "window_s": 10.0,
                    "min_clearance_future_m": 1.0,
                    "ttc_s": 4.0,
                    "risk_level": "high",
                    "collision_label": 0,
                    "used_future_truth": True,
                },
                "15s": {
                    "window_s": 15.0,
                    "min_clearance_future_m": 0.5,
                    "ttc_s": 4.0,
                    "risk_level": "near_miss",
                    "collision_label": 0,
                    "used_future_truth": True,
                },
            },
            "used_future_truth": True,
        }
    )


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
        pickup_surface_z_m=None,
        dropoff_surface_z_m=None,
        pickup_hook_target_z_m=None,
        dropoff_hook_target_z_m=None,
        pickup_floor_id=None,
        dropoff_floor_id=None,
        pickup_building_id=None,
        dropoff_building_id=None,
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


def test_jsonl_writers_append_utf8_and_schema_version(tmp_path: Path) -> None:
    layout = init_run_directory(
        config=_resolved_config(tmp_path),
        episode_id="episode-001",
        scenario_id="scenario-001",
    )
    writers = RecorderJsonlWriters.from_layout(layout)

    writers.write_observations(
        [
            {
                "observation_id": "OBS-001",
                "episode_id": "episode-001",
                "time_s": 1.0,
                "crane_id": "C1",
                "risk_prompt_mode": "R1",
                "observation": {"self": {"crane_id": "C1"}},
                "source_snapshot_id": "SNAP-001",
            }
        ]
    )
    writers.write_decisions(
        [
            {
                "episode_id": "episode-001",
                "time_s": 1.0,
                "crane_id": "C1",
                "provider": "deepseek",
                "model": "deepseek-chat",
                "call_record": {"call_id": "CALL-001"},
            }
        ]
    )
    writers.write_commands(
        [
            {
                "episode_id": "episode-001",
                "time_s": 1.0,
                "decision_index": 1,
                "crane_id": "C1",
                "operator_id": "OP_C1",
                "operator_profile": "aggressive",
                "operator_mode": "llm",
                "observation_id": "OBS-001",
                "provider": "deepseek",
                "model": "deepseek-chat",
                "raw_llm_response": "{...}",
                "parsed_command": {"command_id": "CMD-001"},
                "executed_command": {"command_id": "EXEC-001"},
                "modified_by_intervention": False,
                "modified_by_mechanical_safety": False,
                "latency_ms": 820.0,
                "token_usage": {"prompt_tokens": 10, "completion_tokens": 2},
                "retry_count": 0,
                "validation_errors": [],
                "cache_hit": False,
                "reason": "取货点在右前方，低速接近。",
            }
        ]
    )
    writers.write_interventions(
        [
            {
                "episode_id": "episode-001",
                "time_s": 1.0,
                "intervention_id": "INT-001",
                "crane_id": "C1",
                "safety_mode": "S2",
                "risk_level": "high",
                "action": "limit_speed_on_high_risk",
                "modified": True,
                "reason": "risk high",
                "pair_ids": ["C1-C2"],
            }
        ]
    )
    writers.write_events(
        [
            {
                "event_id": "EVT-001",
                "event_type": "near_miss",
                "episode_id": "episode-001",
                "scenario_id": "scenario-001",
                "frame": 2,
                "time_s": 1.0,
                "crane_ids": ["C1", "C2"],
                "risk_level": "high",
                "details": {"nearest_object_type": "jib-hook"},
            }
        ]
    )
    writers.flush_all()

    paths = [
        layout.observations_path,
        layout.decisions_path,
        layout.commands_path,
        layout.interventions_path,
        layout.events_path,
    ]
    for path in paths:
        lines = path.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 1
        payload = json.loads(lines[0])
        assert payload["schema_version"] == RECORDER_SCHEMA_VERSION

    command_payload = json.loads(
        layout.commands_path.read_text(encoding="utf-8").splitlines()[0]
    )
    assert command_payload["reason"] == "取货点在右前方，低速接近。"


def test_jsonl_writer_converts_non_finite_values_to_null_and_warns(
    tmp_path: Path,
) -> None:
    layout = init_run_directory(
        config=_resolved_config(tmp_path),
        episode_id="episode-001",
        scenario_id="scenario-001",
    )
    writers = RecorderJsonlWriters.from_layout(layout)

    writers.write_events(
        [
            {
                "event_id": "EVT-001",
                "event_type": "near_miss",
                "episode_id": "episode-001",
                "scenario_id": "scenario-001",
                "frame": 2,
                "time_s": 1.0,
                "crane_ids": ["C1", "C2"],
                "risk_level": "high",
                "clearance_min_now_m": math.nan,
                "distance_min_raw_now_m": math.inf,
                "details": {},
            }
        ]
    )
    writers.flush_all()

    payload = json.loads(layout.events_path.read_text(encoding="utf-8").splitlines()[0])

    assert payload["clearance_min_now_m"] is None
    assert payload["distance_min_raw_now_m"] is None
    assert {warning.warning_type for warning in writers.warnings} == {
        "nan_to_null",
        "inf_to_null",
    }


def test_jsonl_writer_rejects_secret_keys_and_extra_fields(tmp_path: Path) -> None:
    layout = init_run_directory(
        config=_resolved_config(tmp_path),
        episode_id="episode-001",
        scenario_id="scenario-001",
    )
    writers = RecorderJsonlWriters.from_layout(layout)

    with pytest.raises(DataExportError):
        writers.write_decisions(
            [
                {
                    "episode_id": "episode-001",
                    "time_s": 1.0,
                    "crane_id": "C1",
                    "provider": "deepseek",
                    "model": "deepseek-chat",
                    "call_record": {"api_key": "sk-secret"},
                }
            ]
        )

    with pytest.raises(DataExportError):
        writers.write_observations(
            [
                {
                    "observation_id": "OBS-001",
                    "episode_id": "episode-001",
                    "time_s": 1.0,
                    "crane_id": "C1",
                    "risk_prompt_mode": "R1",
                    "observation": {"self": {"crane_id": "C1"}},
                    "source_snapshot_id": "SNAP-001",
                    "offline_label": "not allowed",
                }
            ]
        )

    assert not layout.decisions_path.exists()
    assert not layout.observations_path.exists()


def test_build_sim_frame_maps_state_weather_pairs_and_events() -> None:
    frame = build_sim_frame(
        episode_id="episode-001",
        scenario_id="scenario-001",
        frame_index=2,
        time_s=1.0,
        episode_status="running",
        states=[_crane_state("C1")],
        weather_state=_weather_state(),
        pairs=[
            {
                "crane_i": "C1",
                "crane_j": "C2",
                "distance_min_raw_now_m": 6.0,
                "clearance_min_now_m": 4.5,
                "risk_level_now": "medium",
            }
        ],
        events=[{"event_type": "near_miss", "crane_ids": ["C1", "C2"]}],
    )

    dumped = frame.model_dump(mode="json")

    assert dumped["type"] == "sim_frame"
    assert dumped["frame"] == 2
    assert dumped["cranes"][0]["hook"] == [20.0, 8.0, 25.0]
    assert dumped["cranes"][0]["task_stage"] == "move_to_pickup"
    assert dumped["weather"]["visibility"] == "medium"
    assert dumped["pairs"][0]["risk_level_now"] == "medium"
    assert dumped["events"][0]["event_type"] == "near_miss"


def test_build_sim_frame_includes_task_queues_for_panel_contract() -> None:
    queue = TaskQueue(
        crane_id="C1",
        tasks=[_task("C1")],
        active_task_id="T_C1_001",
        next_task_index=1,
    )

    frame = build_sim_frame(
        episode_id="episode-001",
        scenario_id="scenario-001",
        frame_index=2,
        time_s=1.0,
        episode_status="running",
        states=[_crane_state("C1")],
        weather_state=_weather_state(),
        task_queues=[queue],
    )

    dumped = frame.model_dump(mode="json")
    assert dumped["tasks"][0]["crane_id"] == "C1"
    assert dumped["tasks"][0]["active_task_id"] == "T_C1_001"
    assert dumped["tasks"][0]["tasks"][0]["task_id"] == "T_C1_001"
    assert dumped["tasks"][0]["tasks"][0]["priority"] == "medium"
    assert dumped["tasks"][0]["tasks"][0]["pickup"]["surface_z_m"] == 0.0
    assert dumped["tasks"][0]["tasks"][0]["dropoff"]["surface_z_m"] == 20.0
    assert dumped["tasks"][0]["tasks"][0]["dropoff"]["hook_target_z_m"] == 21.8
    assert dumped["tasks"][0]["tasks"][0]["dropoff"]["floor_id"] == "floor_06"


def test_task_parquet_rows_include_vertical_semantics() -> None:
    queue = TaskQueue(
        crane_id="C1",
        tasks=[_task("C1")],
        active_task_id="T_C1_001",
        next_task_index=1,
    )

    frame = build_sim_frame(
        episode_id="episode-001",
        scenario_id="scenario-001",
        frame_index=2,
        time_s=1.0,
        episode_status="running",
        states=[_crane_state("C1")],
        weather_state=_weather_state(),
        task_queues=[queue],
    )

    assert frame.tasks[0]["tasks"][0]["pickup"]["hook_target_z_m"] == 1.8

    from backend.app.sim.recorder import _task_rows_from_task_queues

    rows = _task_rows_from_task_queues(
        [queue],
        episode_id="episode-001",
        scenario_id="scenario-001",
    )
    row = rows[0].model_dump(mode="json")

    assert row["pickup_z"] == 1.8
    assert row["dropoff_z"] == 21.8
    assert row["pickup_surface_z_m"] == 0.0
    assert row["dropoff_surface_z_m"] == 20.0
    assert row["pickup_hook_target_z_m"] == 1.8
    assert row["dropoff_hook_target_z_m"] == 21.8
    assert row["pickup_floor_id"] is None
    assert row["dropoff_floor_id"] == "floor_06"
    assert row["dropoff_building_id"] == "tower_a"


def test_build_sim_frame_enforces_offline_label_isolation() -> None:
    offline_label = _offline_label()

    with pytest.raises(DataExportError):
        build_sim_frame(
            episode_id="episode-001",
            scenario_id="scenario-001",
            frame_index=2,
            time_s=1.0,
            episode_status="running",
            states=[_crane_state("C1")],
            weather_state=_weather_state(),
            offline_labels=[offline_label],
            for_realtime=True,
        )

    frame = build_sim_frame(
        episode_id="episode-001",
        scenario_id="scenario-001",
        frame_index=2,
        time_s=1.0,
        episode_status="running",
        states=[_crane_state("C1")],
        weather_state=_weather_state(),
        offline_labels=[offline_label],
        for_realtime=False,
    )

    dumped = frame.model_dump(mode="json")
    assert dumped["offline_labels"]["pair_labels"][0]["crane_i"] == "C1"
    assert "min_clearance_future_15s_m" in dumped["offline_labels"]["pair_labels"][0]


def test_visual_frame_writer_roundtrips_frames_and_manifest(tmp_path: Path) -> None:
    layout = init_run_directory(
        config=_resolved_config(tmp_path),
        episode_id="episode-001",
        scenario_id="scenario-001",
    )
    writer = VisualFrameWriter(
        frames_path=layout.frames_jsonl_path,
        manifest_path=layout.episode_manifest_path,
    )
    frame = build_sim_frame(
        episode_id="episode-001",
        scenario_id="scenario-001",
        frame_index=0,
        time_s=0.0,
        episode_status="running",
        states=[_crane_state("C1")],
        weather_state=_weather_state(),
    )
    manifest = build_episode_manifest(
        episode_id="episode-001",
        scenario_id="scenario-001",
        episode_status="completed",
        frame_count=1,
        dt_s=0.5,
        crane_configs=[],
        offline_labels_available=False,
    )

    writer.append_frame(frame)
    writer.write_manifest(manifest)
    writer.flush()

    frame_payload = json.loads(layout.frames_jsonl_path.read_text(encoding="utf-8"))
    manifest_payload = json.loads(
        layout.episode_manifest_path.read_text(encoding="utf-8")
    )

    assert SimFrame.model_validate(frame_payload).episode_id == "episode-001"
    assert manifest_payload["episode_status"] == "completed"
    assert manifest_payload["frame_count"] == 1


def test_replace_file_with_fallback_copies_when_replace_is_denied(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tmp_path_file = tmp_path / ".trajectories.parquet.tmp"
    output_path = tmp_path / "trajectories.parquet"
    tmp_path_file.write_bytes(b"parquet bytes")

    def deny_replace(self: Path, target: Path) -> Path:
        raise PermissionError("replace denied by Windows file lock policy")

    monkeypatch.setattr(Path, "replace", deny_replace)

    _replace_file_with_fallback(tmp_path_file, output_path)

    assert output_path.read_bytes() == b"parquet bytes"
    assert not tmp_path_file.exists()


def test_replace_file_with_fallback_succeeds_when_tmp_cleanup_is_denied(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tmp_path_file = tmp_path / ".trajectories.parquet.tmp"
    output_path = tmp_path / "trajectories.parquet"
    tmp_path_file.write_bytes(b"parquet bytes")

    def deny_replace(self: Path, target: Path) -> Path:
        raise PermissionError("replace denied by Windows file lock policy")

    def deny_unlink(self: Path, missing_ok: bool = False) -> None:
        if self == tmp_path_file:
            raise PermissionError("tmp cleanup denied by Windows file lock policy")
        return None

    monkeypatch.setattr(Path, "replace", deny_replace)
    monkeypatch.setattr(Path, "unlink", deny_unlink)

    _replace_file_with_fallback(tmp_path_file, output_path)

    assert output_path.read_bytes() == b"parquet bytes"
    assert tmp_path_file.exists()


def test_build_episode_summary_computes_task_risk_llm_and_quality_metrics() -> None:
    warning = DataExportWarning(
        warning_id="warning-001",
        warning_type="nan_to_null",
        message="converted NaN to null",
    )

    summary = build_episode_summary(
        episode_id="episode-001",
        scenario_id="scenario-001",
        episode_status="completed",
        duration_s=10.0,
        num_cranes=2,
        tasks=[
            {
                "episode_id": "episode-001",
                "scenario_id": "scenario-001",
                "task_id": "T1",
                "crane_id": "C1",
                "task_type": "easy_task",
                "status": "completed",
                "pickup_x": 0.0,
                "pickup_y": 0.0,
                "pickup_z": 0.0,
                "dropoff_x": 1.0,
                "dropoff_y": 1.0,
                "dropoff_z": 0.0,
                "pickup_zone_id": "yard",
                "dropoff_zone_id": "workface",
                "load_type": "steel",
                "load_weight_t": 1.0,
                "load_size_x_m": 1.0,
                "load_size_y_m": 1.0,
                "load_size_z_m": 1.0,
                "actual_start_s": 1.0,
                "completed_time_s": 5.0,
                "deadline_missed": False,
                "overtime_s": 0.0,
            },
            {
                "episode_id": "episode-001",
                "scenario_id": "scenario-001",
                "task_id": "T2",
                "crane_id": "C2",
                "task_type": "overlap_task",
                "status": "failed",
                "pickup_x": 0.0,
                "pickup_y": 0.0,
                "pickup_z": 0.0,
                "dropoff_x": 1.0,
                "dropoff_y": 1.0,
                "dropoff_z": 0.0,
                "pickup_zone_id": "yard",
                "dropoff_zone_id": "workface",
                "load_type": "steel",
                "load_weight_t": 1.0,
                "load_size_x_m": 1.0,
                "load_size_y_m": 1.0,
                "load_size_z_m": 1.0,
                "actual_start_s": 2.0,
                "completed_time_s": None,
                "deadline_missed": True,
                "overtime_s": 2.0,
            },
        ],
        pair_risk_rows=[
            {
                "episode_id": "episode-001",
                "scenario_id": "scenario-001",
                "frame": 1,
                "time_s": 0.5,
                "crane_i": "C1",
                "crane_j": "C2",
                "clearance_min_now_m": 4.0,
                "risk_level_now": "safe",
            },
            {
                "episode_id": "episode-001",
                "scenario_id": "scenario-001",
                "frame": 2,
                "time_s": 1.0,
                "crane_i": "C1",
                "crane_j": "C2",
                "clearance_min_now_m": 1.0,
                "risk_level_now": "high",
            },
            {
                "episode_id": "episode-001",
                "scenario_id": "scenario-001",
                "frame": 3,
                "time_s": 1.5,
                "crane_i": "C1",
                "crane_j": "C2",
                "clearance_min_now_m": 0.5,
                "risk_level_now": "near_miss",
            },
        ],
        command_logs=[
            {
                "episode_id": "episode-001",
                "time_s": 1.0,
                "crane_id": "C1",
                "operator_profile": "aggressive",
                "latency_ms": 100.0,
                "cache_hit": True,
                "validation_errors": [],
            },
            {
                "episode_id": "episode-001",
                "time_s": 2.0,
                "crane_id": "C2",
                "operator_profile": "cautious",
                "latency_ms": 300.0,
                "cache_hit": False,
                "validation_errors": [{"message": "bad json"}],
            },
        ],
        event_logs=[
            {
                "event_id": "EVT-001",
                "event_type": "near_miss",
                "episode_id": "episode-001",
                "frame": 2,
                "time_s": 1.0,
            },
            {
                "event_id": "EVT-002",
                "event_type": "llm_timeout",
                "episode_id": "episode-001",
                "frame": 2,
                "time_s": 1.0,
            },
            {
                "event_id": "EVT-003",
                "event_type": "ignored_risk_hint",
                "episode_id": "episode-001",
                "frame": 3,
                "time_s": 1.5,
            },
        ],
        warnings=[warning],
        state_jump_max_m=0.75,
        replay_available=True,
        dt_s=0.5,
    )

    assert summary.num_tasks_total == 2
    assert summary.num_tasks_completed == 1
    assert summary.num_tasks_failed == 1
    assert summary.task_completion_rate == 0.5
    assert summary.mean_task_duration_s == 4.0
    assert summary.deadline_missed_count == 1
    assert summary.overtime_mean_s == 1.0
    assert summary.risk_frame_ratio_by_level == {
        "safe": pytest.approx(1 / 3),
        "high": pytest.approx(1 / 3),
        "near_miss": pytest.approx(1 / 3),
    }
    assert summary.min_clearance_over_episode == 0.5
    assert summary.high_risk_duration_s == 1.0
    assert summary.num_llm_calls == 2
    assert summary.llm_invalid_output_count == 1
    assert summary.llm_timeout_count == 1
    assert summary.mean_latency_ms == 200.0
    assert summary.cache_hit_count == 1
    assert summary.operator_profile_distribution == {"aggressive": 1, "cautious": 1}
    assert summary.ignored_risk_hint_count == 1
    assert summary.has_nan is True
    assert summary.has_inf is False
    assert summary.max_state_jump == 0.75
    assert summary.replay_available is True


def test_write_episode_summary_updates_metadata_json(tmp_path: Path) -> None:
    layout = init_run_directory(
        config=_resolved_config(tmp_path),
        episode_id="episode-001",
        scenario_id="scenario-001",
    )
    summary = EpisodeSummary.model_validate(_episode_summary_payload())

    write_episode_summary(layout=layout, summary=summary)

    summary_payload = json.loads(layout.episode_summary_path.read_text(encoding="utf-8"))
    metadata_payload = json.loads(
        layout.episode_metadata_path.read_text(encoding="utf-8")
    )

    assert EpisodeSummary.model_validate(summary_payload).episode_id == "episode-001"
    assert metadata_payload["episode_status"] == "completed"
    assert metadata_payload["files"]["episode_summary"] == "metadata/episode_summary.json"


def test_recorder_orchestrates_initial_step_offline_labels_and_finalize(
    tmp_path: Path,
) -> None:
    config = _resolved_config(tmp_path)
    recorder = Recorder.from_config(config)
    initial_state = _crane_state("C1")
    initial_dump = initial_state.model_dump(mode="json")

    initial_frame = recorder.record_initial_frame(
        episode_id="episode-001",
        frame_index=0,
        time_s=0.0,
        states=[initial_state],
        weather_state=_weather_state(),
        status="running",
    )
    step_frame = recorder.record_step(
        episode_id="episode-001",
        frame_index=1,
        time_s=0.5,
        states=[initial_state],
        weather_state=_weather_state(),
        events=[
            {
                "event_id": "EVT-001",
                "event_type": "near_miss",
                "episode_id": "episode-001",
                "scenario_id": "site_001",
                "frame": 1,
                "time_s": 0.5,
                "crane_ids": ["C1", "C2"],
                "risk_level": "high",
                "details": {},
            }
        ],
        status="running",
    )
    recorder.write_offline_labels([_offline_label()])
    summary = recorder.finalize(episode_status="completed")

    layout = recorder.layout
    assert layout is not None
    assert initial_frame.frame == 0
    assert step_frame.frame == 1
    assert summary.episode_status == "completed"
    assert initial_state.model_dump(mode="json") == initial_dump

    trajectories = pq.read_table(layout.trajectories_path)
    weather = pq.read_table(layout.weather_path)
    pair_risks = pq.read_table(layout.pair_risks_path)
    frames = [
        json.loads(line)
        for line in layout.frames_jsonl_path.read_text(encoding="utf-8").splitlines()
    ]
    events = [
        json.loads(line)
        for line in layout.events_path.read_text(encoding="utf-8").splitlines()
    ]
    summary_payload = json.loads(layout.episode_summary_path.read_text(encoding="utf-8"))

    assert trajectories.num_rows == 2
    assert weather.num_rows == 2
    assert pair_risks.num_rows == 1
    assert frames[0]["frame"] == 0
    assert frames[1]["frame"] == 1
    assert events[0]["event_type"] == "near_miss"
    assert summary_payload["near_miss_count"] == 1


def test_recorder_step_writes_task_queues_into_visual_frames(tmp_path: Path) -> None:
    config = _resolved_config(tmp_path)
    recorder = Recorder.from_config(config)
    queue = TaskQueue(
        crane_id="C1",
        tasks=[_task("C1")],
        active_task_id="T_C1_001",
        next_task_index=1,
    )

    frame = recorder.record_step(
        episode_id="episode-001",
        frame_index=1,
        time_s=0.5,
        states=[_crane_state("C1")],
        weather_state=_weather_state(),
        task_queues=[queue],
        status="running",
    )

    assert frame.tasks[0]["active_task_id"] == "T_C1_001"

    assert recorder.layout is not None
    assert recorder.visual_writer is not None
    recorder.visual_writer.flush()
    frames = [
        json.loads(line)
        for line in recorder.layout.frames_jsonl_path.read_text(encoding="utf-8").splitlines()
    ]
    assert frames[0]["tasks"][0]["active_task_id"] == "T_C1_001"
    assert frames[0]["tasks"][0]["tasks"][0]["task_id"] == "T_C1_001"


def test_production_recorder_adapter_does_not_flush_full_writers_per_frame() -> None:
    class CountingWriters:
        def __init__(self) -> None:
            self.flush_count = 0

        def flush_all(self) -> None:
            self.flush_count += 1

    class CountingVisualWriter:
        def __init__(self) -> None:
            self.flush_count = 0

        def flush(self) -> None:
            self.flush_count += 1

    class StubRecorder:
        def __init__(self) -> None:
            self.layout = None
            self.parquet_writers = CountingWriters()
            self.jsonl_writers = CountingWriters()
            self.visual_writer = CountingVisualWriter()
            self.finalize_count = 0

        def record_initial_frame(self, **kwargs):
            return SimFrame(
                episode_id=kwargs["episode_id"],
                scenario_id="scenario-001",
                frame=kwargs["frame_index"],
                time_s=kwargs["time_s"],
                episode_status="running",
                cranes=[],
                pairs=[],
                tasks=[],
                weather=SimFrameWeather(wind_speed_m_s=1.0, visibility="good"),
                events=[],
            )

        def record_step(self, **kwargs):
            return self.record_initial_frame(**kwargs)

        def finalize(self, *, episode_status):
            self.finalize_count += 1
            return {"episode_status": episode_status}

    recorder = StubRecorder()
    adapter = ProductionRecorderAdapter(recorder)
    kwargs = {
        "episode_id": "episode-001",
        "frame_index": 0,
        "time_s": 0.0,
        "states": [],
        "weather_state": _weather_state(),
        "status": "running",
    }

    adapter.record_initial_frame(**kwargs)
    adapter.record_step(**{**kwargs, "frame_index": 1, "time_s": 0.5})
    adapter.finalize(episode_status="completed")

    assert recorder.parquet_writers.flush_count == 0
    assert recorder.jsonl_writers.flush_count == 0
    assert recorder.visual_writer.flush_count == 0
    assert recorder.finalize_count == 1


def test_record_initial_frame_requires_zero_time_and_frame(tmp_path: Path) -> None:
    recorder = Recorder.from_config(_resolved_config(tmp_path))

    with pytest.raises(DataExportError):
        recorder.record_initial_frame(
            episode_id="episode-001",
            frame_index=1,
            time_s=0.5,
            states=[_crane_state("C1")],
            weather_state=_weather_state(),
            status="running",
        )
