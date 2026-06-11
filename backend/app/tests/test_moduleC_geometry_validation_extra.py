from __future__ import annotations

import math

import pytest

from backend.app.schemas.config import ScenarioConfig
from backend.app.sim.crane_model import build_crane_model_library
from backend.app.sim.layout import build_crane_configs
from backend.app.sim.physics import (
    PhysicsStateError,
    initialize_crane_state,
    recompute_state_geometry,
    validate_crane_state,
)
from backend.app.tests.test_config_schema import load_fixture


def _crane_config():
    raw = load_fixture("scenario_valid.yaml")
    raw["layout"]["mode"] = "manual"
    raw["layout"]["num_cranes"] = 1
    raw["cranes"] = [
        {
            "crane_id": "TC_GEOM_EXTRA",
            "model_id": "generic_flat_top_55m",
            "base": [12.0, -8.0, 0.0],
            "mast_height_m": 52.0,
            "theta_init_deg": 0.0,
            "slew": {"mode": "continuous"},
        }
    ]
    scenario = ScenarioConfig.model_validate(raw)
    model_library = build_crane_model_library(scenario.crane_models)
    return build_crane_configs(scenario.cranes, model_library, scenario, source="manual")[0]


def test_validate_crane_state_rejects_non_finite_nested_hook_coordinate() -> None:
    crane = _crane_config()
    state = initialize_crane_state(crane).model_copy(
        update={"hook_position": [1.0, math.inf, 2.0]}
    )

    with pytest.raises(PhysicsStateError) as exc_info:
        validate_crane_state(crane, state)

    assert exc_info.value.error_code == "PHYS_E_001"
    assert exc_info.value.field_path == "hook_position[1]"


@pytest.mark.parametrize(
    "field,update,expected_path",
    [
        ("root_position", {"root_position": [99.0, -8.0, 52.0]}, "root_position"),
        ("tip_position", {"tip_position": [0.0, 0.0, 0.0]}, "tip_position"),
        ("hook_position", {"hook_position": [0.0, 0.0, 0.0]}, "hook_position"),
    ],
)
def test_validate_crane_state_rejects_stale_geometry_fields(
    field: str,
    update: dict,
    expected_path: str,
) -> None:
    crane = _crane_config()
    state = initialize_crane_state(crane).model_copy(update=update)

    with pytest.raises(PhysicsStateError) as exc_info:
        validate_crane_state(crane, state)

    assert exc_info.value.error_code == "PHYS_E_002", field
    assert exc_info.value.field_path == expected_path
    assert exc_info.value.details["reason"] == "geometry_inconsistent"


def test_recompute_state_geometry_overwrites_stale_geometry_and_preserves_task_fields() -> None:
    crane = _crane_config()
    state = initialize_crane_state(crane).model_copy(
        update={
            "theta_rad": math.pi,
            "trolley_r_m": 20.0,
            "hook_h_m": 40.0,
            "tip_position": [999.0, 999.0, 999.0],
            "hook_position": [999.0, 999.0, 999.0],
            "load_attached": True,
            "load_type": "steel",
            "load_weight_t": 1.5,
            "task_id": "T-001",
            "task_stage": "move_to_dropoff",
        }
    )

    recomputed = recompute_state_geometry(crane, state)

    assert recomputed.tip_position == pytest.approx([-43.0, -8.0, 52.0])
    assert recomputed.hook_position == pytest.approx([-8.0, -8.0, 40.0])
    assert recomputed.load_position == pytest.approx(recomputed.hook_position)
    assert recomputed.load_type == "steel"
    assert recomputed.load_weight_t == 1.5
    assert recomputed.task_id == "T-001"
    assert recomputed.task_stage == "move_to_dropoff"
    validate_crane_state(crane, recomputed)
