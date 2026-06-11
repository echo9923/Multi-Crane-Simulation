from __future__ import annotations

import math
from copy import deepcopy

import pytest

from backend.app.schemas.config import ScenarioConfig
from backend.app.schemas.task import TaskStatus
from backend.app.sim.crane_model import build_crane_model_library
from backend.app.sim.layout import build_crane_configs
from backend.app.sim.layout_geometry import point_in_boundary, point_in_zone
from backend.app.sim.task_generation import TaskGenerationError, generate_task_queues
from backend.app.tests.test_config_schema import load_fixture


def _scenario_raw() -> dict:
    raw = load_fixture("scenario_valid.yaml")
    raw["layout"]["mode"] = "manual"
    raw["layout"]["num_cranes"] = 3
    raw["cranes"] = [
        {
            "crane_id": "C1",
            "model_id": "generic_flat_top_55m",
            "base": [-30.0, -20.0, 0.0],
            "mast_height_m": 50.0,
            "theta_init_deg": 0.0,
            "slew": {"mode": "continuous"},
        },
        {
            "crane_id": "C2",
            "model_id": "generic_flat_top_55m",
            "base": [20.0, -20.0, 0.0],
            "mast_height_m": 52.0,
            "theta_init_deg": 90.0,
            "slew": {"mode": "continuous"},
        },
        {
            "crane_id": "C3",
            "model_id": "generic_flat_top_55m",
            "base": [-5.0, 25.0, 0.0],
            "mast_height_m": 54.0,
            "theta_init_deg": 180.0,
            "slew": {"mode": "continuous"},
        },
    ]
    raw["site"]["material_zones"] = [
        {
            "zone_id": "mat_west",
            "type": "box",
            "center": [-35.0, -10.0, 1.0],
            "size": [16.0, 14.0, 2.0],
            "z_range_m": [0.5, 1.5],
            "load_types": ["rebar_bundle", "formwork"],
        },
        {
            "zone_id": "mat_overlap",
            "type": "box",
            "center": [0.0, -10.0, 1.0],
            "size": [12.0, 12.0, 2.0],
            "z_range_m": [0.5, 1.5],
            "load_types": ["rebar_bundle"],
        },
    ]
    raw["site"]["work_zones"] = [
        {
            "zone_id": "work_east",
            "type": "box",
            "center": [25.0, 10.0, 28.0],
            "size": [14.0, 14.0, 4.0],
            "z_range_m": [26.0, 30.0],
            "accepted_load_types": ["rebar_bundle", "formwork"],
        },
        {
            "zone_id": "work_overlap",
            "type": "box",
            "center": [0.0, 10.0, 26.0],
            "size": [12.0, 12.0, 4.0],
            "z_range_m": [24.0, 28.0],
            "accepted_load_types": ["rebar_bundle"],
        },
    ]
    raw["tasks"]["num_tasks_per_crane"] = 3
    raw["tasks"]["queue_policy"]["start_mode"] = "staggered"
    raw["tasks"]["queue_policy"]["initial_start_jitter_s"] = [0.0, 6.0]
    raw["tasks"]["queue_policy"]["inter_task_delay_s"] = [2.0, 2.0]
    raw["tasks"]["task_type_distribution"] = {
        "easy_task": 0.34,
        "overlap_task": 0.33,
        "stress_task": 0.33,
    }
    raw["tasks"]["priority_distribution"] = {
        "low": 0.2,
        "medium": 0.5,
        "high": 0.3,
    }
    return raw


def _scenario_and_cranes(raw: dict | None = None):
    scenario = ScenarioConfig.model_validate(raw or _scenario_raw())
    model_library = build_crane_model_library(scenario.crane_models)
    cranes = build_crane_configs(scenario.cranes, model_library, scenario, source="manual")
    return scenario, cranes


def test_same_seed_generates_identical_task_queues() -> None:
    scenario, cranes = _scenario_and_cranes()

    first = generate_task_queues(scenario, cranes, seed=1234)
    second = generate_task_queues(scenario, cranes, seed=1234)

    assert first.model_dump(mode="json") == second.model_dump(mode="json")


def test_different_seed_changes_generated_tasks() -> None:
    scenario, cranes = _scenario_and_cranes()

    first = generate_task_queues(scenario, cranes, seed=1234)
    second = generate_task_queues(scenario, cranes, seed=5678)

    assert first.model_dump(mode="json")["tasks"] != second.model_dump(mode="json")["tasks"]


def test_auto_generation_creates_per_crane_queues_with_stable_ids() -> None:
    scenario, cranes = _scenario_and_cranes()

    result = generate_task_queues(scenario, cranes, seed=202)

    assert [queue.crane_id for queue in result.queues] == ["C1", "C2", "C3"]
    assert [len(queue.tasks) for queue in result.queues] == [3, 3, 3]
    assert [task.task_id for task in result.queues[0].tasks] == [
        "T_C1_001",
        "T_C1_002",
        "T_C1_003",
    ]
    assert len({task.task_id for task in result.tasks}) == len(result.tasks)
    assert all(task.status == TaskStatus.PENDING for task in result.tasks)
    assert result.report.num_cranes == 3
    assert result.report.num_tasks_total == 9


def test_generated_points_use_zone_contracts_and_boundary() -> None:
    scenario, cranes = _scenario_and_cranes()

    result = generate_task_queues(scenario, cranes, seed=404)

    material_by_id = {zone.zone_id: zone for zone in scenario.site.material_zones}
    work_by_id = {zone.zone_id: zone for zone in scenario.site.work_zones}
    for task in result.tasks:
        pickup_zone = material_by_id[task.pickup_zone_id]
        dropoff_zone = work_by_id[task.dropoff_zone_id]
        assert task.pickup.zone_type == "material"
        assert task.dropoff.zone_type == "work"
        assert point_in_zone(task.pickup.as_xyz(), pickup_zone)
        assert point_in_zone(task.dropoff.as_xyz(), dropoff_zone)
        assert point_in_boundary(task.pickup.as_xyz(), scenario.site.boundary)
        assert point_in_boundary(task.dropoff.as_xyz(), scenario.site.boundary)
        assert task.load_type in scenario.load_types
        assert task.load_type in (pickup_zone.load_types or scenario.load_types.keys())
        assert task.load_type in (
            dropoff_zone.accepted_load_types or scenario.load_types.keys()
        )


def test_stress_tasks_have_close_planned_starts_and_tighter_deadlines() -> None:
    raw = _scenario_raw()
    raw["tasks"]["task_type_distribution"] = {
        "easy_task": 0.0,
        "overlap_task": 0.0,
        "stress_task": 1.0,
    }
    scenario, cranes = _scenario_and_cranes(raw)

    result = generate_task_queues(scenario, cranes, seed=808)

    first_starts = [queue.tasks[0].planned_start_s for queue in result.queues]
    deadlines = [task.deadline_s for task in result.tasks]
    assert max(first_starts) - min(first_starts) <= 3.0
    assert all(deadline is not None and deadline <= 140.0 for deadline in deadlines)
    assert result.report.num_tasks_by_type == {"stress_task": 9}


def test_manual_generation_preserves_template_id_and_assigns_feasible_crane() -> None:
    raw = _scenario_raw()
    raw["tasks"]["generation_mode"] = "manual"
    raw["tasks"]["manual_tasks"] = [
        {
            "task_id": "manual_pick_001",
            "task_type": "easy_task",
            "pickup_zone_id": "mat_west",
            "dropoff_zone_id": "work_east",
            "load_type": "formwork",
            "priority": "high",
        }
    ]
    scenario, cranes = _scenario_and_cranes(raw)

    result = generate_task_queues(scenario, cranes, seed=606)

    assert [task.task_id for task in result.tasks] == ["manual_pick_001"]
    assert result.tasks[0].crane_id in {"C1", "C2", "C3"}
    assert result.tasks[0].priority == "high"
    assert result.tasks[0].load_type == "formwork"
    assert sum(len(queue.tasks) for queue in result.queues) == 1


def test_missing_material_zones_returns_task_error() -> None:
    raw = _scenario_raw()
    raw["site"]["material_zones"] = []
    scenario, cranes = _scenario_and_cranes(raw)

    with pytest.raises(TaskGenerationError) as exc_info:
        generate_task_queues(scenario, cranes, seed=909)

    assert exc_info.value.error_code == "TASK_E_001"
    assert exc_info.value.reason == "missing_material_or_work_zones"


def test_overlap_task_without_overlap_region_reports_reason() -> None:
    raw = _scenario_raw()
    raw["cranes"] = [
        {
            **deepcopy(raw["cranes"][0]),
            "crane_id": "C1",
            "base": [-80.0, -80.0, 0.0],
        }
    ]
    raw["layout"]["num_cranes"] = 1
    raw["tasks"]["task_type_distribution"] = {
        "easy_task": 0.0,
        "overlap_task": 1.0,
        "stress_task": 0.0,
    }
    scenario, cranes = _scenario_and_cranes(raw)

    with pytest.raises(TaskGenerationError) as exc_info:
        generate_task_queues(scenario, cranes, seed=303)

    assert exc_info.value.error_code == "TASK_E_001"
    assert exc_info.value.reason == "no_task_overlap_region"
