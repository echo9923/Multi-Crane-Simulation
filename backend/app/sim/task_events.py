from __future__ import annotations

from typing import Any, Dict, Optional

from backend.app.schemas.task import Task, TaskEventPayload


def build_task_event(
    event_type: str,
    *,
    time_s: float,
    frame_index: Optional[int],
    crane_id: str,
    task: Optional[Task],
    task_stage: Optional[str],
    reason: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
) -> TaskEventPayload:
    return TaskEventPayload(
        event_type=event_type,
        time_s=time_s,
        frame_index=frame_index,
        crane_id=crane_id,
        task_id=task.task_id if task is not None else None,
        task_type=task.task_type if task is not None else None,
        task_status=task.status if task is not None else None,
        task_stage=task_stage,
        reason=reason,
        details=details or {},
    )
