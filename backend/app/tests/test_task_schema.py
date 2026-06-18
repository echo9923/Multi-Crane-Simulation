from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.app.schemas.config import ScenarioConfig
from backend.app.schemas.task import (
    Task,
    TaskActionSignal,
    TaskEventPayload,
    TaskGenerationReport,
    TaskPoint,
    TaskQueue,
    TaskStage,
    TaskStatus,
)
from backend.app.tests.test_config_schema import load_fixture


def _task_point(zone_type: str = "material") -> TaskPoint:
    return TaskPoint(
        x=10.0,
        y=20.0,
        z=1.5,
        zone_id="zone_1",
        zone_type=zone_type,
    )


def _task() -> Task:
    return Task(
        task_id="T_C1_001",
        crane_id="C1",
        task_type="easy_task",
        pickup=_task_point("material"),
        dropoff=_task_point("work").model_copy(update={"z": 30.0}),
        pickup_zone_id="material_1",
        dropoff_zone_id="work_1",
        planned_start_s=0.0,
        load_type="rebar_bundle",
        load_weight_t=2.0,
        load_size_m=[6.0, 1.0, 1.0],
        priority="medium",
        deadline_s=180.0,
        generation_seed=123,
        generation_attempt=1,
    )


def test_task_status_and_stage_enums_do_not_overlap_pending_and_idle() -> None:
    assert {status.value for status in TaskStatus} == {
        "pending",
        "active",
        "completed",
        "failed",
        "skipped",
    }
    assert {stage.value for stage in TaskStage} == {
        "idle",
        "move_to_pickup",
        "align_pickup",
        "lower_for_attach",
        "attach_pending",
        "lift_load",
        "move_to_dropoff",
        "align_dropoff",
        "lower_for_release",
        "release_pending",
        "recovery_release",
    }
    assert "pending" not in {stage.value for stage in TaskStage}
    assert "idle" not in {status.value for status in TaskStatus}


def test_task_and_queue_are_json_serializable() -> None:
    task = _task()
    queue = TaskQueue(crane_id="C1", tasks=[task])

    payload = queue.model_dump(mode="json")

    assert payload["tasks"][0]["task_id"] == "T_C1_001"
    assert payload["tasks"][0]["status"] == "pending"
    assert payload["active_task_id"] is None
    assert payload["blocked_by_recovery"] is False


def test_task_point_accepts_optional_vertical_semantics() -> None:
    point = TaskPoint(
        x=10.0,
        y=20.0,
        z=21.2,
        zone_id="floor_05",
        zone_type="work",
        surface_z_m=18.0,
        load_center_z_m=18.4,
        hook_target_z_m=21.2,
        approach_z_m=25.2,
        floor_id="floor_05",
        building_id="tower_a",
        zone_role="floor_slab",
    )

    payload = point.model_dump(mode="json")

    assert point.as_xyz() == [10.0, 20.0, 21.2]
    assert payload["surface_z_m"] == 18.0
    assert payload["load_center_z_m"] == 18.4
    assert payload["hook_target_z_m"] == 21.2
    assert payload["approach_z_m"] == 25.2
    assert payload["floor_id"] == "floor_05"
    assert payload["building_id"] == "tower_a"
    assert payload["zone_role"] == "floor_slab"


def test_recovery_release_task_type_is_runtime_only_but_serializable() -> None:
    task = _task().model_copy(
        update={
            "task_id": "R_C1_T_C1_001",
            "task_type": "recovery_release",
            "source_failed_task_id": "T_C1_001",
            "priority": "high",
            "deadline_s": None,
        }
    )

    assert task.model_dump(mode="json")["task_type"] == "recovery_release"
    assert task.source_failed_task_id == "T_C1_001"


def test_task_action_signal_exposes_only_task_action_summary() -> None:
    signal = TaskActionSignal(
        crane_id="C1",
        command_id="cmd_001",
        time_s=12.0,
        task_action="request_attach",
        motion_is_non_neutral=True,
    )

    assert signal.model_dump(mode="json") == {
        "schema_version": "1.0",
        "crane_id": "C1",
        "command_id": "cmd_001",
        "time_s": 12.0,
        "task_action": "request_attach",
        "motion_is_non_neutral": True,
    }


def test_task_generation_report_and_event_payload_are_serializable() -> None:
    report = TaskGenerationReport(
        seed=123,
        num_cranes=2,
        num_tasks_total=4,
        num_tasks_by_type={"easy_task": 2, "overlap_task": 1, "stress_task": 1},
        num_resample_attempts=3,
        warnings=[],
        blocking_errors=[],
    )
    event = TaskEventPayload(
        event_type="task_started",
        time_s=0.0,
        frame_index=None,
        crane_id="C1",
        task_id="T_C1_001",
        task_type="easy_task",
        task_status="active",
        task_stage="move_to_pickup",
        reason=None,
        details={"planned_start_s": 0.0},
    )

    assert report.model_dump(mode="json")["num_tasks_total"] == 4
    assert event.model_dump(mode="json")["details"]["planned_start_s"] == 0.0


def test_task_config_defaults_include_speed_thresholds_and_recovery() -> None:
    config = ScenarioConfig.model_validate(load_fixture("scenario_valid.yaml"))
    state_machine = config.tasks.state_machine

    assert state_machine.attach_speed_threshold.slew_deg_s == pytest.approx(0.3)
    assert state_machine.attach_speed_threshold.trolley_m_s == pytest.approx(0.08)
    assert state_machine.attach_speed_threshold.hoist_m_s == pytest.approx(0.05)
    assert state_machine.release_speed_threshold.slew_deg_s == pytest.approx(0.3)
    assert state_machine.no_progress_xy_epsilon_m == pytest.approx(0.25)
    assert config.tasks.recovery.enabled is True
    assert config.tasks.recovery.policy == "attempt_safe_release"
    assert config.tasks.recovery.emergency_drop_zones == []


def test_recovery_release_is_not_allowed_in_generation_distribution() -> None:
    raw = load_fixture("scenario_valid.yaml")
    raw["tasks"]["task_type_distribution"] = {
        "easy_task": 0.5,
        "recovery_release": 0.5,
    }

    with pytest.raises(ValidationError) as exc_info:
        ScenarioConfig.model_validate(raw)

    assert any(
        error["loc"][:2] == ("tasks", "task_type_distribution")
        for error in exc_info.value.errors()
    )


def test_recovery_policy_rejects_unknown_values() -> None:
    raw = load_fixture("scenario_valid.yaml")
    raw["tasks"]["recovery"] = {
        "enabled": True,
        "policy": "auto_clear_load",
        "emergency_drop_zones": [],
    }

    with pytest.raises(ValidationError) as exc_info:
        ScenarioConfig.model_validate(raw)

    assert ("tasks", "recovery", "policy") in [
        error["loc"] for error in exc_info.value.errors()
    ]
