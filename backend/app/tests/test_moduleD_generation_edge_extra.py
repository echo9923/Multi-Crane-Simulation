from __future__ import annotations

from copy import deepcopy

import pytest

from backend.app.schemas.config import ScenarioConfig
from backend.app.sim.crane_model import build_crane_model_library
from backend.app.sim.layout import build_crane_configs
from backend.app.sim.task_generation import TaskGenerationError, generate_task_queues
from backend.app.tests.test_config_schema import load_fixture


def _raw() -> dict:
    raw = load_fixture("scenario_valid.yaml")
    raw["layout"]["mode"] = "manual"
    raw["layout"]["num_cranes"] = 2
    raw["cranes"] = [
        {
            "crane_id": "C_B",
            "model_id": "generic_flat_top_55m",
            "base": [20.0, -20.0, 0.0],
            "mast_height_m": 52.0,
            "theta_init_deg": 90.0,
            "slew": {"mode": "continuous"},
        },
        {
            "crane_id": "C_A",
            "model_id": "generic_flat_top_55m",
            "base": [-30.0, -20.0, 0.0],
            "mast_height_m": 50.0,
            "theta_init_deg": 0.0,
            "slew": {"mode": "continuous"},
        },
    ]
    raw["site"]["material_zones"] = [
        {
            "zone_id": "mat_a",
            "type": "box",
            "center": [-25.0, -10.0, 1.0],
            "size": [10.0, 10.0, 2.0],
            "z_range_m": [0.5, 1.5],
            "load_types": ["rebar_bundle"],
        }
    ]
    raw["site"]["work_zones"] = [
        {
            "zone_id": "work_a",
            "type": "box",
            "center": [15.0, 5.0, 28.0],
            "size": [10.0, 10.0, 4.0],
            "z_range_m": [26.0, 30.0],
            "accepted_load_types": ["rebar_bundle"],
        }
    ]
    raw["tasks"]["num_tasks_per_crane"] = 2
    raw["tasks"]["task_type_distribution"] = {
        "easy_task": 1.0,
        "overlap_task": 0.0,
        "stress_task": 0.0,
    }
    return raw


def _scenario_and_cranes(raw: dict | None = None):
    scenario = ScenarioConfig.model_validate(raw or _raw())
    library = build_crane_model_library(scenario.crane_models)
    cranes = build_crane_configs(scenario.cranes, library, scenario, source="manual")
    return scenario, cranes


def test_generation_sorts_cranes_for_stable_queue_order() -> None:
    scenario, cranes = _scenario_and_cranes()

    result = generate_task_queues(scenario, list(reversed(cranes)), seed=100)

    assert [queue.crane_id for queue in result.queues] == ["C_A", "C_B"]
    assert [task.task_id for task in result.queues[0].tasks] == [
        "T_C_A_001",
        "T_C_A_002",
    ]


def test_generation_fails_when_zone_pair_has_no_supported_load_type() -> None:
    raw = _raw()
    raw["site"]["material_zones"][0]["load_types"] = ["steel_beam"]
    raw["site"]["work_zones"][0]["accepted_load_types"] = ["formwork"]
    scenario, cranes = _scenario_and_cranes(raw)

    with pytest.raises(TaskGenerationError) as exc_info:
        generate_task_queues(scenario, cranes, seed=100)

    assert exc_info.value.error_code == "TASK_E_001"
    assert exc_info.value.reason == "no_supported_load_type"


def test_polygon_zone_without_sampleable_area_reports_sampling_failure() -> None:
    raw = _raw()
    raw["layout"]["max_sampling_attempts"] = 3
    raw["site"]["material_zones"][0] = {
        "zone_id": "bad_poly",
        "type": "polygon",
        "z_range_m": [0.5, 1.5],
        "load_types": ["rebar_bundle"],
        "points": [[-20.0, -20.0], [-20.0, -20.0], [-20.0, -20.0]],
    }
    scenario, cranes = _scenario_and_cranes(raw)

    with pytest.raises(TaskGenerationError) as exc_info:
        generate_task_queues(scenario, cranes, seed=100)

    assert exc_info.value.error_code == "TASK_E_001"
    assert exc_info.value.reason == "point_sampling_failed"


def test_manual_template_with_no_feasible_crane_returns_stable_error() -> None:
    raw = _raw()
    raw["tasks"]["generation_mode"] = "manual"
    raw["tasks"]["manual_tasks"] = [
        {
            "task_id": "manual_far",
            "task_type": "easy_task",
            "pickup_zone_id": "mat_far",
            "dropoff_zone_id": "work_a",
            "load_type": "rebar_bundle",
            "priority": "medium",
        }
    ]
    raw["site"]["material_zones"].append(
        {
            "zone_id": "mat_far",
            "type": "box",
            "center": [95.0, 95.0, 1.0],
            "size": [4.0, 4.0, 2.0],
            "z_range_m": [0.5, 1.5],
            "load_types": ["rebar_bundle"],
        }
    )
    scenario, cranes = _scenario_and_cranes(raw)

    with pytest.raises(TaskGenerationError) as exc_info:
        generate_task_queues(scenario, cranes, seed=100)

    assert exc_info.value.error_code == "TASK_E_001"
    assert exc_info.value.reason == "manual_task_unassignable"
