from __future__ import annotations

import math
from collections import Counter
from pathlib import Path

import yaml

from backend.app.schemas.config import ScenarioConfig
from backend.app.sim.crane_model import build_crane_model_library
from backend.app.sim.layout import build_crane_configs
from backend.app.sim.layout_geometry import horizontal_distance
from backend.app.sim.physics import initialize_crane_state
from backend.app.sim.task_generation import generate_task_queues


REPO_ROOT = Path(__file__).resolve().parents[3]


def _load_demo_scenario() -> ScenarioConfig:
    raw = yaml.safe_load(
        (REPO_ROOT / "configs/deepseek_demo_4x2_manual.yaml").read_text(
            encoding="utf-8"
        )
    )
    return ScenarioConfig.model_validate(raw["scenario"])


def test_deepseek_demo_config_assigns_two_reachable_tasks_per_crane() -> None:
    scenario = _load_demo_scenario()
    library = build_crane_model_library(scenario.crane_models)
    cranes = build_crane_configs(scenario.cranes, library, scenario, source="manual")

    result = generate_task_queues(scenario, cranes, seed=scenario.seed)

    counts = Counter(task.crane_id for task in result.tasks)
    assert counts == {"C1": 2, "C2": 2, "C3": 2, "C4": 2}
    for queue in result.queues:
        assert len(queue.tasks) == 2
        assert all(task.crane_id == queue.crane_id for task in queue.tasks)


def test_deepseek_demo_first_pickup_starts_near_initial_hook_direction() -> None:
    scenario = _load_demo_scenario()
    library = build_crane_model_library(scenario.crane_models)
    cranes = build_crane_configs(scenario.cranes, library, scenario, source="manual")
    result = generate_task_queues(scenario, cranes, seed=scenario.seed)
    queues_by_crane = {queue.crane_id: queue for queue in result.queues}

    for crane in cranes:
        state = initialize_crane_state(crane)
        first_task = queues_by_crane[crane.crane_id].tasks[0]
        pickup = first_task.pickup.as_xyz()
        target_angle = math.degrees(
            math.atan2(pickup[1] - crane.base[1], pickup[0] - crane.base[0])
        )
        angle_error = (target_angle - crane.theta_init_deg + 180.0) % 360.0 - 180.0

        assert abs(angle_error) <= 4.0, crane.crane_id
        assert horizontal_distance(state.hook_position, pickup) <= 2.0, crane.crane_id
        assert abs(state.hook_h_m - first_task.pickup.z) <= 6.0, crane.crane_id
