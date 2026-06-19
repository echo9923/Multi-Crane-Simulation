from __future__ import annotations

from copy import deepcopy

from backend.app.core.config_resolver import resolve_config
from backend.app.sim.layout_reachability import check_layout_reachability
from backend.app.tests.test_config_schema import load_fixture


def _manual_raw() -> dict:
    raw = load_fixture("scenario_valid.yaml")
    raw["layout"]["mode"] = "manual"
    raw["layout"]["num_cranes"] = 1
    raw["cranes"] = [
        {
            "crane_id": "TC_A",
            "model_id": "generic_flat_top_55m",
            "base": [-60.0, -60.0, 0.0],
            "mast_height_m": 55.0,
            "theta_init_deg": 0.0,
            "slew": {"mode": "continuous"},
        }
    ]
    return raw


def _report(raw: dict):
    resolved = resolve_config(raw, load_fixture("experiment_valid.yaml"))
    return check_layout_reachability(
        resolved.layout.resolved_cranes,
        raw["site"]["material_zones"],
        raw["site"]["work_zones"],
        raw["load_types"],
        raw["tasks"],
    )


def test_material_and_work_zones_can_be_reachable() -> None:
    raw = _manual_raw()
    raw["site"]["work_zones"][0]["center"] = [-45.0, -45.0, 30.0]
    raw["site"]["work_zones"][0]["z_range_m"] = [28.0, 32.0]

    report = _report(raw)

    assert report.can_generate_tasks is True
    assert report.material_zone_reports[0]["reachable_by_crane_ids"] == ["TC_A"]
    assert report.work_zone_reports[0]["reachable_by_crane_ids"] == ["TC_A"]


def test_zone_outside_all_work_radius_is_blocking() -> None:
    raw = _manual_raw()
    raw["site"]["material_zones"][0]["points"] = [[80, 80], [90, 80], [90, 90], [80, 90]]

    report = _report(raw)

    assert report.can_generate_tasks is False
    assert "material_zone_unreachable" in report.blocking_reasons


def test_work_zone_above_hook_height_is_blocking() -> None:
    raw = _manual_raw()
    raw["site"]["work_zones"][0]["center"] = [-45.0, -45.0, 79.0]
    raw["site"]["work_zones"][0]["z_range_m"] = [78.0, 80.0]

    report = _report(raw)

    assert report.can_generate_tasks is False
    assert "work_zone_unreachable" in report.blocking_reasons


def test_overweight_load_type_is_blocking() -> None:
    raw = _manual_raw()
    raw["site"]["work_zones"][0]["center"] = [-45.0, -45.0, 30.0]
    raw["site"]["work_zones"][0]["accepted_load_types"] = ["steel_beam"]
    raw["load_types"]["steel_beam"]["weight_range_t"] = [12.0, 15.0]

    report = _report(raw)

    assert report.can_generate_tasks is False
    assert "load_type_over_capacity" in report.blocking_reasons


def test_capacity_check_uses_representative_point_radius() -> None:
    raw = _manual_raw()
    raw["site"]["material_zones"][0]["type"] = "box"
    raw["site"]["material_zones"][0]["center"] = [-25.0, -60.0, 1.0]
    raw["site"]["material_zones"][0]["size"] = [1.0, 1.0, 1.0]
    raw["site"]["material_zones"][0].pop("points", None)
    raw["site"]["material_zones"][0]["load_types"] = ["steel_beam"]
    raw["site"]["work_zones"][0]["center"] = [-25.0, -60.0, 30.0]
    raw["site"]["work_zones"][0]["size"] = [1.0, 1.0, 1.0]
    raw["site"]["work_zones"][0]["accepted_load_types"] = ["steel_beam"]
    raw["load_types"]["steel_beam"]["weight_range_t"] = [2.0, 5.0]

    report = _report(raw)

    assert report.can_generate_tasks is False
    assert "load_type_over_capacity" in report.blocking_reasons


def test_missing_load_type_reference_is_reported() -> None:
    raw = _manual_raw()
    raw["site"]["material_zones"][0]["load_types"] = ["missing_type"]

    report = _report(raw)

    assert report.can_generate_tasks is False
    assert "unknown_load_type" in report.blocking_reasons


def test_material_and_work_load_type_mismatch_is_reported() -> None:
    raw = _manual_raw()
    raw["site"]["material_zones"][0]["load_types"] = ["steel_beam"]
    raw["site"]["work_zones"][0]["accepted_load_types"] = ["formwork"]

    report = _report(raw)

    assert report.can_generate_tasks is False
    assert "no_material_work_load_type_intersection" in report.blocking_reasons


def test_multi_crane_report_lists_reachable_crane_ids() -> None:
    raw = _manual_raw()
    raw["layout"]["num_cranes"] = 2
    raw["cranes"].append(
        {
            "crane_id": "TC_B",
            "model_id": "generic_flat_top_55m",
            "base": [45.0, 45.0, 0.0],
            "mast_height_m": 55.0,
            "theta_init_deg": 0.0,
            "slew": {"mode": "continuous"},
        }
    )
    raw["site"]["work_zones"][0]["center"] = [45.0, 45.0, 30.0]

    report = _report(raw)

    assert "TC_A" in report.material_zone_reports[0]["reachable_by_crane_ids"]
    assert "TC_B" in report.work_zone_reports[0]["reachable_by_crane_ids"]


def test_per_crane_queue_requires_each_crane_to_have_task_pair() -> None:
    raw = _manual_raw()
    raw["layout"]["num_cranes"] = 2
    raw["cranes"][0]["crane_id"] = "TC_MATERIAL"
    raw["site"]["material_zones"][0]["type"] = "box"
    raw["site"]["material_zones"][0]["center"] = [-45.0, -60.0, 1.0]
    raw["site"]["material_zones"][0]["size"] = [1.0, 1.0, 1.0]
    raw["site"]["material_zones"][0].pop("points", None)
    raw["site"]["work_zones"][0]["center"] = [45.0, 60.0, 30.0]
    raw["site"]["work_zones"][0]["size"] = [1.0, 1.0, 1.0]
    raw["cranes"].append(
        {
            "crane_id": "TC_WORK",
            "model_id": "generic_flat_top_55m",
            "base": [60.0, 60.0, 0.0],
            "mast_height_m": 55.0,
            "theta_init_deg": 0.0,
            "slew": {"mode": "continuous"},
        }
    )

    report = _report(raw)

    assert report.can_generate_tasks is False
    assert "per_crane_task_pair_unreachable" in report.blocking_reasons


def test_manual_precheck_report_does_not_create_task_fields() -> None:
    report = _report(_manual_raw())
    payload = report.model_dump(mode="json")

    assert "TASK_E_001" not in str(payload)
    assert "TASK_E_002" not in str(payload)
    assert "task_id" not in str(payload)
    assert "task_stage" not in str(payload)
