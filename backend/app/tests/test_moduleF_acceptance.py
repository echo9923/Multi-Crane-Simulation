from __future__ import annotations

import ast
from pathlib import Path

from backend.app.schemas.config import ScenarioConfig
from backend.app.schemas.control import ControlTarget
from backend.app.schemas.observation import OnlineRiskHint
from backend.app.schemas.task import TaskPoint
from backend.app.schemas.weather import WeatherState
from backend.app.sim.crane_model import build_crane_model_library
from backend.app.sim.layout import build_crane_configs
from backend.app.sim.observation import (
    ObservationBuildError,
    ObservationWorldSnapshot,
    build_observation,
    build_observations_for_snapshot,
)
from backend.app.sim.physics import initialize_crane_state
from backend.app.sim.task_observation import TaskObservationContext
from backend.app.sim.task_queue import IdleObservationContext
from backend.app.sim.weather import build_weather_visibility_context
from backend.app.tests.test_config_schema import load_fixture


REPO_ROOT = Path(__file__).resolve().parents[3]


def _cranes():
    raw = load_fixture("scenario_valid.yaml")
    raw["layout"]["mode"] = "manual"
    raw["layout"]["num_cranes"] = 2
    raw["cranes"] = [
        {
            "crane_id": "C1",
            "model_id": "generic_flat_top_55m",
            "base": [0.0, 0.0, 0.0],
            "mast_height_m": 50.0,
            "theta_init_deg": 0.0,
            "slew": {"mode": "continuous"},
        },
        {
            "crane_id": "C2",
            "model_id": "generic_flat_top_55m",
            "base": [30.0, 0.0, 0.0],
            "mast_height_m": 52.0,
            "theta_init_deg": 180.0,
            "slew": {"mode": "continuous"},
        },
    ]
    scenario = ScenarioConfig.model_validate(raw)
    library = build_crane_model_library(scenario.crane_models)
    return build_crane_configs(scenario.cranes, library, scenario, source="manual")


def _snapshot() -> ObservationWorldSnapshot:
    c1, c2 = _cranes()
    state_c1 = initialize_crane_state(c1).model_copy(
        update={
            "hook_position": [10.0, 0.0, 30.0],
            "trolley_r_m": 10.0,
            "hook_h_m": 30.0,
            "task_stage": "move_to_pickup",
        }
    )
    state_c2 = initialize_crane_state(c2).model_copy(
        update={
            "hook_position": [35.0, 5.0, 31.0],
            "theta_dot_rad_s": 0.1,
            "trolley_v_m_s": -0.2,
            "task_stage": "move_to_dropoff",
            "load_attached": True,
        }
    )
    weather = WeatherState(
        time_s=42.0,
        mode="schedule",
        wind_speed_m_s=8.0,
        wind_gust_m_s=12.0,
        wind_direction_deg=90.0,
        visibility_level="medium",
        rain_level="none",
        fog_level="light",
        source_segment_id="medium",
        generation_seed=303,
        generation_step=42,
    )
    visibility = build_weather_visibility_context(
        weather,
        weather_seed=303,
        decision_time_bucket=42,
    )
    active_context = TaskObservationContext(
        crane_id="C1",
        time_s=42.0,
        has_active_task=True,
        task_id="T_C1_001",
        task_type="overlap_task",
        task_stage="move_to_pickup",
        priority="high",
        deadline_s=180.0,
        deadline_missed=False,
        overtime_s=0.0,
        pickup=TaskPoint(
            x=30.0,
            y=10.0,
            z=10.0,
            zone_id="mat",
            zone_type="material",
        ),
        dropoff=TaskPoint(
            x=-5.0,
            y=15.0,
            z=32.0,
            zone_id="work",
            zone_type="work",
        ),
        current_target=TaskPoint(
            x=30.0,
            y=10.0,
            z=10.0,
            zone_id="mat",
            zone_type="material",
        ),
        load_type="rebar_bundle",
        load_weight_t=2.5,
        load_size_m=[2.0, 1.0, 1.0],
        load_attached=False,
        ground_signal_hint="吊钩在目标点西侧，请进行局部微调。",
    )
    idle_context = IdleObservationContext(
        crane_id="C2",
        time_s=42.0,
        has_active_task=False,
        task_id=None,
        task_stage="idle",
        current_target=None,
        ground_signal_hint="当前无任务，请保持塔吊安全静止并观察现场。",
    )
    return ObservationWorldSnapshot(
        snapshot_id="SNAP_0042",
        time_s=42.0,
        decision_time_bucket=42,
        crane_states=[state_c1, state_c2],
        crane_configs=[c1, c2],
        weather_state=weather,
        visibility_context=visibility,
        neighbor_map={"C1": ["C2"], "C2": ["C1"]},
        task_contexts={"C1": active_context, "C2": idle_context},
        current_commands={
            "C1": ControlTarget(
                crane_id="C1",
                target_slew_velocity_rad_s=-0.1,
                target_trolley_velocity_m_s=0.2,
                target_hoist_velocity_m_s=0.0,
            )
        },
        recent_decisions={
            "C1": [
                {
                    "time_s": 41.0,
                    "command_summary": "slew right gear1",
                    "result": "closer_to_pickup",
                }
            ]
        },
        recent_events={
            "C1": [
                {
                    "event_type": "task_started",
                    "time_s": 40.0,
                    "summary": "task started",
                }
            ]
        },
    )


def _risk() -> OnlineRiskHint:
    return OnlineRiskHint(
        source="online_risk",
        risk_level="medium",
        nearest_neighbor="C2",
        nearest_object_type="jib-hook",
        clearance_now_m=4.2,
        estimated_clearance_next_5s_m=3.1,
        relative_motion="closing",
        confidence=0.9,
        suggestion="slow_down_or_hold",
    )


def test_build_observation_assembles_complete_llm_json_without_leaks() -> None:
    snapshot = _snapshot()

    observation = build_observation(
        snapshot=snapshot,
        crane_id="C1",
        risk_prompt_mode="R1",
        operator_profile="aggressive",
        online_risk=_risk(),
        operator_id="OP_C1",
    )
    payload = observation.model_dump(mode="json")
    payload_text = str(payload)

    assert payload["observation_id"] == "OBS_SNAP_0042_C1"
    assert payload["source_snapshot_id"] == "SNAP_0042"
    assert payload["operator_id"] == "OP_C1"
    assert payload["task"]["type"] == "overlap_task"
    assert payload["self_state"]["current_command"]["left_joystick"]["slew"] == {
        "direction": "right",
        "gear": 1,
    }
    assert payload["visible_neighbors"][0]["crane_id"] == "C2"
    assert payload["weather"]["visibility"] == "medium"
    assert payload["safety_hint"]["nearest_neighbor"] == "C2"
    assert payload["available_actions"]["gear"] == [0, 1, 2, 3, 4, 5]
    assert payload["memory"]["recent_decisions"][0]["result"] == "closer_to_pickup"
    assert payload["memory"]["event_summary"] == ["task_started at 40.0: task started"]

    for forbidden in [
        "planned_start_s",
        "future_min_distance",
        "offline_ttc",
        "offline_label",
        "future_ttc",
        "source_failed_task_id",
        "neighbor_task_id",
        "pickup_zone_id",
        "dropoff_zone_id",
    ]:
        assert forbidden not in payload_text


def test_build_observation_is_replay_stable_for_same_snapshot() -> None:
    snapshot = _snapshot()

    first = build_observation(
        snapshot=snapshot,
        crane_id="C1",
        risk_prompt_mode="R1",
        operator_profile="aggressive",
        online_risk=_risk(),
    )
    second = build_observation(
        snapshot=snapshot,
        crane_id="C1",
        risk_prompt_mode="R1",
        operator_profile="aggressive",
        online_risk=_risk(),
    )

    assert first.model_dump(mode="json") == second.model_dump(mode="json")


def test_build_observations_for_snapshot_uses_same_snapshot_for_batch() -> None:
    observations = build_observations_for_snapshot(
        snapshot=_snapshot(),
        crane_ids=["C1", "C2"],
        risk_prompt_mode="R0",
        operator_profiles={"C1": "aggressive", "C2": "conservative"},
        online_risks={"C1": _risk()},
        operator_ids={"C1": "OP_C1", "C2": "OP_C2"},
    )

    assert [observation.crane_id for observation in observations] == ["C1", "C2"]
    assert {observation.source_snapshot_id for observation in observations} == {
        "SNAP_0042"
    }
    assert observations[0].safety_hint is None
    assert observations[1].operator_profile == "conservative"


def test_build_observation_rejects_missing_task_context() -> None:
    snapshot = _snapshot().model_copy(update={"task_contexts": {}})

    try:
        build_observation(
            snapshot=snapshot,
            crane_id="C1",
            risk_prompt_mode="R0",
            operator_profile="normal",
        )
    except ObservationBuildError as exc:
        assert exc.episode_status == "failed_invalid_state"
        assert exc.field_path == "task_contexts.C1"
    else:
        raise AssertionError("missing task context should fail")


def test_observation_memory_sanitizes_forbidden_history_keys() -> None:
    snapshot = _snapshot().model_copy(
        update={
            "recent_decisions": {
                "C1": [
                    {
                        "time_s": 41.0,
                        "command_summary": "slew right gear1",
                        "result": "closer_to_pickup",
                        "future_min_distance": 0.1,
                        "offline_ttc": 2.0,
                        "planned_start_s": 99.0,
                    }
                ]
            },
            "recent_events": {
                "C1": [
                    {
                        "event_type": "task_failed",
                        "time_s": 40.0,
                        "summary": "task failed",
                        "details": {"source_failed_task_id": "T_C1_001"},
                    }
                ]
            },
        }
    )

    observation = build_observation(
        snapshot=snapshot,
        crane_id="C1",
        risk_prompt_mode="R0",
        operator_profile="normal",
    )
    payload_text = str(observation.model_dump(mode="json"))

    assert "command_summary" in payload_text
    for forbidden in [
        "future_min_distance",
        "offline_ttc",
        "planned_start_s",
        "source_failed_task_id",
    ]:
        assert forbidden not in payload_text


def test_module_f_boundaries_remain_static() -> None:
    banned_imports = (
        "backend.app.llm",
        "backend.app.recorder",
        "backend.app.risk",
        "backend.app.sim.risk",
        "backend.app.sim.physics",
        "backend.app.sim.task_state_machine",
        "backend.app.sim.task_failure",
    )
    banned_names = {
        "RawLLMResponse",
        "TaskQueue",
        "step_task_state_machine",
        "near_miss",
        "collision",
        "offline_label",
        "future_min_distance",
        "offline_ttc",
        "ParquetWriter",
    }

    for relative_path in [
        "backend/app/sim/observation.py",
        "backend/app/schemas/observation.py",
    ]:
        tree = ast.parse((REPO_ROOT / relative_path).read_text(encoding="utf-8"))
        imported = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.append(node.module)

        assert not [module for module in imported if module.startswith(banned_imports)]
        names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
        assert banned_names.isdisjoint(names)
