from __future__ import annotations

import ast
import math
from pathlib import Path

from backend.app.schemas.config import ScenarioConfig
from backend.app.schemas.state import CraneState
from backend.app.schemas.task import TaskActionSignal
from backend.app.sim.crane_model import build_crane_model_library
from backend.app.sim.layout import build_crane_configs
from backend.app.sim.task_failure import (
    TaskFailureRuntimeState,
    handle_task_timing_and_failures,
)
from backend.app.sim.task_generation import generate_task_queues
from backend.app.sim.task_observation import build_task_observation_context
from backend.app.sim.task_queue import all_ordinary_tasks_terminal, schedule_task_queues
from backend.app.sim.task_state_machine import TaskRuntimeState, step_task_state_machine
from backend.app.tests.test_config_schema import load_fixture


REPO_ROOT = Path(__file__).resolve().parents[3]


def _scenario_raw() -> dict:
    raw = load_fixture("scenario_valid.yaml")
    raw["layout"]["mode"] = "manual"
    raw["layout"]["num_cranes"] = 3
    raw["cranes"] = [
        {
            "crane_id": "D1",
            "model_id": "generic_flat_top_55m",
            "base": [-30.0, -20.0, 0.0],
            "mast_height_m": 50.0,
            "theta_init_deg": 0.0,
            "slew": {"mode": "continuous"},
        },
        {
            "crane_id": "D2",
            "model_id": "generic_flat_top_55m",
            "base": [20.0, -20.0, 0.0],
            "mast_height_m": 52.0,
            "theta_init_deg": 90.0,
            "slew": {"mode": "continuous"},
        },
        {
            "crane_id": "D3",
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
    raw["tasks"]["queue_policy"]["initial_start_jitter_s"] = [0.0, 3.0]
    raw["tasks"]["queue_policy"]["inter_task_delay_s"] = [2.0, 2.0]
    raw["tasks"]["task_type_distribution"] = {
        "easy_task": 0.34,
        "overlap_task": 0.33,
        "stress_task": 0.33,
    }
    return raw


def _scenario_and_cranes():
    scenario = ScenarioConfig.model_validate(_scenario_raw())
    library = build_crane_model_library(scenario.crane_models)
    cranes = build_crane_configs(scenario.cranes, library, scenario, source="manual")
    return scenario, cranes


def _state_for_task(crane, task, *, stage: str, target, load_attached=False) -> CraneState:
    x, y, z = target
    theta = math.atan2(y - crane.base[1], x - crane.base[0])
    radius = math.hypot(x - crane.base[0], y - crane.base[1])
    return CraneState(
        crane_id=crane.crane_id,
        theta_rad=theta,
        theta_sin=math.sin(theta),
        theta_cos=math.cos(theta),
        trolley_r_m=radius,
        hook_h_m=z,
        root_position=crane.root,
        tip_position=[0.0, 0.0, 0.0],
        hook_position=[x, y, z],
        cable_length_m=crane.root[2] - z,
        load_attached=load_attached,
        load_type=task.load_type if load_attached else None,
        load_weight_t=task.load_weight_t if load_attached else 0.0,
        load_size_m=task.load_size_m if load_attached else None,
        task_id=task.task_id,
        task_stage=stage,
    )


def _signal(action: str) -> TaskActionSignal:
    return TaskActionSignal(
        crane_id="D1",
        command_id="cmd",
        time_s=0.0,
        task_action=action,
    )


def test_module_d_generates_and_starts_deterministic_per_crane_queues() -> None:
    scenario, cranes = _scenario_and_cranes()

    result = generate_task_queues(scenario, cranes, seed=777)
    second = generate_task_queues(scenario, cranes, seed=777)
    scheduled = schedule_task_queues(
        result.queues,
        {
            crane.crane_id: _state_for_task(
                crane,
                result.queues[index].tasks[0],
                stage="idle",
                target=[crane.base[0] + crane.trolley_r_min_m, crane.base[1], 20.0],
            )
            for index, crane in enumerate(cranes)
        },
        time_s=10.0,
    )

    assert result.model_dump(mode="json") == second.model_dump(mode="json")
    assert len(result.queues) == 3
    assert [len(queue.tasks) for queue in result.queues] == [3, 3, 3]
    assert sum(task.task_type == "easy_task" for task in result.tasks) >= 1
    assert sum(task.task_type == "overlap_task" for task in result.tasks) >= 1
    assert sum(task.task_type == "stress_task" for task in result.tasks) >= 1
    assert {queue.active_task_id for queue in scheduled.queues} == {
        queue.tasks[0].task_id for queue in result.queues
    }
    assert len(scheduled.events) == 3


def test_module_d_easy_task_can_attach_release_and_finish() -> None:
    scenario, cranes = _scenario_and_cranes()
    crane = cranes[0]
    task = generate_task_queues(scenario, cranes, seed=777).queues[0].tasks[0]

    attach_state = _state_for_task(
        crane,
        task,
        stage="lower_for_attach",
        target=[task.pickup.x, task.pickup.y, task.pickup.z],
    )
    attached = step_task_state_machine(
        task,
        crane,
        attach_state,
        _signal("request_attach"),
        time_s=1.0,
        config=scenario.tasks.state_machine,
        attach_delay_s=0.0,
    )
    attached_done = step_task_state_machine(
        attached.task,
        crane,
        attached.state,
        TaskActionSignal(crane_id="D1", time_s=1.1),
        time_s=1.1,
        config=scenario.tasks.state_machine,
        runtime=attached.runtime,
        attach_delay_s=0.0,
    )
    release_state = _state_for_task(
        crane,
        attached_done.task,
        stage="lower_for_release",
        target=[task.dropoff.x, task.dropoff.y, task.dropoff.z],
        load_attached=True,
    )
    releasing = step_task_state_machine(
        attached_done.task,
        crane,
        release_state,
        _signal("request_release"),
        time_s=2.0,
        config=scenario.tasks.state_machine,
        release_delay_s=0.0,
    )
    completed = step_task_state_machine(
        releasing.task,
        crane,
        releasing.state,
        TaskActionSignal(crane_id="D1", time_s=2.1),
        time_s=2.1,
        config=scenario.tasks.state_machine,
        runtime=releasing.runtime,
        release_delay_s=0.0,
    )

    assert attached_done.state.load_attached is True
    assert completed.task.status == "completed"
    assert completed.state.load_attached is False
    context = build_task_observation_context(
        crane.crane_id,
        completed.state,
        active_task=None,
        time_s=2.1,
        recent_events=completed.events,
    )
    assert context.has_active_task is False


def test_module_d_release_failure_enters_recovery_without_clearing_load() -> None:
    scenario, cranes = _scenario_and_cranes()
    crane = cranes[0]
    task = generate_task_queues(scenario, cranes, seed=777).queues[0].tasks[0]
    loaded_state = _state_for_task(
        crane,
        task,
        stage="release_pending",
        target=[task.dropoff.x, task.dropoff.y, task.dropoff.z],
        load_attached=True,
    )

    result = handle_task_timing_and_failures(
        task.model_copy(update={"status": "active", "started_at_s": 0.0}),
        loaded_state,
        scenario,
        crane,
        time_s=200.0,
        runtime=TaskFailureRuntimeState(
            release_stage_started_at_s=0.0,
            last_progress_at_s=199.0,
        ),
    )

    assert result.task.status == "failed"
    assert result.recovery_task is not None
    assert result.state.task_stage == "recovery_release"
    assert result.state.load_attached is True
    assert result.events[-1].event_type == "recovery_release_started"


def test_module_d_terminal_query_and_boundary_imports() -> None:
    scenario, cranes = _scenario_and_cranes()
    queues = generate_task_queues(scenario, cranes, seed=777).queues
    terminal = [
        queue.model_copy(
            update={
                "tasks": [
                    task.model_copy(update={"status": "completed"})
                    for task in queue.tasks
                ],
                "next_task_index": len(queue.tasks),
            }
        )
        for queue in queues
    ]

    assert all_ordinary_tasks_terminal(terminal) is True

    banned_prefixes = (
        "backend.app.llm",
        "backend.app.recorder",
        "backend.app.risk",
        "backend.app.controllers",
        "backend.app.frontend",
    )
    module_paths = [
        REPO_ROOT / "backend/app/sim/task_generation.py",
        REPO_ROOT / "backend/app/sim/task_feasibility.py",
        REPO_ROOT / "backend/app/sim/task_queue.py",
        REPO_ROOT / "backend/app/sim/task_state_machine.py",
        REPO_ROOT / "backend/app/sim/task_failure.py",
        REPO_ROOT / "backend/app/sim/task_observation.py",
        REPO_ROOT / "backend/app/sim/task_events.py",
    ]
    for path in module_paths:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imported = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.append(node.module)

        assert not [
            module for module in imported if module.startswith(banned_prefixes)
        ], path
