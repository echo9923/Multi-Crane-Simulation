from __future__ import annotations

from pathlib import Path

import pytest

from backend.app.core.config_loader import load_demo_config
from backend.app.core.config_resolver import resolve_config
from backend.app.schemas.crane import CraneConfig
from backend.app.api.production_runner import scenario_config_from_resolved
from backend.app.sim.manual_task_validation import validate_manual_task_plan

REPO_ROOT = Path(__file__).resolve().parents[3]
CURATED_CONFIGS = [
    "curated_dense_highrise_ground.yaml",
    "curated_elevated_crane_transfer.yaml",
    "curated_complex_cross_lifting.yaml",
]


def _validation_report(config_name: str):
    scenario, experiment, dataset = load_demo_config(REPO_ROOT / "configs" / config_name)
    assert experiment is not None
    resolved = resolve_config(scenario, experiment, dataset)
    resolved_scenario = scenario_config_from_resolved(resolved)
    cranes = [
        CraneConfig.model_validate(crane)
        for crane in resolved.layout.resolved_cranes or []
    ]
    return validate_manual_task_plan(resolved_scenario, cranes)


@pytest.mark.parametrize("config_name", CURATED_CONFIGS)
def test_curated_manual_tasks_are_all_reachable(config_name: str) -> None:
    report = _validation_report(config_name)

    assert report.valid is True
    assert report.task_reports
    assert report.task_count == len(report.task_reports)
    for task_report in report.task_reports:
        assert task_report.pickup_reachable is True, task_report
        assert task_report.dropoff_reachable is True, task_report
        assert task_report.required_transport_height_m is not None
        assert task_report.capacity_margin_t is not None
        assert task_report.capacity_margin_t >= 0
        assert task_report.blocking_reasons == []


def test_curated_task_count_matches_per_crane_hint() -> None:
    report = _validation_report("curated_complex_cross_lifting.yaml")

    assert report.task_count == 12
    assert report.expected_task_count == 10
    assert report.warnings
    assert report.warnings[0]["reason"] == "manual_task_count_exceeds_num_tasks_per_crane_hint"
