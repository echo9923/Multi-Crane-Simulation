from __future__ import annotations

from backend.app.schemas.config import ScenarioConfig
from backend.app.schemas.control import ControlTarget
from backend.app.sim.crane_model import build_crane_model_library
from backend.app.sim.layout import build_crane_configs
from backend.app.sim.physics import (
    PHYSICS_SCHEMA_VERSION,
    build_physics_frame,
    crane_state_to_trajectory_row,
    initialize_crane_state,
    step_crane_state,
)
from backend.app.tests.test_config_schema import load_fixture


def _crane_config():
    raw = load_fixture("scenario_valid.yaml")
    raw["layout"]["mode"] = "manual"
    raw["layout"]["num_cranes"] = 1
    raw["cranes"] = [
        {
            "crane_id": "TC_IFACE",
            "model_id": "generic_flat_top_55m",
            "base": [0.0, 0.0, 0.0],
            "mast_height_m": 50.0,
            "theta_init_deg": 0.0,
            "slew": {"mode": "continuous"},
        }
    ]
    scenario = ScenarioConfig.model_validate(raw)
    model_library = build_crane_model_library(scenario.crane_models)
    return build_crane_configs(scenario.cranes, model_library, scenario, source="manual")[0]


def _neutral_target(crane_id: str = "TC_IFACE") -> ControlTarget:
    return ControlTarget(
        crane_id=crane_id,
        target_slew_velocity_rad_s=0.0,
        target_trolley_velocity_m_s=0.0,
        target_hoist_velocity_m_s=0.0,
    )


def test_physics_schema_version_is_shared_by_control_state_and_frames() -> None:
    crane = _crane_config()
    state = initialize_crane_state(crane)
    target = _neutral_target()
    frame = build_physics_frame(frame_index=0, time_s=0.0, states=[state])

    assert PHYSICS_SCHEMA_VERSION == "1.0"
    assert state.schema_version == PHYSICS_SCHEMA_VERSION
    assert target.schema_version == PHYSICS_SCHEMA_VERSION
    assert frame["schema_version"] == PHYSICS_SCHEMA_VERSION


def test_build_physics_frame_documents_initial_and_step_after_recording_contract() -> None:
    crane = _crane_config()
    initial = initialize_crane_state(crane)
    stepped = step_crane_state(crane, initial, _neutral_target(), dt=0.05)

    initial_frame = build_physics_frame(frame_index=0, time_s=0.0, states=[initial])
    next_frame = build_physics_frame(frame_index=1, time_s=0.05, states=[stepped])

    assert initial_frame["frame_index"] == 0
    assert initial_frame["time_s"] == 0.0
    assert initial_frame["states"][0]["crane_id"] == "TC_IFACE"
    assert next_frame["frame_index"] == 1
    assert next_frame["time_s"] == 0.05
    assert next_frame["states"][0]["crane_id"] == "TC_IFACE"


def test_crane_state_to_trajectory_row_exports_physics_columns_only() -> None:
    crane = _crane_config()
    state = initialize_crane_state(crane)

    row = crane_state_to_trajectory_row(state, frame_index=0, time_s=0.0)

    assert row["schema_version"] == PHYSICS_SCHEMA_VERSION
    assert row["frame_index"] == 0
    assert row["time_s"] == 0.0
    assert row["crane_id"] == "TC_IFACE"
    assert row["theta_rad"] == state.theta_rad
    assert row["theta_sin"] == state.theta_sin
    assert row["theta_cos"] == state.theta_cos
    assert row["hook_x_m"] == state.hook_position[0]
    assert row["hook_y_m"] == state.hook_position[1]
    assert row["hook_z_m"] == state.hook_position[2]
    assert row["tip_x_m"] == state.tip_position[0]
    assert row["tip_y_m"] == state.tip_position[1]
    assert row["tip_z_m"] == state.tip_position[2]
    assert row["load_x_m"] is None
    assert "raw_llm_response" not in row
    assert "online_risk" not in row
    assert "task_status" not in row


def test_control_target_schema_stays_continuous_and_free_of_task_semantics() -> None:
    fields = set(ControlTarget.model_fields)

    assert {
        "target_slew_velocity_rad_s",
        "target_trolley_velocity_m_s",
        "target_hoist_velocity_m_s",
        "emergency_stop",
        "hold_position",
    } <= fields
    assert "task_action" not in fields
    assert "llm_reason" not in fields
    assert "operator_profile" not in fields
