from __future__ import annotations

from backend.app.schemas.config import ScenarioConfig
from backend.app.sim.crane_model import build_crane_model_library
from backend.app.sim.layout import build_crane_configs
from backend.app.sim.physics import (
    PHYSICS_SCHEMA_VERSION,
    build_physics_frame,
    crane_state_to_trajectory_row,
    initialize_crane_state,
    recompute_state_geometry,
)
from backend.app.tests.test_config_schema import load_fixture


def _crane_config():
    raw = load_fixture("scenario_valid.yaml")
    raw["layout"]["mode"] = "manual"
    raw["layout"]["num_cranes"] = 1
    raw["cranes"] = [
        {
            "crane_id": "TC_SERIAL",
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


def test_trajectory_row_exports_load_position_when_attached() -> None:
    crane = _crane_config()
    state = recompute_state_geometry(
        crane,
        initialize_crane_state(crane).model_copy(
            update={
                "load_attached": True,
                "load_type": "rebar",
                "load_weight_t": 2.25,
                "load_size_m": [1.0, 2.0, 3.0],
                "task_id": "TASK-42",
                "task_stage": "transport",
            }
        ),
    )

    row = crane_state_to_trajectory_row(state, frame_index=7, time_s=0.35)

    assert row["schema_version"] == PHYSICS_SCHEMA_VERSION
    assert row["frame_index"] == 7
    assert row["time_s"] == 0.35
    assert row["load_x_m"] == state.hook_position[0]
    assert row["load_y_m"] == state.hook_position[1]
    assert row["load_z_m"] == state.hook_position[2]
    assert row["load_attached"] is True
    assert row["load_type"] == "rebar"
    assert row["load_weight_t"] == 2.25
    assert row["task_id"] == "TASK-42"
    assert row["task_stage"] == "transport"


def test_build_physics_frame_uses_serialized_snapshot_not_state_objects() -> None:
    crane = _crane_config()
    state = initialize_crane_state(crane)

    frame = build_physics_frame(frame_index=3, time_s=0.15, states=[state])
    modified = state.model_copy(update={"task_stage": "modified_after_frame"})

    assert frame["states"][0]["task_stage"] == "idle"
    assert modified.task_stage == "modified_after_frame"
    assert frame["states"][0] is not state


def test_trajectory_row_does_not_export_non_physics_runtime_payloads() -> None:
    crane = _crane_config()
    row = crane_state_to_trajectory_row(
        initialize_crane_state(crane),
        frame_index=0,
        time_s=0.0,
    )

    forbidden = {
        "raw_llm_response",
        "parsed_command",
        "executed_command",
        "online_risk",
        "offline_risk_label",
        "frame_record",
        "sim_frame",
    }

    assert forbidden.isdisjoint(row)
