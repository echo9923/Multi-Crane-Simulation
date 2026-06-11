from __future__ import annotations

from copy import deepcopy

import pytest

from backend.app.schemas.config import ScenarioConfig
from backend.app.schemas.task import Task, TaskPoint
from backend.app.sim.crane_model import build_crane_model_library
from backend.app.sim.layout import build_crane_configs
from backend.app.sim.task_feasibility import validate_task_feasibility
from backend.app.tests.test_config_schema import load_fixture


def _raw() -> dict:
    raw = load_fixture("scenario_valid.yaml")
    raw["layout"]["mode"] = "manual"
    raw["layout"]["num_cranes"] = 1
    raw["cranes"] = [
        {
            "crane_id": "C1",
            "model_id": "generic_flat_top_55m",
            "base": [0.0, 0.0, 0.0],
            "mast_height_m": 50.0,
            "theta_init_deg": 0.0,
            "slew": {"mode": "continuous"},
        }
    ]
    raw["site"]["material_zones"] = [
        {
            "zone_id": "mat_a",
            "type": "box",
            "center": [20.0, 0.0, 1.0],
            "size": [8.0, 8.0, 2.0],
            "z_range_m": [0.5, 1.5],
            "load_types": ["rebar_bundle"],
        }
    ]
    raw["site"]["work_zones"] = [
        {
            "zone_id": "work_a",
            "type": "box",
            "center": [25.0, 0.0, 30.0],
            "size": [8.0, 8.0, 4.0],
            "z_range_m": [28.0, 32.0],
            "accepted_load_types": ["rebar_bundle"],
        }
    ]
    raw["site"]["forbidden_zones"] = [
        {
            "zone_id": "forbidden_a",
            "type": "box",
            "center": [40.0, 0.0, 1.0],
            "size": [8.0, 8.0, 4.0],
        }
    ]
    return raw


def _scenario_and_crane(raw: dict | None = None):
    scenario = ScenarioConfig.model_validate(raw or _raw())
    library = build_crane_model_library(scenario.crane_models)
    crane = build_crane_configs(scenario.cranes, library, scenario, source="manual")[0]
    return scenario, crane


def _task(**updates) -> Task:
    task = Task(
        task_id="T_C1_001",
        crane_id="C1",
        task_type="easy_task",
        pickup=TaskPoint(
            x=20.0,
            y=0.0,
            z=1.0,
            zone_id="mat_a",
            zone_type="material",
        ),
        dropoff=TaskPoint(
            x=25.0,
            y=0.0,
            z=30.0,
            zone_id="work_a",
            zone_type="work",
        ),
        pickup_zone_id="mat_a",
        dropoff_zone_id="work_a",
        planned_start_s=0.0,
        load_type="rebar_bundle",
        load_weight_t=2.0,
        load_size_m=[6.0, 1.0, 1.0],
        priority="medium",
        deadline_s=180.0,
        generation_seed=1,
        generation_attempt=0,
    )
    return task.model_copy(update=updates)


def test_reachable_task_passes_with_capacity_margins() -> None:
    scenario, crane = _scenario_and_crane()

    report = validate_task_feasibility(_task(), crane, scenario)

    assert report.feasible is True
    assert report.blocking_error_code is None
    assert report.pickup_reachable is True
    assert report.dropoff_reachable is True
    assert report.pickup_capacity_margin_t is not None
    assert report.pickup_capacity_margin_t > 0


def test_pickup_outside_radius_maps_to_task_e_001() -> None:
    scenario, crane = _scenario_and_crane()
    task = _task(
        pickup=TaskPoint(
            x=80.0,
            y=0.0,
            z=1.0,
            zone_id="mat_a",
            zone_type="material",
        )
    )

    report = validate_task_feasibility(task, crane, scenario)

    assert report.feasible is False
    assert report.blocking_error_code == "TASK_E_001"
    assert "pickup_outside_radius" in report.blocking_reasons


def test_dropoff_height_unreachable_maps_to_task_e_001() -> None:
    scenario, crane = _scenario_and_crane()
    task = _task(
        dropoff=TaskPoint(
            x=25.0,
            y=0.0,
            z=-1.0,
            zone_id="work_a",
            zone_type="work",
        )
    )

    report = validate_task_feasibility(task, crane, scenario)

    assert report.blocking_error_code == "TASK_E_001"
    assert "dropoff_height_unreachable" in report.blocking_reasons


def test_boundary_and_forbidden_zone_failures_are_task_e_001() -> None:
    scenario, crane = _scenario_and_crane()
    outside = _task(
        dropoff=TaskPoint(
            x=120.0,
            y=0.0,
            z=30.0,
            zone_id="work_a",
            zone_type="work",
        )
    )
    forbidden = _task(
        pickup=TaskPoint(
            x=40.0,
            y=0.0,
            z=1.0,
            zone_id="mat_a",
            zone_type="material",
        )
    )

    outside_report = validate_task_feasibility(outside, crane, scenario)
    forbidden_report = validate_task_feasibility(forbidden, crane, scenario)

    assert outside_report.blocking_error_code == "TASK_E_001"
    assert "dropoff_outside_site_boundary" in outside_report.blocking_reasons
    assert forbidden_report.blocking_error_code == "TASK_E_001"
    assert "pickup_inside_forbidden_zone" in forbidden_report.blocking_reasons


def test_load_type_support_failures_are_task_e_001() -> None:
    scenario, crane = _scenario_and_crane()
    unknown = _task(load_type="unknown_load")
    pickup_rejects = _task(load_type="formwork")

    unknown_report = validate_task_feasibility(unknown, crane, scenario)
    pickup_report = validate_task_feasibility(pickup_rejects, crane, scenario)

    assert unknown_report.blocking_error_code == "TASK_E_001"
    assert "unknown_load_type" in unknown_report.blocking_reasons
    assert pickup_report.blocking_error_code == "TASK_E_001"
    assert "pickup_zone_rejects_load_type" in pickup_report.blocking_reasons


def test_dropoff_rejects_load_type_is_task_e_001() -> None:
    raw = _raw()
    raw["site"]["material_zones"][0]["load_types"] = ["formwork"]
    raw["site"]["work_zones"][0]["accepted_load_types"] = ["rebar_bundle"]
    scenario, crane = _scenario_and_crane(raw)

    report = validate_task_feasibility(_task(load_type="formwork"), crane, scenario)

    assert report.blocking_error_code == "TASK_E_001"
    assert "dropoff_zone_rejects_load_type" in report.blocking_reasons


def test_capacity_uses_load_chart_not_only_max_load() -> None:
    raw = _raw()
    raw["crane_models"][0]["load_chart_points"] = [
        {"radius_m": 10.0, "capacity_t": 6.0},
        {"radius_m": 20.0, "capacity_t": 4.0},
        {"radius_m": 50.0, "capacity_t": 1.0},
    ]
    scenario, crane = _scenario_and_crane(raw)
    task = _task(load_weight_t=3.8)

    report = validate_task_feasibility(task, crane, scenario)

    assert report.feasible is False
    assert report.blocking_error_code == "TASK_E_002"
    assert "dropoff_over_capacity" in report.blocking_reasons
    assert report.dropoff_capacity_margin_t is not None
    assert report.dropoff_capacity_margin_t < 0


def test_b_precheck_does_not_replace_task_level_reachability() -> None:
    raw = _raw()
    raw["site"]["work_zones"][0]["center"] = [25.0, 0.0, 30.0]
    scenario, crane = _scenario_and_crane(raw)
    task = _task(
        dropoff=TaskPoint(
            x=60.0,
            y=0.0,
            z=30.0,
            zone_id="work_a",
            zone_type="work",
        )
    )

    report = validate_task_feasibility(task, crane, scenario)

    assert report.feasible is False
    assert report.blocking_error_code == "TASK_E_001"
    assert "dropoff_outside_radius" in report.blocking_reasons
