from __future__ import annotations

from pathlib import Path

from backend.app.api.production_runner import scenario_config_from_resolved
from backend.app.core.config_loader import load_demo_config
from backend.app.core.config_resolver import resolve_config
from backend.app.schemas.crane import CraneConfig
from backend.app.sim.manual_task_validation import validate_manual_task_plan
from backend.app.sim.task_generation import generate_task_queues

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_curated_ground_scene_reaches_task_queue_generation_with_mock_provider() -> None:
    scenario, experiment, dataset = load_demo_config(
        REPO_ROOT / "configs" / "curated_dense_highrise_ground.yaml",
        overrides={
            "experiment": {
                "llm": {
                    "provider": "mock",
                    "model": "mock-curated",
                    "api_key_env": None,
                    "api_key": None,
                    "timeout_s": 1,
                    "max_retries": 0,
                },
            },
        },
    )
    assert experiment is not None
    resolved = resolve_config(scenario, experiment, dataset)
    resolved_scenario = scenario_config_from_resolved(resolved)
    cranes = [
        CraneConfig.model_validate(crane)
        for crane in resolved.layout.resolved_cranes or []
    ]

    validation = validate_manual_task_plan(resolved_scenario, cranes)
    result = generate_task_queues(
        resolved_scenario,
        cranes,
        seed=int(resolved.seeds.task),
    )

    assert validation.valid is True
    assert len(result.tasks) == 8
    assert {queue.crane_id: len(queue.tasks) for queue in result.queues} == {
        "C1": 2,
        "C2": 2,
        "C3": 2,
        "C4": 2,
    }
    assert result.report.blocking_errors == []
