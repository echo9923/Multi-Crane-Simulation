from __future__ import annotations

from pathlib import Path

import pytest

from backend.app.core.config_loader import load_demo_config
from backend.app.core.config_resolver import resolve_config
from backend.app.schemas.enums import LayoutMode, TaskGenerationMode

REPO_ROOT = Path(__file__).resolve().parents[3]
CURATED_CONFIGS = [
    "curated_dense_highrise_ground.yaml",
    "curated_elevated_crane_transfer.yaml",
    "curated_complex_cross_lifting.yaml",
]


@pytest.mark.parametrize("config_name", CURATED_CONFIGS)
def test_curated_scenario_loads_and_resolves(config_name: str) -> None:
    scenario, experiment, dataset = load_demo_config(REPO_ROOT / "configs" / config_name)

    assert experiment is not None
    assert dataset is None
    assert scenario.layout.mode is LayoutMode.MANUAL
    assert scenario.tasks.generation_mode is TaskGenerationMode.MANUAL
    assert scenario.tasks.manual_tasks
    assert scenario.site.buildings
    assert scenario.site.material_zones
    assert scenario.site.work_zones

    resolved = resolve_config(scenario, experiment, dataset)

    assert resolved.layout.mode == "manual"
    assert resolved.layout.resolved_cranes
    assert len(resolved.layout.resolved_cranes) == scenario.layout.num_cranes
    assert resolved.scenario["tasks"]["manual_tasks"]
    assert resolved.runtime.sim["stop_when_all_tasks_done"] is True
