from __future__ import annotations

from copy import deepcopy

import pytest

from backend.app.schemas.config import ScenarioConfig
from backend.app.sim.crane_model import build_crane_model_library
from backend.app.sim.layout import LayoutResolutionError, validate_manual_layout
from backend.app.tests.test_config_schema import load_fixture


def _manual_scenario(*, cranes: list[dict] | None = None) -> ScenarioConfig:
    raw = load_fixture("scenario_valid.yaml")
    raw["layout"]["mode"] = "manual"
    raw["layout"]["num_cranes"] = len(cranes) if cranes is not None else 2
    raw["cranes"] = cranes or [
        {
            "crane_id": "TC_A",
            "model_id": "generic_flat_top_55m",
            "base": [-60.0, -60.0, 0.0],
            "mast_height_m": 45.0,
            "theta_init_deg": 20.0,
            "slew": {"mode": "continuous"},
        },
        {
            "crane_id": "TC_B",
            "model_id": "generic_flat_top_55m",
            "base": [45.0, 45.0, 0.0],
            "mast_height_m": 50.0,
            "theta_init_deg": 90.0,
            "slew": {"mode": "continuous"},
        },
    ]
    return ScenarioConfig.model_validate(raw)


def _validate(scenario: ScenarioConfig):
    library = build_crane_model_library(scenario.crane_models)
    return validate_manual_layout(scenario, library)


def test_valid_manual_layout_passes_for_arbitrary_crane_ids() -> None:
    result = _validate(_manual_scenario())

    assert [crane.crane_id for crane in result.cranes] == ["TC_A", "TC_B"]
    assert result.diagnostics.warnings == []


def test_manual_count_mismatch_fails() -> None:
    scenario = _manual_scenario()
    scenario = scenario.model_copy(
        update={"layout": scenario.layout.model_copy(update={"num_cranes": 3})}
    )

    with pytest.raises(LayoutResolutionError) as exc_info:
        _validate(scenario)

    assert exc_info.value.reason == "manual_count_mismatch"
    assert exc_info.value.field_path == "cranes"


def test_duplicate_crane_id_fails() -> None:
    raw_cranes = [crane.model_dump(mode="json") for crane in _manual_scenario().cranes]
    raw_cranes[1]["crane_id"] = raw_cranes[0]["crane_id"]

    with pytest.raises(LayoutResolutionError) as exc_info:
        _validate(_manual_scenario(cranes=raw_cranes))

    assert exc_info.value.reason == "duplicate_crane_id"


def test_unknown_model_id_fails() -> None:
    raw_cranes = [crane.model_dump(mode="json") for crane in _manual_scenario().cranes]
    raw_cranes[0]["model_id"] = "missing_model"

    with pytest.raises(LayoutResolutionError) as exc_info:
        _validate(_manual_scenario(cranes=raw_cranes))

    assert exc_info.value.reason == "unknown_model_id"
    assert exc_info.value.field_path == "cranes[0].model_id"


@pytest.mark.parametrize(
    "base",
    [
        [-101.0, -60.0, 0.0],
        [-60.0, -101.0, 0.0],
        [-60.0, -60.0, -1.0],
    ],
)
def test_base_out_of_boundary_fails(base: list[float]) -> None:
    raw_cranes = [crane.model_dump(mode="json") for crane in _manual_scenario().cranes]
    raw_cranes[0]["base"] = base

    with pytest.raises(LayoutResolutionError) as exc_info:
        _validate(_manual_scenario(cranes=raw_cranes))

    assert exc_info.value.reason == "base_out_of_boundary"
    assert exc_info.value.field_path == "cranes[0].base"


def test_base_inside_box_forbidden_zone_fails() -> None:
    raw_cranes = [crane.model_dump(mode="json") for crane in _manual_scenario().cranes]
    raw_cranes[0]["base"] = [0.0, 0.0, 0.0]

    with pytest.raises(LayoutResolutionError) as exc_info:
        _validate(_manual_scenario(cranes=raw_cranes))

    assert exc_info.value.reason == "base_inside_forbidden_zone"
    assert exc_info.value.details["zone_id"] == "building_core"


@pytest.mark.parametrize("mast_height", [39.0, 66.0])
def test_mast_height_out_of_model_range_fails(mast_height: float) -> None:
    raw_cranes = [crane.model_dump(mode="json") for crane in _manual_scenario().cranes]
    raw_cranes[0]["mast_height_m"] = mast_height

    with pytest.raises(LayoutResolutionError) as exc_info:
        _validate(_manual_scenario(cranes=raw_cranes))

    assert exc_info.value.reason == "mast_height_out_of_model_range"


def test_root_z_above_boundary_fails() -> None:
    raw = load_fixture("scenario_valid.yaml")
    raw["site"]["boundary"]["z_max"] = 42.0
    raw["layout"]["mode"] = "manual"
    raw["layout"]["num_cranes"] = 1
    raw["cranes"] = [
        {
            "crane_id": "TC_A",
            "model_id": "generic_flat_top_55m",
            "base": [-60.0, -60.0, 0.0],
            "mast_height_m": 45.0,
            "theta_init_deg": 0.0,
            "slew": {"mode": "continuous"},
        }
    ]
    scenario = ScenarioConfig.model_validate(raw)

    with pytest.raises(LayoutResolutionError) as exc_info:
        _validate(scenario)

    assert exc_info.value.reason == "root_z_out_of_boundary"


def test_root_distance_too_small_fails() -> None:
    raw_cranes = [crane.model_dump(mode="json") for crane in _manual_scenario().cranes]
    raw_cranes[1]["base"] = [-55.0, -60.0, 0.0]

    with pytest.raises(LayoutResolutionError) as exc_info:
        _validate(_manual_scenario(cranes=raw_cranes))

    assert exc_info.value.reason == "root_distance_too_small"
    assert exc_info.value.details["min_base_distance_m"] == 8.0


def test_limited_slew_without_theta_limit_fails() -> None:
    raw_cranes = [crane.model_dump(mode="json") for crane in _manual_scenario().cranes]
    raw_cranes[0]["slew"] = {"mode": "limited"}

    with pytest.raises(LayoutResolutionError) as exc_info:
        _validate(_manual_scenario(cranes=raw_cranes))

    assert exc_info.value.reason == "limited_slew_missing_theta_limit"
