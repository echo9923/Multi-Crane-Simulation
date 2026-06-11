from __future__ import annotations

import math

import pytest
from pydantic import ValidationError

from backend.app.schemas.config import ScenarioConfig
from backend.app.schemas.control import ControlTarget
from backend.app.schemas.observation import (
    OBSERVATION_SCHEMA_VERSION,
    AvailableActions,
    Observation,
)
from backend.app.sim.crane_model import build_crane_model_library
from backend.app.sim.layout import build_crane_configs
from backend.app.sim.observation import (
    ObservationBuildError,
    build_self_state_summary,
)
from backend.app.sim.physics import initialize_crane_state
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
    assert summary.slew_motion == "slow_right"
    assert summary.trolley_r_m == 24.5
    assert summary.hook_h_m == 30.5
    assert summary.load_attached is True
    assert summary.load_type == "rebar_bundle"
    assert summary.load_weight_t == 2.5
    assert summary.current_command.left_joystick.slew.direction == "right"
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
