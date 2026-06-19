from __future__ import annotations

from backend.app.core.config_resolver import resolve_config
from backend.app.sim.layout_reachability import check_layout_reachability
from backend.app.tests.test_config_schema import load_fixture


def _base_manual_raw() -> dict:
    raw = load_fixture("scenario_valid.yaml")
    raw["layout"]["mode"] = "manual"
    raw["layout"]["num_cranes"] = 1
    raw["cranes"] = [
        {
            "crane_id": "TC_A",
            "model_id": "generic_flat_top_55m",
            "base": [0.0, 0.0, 0.0],
            "mast_height_m": 55.0,
            "theta_init_deg": 0.0,
            "slew": {"mode": "continuous"},
        }
    ]
    raw["site"]["forbidden_zones"] = []
    raw["site"]["material_zones"] = [
        {
            "zone_id": "box_yard",
            "type": "box",
            "center": [20.0, 0.0, 0.0],
            "size": [10.0, 6.0, 2.0],
            "load_types": ["formwork"],
        }
    ]
    raw["site"]["work_zones"] = [
        {
            "zone_id": "box_work",
            "type": "box",
            "center": [20.0, 0.0, 30.0],
            "size": [10.0, 6.0, 2.0],
            "accepted_load_types": ["formwork"],
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


def test_box_zone_report_checks_center_and_four_corners() -> None:
    report = _report(_base_manual_raw())

    points = report.material_zone_reports[0]["representative_points_checked"]
    assert len(points) == 5
    assert [20.0, 0.0, 1.5] in points
    assert [15.0, -3.0, 1.5] in points
    assert [25.0, 3.0, 1.5] in points


def test_zone_inside_trolley_min_radius_is_unreachable() -> None:
    raw = _base_manual_raw()
    raw["site"]["material_zones"][0]["center"] = [0.0, 0.0, 0.0]
    raw["site"]["material_zones"][0]["size"] = [1.0, 1.0, 1.0]

    report = _report(raw)

    assert report.can_generate_tasks is False
    assert "material_zone_unreachable" in report.blocking_reasons


def test_polygon_zone_report_checks_centroid_and_vertices() -> None:
    raw = _base_manual_raw()
    raw["site"]["material_zones"][0] = {
        "zone_id": "poly_yard",
        "type": "polygon",
        "z_range_m": [2.0, 4.0],
        "load_types": ["formwork"],
        "points": [[10.0, 0.0], [20.0, 0.0], [20.0, 10.0], [10.0, 10.0]],
    }

    report = _report(raw)

    points = report.material_zone_reports[0]["representative_points_checked"]
    assert points[0] == [15.0, 5.0, 3.0]
    assert [10.0, 0.0, 3.0] in points
    assert [20.0, 10.0, 3.0] in points


def test_different_cranes_covering_material_and_work_is_not_per_crane_generateable() -> None:
    raw = _base_manual_raw()
    raw["layout"]["num_cranes"] = 2
    raw["cranes"][0]["crane_id"] = "TC_MATERIAL"
    raw["cranes"][0]["base"] = [-60.0, -60.0, 0.0]
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
    raw["site"]["material_zones"][0]["center"] = [-45.0, -60.0, 0.0]
    raw["site"]["material_zones"][0]["size"] = [1.0, 1.0, 1.0]
    raw["site"]["work_zones"][0]["center"] = [45.0, 60.0, 30.0]
    raw["site"]["work_zones"][0]["size"] = [1.0, 1.0, 1.0]

    report = _report(raw)

    assert report.can_generate_tasks is False
    assert report.material_zone_reports[0]["reachable_by_crane_ids"] == ["TC_MATERIAL"]
    assert report.work_zone_reports[0]["reachable_by_crane_ids"] == ["TC_WORK"]
    assert "per_crane_task_pair_unreachable" in report.blocking_reasons


def test_load_capacity_must_cover_material_and_work_side_radii() -> None:
    raw = _base_manual_raw()
    raw["site"]["material_zones"][0]["center"] = [10.0, 0.0, 0.0]
    raw["site"]["material_zones"][0]["size"] = [1.0, 1.0, 1.0]
    raw["site"]["work_zones"][0]["center"] = [45.0, 0.0, 30.0]
    raw["site"]["work_zones"][0]["size"] = [1.0, 1.0, 1.0]
    raw["load_types"]["formwork"]["weight_range_t"] = [1.0, 3.0]

    report = _report(raw)

    assert report.can_generate_tasks is False
    assert "load_type_over_capacity" in report.blocking_reasons
    assert report.load_type_reports[0]["material_reachable_by_crane_ids"] == ["TC_A"]
    assert report.load_type_reports[0]["work_reachable_by_crane_ids"] == []
