from __future__ import annotations

import math

import pytest

from backend.app.schemas.config import ScenarioConfig
from backend.app.sim.crane_model import build_crane_model_library
from backend.app.sim.layout import build_crane_configs
from backend.app.sim.physics import (
    compute_hook_position,
    compute_tip_position,
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
            "crane_id": "TC_GEOM",
            "model_id": "generic_flat_top_55m",
            "base": [10.0, 20.0, 0.0],
            "mast_height_m": 50.0,
            "theta_init_deg": 0.0,
            "slew": {"mode": "continuous"},
        }
    ]
    scenario = ScenarioConfig.model_validate(raw)
    model_library = build_crane_model_library(scenario.crane_models)
    return build_crane_configs(scenario.cranes, model_library, scenario, source="manual")[0]


def test_compute_tip_and_hook_positions_for_zero_angle() -> None:
    crane = _crane_config()

    tip = compute_tip_position(crane, 0.0)
    hook = compute_hook_position(crane, 0.0, trolley_r_m=25.0, hook_h_m=30.0)

    assert tip == pytest.approx([65.0, 20.0, 50.0], abs=1e-6)
    assert hook == pytest.approx([35.0, 20.0, 30.0], abs=1e-6)


def test_compute_tip_and_hook_positions_for_half_pi_angle() -> None:
    crane = _crane_config()

    tip = compute_tip_position(crane, math.pi / 2.0)
    hook = compute_hook_position(
        crane,
        math.pi / 2.0,
        trolley_r_m=25.0,
        hook_h_m=30.0,
    )

    assert tip == pytest.approx([10.0, 75.0, 50.0], abs=1e-6)
    assert hook == pytest.approx([10.0, 45.0, 30.0], abs=1e-6)


def test_recompute_state_geometry_refreshes_derived_fields_without_changing_motion() -> None:
    crane = _crane_config()
    state = initialize_crane_state(crane).model_copy(
        update={
            "theta_rad": math.pi / 2.0,
            "theta_sin": -999.0,
            "theta_cos": -999.0,
            "trolley_r_m": 25.0,
            "hook_h_m": 30.0,
            "tip_position": [0.0, 0.0, 0.0],
            "hook_position": [0.0, 0.0, 0.0],
            "cable_length_m": 0.0,
            "load_attached": True,
        }
    )

    recomputed = recompute_state_geometry(crane, state)

    assert recomputed.theta_rad == pytest.approx(math.pi / 2.0)
    assert recomputed.trolley_r_m == pytest.approx(25.0)
    assert recomputed.hook_h_m == pytest.approx(30.0)
    assert recomputed.theta_sin == pytest.approx(1.0, abs=1e-6)
    assert recomputed.theta_cos == pytest.approx(0.0, abs=1e-6)
    assert recomputed.root_position == pytest.approx(crane.root, abs=1e-6)
    assert recomputed.tip_position == pytest.approx([10.0, 75.0, 50.0], abs=1e-6)
    assert recomputed.hook_position == pytest.approx([10.0, 45.0, 30.0], abs=1e-6)
    assert recomputed.cable_length_m == pytest.approx(20.0, abs=1e-6)
    assert recomputed.load_position == pytest.approx(recomputed.hook_position, abs=1e-6)


def test_recompute_state_geometry_keeps_load_position_null_when_unattached() -> None:
    crane = _crane_config()
    state = initialize_crane_state(crane).model_copy(
        update={
            "load_attached": False,
            "load_position": [1.0, 2.0, 3.0],
        }
    )

    recomputed = recompute_state_geometry(crane, state)

    assert recomputed.load_position is None
