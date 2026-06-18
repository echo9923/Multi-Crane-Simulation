from __future__ import annotations

import math

import pytest
from pydantic import ValidationError

from backend.app.schemas.config import ScenarioConfig
from backend.app.schemas.control import ControlTarget
from backend.app.schemas.observation import (
    OBSERVATION_SCHEMA_VERSION,
    AvailableActions,
    OnlineRiskHint,
    Observation,
)
from backend.app.schemas.weather import WeatherVisibilityContext
from backend.app.schemas.task import Task, TaskPoint
from backend.app.sim.crane_model import build_crane_model_library
from backend.app.sim.layout import build_crane_configs
from backend.app.sim.observation import (
    ObservationBuildError,
    build_safety_hint,
    build_task_summary,
    build_self_state_summary,
)
from backend.app.sim.physics import initialize_crane_state
from backend.app.sim.task_observation import (
    TaskObservationContext,
    build_task_observation_context,
)
from backend.app.sim.task_queue import IdleObservationContext
from backend.app.tests.test_config_schema import load_fixture


def _crane_config():
    raw = load_fixture("scenario_valid.yaml")
    raw["layout"]["mode"] = "manual"
    raw["layout"]["num_cranes"] = 1
    raw["cranes"] = [
        {
            "crane_id": "C1",
            "model_id": "generic_flat_top_55m",
            "base": [0.0, 0.0, 0.0],
            "mast_height_m": 50.0,
            "theta_init_deg": 45.0,
            "slew": {"mode": "continuous"},
        }
    ]
    scenario = ScenarioConfig.model_validate(raw)
    library = build_crane_model_library(scenario.crane_models)
    return build_crane_configs(scenario.cranes, library, scenario, source="manual")[0]


def _visibility_context(**overrides) -> WeatherVisibilityContext:
    payload = {
        "time_s": 42.0,
        "visibility_level": "poor",
        "neighbor_visibility_radius_m": 45.0,
        "distance_noise_m": 5.0,
        "hide_hook_prob": 0.5,
        "visibility_confidence": 0.4,
        "distance_precision_m": 5.0,
        "noise_seed": 123,
        "profile_source": "default",
    }
    payload.update(overrides)
    return WeatherVisibilityContext.model_validate(payload)


def _task_for_lift_target() -> Task:
    return Task(
        task_id="T_C1_001",
        crane_id="C1",
        task_type="easy_task",
        pickup=TaskPoint(
            x=20.0,
            y=0.0,
            z=10.0,
            zone_id="mat",
            zone_type="material",
        ),
        dropoff=TaskPoint(
            x=25.0,
            y=0.0,
            z=11.0,
            zone_id="work",
            zone_type="work",
        ),
        pickup_zone_id="mat",
        dropoff_zone_id="work",
        planned_start_s=0.0,
        load_type="rebar_bundle",
        load_weight_t=2.0,
        load_size_m=[2.0, 1.0, 1.0],
        priority="medium",
        deadline_s=180.0,
        status="active",
        started_at_s=0.0,
        generation_seed=1,
        generation_attempt=0,
    )


def _valid_observation_payload() -> dict:
    return {
        "schema_version": OBSERVATION_SCHEMA_VERSION,
        "observation_id": "OBS_SNAP_0001_C1",
        "source_snapshot_id": "SNAP_0001",
        "operator_id": "OP_C1",
        "crane_id": "C1",
        "time_s": 42.0,
        "operator_profile": "aggressive",
        "risk_prompt_mode": "R1",
        "task": {
            "stage": "move_to_pickup",
            "has_active_task": True,
            "type": "overlap_task",
            "priority": "high",
            "deadline_s": 180.0,
            "deadline_missed": False,
            "overtime_s": 0.0,
            "pickup_relative_direction": "right_front",
            "pickup_distance_m": 18.0,
            "pickup_height_delta_m": -22.0,
            "dropoff_relative_direction": "left_front",
            "dropoff_distance_m": 52.0,
            "dropoff_height_delta_m": 4.0,
            "current_target_relative_direction": "right_front",
            "current_target_distance_m": 18.0,
            "current_target_height_delta_m": -22.0,
            "load_attached": False,
            "load_type": "rebar_bundle",
            "load_weight_t": 2.5,
            "signal_hint": "吊钩在目标点西侧 18.0m，请进行局部微调。",
        },
        "self_state": {
            "slew_angle_deg": 45.0,
            "slew_motion": "slow_right",
            "trolley_r_m": 24.0,
            "hook_h_m": 31.0,
            "load_attached": False,
            "load_type": None,
            "load_weight_t": 0.0,
            "current_command": {
                "left_joystick": {
                    "slew": {"direction": "right", "gear": 1},
                    "trolley": {"direction": "neutral", "gear": 0},
                },
                "right_joystick": {
                    "hoist": {"direction": "neutral", "gear": 0}
                },
                "deadman_pressed": True,
                "emergency_stop": False,
                "hold_position": False,
            },
        },
        "visible_neighbors": [
            {
                "crane_id": "C2",
                "relative_direction": "right_front",
                "distance_m": 34.0,
                "distance_level": "near",
                "hook_visible": True,
                "hook_height_m": 30.0,
                "jib_motion": "slow_left",
                "trolley_motion": "out",
                "hoist_motion": "hold",
                "load_attached": True,
                "task_stage": "move_to_dropoff",
                "in_overlap_zone": True,
            }
        ],
        "weather": {
            "wind_speed_m_s": 8.0,
            "gust_m_s": 12.0,
            "wind_direction_deg": 90.0,
            "visibility": "medium",
            "rain_level": "none",
            "fog_level": "light",
            "visibility_confidence": 0.7,
        },
        "safety_hint": {
            "source": "online_risk",
            "risk_level": "medium",
            "nearest_neighbor": "C2",
            "nearest_object_type": "jib-hook",
            "clearance_now_m": 4.0,
            "estimated_clearance_next_5s_m": 3.0,
            "relative_motion": "closing",
            "confidence": 0.7,
            "suggestion": "slow_down_or_hold",
        },
        "available_actions": {
            "slew_direction": ["left", "neutral", "right"],
            "trolley_direction": ["in", "neutral", "out"],
            "hoist_direction": ["up", "neutral", "down"],
            "gear": [0, 1, 2, 3, 4, 5],
            "deadman_pressed": [True, False],
            "emergency_stop": [True, False],
            "task_action": ["none", "request_attach", "request_release"],
        },
        "memory": {
            "task_history_summary": "本任务开始后已右回转并向外移动小车。",
            "recent_decisions": [
                {
                    "time_s": 41.0,
                    "command_summary": "slew right gear2",
                    "result": "closer_to_pickup",
                }
            ],
            "event_summary": ["没有发生碰撞；上一任务未超时。"],
        },
    }


def test_observation_schema_accepts_llm_consumable_payload() -> None:
    observation = Observation.model_validate(_valid_observation_payload())

    payload = observation.model_dump(mode="json")

    assert payload["schema_version"] == "1.0"
    assert payload["operator_profile"] == "aggressive"
    assert payload["risk_prompt_mode"] == "R1"
    assert payload["visible_neighbors"][0]["crane_id"] == "C2"


def test_observation_schema_forbids_extra_fields_recursively() -> None:
    payload = _valid_observation_payload()
    payload["visible_neighbors"][0]["task_id"] = "T_C2_001"

    with pytest.raises(ValidationError) as exc_info:
        Observation.model_validate(payload)

    assert ("visible_neighbors", 0, "task_id") in [
        tuple(error["loc"]) for error in exc_info.value.errors()
    ]


def test_observation_schema_forbids_extra_memory_decision_fields() -> None:
    payload = _valid_observation_payload()
    payload["memory"]["recent_decisions"][0]["future_min_distance"] = 0.1

    with pytest.raises(ValidationError) as exc_info:
        Observation.model_validate(payload)

    assert ("memory", "recent_decisions", 0, "future_min_distance") in [
        tuple(error["loc"]) for error in exc_info.value.errors()
    ]


def test_observation_schema_rejects_nan_and_inf_values() -> None:
    payload = _valid_observation_payload()
    payload["self_state"]["hook_h_m"] = math.nan

    with pytest.raises(ValidationError):
        Observation.model_validate(payload)

    payload = _valid_observation_payload()
    payload["weather"]["wind_speed_m_s"] = math.inf

    with pytest.raises(ValidationError):
        Observation.model_validate(payload)


def test_r0_observation_allows_empty_safety_hint() -> None:
    payload = _valid_observation_payload()
    payload["risk_prompt_mode"] = "R0"
    payload["safety_hint"] = None

    observation = Observation.model_validate(payload)

    assert observation.safety_hint is None


def test_available_actions_validate_expected_gear_bounds() -> None:
    actions = AvailableActions()

    assert actions.gear == [0, 1, 2, 3, 4, 5]

    with pytest.raises(ValidationError):
        AvailableActions(gear=[0, 1, 2, 3, 4, 5, 6])


def test_observation_schema_does_not_define_forbidden_fields() -> None:
    forbidden = {
        "future_min_distance",
        "offline_ttc",
        "offline_label",
        "future_ttc",
        "planned_start_s",
        "neighbor_task_id",
    }
    schema_text = str(Observation.model_json_schema())

    assert forbidden.isdisjoint(schema_text.split("'"))
    for field_name in forbidden:
        assert field_name not in schema_text


def test_build_self_state_summary_rounds_values_and_maps_current_command() -> None:
    crane = _crane_config()
    state = initialize_crane_state(crane).model_copy(
        update={
            "theta_rad": math.radians(45.0),
            "theta_dot_rad_s": -0.2,
            "trolley_r_m": 24.26,
            "trolley_v_m_s": 0.5,
            "hook_h_m": 30.74,
            "hoist_v_m_s": -0.25,
            "load_attached": True,
            "load_type": "rebar_bundle",
            "load_weight_t": 2.5,
        }
    )
    current_command = ControlTarget(
        crane_id="C1",
        target_slew_velocity_rad_s=-0.2,
        target_trolley_velocity_m_s=0.5,
        target_hoist_velocity_m_s=-0.25,
    )

    summary = build_self_state_summary(
        state=state,
        crane_config=crane,
        current_command=current_command,
        distance_precision_m=0.5,
    )

    assert summary.slew_angle_deg == 45.0
    assert summary.slew_motion == "slow_left"
    assert summary.trolley_r_m == 24.5
    assert summary.hook_h_m == 30.5
    assert summary.load_attached is True
    assert summary.load_type == "rebar_bundle"
    assert summary.load_weight_t == 2.5
    assert summary.current_command.left_joystick.slew.direction == "left"
    assert summary.current_command.left_joystick.slew.gear == 1
    assert summary.current_command.left_joystick.trolley.direction == "out"
    assert summary.current_command.right_joystick.hoist.direction == "down"


def test_build_self_state_summary_defaults_to_neutral_command() -> None:
    crane = _crane_config()
    state = initialize_crane_state(crane)

    summary = build_self_state_summary(
        state=state,
        crane_config=crane,
        current_command=None,
        distance_precision_m=1.0,
    )

    assert summary.slew_motion == "hold"
    assert summary.current_command.left_joystick.slew.direction == "neutral"
    assert summary.current_command.left_joystick.trolley.direction == "neutral"
    assert summary.current_command.right_joystick.hoist.direction == "neutral"
    assert summary.current_command.left_joystick.slew.gear == 0
    assert summary.current_command.deadman_pressed is True
    assert summary.current_command.emergency_stop is False


def test_build_self_state_summary_rejects_mismatched_identity() -> None:
    crane = _crane_config()
    state = initialize_crane_state(crane).model_copy(update={"crane_id": "OTHER"})

    with pytest.raises(ObservationBuildError) as exc_info:
        build_self_state_summary(
            state=state,
            crane_config=crane,
            current_command=None,
            distance_precision_m=1.0,
        )

    assert exc_info.value.error_code == "OBSERVATION_E_INVALID_STATE"
    assert exc_info.value.episode_status == "failed_invalid_state"


def test_build_task_summary_uses_active_context_relative_to_own_hook() -> None:
    crane = _crane_config()
    state = initialize_crane_state(crane).model_copy(
        update={"hook_position": [10.0, 10.0, 30.0]}
    )
    context = TaskObservationContext(
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
            y=40.0,
            z=10.0,
            zone_id="mat",
            zone_type="material",
        ),
        dropoff=TaskPoint(
            x=-10.0,
            y=20.0,
            z=32.0,
            zone_id="work",
            zone_type="work",
        ),
        current_target=TaskPoint(
            x=30.0,
            y=40.0,
            z=10.0,
            zone_id="mat",
            zone_type="material",
        ),
        load_type="rebar_bundle",
        load_weight_t=2.25,
        load_size_m=[2.0, 1.0, 1.0],
        load_attached=False,
        ground_signal_hint="吊钩在目标点西侧，请进行局部微调。",
    )

    summary = build_task_summary(
        task_context=context,
        observer_state=state,
        distance_precision_m=5.0,
    )

    assert summary.stage == "move_to_pickup"
    assert summary.has_active_task is True
    assert summary.type == "overlap_task"
    assert summary.priority == "high"
    assert summary.deadline_s == 180.0
    assert summary.pickup_relative_direction == "right_front"
    assert summary.pickup_distance_m == 35.0
    assert summary.pickup_height_delta_m == -20.0
    assert summary.dropoff_relative_direction == "left_front"
    assert summary.dropoff_distance_m == 20.0
    assert summary.dropoff_height_delta_m == 0.0
    assert summary.current_target_relative_direction == "right_front"
    assert summary.load_type == "rebar_bundle"
    assert summary.load_weight_t == 2.25
    assert summary.signal_hint == "吊钩在目标点西侧，请进行局部微调。"


def test_build_task_summary_adds_control_native_hint_for_current_target() -> None:
    crane = _crane_config()
    state = initialize_crane_state(crane).model_copy(
        update={
            "theta_rad": math.radians(0.0),
            "theta_dot_rad_s": 0.0,
            "trolley_r_m": 10.0,
            "trolley_v_m_s": 0.0,
            "hook_h_m": 20.0,
            "hoist_v_m_s": 0.0,
            "hook_position": [10.0, 0.0, 20.0],
        }
    )
    context = TaskObservationContext(
        crane_id="C1",
        time_s=42.0,
        has_active_task=True,
        task_id="T_C1_001",
        task_type="easy_task",
        task_stage="move_to_pickup",
        priority="medium",
        pickup=TaskPoint(
            x=0.0,
            y=-20.0,
            z=8.0,
            zone_id="mat",
            zone_type="material",
        ),
        dropoff=TaskPoint(
            x=25.0,
            y=0.0,
            z=12.0,
            zone_id="work",
            zone_type="work",
        ),
        current_target=TaskPoint(
            x=0.0,
            y=-20.0,
            z=8.0,
            zone_id="mat",
            zone_type="material",
        ),
        load_type="rebar_bundle",
        load_weight_t=2.0,
        load_size_m=[2.0, 1.0, 1.0],
        load_attached=False,
        ground_signal_hint="请按控制提示接近取货点。",
        crane_config=crane,
        state_machine_config=ScenarioConfig.model_validate(
            load_fixture("scenario_valid.yaml")
        ).tasks.state_machine,
    )

    summary = build_task_summary(
        task_context=context,
        observer_state=state,
        distance_precision_m=0.5,
    )

    assert summary.control_hint is not None
    assert summary.control_hint.target_kind == "pickup"
    assert summary.control_hint.slew_hint_direction == "left"
    assert summary.control_hint.trolley_hint_direction == "out"
    assert summary.control_hint.hoist_hint_direction == "down"
    assert summary.control_hint.angular_error_deg == -90.0
    assert summary.control_hint.radial_error_m == 10.0
    assert summary.control_hint.height_error_m == -12.0
    assert summary.control_hint.xy_error_m == 22.5
    assert summary.control_hint.can_request_attach is False
    assert summary.control_hint.attach_blocking_reason == "wrong_stage"
    assert summary.control_hint.can_request_release is False
    assert summary.control_hint.release_blocking_reason == "wrong_stage"


def test_build_task_summary_marks_attach_ready_when_thresholds_match_state_machine() -> None:
    crane = _crane_config()
    state = initialize_crane_state(crane).model_copy(
        update={
            "theta_rad": math.radians(0.0),
            "theta_dot_rad_s": 0.0,
            "trolley_r_m": 20.0,
            "trolley_v_m_s": 0.0,
            "hook_h_m": 1.1,
            "hoist_v_m_s": 0.0,
            "hook_position": [20.0, 0.0, 1.1],
            "task_stage": "lower_for_attach",
        }
    )
    scenario = ScenarioConfig.model_validate(load_fixture("scenario_valid.yaml"))
    context = TaskObservationContext(
        crane_id="C1",
        time_s=42.0,
        has_active_task=True,
        task_id="T_C1_001",
        task_type="easy_task",
        task_stage="lower_for_attach",
        priority="medium",
        pickup=TaskPoint(
            x=20.5,
            y=0.0,
            z=1.0,
            zone_id="mat",
            zone_type="material",
        ),
        dropoff=TaskPoint(
            x=25.0,
            y=0.0,
            z=12.0,
            zone_id="work",
            zone_type="work",
        ),
        current_target=TaskPoint(
            x=20.5,
            y=0.0,
            z=1.0,
            zone_id="mat",
            zone_type="material",
        ),
        load_type="rebar_bundle",
        load_weight_t=2.0,
        load_size_m=[2.0, 1.0, 1.0],
        load_attached=False,
        ground_signal_hint="满足条件时请求挂载。",
        crane_config=crane,
        state_machine_config=scenario.tasks.state_machine,
    )

    summary = build_task_summary(
        task_context=context,
        observer_state=state,
        distance_precision_m=0.1,
    )

    assert summary.control_hint is not None
    assert summary.control_hint.target_kind == "pickup"
    assert summary.control_hint.can_request_attach is True
    assert summary.control_hint.attach_blocking_reason is None
    assert summary.control_hint.slew_hint_direction == "neutral"
    assert summary.control_hint.trolley_hint_direction == "neutral"
    assert summary.control_hint.hoist_hint_direction == "neutral"


def test_build_task_summary_holds_horizontal_axes_when_only_attach_height_blocks() -> None:
    crane = _crane_config()
    state = initialize_crane_state(crane).model_copy(
        update={
            "theta_rad": math.radians(0.0),
            "theta_dot_rad_s": 0.0,
            "trolley_r_m": 20.0,
            "trolley_v_m_s": 0.0,
            "hook_h_m": 4.0,
            "hoist_v_m_s": 0.0,
            "hook_position": [20.0, 0.0, 4.0],
            "task_stage": "lower_for_attach",
        }
    )
    scenario = ScenarioConfig.model_validate(load_fixture("scenario_valid.yaml"))
    context = TaskObservationContext(
        crane_id="C1",
        time_s=42.0,
        has_active_task=True,
        task_id="T_C1_001",
        task_type="easy_task",
        task_stage="lower_for_attach",
        priority="medium",
        pickup=TaskPoint(
            x=20.5,
            y=0.0,
            z=1.0,
            zone_id="mat",
            zone_type="material",
        ),
        dropoff=TaskPoint(
            x=25.0,
            y=0.0,
            z=12.0,
            zone_id="work",
            zone_type="work",
        ),
        current_target=TaskPoint(
            x=20.5,
            y=0.0,
            z=1.0,
            zone_id="mat",
            zone_type="material",
        ),
        load_type="rebar_bundle",
        load_weight_t=2.0,
        load_size_m=[2.0, 1.0, 1.0],
        load_attached=False,
        ground_signal_hint="只需继续下降。",
        crane_config=crane,
        state_machine_config=scenario.tasks.state_machine,
    )

    summary = build_task_summary(
        task_context=context,
        observer_state=state,
        distance_precision_m=0.1,
    )

    assert summary.control_hint is not None
    assert summary.control_hint.attach_blocking_reason == "height_error_too_large"
    assert summary.control_hint.slew_hint_direction == "neutral"
    assert summary.control_hint.trolley_hint_direction == "neutral"
    assert summary.control_hint.hoist_hint_direction == "down"


def test_build_task_summary_lift_load_uses_state_machine_lift_target() -> None:
    crane = _crane_config()
    scenario = ScenarioConfig.model_validate(load_fixture("scenario_valid.yaml"))
    state_machine_config = scenario.tasks.state_machine.model_copy(
        update={
            "lift_clearance_m": 2.0,
            "safe_transport_height_m": 12.0,
        }
    )
    below_target = initialize_crane_state(crane).model_copy(
        update={
            "theta_rad": math.radians(0.0),
            "theta_dot_rad_s": 0.0,
            "trolley_r_m": 20.0,
            "trolley_v_m_s": 0.0,
            "hook_h_m": 11.5,
            "hoist_v_m_s": 0.0,
            "hook_position": [20.0, 0.0, 11.5],
            "load_attached": True,
            "task_stage": "lift_load",
        }
    )
    context = build_task_observation_context(
        "C1",
        below_target,
        active_task=_task_for_lift_target(),
        time_s=42.0,
        recent_events=[],
        crane_config=crane,
        state_machine_config=state_machine_config,
    )

    below_summary = build_task_summary(
        task_context=context,
        observer_state=below_target,
        distance_precision_m=0.1,
    )

    assert below_summary.control_hint is not None
    assert below_summary.control_hint.target_kind == "lift"
    assert below_summary.control_hint.height_error_m == 1.5
    assert below_summary.control_hint.hoist_hint_direction == "up"
    assert below_summary.control_hint.slew_hint_direction == "neutral"
    assert below_summary.control_hint.trolley_hint_direction == "neutral"

    at_target = below_target.model_copy(
        update={
            "hook_h_m": 13.0,
            "hook_position": [20.0, 0.0, 13.0],
        }
    )

    at_summary = build_task_summary(
        task_context=context,
        observer_state=at_target,
        distance_precision_m=0.1,
    )

    assert at_summary.control_hint is not None
    assert at_summary.control_hint.height_error_m == 0.0
    assert at_summary.control_hint.hoist_hint_direction == "neutral"


def test_build_task_summary_align_dropoff_targets_dropoff_height() -> None:
    crane = _crane_config()
    scenario = ScenarioConfig.model_validate(load_fixture("scenario_valid.yaml"))
    state = initialize_crane_state(crane).model_copy(
        update={
            "theta_rad": math.radians(0.0),
            "theta_dot_rad_s": 0.0,
            "trolley_r_m": 25.0,
            "trolley_v_m_s": 0.0,
            "hook_h_m": 11.0,
            "hoist_v_m_s": 0.0,
            "hook_position": [25.0, 0.0, 11.0],
            "load_attached": True,
            "task_stage": "align_dropoff",
        }
    )
    context = build_task_observation_context(
        "C1",
        state,
        active_task=_task_for_lift_target(),
        time_s=42.0,
        recent_events=[],
        crane_config=crane,
        state_machine_config=scenario.tasks.state_machine,
    )

    summary = build_task_summary(
        task_context=context,
        observer_state=state,
        distance_precision_m=0.1,
    )

    assert context.current_target is not None
    assert context.current_target.x == 25.0
    assert context.current_target.y == 0.0
    assert context.current_target.z == 11.0
    assert summary.control_hint is not None
    assert summary.control_hint.target_kind == "dropoff"
    assert summary.control_hint.height_error_m == 0.0
    assert summary.control_hint.hoist_hint_direction == "neutral"


def test_build_task_summary_idle_context_does_not_leak_next_task() -> None:
    crane = _crane_config()
    state = initialize_crane_state(crane)
    context = IdleObservationContext(
        crane_id="C1",
        time_s=12.0,
        has_active_task=False,
        task_id=None,
        task_stage="idle",
        current_target=None,
        ground_signal_hint="当前无任务，请保持塔吊安全静止并观察现场。",
    )

    summary = build_task_summary(
        task_context=context,
        observer_state=state,
        distance_precision_m=1.0,
    )
    payload = summary.model_dump(mode="json")

    assert summary.has_active_task is False
    assert summary.stage == "idle"
    assert summary.type is None
    assert summary.pickup_relative_direction is None
    assert summary.dropoff_relative_direction is None
    assert summary.current_target_distance_m is None
    assert "planned_start_s" not in str(payload)


def test_build_task_summary_rejects_mismatched_context_identity() -> None:
    crane = _crane_config()
    state = initialize_crane_state(crane)
    context = IdleObservationContext(
        crane_id="OTHER",
        time_s=12.0,
        has_active_task=False,
        task_id=None,
        task_stage="idle",
        current_target=None,
        ground_signal_hint="当前无任务，请保持塔吊安全静止并观察现场。",
    )

    with pytest.raises(ObservationBuildError) as exc_info:
        build_task_summary(
            task_context=context,
            observer_state=state,
            distance_precision_m=1.0,
        )

    assert exc_info.value.field_path == "task_context.crane_id"


def test_build_safety_hint_suppresses_online_risk_in_r0_mode() -> None:
    risk = OnlineRiskHint(
        source="online_risk",
        risk_level="high",
        nearest_neighbor="C2",
        nearest_object_type="jib-hook",
        clearance_now_m=4.2,
        estimated_clearance_next_5s_m=3.1,
        relative_motion="closing",
        confidence=0.9,
        suggestion="hold",
    )

    hint = build_safety_hint(
        risk_prompt_mode="R0",
        online_risk=risk,
        visibility=_visibility_context(),
        distance_precision_m=1.0,
    )

    assert hint is None


def test_build_safety_hint_rounds_clearance_and_caps_visibility_confidence() -> None:
    risk = OnlineRiskHint(
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

    hint = build_safety_hint(
        risk_prompt_mode="R1",
        online_risk=risk,
        visibility=_visibility_context(visibility_confidence=0.4),
        distance_precision_m=1.0,
    )

    assert hint is not None
    assert hint.nearest_neighbor == "C2"
    assert hint.clearance_now_m == 4.0
    assert hint.estimated_clearance_next_5s_m == 3.0
    assert hint.confidence == 0.4
    assert hint.suggestion == "slow_down_or_hold"


def test_build_safety_hint_returns_none_when_r1_has_no_online_risk() -> None:
    hint = build_safety_hint(
        risk_prompt_mode="R1",
        online_risk=None,
        visibility=_visibility_context(),
        distance_precision_m=1.0,
    )

    assert hint is None
