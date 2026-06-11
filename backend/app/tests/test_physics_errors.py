from __future__ import annotations

import math

import pytest

from backend.app.schemas.config import ScenarioConfig
from backend.app.schemas.control import ControlTarget
from backend.app.sim.crane_model import build_crane_model_library
from backend.app.sim.layout import build_crane_configs
from backend.app.sim.physics import (
    PhysicsStateError,
    initialize_crane_state,
    recompute_state_geometry,
    step_crane_state,
    validate_crane_state,
)
from backend.app.tests.test_config_schema import load_fixture


def _crane_config():
    raw = load_fixture("scenario_valid.yaml")
    raw["layout"]["mode"] = "manual"
    raw["layout"]["num_cranes"] = 1
    raw["cranes"] = [
        {
            "crane_id": "TC_ERR",
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


def _neutral_target(crane_id: str = "TC_ERR") -> ControlTarget:
    return ControlTarget(
        crane_id=crane_id,
        target_slew_velocity_rad_s=0.0,
        target_trolley_velocity_m_s=0.0,
        target_hoist_velocity_m_s=0.0,
    )


def test_validate_crane_state_maps_nan_to_phys_e_001() -> None:
    crane = _crane_config()
    state = initialize_crane_state(crane).model_copy(update={"theta_rad": math.nan})

    with pytest.raises(PhysicsStateError) as exc_info:
        validate_crane_state(crane, state)

    error = exc_info.value
    assert error.error_code == "PHYS_E_001"
    assert error.category == "episode_failed"
    assert error.episode_status == "failed_invalid_state"
    assert error.crane_id == "TC_ERR"
    assert error.field_path == "theta_rad"
    assert math.isnan(error.details["value"])


def test_step_crane_state_rejects_non_positive_dt_as_phys_e_002() -> None:
    crane = _crane_config()
    state = initialize_crane_state(crane)

    with pytest.raises(PhysicsStateError) as exc_info:
        step_crane_state(crane, state, _neutral_target(), dt=0.0)

    assert exc_info.value.error_code == "PHYS_E_002"
    assert exc_info.value.field_path == "dt"
    assert exc_info.value.details["reason"] == "non_positive_dt"


def test_validate_crane_state_rejects_unrecoverable_trolley_range() -> None:
    crane = _crane_config()
    state = initialize_crane_state(crane).model_copy(
        update={"trolley_r_m": crane.trolley_r_max_m + 0.5}
    )

    with pytest.raises(PhysicsStateError) as exc_info:
        validate_crane_state(crane, state)

    assert exc_info.value.error_code == "PHYS_E_002"
    assert exc_info.value.field_path == "trolley_r_m"
    assert exc_info.value.details["limit"] == [
        crane.trolley_r_min_m,
        crane.trolley_r_max_m,
    ]


def test_validate_crane_state_rejects_hook_above_root() -> None:
    crane = _crane_config()
    state = initialize_crane_state(crane).model_copy(
        update={"hook_h_m": crane.root[2] + 0.01}
    )

    with pytest.raises(PhysicsStateError) as exc_info:
        validate_crane_state(crane, state)

    assert exc_info.value.error_code == "PHYS_E_002"
    assert exc_info.value.field_path == "hook_h_m"
    assert exc_info.value.details["reason"] == "hook_above_root"


def test_validate_crane_state_rejects_inconsistent_trig_cache() -> None:
    crane = _crane_config()
    state = initialize_crane_state(crane).model_copy(update={"theta_sin": 1.0})

    with pytest.raises(PhysicsStateError) as exc_info:
        validate_crane_state(crane, state)

    assert exc_info.value.error_code == "PHYS_E_002"
    assert exc_info.value.field_path == "theta_sin"
    assert exc_info.value.details["reason"] == "theta_trig_inconsistent"


def test_step_crane_state_reports_abnormal_jump() -> None:
    crane = _crane_config()
    state = recompute_state_geometry(
        crane,
        initialize_crane_state(crane).model_copy(
            update={"trolley_r_m": crane.trolley_r_max_m - 0.01}
        ),
    )
    target = ControlTarget(
        crane_id="TC_ERR",
        target_slew_velocity_rad_s=0.0,
        target_trolley_velocity_m_s=crane.model.trolley_speed_max_m_s,
        target_hoist_velocity_m_s=0.0,
    )

    with pytest.raises(PhysicsStateError) as exc_info:
        step_crane_state(crane, state, target, dt=1000.0)

    assert exc_info.value.error_code == "PHYS_E_002"
    assert exc_info.value.field_path == "trolley_r_m"
    assert exc_info.value.details["reason"] == "abnormal_state_jump"
