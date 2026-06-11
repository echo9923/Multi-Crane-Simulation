from __future__ import annotations

import math

import pytest
from pydantic import ValidationError

from backend.app.schemas.control import (
    CONTROLLER_SCHEMA_VERSION,
    DEFAULT_HOIST_GEAR_SPEEDS_M_S,
    DEFAULT_SLEW_GEAR_SPEEDS_RAD_S,
    DEFAULT_TROLLEY_GEAR_SPEEDS_M_S,
    AxisControlDiagnostic,
    ControlTarget,
    ControllerConfig,
    ControllerDiagnostic,
)


def test_controller_config_defaults_match_module_i_tables() -> None:
    config = ControllerConfig(controller_hz=20.0)

    assert config.schema_version == CONTROLLER_SCHEMA_VERSION
    assert config.controller_dt_s == pytest.approx(0.05)
    assert config.slew_gear_speeds_rad_s == DEFAULT_SLEW_GEAR_SPEEDS_RAD_S
    assert config.trolley_gear_speeds_m_s == DEFAULT_TROLLEY_GEAR_SPEEDS_M_S
    assert config.hoist_gear_speeds_m_s == DEFAULT_HOIST_GEAR_SPEEDS_M_S
    assert config.slew_gear_speeds_rad_s == {
        0: 0.0,
        1: 0.15,
        2: 0.3,
        3: 0.5,
        4: 0.65,
        5: 0.8,
    }
    assert config.trolley_gear_speeds_m_s == {
        0: 0.0,
        1: 0.08,
        2: 0.15,
        3: 0.3,
        4: 0.4,
        5: 0.5,
    }
    assert config.hoist_gear_speeds_m_s == {
        0: 0.0,
        1: 0.1,
        2: 0.2,
        3: 0.35,
        4: 0.5,
        5: 0.6,
    }


@pytest.mark.parametrize(
    "payload",
    [
        {"controller_hz": 0.0},
        {"controller_hz": math.inf},
        {"controller_hz": math.nan},
        {"controller_hz": 20.0, "slew_gear_speeds_rad_s": {0: 0.0, 1: 0.1}},
        {
            "controller_hz": 20.0,
            "trolley_gear_speeds_m_s": {
                0: 0.01,
                1: 0.08,
                2: 0.15,
                3: 0.3,
                4: 0.4,
                5: 0.5,
            },
        },
        {
            "controller_hz": 20.0,
            "hoist_gear_speeds_m_s": {
                0: 0.0,
                1: 0.1,
                2: 0.2,
                3: 0.15,
                4: 0.5,
                5: 0.6,
            },
        },
    ],
)
def test_controller_config_rejects_invalid_values(payload: dict) -> None:
    with pytest.raises(ValidationError):
        ControllerConfig.model_validate(payload)


def test_controller_diagnostic_serializes_and_forbids_extra_fields() -> None:
    axis = AxisControlDiagnostic(
        axis="slew",
        direction="right",
        gear=3,
        speed_scale=0.5,
        current_velocity=0.1,
        desired_velocity_before_speed_clamp=0.25,
        desired_velocity_after_speed_clamp=0.25,
        target_velocity=0.2,
        speed_clamped=False,
        acceleration_limited=True,
        speed_clamp_delta=0.0,
        acceleration_delta=0.1,
        max_velocity_abs=0.8,
        max_acceleration_abs=0.3,
    )
    diagnostic = ControllerDiagnostic(
        diagnostic_id="CTRL_DIAG_cmd-001",
        crane_id="C1",
        source_command_id="cmd-001",
        mode="normal",
        controller_dt_s=0.05,
        command_time_s=1.0,
        now_s=1.05,
        command_duration_s=1.0,
        command_expired=False,
        deadman_pressed=True,
        emergency_stop_requested=False,
        axes=[axis],
    )

    dumped = diagnostic.model_dump(mode="json")

    assert dumped["schema_version"] == CONTROLLER_SCHEMA_VERSION
    assert dumped["axes"][0]["axis"] == "slew"
    with pytest.raises(ValidationError):
        ControllerDiagnostic.model_validate({**dumped, "unexpected": "nope"})


def test_controller_diagnostic_rejects_nan_and_invalid_mode() -> None:
    valid_axis = {
        "axis": "trolley",
        "direction": "out",
        "gear": 2,
        "speed_scale": 1.0,
        "current_velocity": 0.0,
        "desired_velocity_before_speed_clamp": 0.15,
        "desired_velocity_after_speed_clamp": 0.15,
        "target_velocity": 0.1,
        "max_velocity_abs": 0.5,
        "max_acceleration_abs": 0.4,
    }

    with pytest.raises(ValidationError):
        AxisControlDiagnostic.model_validate({**valid_axis, "target_velocity": math.nan})

    with pytest.raises(ValidationError):
        ControllerDiagnostic(
            diagnostic_id="CTRL_DIAG_cmd-001",
            crane_id="C1",
            source_command_id="cmd-001",
            mode="not_a_mode",
            controller_dt_s=0.05,
            axes=[AxisControlDiagnostic.model_validate(valid_axis)],
        )


def test_control_target_keeps_pure_numeric_contract() -> None:
    forbidden_fields = {"task_id", "task_stage", "reason", "llm_reason"}

    assert forbidden_fields.isdisjoint(ControlTarget.model_fields)
    with pytest.raises(ValidationError):
        ControlTarget(
            crane_id="C1",
            target_slew_velocity_rad_s=0.0,
            target_trolley_velocity_m_s=0.0,
            target_hoist_velocity_m_s=0.0,
            task_id="task-001",
        )
