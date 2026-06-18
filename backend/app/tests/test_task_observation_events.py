from __future__ import annotations

import ast
import json
import math
from pathlib import Path

from backend.app.schemas.config import ScenarioConfig
from backend.app.schemas.state import CraneState
from backend.app.schemas.task import Task, TaskPoint
from backend.app.sim.task_events import build_task_event
from backend.app.sim.task_observation import build_task_observation_context
from backend.app.tests.test_config_schema import load_fixture


REPO_ROOT = Path(__file__).resolve().parents[3]


def _task(task_type: str = "easy_task") -> Task:
    return Task(
        task_id="T_C1_001" if task_type != "recovery_release" else "R_C1_T_C1_001",
        crane_id="C1",
        task_type=task_type,
        pickup=TaskPoint(
            x=20.0,
            y=0.0,
            z=1.0,
            zone_id="mat_a",
            zone_type="material",
        ),
        dropoff=TaskPoint(
            x=25.0,
            y=5.0,
            z=30.0,
            zone_id="work_a",
            zone_type="work" if task_type != "recovery_release" else "recovery",
        ),
        pickup_zone_id="mat_a",
        dropoff_zone_id="work_a",
        planned_start_s=0.0,
        load_type="rebar_bundle",
        load_weight_t=2.0,
        load_size_m=[6.0, 1.0, 1.0],
        priority="high" if task_type == "recovery_release" else "medium",
        deadline_s=None if task_type == "recovery_release" else 180.0,
        deadline_missed=True,
        overtime_s=5.0,
        status="active",
        started_at_s=0.0,
        source_failed_task_id="T_C1_001" if task_type == "recovery_release" else None,
        generation_seed=1,
        generation_attempt=0,
    )


def _state(*, stage: str, x: float = 19.4, y: float = -0.3, z: float = 2.2) -> CraneState:
    theta = math.atan2(y, x)
    radius = math.hypot(x, y)
    return CraneState(
        crane_id="C1",
        theta_rad=theta,
        theta_sin=math.sin(theta),
        theta_cos=math.cos(theta),
        trolley_r_m=radius,
        hook_h_m=z,
        root_position=[0.0, 0.0, 50.0],
        tip_position=[50.0, 0.0, 50.0],
        hook_position=[x, y, z],
        cable_length_m=50.0 - z,
        load_attached=stage
        in {
            "lift_load",
            "move_to_dropoff",
            "align_dropoff",
            "lower_for_release",
            "release_pending",
            "recovery_release",
        },
        load_type="rebar_bundle",
        load_weight_t=2.0,
        load_size_m=[6.0, 1.0, 1.0],
        task_id=None if stage == "idle" else "T_C1_001",
        task_stage=stage,
    )


def test_active_task_observation_contains_current_task_target_and_deadline() -> None:
    context = build_task_observation_context(
        "C1",
        _state(stage="lower_for_attach"),
        active_task=_task(),
        time_s=12.0,
        recent_events=[],
    )

    assert context.has_active_task is True
    assert context.task_id == "T_C1_001"
    assert context.current_target == _task().pickup
    assert context.priority == "medium"
    assert context.deadline_missed is True
    assert context.overtime_s == 5.0
    assert context.ground_signal_hint is not None


def test_lift_load_current_target_matches_state_machine_lift_threshold() -> None:
    scenario = ScenarioConfig.model_validate(load_fixture("scenario_valid.yaml"))
    state_machine_config = scenario.tasks.state_machine.model_copy(
        update={
            "lift_clearance_m": 2.0,
            "safe_transport_height_m": 12.0,
        }
    )
    task = _task().model_copy(
        update={
            "pickup": TaskPoint(
                x=20.0,
                y=0.0,
                z=10.0,
                zone_id="mat_a",
                zone_type="material",
            ),
            "dropoff": TaskPoint(
                x=25.0,
                y=5.0,
                z=11.0,
                zone_id="work_a",
                zone_type="work",
            ),
        }
    )

    context = build_task_observation_context(
        "C1",
        _state(stage="lift_load", x=20.0, y=0.0, z=11.5),
        active_task=task,
        time_s=12.0,
        recent_events=[],
        state_machine_config=state_machine_config,
    )

    assert context.current_target is not None
    assert context.current_target.z == 13.0


def test_idle_observation_hides_next_task_information() -> None:
    context = build_task_observation_context(
        "C1",
        _state(stage="idle"),
        active_task=None,
        time_s=0.0,
        recent_events=[],
    )
    payload = context.model_dump(mode="json")

    assert payload["has_active_task"] is False
    assert payload["task_id"] is None
    assert payload["pickup"] is None
    assert payload["dropoff"] is None
    assert payload["current_target"] is None
    assert "T_C1_001" not in str(payload)


def test_recovery_observation_identifies_recovery_release() -> None:
    task = _task("recovery_release")
    context = build_task_observation_context(
        "C1",
        _state(stage="recovery_release", x=24.5, y=4.5, z=30.2),
        active_task=task,
        time_s=20.0,
        recent_events=[],
    )

    assert context.task_type == "recovery_release"
    assert context.deadline_s is None
    assert context.current_target == task.dropoff
    assert "恢复卸载" in context.ground_signal_hint


def test_ground_signal_hint_is_local_and_not_global_route() -> None:
    context = build_task_observation_context(
        "C1",
        _state(stage="lower_for_attach"),
        active_task=_task(),
        time_s=12.0,
        recent_events=[],
    )

    assert "东侧" in context.ground_signal_hint or "西侧" in context.ground_signal_hint
    assert "高度偏高" in context.ground_signal_hint
    assert "路线" not in context.ground_signal_hint
    assert "不会碰撞" not in context.ground_signal_hint


def test_task_events_are_json_serializable_with_expected_details() -> None:
    rejected = build_task_event(
        "attach_request_rejected",
        time_s=12.0,
        frame_index=3,
        crane_id="C1",
        task=_task(),
        task_stage="lower_for_attach",
        reason="xy_error_too_large",
        details={"xy_error_m": 2.5},
    )
    failed = build_task_event(
        "task_failed",
        time_s=20.0,
        frame_index=4,
        crane_id="C1",
        task=_task(),
        task_stage="recovery_release",
        reason="failed_release_timeout",
        details={
            "error_code": "TASK_E_103",
            "failure_reason": "failed_release_timeout",
            "load_attached": True,
            "recovery_task_id": "R_C1_T_C1_001",
        },
    )

    json.dumps(rejected.model_dump(mode="json"), ensure_ascii=False)
    payload = failed.model_dump(mode="json")
    assert payload["details"]["error_code"] == "TASK_E_103"
    assert payload["details"]["recovery_task_id"] == "R_C1_T_C1_001"


def test_task_observation_and_events_do_not_import_llm_or_recorder() -> None:
    banned_prefixes = (
        "backend.app.llm",
        "backend.app.recorder",
        "backend.app.risk",
    )
    for path in [
        REPO_ROOT / "backend/app/sim/task_observation.py",
        REPO_ROOT / "backend/app/sim/task_events.py",
    ]:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imported = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.append(node.module)

        assert not [
            module for module in imported if module.startswith(banned_prefixes)
        ], path
