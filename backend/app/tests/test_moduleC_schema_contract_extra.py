from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.app.schemas.control import ControlTarget
from backend.app.schemas.state import CraneState


def _state_payload() -> dict:
    return {
        "crane_id": "TC_SCHEMA",
        "theta_rad": 0.0,
        "theta_dot_rad_s": 0.0,
        "theta_ddot_rad_s2": 0.0,
        "theta_sin": 0.0,
        "theta_cos": 1.0,
        "trolley_r_m": 5.0,
        "trolley_v_m_s": 0.0,
        "hook_h_m": 48.0,
        "hoist_v_m_s": 0.0,
        "root_position": [0.0, 0.0, 50.0],
        "tip_position": [55.0, 0.0, 50.0],
        "hook_position": [5.0, 0.0, 48.0],
        "cable_length_m": 2.0,
    }


def test_crane_state_rejects_unknown_runtime_fields() -> None:
    payload = _state_payload()
    payload["raw_llm_response"] = "must not live in physics state"

    with pytest.raises(ValidationError) as exc_info:
        CraneState.model_validate(payload)

    assert ("raw_llm_response",) in [error["loc"] for error in exc_info.value.errors()]


@pytest.mark.parametrize(
    "field",
    [
        "root_position",
        "tip_position",
        "hook_position",
        "load_position",
        "load_size_m",
    ],
)
def test_crane_state_requires_three_component_vectors(field: str) -> None:
    payload = _state_payload()
    payload[field] = [1.0, 2.0]

    with pytest.raises(ValidationError) as exc_info:
        CraneState.model_validate(payload)

    assert (field,) in [error["loc"] for error in exc_info.value.errors()]


def test_crane_state_rejects_negative_load_weight() -> None:
    payload = _state_payload()
    payload["load_weight_t"] = -0.01

    with pytest.raises(ValidationError) as exc_info:
        CraneState.model_validate(payload)

    assert ("load_weight_t",) in [error["loc"] for error in exc_info.value.errors()]


def test_control_target_rejects_unknown_task_semantics() -> None:
    with pytest.raises(ValidationError) as exc_info:
        ControlTarget.model_validate(
            {
                "crane_id": "TC_SCHEMA",
                "target_slew_velocity_rad_s": 0.0,
                "target_trolley_velocity_m_s": 0.0,
                "target_hoist_velocity_m_s": 0.0,
                "task_action": "attach",
            }
        )

    assert ("task_action",) in [error["loc"] for error in exc_info.value.errors()]


def test_control_target_preserves_optional_source_command_id() -> None:
    target = ControlTarget(
        crane_id="TC_SCHEMA",
        target_slew_velocity_rad_s=0.1,
        target_trolley_velocity_m_s=0.2,
        target_hoist_velocity_m_s=-0.3,
        source_command_id="cmd-001",
    )

    assert target.source_command_id == "cmd-001"
