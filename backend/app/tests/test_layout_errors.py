from __future__ import annotations

from backend.app.sim.crane_model import (
    CraneModelLibraryError,
    crane_model_error_to_config_error,
)
from backend.app.sim.layout import LayoutResolutionError, layout_error_to_config_error


def test_crane_model_error_maps_to_lay_e_003() -> None:
    error = CraneModelLibraryError(
        "invalid crane model",
        model_id="bad_model",
        reason="invalid_crane_model",
        field_path="crane_models[0].jib_length_m",
        details={"constraint": "jib_length_m"},
    )

    config_error = crane_model_error_to_config_error(error, source_file="scenario.yaml")

    assert config_error.error_code == "LAY_E_003"
    assert config_error.category == "startup_error"
    assert config_error.field_path == "crane_models[0].jib_length_m"
    assert config_error.source_file == "scenario.yaml"
    assert config_error.details["reason"] == "invalid_crane_model"
    assert config_error.details["model_id"] == "bad_model"


def test_manual_layout_error_maps_to_lay_e_002() -> None:
    error = LayoutResolutionError(
        "crane base is outside site boundary",
        reason="base_out_of_boundary",
        field_path="cranes[0].base",
        details={"crane_id": "TC_A"},
    )

    config_error = layout_error_to_config_error(error, source_file="scenario.yaml")

    assert config_error.error_code == "LAY_E_002"
    assert config_error.category == "startup_error"
    assert config_error.field_path == "cranes[0].base"
    assert config_error.source_file == "scenario.yaml"
    assert config_error.details["reason"] == "base_out_of_boundary"
    assert config_error.details["crane_id"] == "TC_A"
