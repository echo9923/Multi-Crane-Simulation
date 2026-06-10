from __future__ import annotations

from copy import deepcopy

from backend.app.core.config_resolver import resolve_config
from backend.app.sim.layout_reachability import check_layout_reachability
from backend.app.tests.test_config_schema import load_fixture


def _manual_chart_scenario() -> dict:
    raw = load_fixture("scenario_valid.yaml")
    raw["layout"]["mode"] = "manual"
    raw["layout"]["num_cranes"] = 1
    raw["cranes"] = [
        {
            "crane_id": "TC_CHART",
            "model_id": "generic_flat_top_55m",
            "base": [0.0, 0.0, 0.0],
            "mast_height_m": 55.0,
            "theta_init_deg": 0.0,
            "slew": {"mode": "continuous"},
        }
    ]
    raw["site"]["forbidden_zones"] = []
    raw["crane_models"][0]["load_chart_points"] = [
        {"radius_m": 5.0, "capacity_t": 6.0},
        {"radius_m": 20.0, "capacity_t": 2.5},
        {"radius_m": 55.0, "capacity_t": 1.0},
    ]
    raw["site"]["material_zones"] = [
        {
            "zone_id": "near_yard",
            "type": "box",
            "center": [20.0, 0.0, 1.0],
            "size": [1.0, 1.0, 1.0],
            "load_types": ["rebar_bundle"],
        }
    ]
    raw["site"]["work_zones"] = [
        {
            "zone_id": "near_work",
            "type": "box",
            "center": [20.0, 0.0, 30.0],
            "size": [1.0, 1.0, 1.0],
            "accepted_load_types": ["rebar_bundle"],
        }
    ]
    raw["load_types"]["rebar_bundle"]["weight_range_t"] = [1.0, 3.0]
    return raw


def _reachability_report(raw: dict):
    resolved = resolve_config(raw, load_fixture("experiment_valid.yaml"))
    return check_layout_reachability(
        resolved.layout.resolved_cranes,
        raw["site"]["material_zones"],
        raw["site"]["work_zones"],
        raw["load_types"],
        raw["tasks"],
    )


def test_scenario_model_load_chart_points_survive_resolved_snapshot() -> None:
    raw = _manual_chart_scenario()

    resolved = resolve_config(raw, load_fixture("experiment_valid.yaml"))

    model = resolved.layout.model_library_snapshot["generic_flat_top_55m"]
    assert model["source"] == "yaml_override"
    assert model["load_chart_points"] == raw["crane_models"][0]["load_chart_points"]
    assert resolved.layout.resolved_cranes[0]["model"]["load_chart_points"] == raw[
        "crane_models"
    ][0]["load_chart_points"]


def test_reachability_uses_custom_load_chart_points_for_capacity() -> None:
    raw = _manual_chart_scenario()

    report = _reachability_report(raw)

    assert report.can_generate_tasks is False
    assert "load_type_over_capacity" in report.blocking_reasons
    assert report.load_type_reports[0]["min_capacity_margin_t"] < 0


def test_reachability_passes_when_custom_load_chart_has_enough_capacity() -> None:
    raw = _manual_chart_scenario()
    raw = deepcopy(raw)
    raw["crane_models"][0]["load_chart_points"][1]["capacity_t"] = 4.0

    report = _reachability_report(raw)

    assert report.can_generate_tasks is True
    assert report.blocking_reasons == []
