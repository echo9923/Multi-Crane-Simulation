from __future__ import annotations

from pathlib import Path

from backend.app.core.config_loader import load_demo_config
from backend.app.core.config_resolver import resolve_config
from backend.app.schemas.crane import CraneConfig
from backend.app.api.production_runner import scenario_config_from_resolved
from backend.app.sim.manual_task_validation import validate_manual_task_plan

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_elevated_curated_scene_has_reachable_base_z_crane_tasks() -> None:
    scenario, experiment, dataset = load_demo_config(
        REPO_ROOT / "configs" / "curated_elevated_crane_transfer.yaml"
    )
    assert experiment is not None
    resolved = resolve_config(scenario, experiment, dataset)
    resolved_scenario = scenario_config_from_resolved(resolved)
    cranes = [
        CraneConfig.model_validate(crane)
        for crane in resolved.layout.resolved_cranes or []
    ]

    elevated = [crane for crane in cranes if crane.base[2] > 0]
    assert elevated
    for crane in elevated:
        assert crane.root[2] == crane.base[2] + crane.mast_height_m

    report = validate_manual_task_plan(resolved_scenario, cranes)
    elevated_ids = {crane.crane_id for crane in elevated}
    elevated_reports = [
        item for item in report.task_reports if item.crane_id in elevated_ids
    ]

    assert elevated_reports
    assert all(item.pickup_reachable and item.dropoff_reachable for item in elevated_reports)
    assert all(not item.blocking_reasons for item in elevated_reports)
