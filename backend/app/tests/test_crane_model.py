from __future__ import annotations

import math
from copy import deepcopy

import pytest

from backend.app.schemas.config import ScenarioConfig
from backend.app.sim.crane_model import (
    CraneModelLibraryError,
    build_crane_model_library,
)
from backend.app.tests.test_config_schema import load_fixture


def _scenario_config() -> ScenarioConfig:
    return ScenarioConfig.model_validate(load_fixture("scenario_valid.yaml"))


def test_builtin_generic_flat_top_55m_exists() -> None:
    library = build_crane_model_library([])

    model = library["generic_flat_top_55m"]

    assert model.model_id == "generic_flat_top_55m"
    assert model.source == "builtin"
    assert model.jib_length_m == 55


def test_yaml_override_replaces_builtin_model() -> None:
    scenario = _scenario_config()
    override = scenario.crane_models[0].model_copy(
        update={"jib_length_m": 60.0, "trolley_r_max_m": 55.0}
    )

    library = build_crane_model_library([override])

    model = library["generic_flat_top_55m"]
    assert model.source == "yaml_override"
    assert model.jib_length_m == 60.0
    assert model.trolley_r_max_m == 55.0


def test_yaml_new_model_is_available_by_id() -> None:
    scenario = _scenario_config()
    new_model = scenario.crane_models[0].model_copy(update={"model_id": "site_special_65m"})

    library = build_crane_model_library([new_model])

    assert library["site_special_65m"].source == "yaml_new"


def test_duplicate_yaml_model_id_fails() -> None:
    scenario = _scenario_config()

    with pytest.raises(CraneModelLibraryError) as exc_info:
        build_crane_model_library([scenario.crane_models[0], scenario.crane_models[0]])

    assert exc_info.value.reason == "duplicate_model_id"
    assert exc_info.value.model_id == "generic_flat_top_55m"


def test_speed_fields_convert_from_deg_to_rad() -> None:
    scenario = _scenario_config()

    model = build_crane_model_library(scenario.crane_models)["generic_flat_top_55m"]

    assert model.slew_speed_max_rad_s == pytest.approx(math.radians(0.8))
    assert model.slew_acc_max_rad_s2 == pytest.approx(math.radians(0.3))
    assert model.trolley_acc_max_m_s2 == pytest.approx(0.4)
    assert model.hoist_acc_max_m_s2 == pytest.approx(0.5)


def test_capacity_at_radius_uses_chart_and_moment_limits() -> None:
    model = build_crane_model_library(_scenario_config().crane_models)[
        "generic_flat_top_55m"
    ]

    assert model.capacity_at_radius_t(10) == pytest.approx(min(6.0, 90.0 / 10.0))
    assert model.capacity_at_radius_t(15) == pytest.approx(min(6.0, 90.0 / 15.0))
    assert model.capacity_at_radius_t(55) <= model.tip_load_t
    assert model.capacity_at_radius_t(56) == 0.0


def test_load_allowed_and_moment_helpers_use_radius_capacity() -> None:
    model = build_crane_model_library(_scenario_config().crane_models)[
        "generic_flat_top_55m"
    ]

    assert model.moment_at_radius_t_m(3.0, 25.0) == pytest.approx(75.0)
    assert model.is_load_allowed(2.0, 20.0) is (
        2.0 <= model.capacity_at_radius_t(20.0)
    )


@pytest.mark.parametrize(
    "update,reason",
    [
        ({"max_load_radius_m": 56.0}, "max_load_radius_exceeds_jib_length"),
        ({"trolley_r_max_m": 56.0}, "trolley_r_max_exceeds_jib_length"),
        ({"tip_load_t": 7.0}, "tip_load_exceeds_max_load"),
        ({"mast_height_range_m": [65.0, 40.0]}, "invalid_mast_height_range"),
    ],
)
def test_invalid_model_constraints_fail(update: dict, reason: str) -> None:
    raw = load_fixture("scenario_valid.yaml")
    raw_model = deepcopy(raw["crane_models"][0])
    raw_model.update(update)

    with pytest.raises(CraneModelLibraryError) as exc_info:
        build_crane_model_library([raw_model])

    assert exc_info.value.reason == reason


def test_load_chart_points_are_validated() -> None:
    raw = load_fixture("scenario_valid.yaml")
    raw_model = deepcopy(raw["crane_models"][0])
    raw_model["load_chart_points"] = [
        {"radius_m": 20.0, "capacity_t": 4.0},
        {"radius_m": 10.0, "capacity_t": 5.0},
    ]

    with pytest.raises(CraneModelLibraryError) as exc_info:
        build_crane_model_library([raw_model])

    assert exc_info.value.reason == "invalid_load_chart_points"
