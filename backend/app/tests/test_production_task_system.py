from __future__ import annotations

from pathlib import Path

from backend.app.api.production_runner import build_production_episode_runner
from backend.app.tests.test_production_runner import _production_smoke_config


def test_production_task_system_activates_tasks_and_builds_context(
    tmp_path: Path,
) -> None:
    runner = build_production_episode_runner(
        episode_id="E-production-task-system",
        resolved_config=_production_smoke_config(tmp_path),
    )

    assert any(queue.tasks for queue in runner.runner.task_queues)

    result = runner.run_one_frame()

    assert result.frame_index == 1
    assert any(queue.active_task_id for queue in runner.runner.task_queues)
    assert any(
        getattr(context, "has_active_task", False)
        or (
            isinstance(context, dict)
            and context.get("task", {}).get("has_active_task")
        )
        for context in runner.runner.task_contexts.values()
    )

    run_dir = runner.recorder.run_dir
    assert run_dir is not None
    events = (run_dir / "logs" / "events.jsonl").read_text(encoding="utf-8")
    assert "task_started" in events
