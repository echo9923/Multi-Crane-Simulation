from __future__ import annotations

from backend.app.sim.observation import build_memory_summary


def test_memory_summary_uses_reason_when_event_summary_is_missing() -> None:
    memory = build_memory_summary(
        recent_decisions=[],
        recent_events=[
            {
                "event_type": "task_recovered",
                "time_s": 21.5,
                "reason": "operator returned to safe state",
                "future_min_distance": 0.1,
            }
        ],
    )

    assert memory.task_history_summary == "最近已有 1 条任务事件。"
    assert memory.event_summary == [
        "task_recovered at 21.5: operator returned to safe state"
    ]
    assert "future_min_distance" not in str(memory.model_dump(mode="json"))


def test_empty_memory_summary_has_empty_lists_and_no_text_summary() -> None:
    memory = build_memory_summary(recent_decisions=[], recent_events=[])

    assert memory.task_history_summary is None
    assert memory.recent_decisions == []
    assert memory.event_summary == []


def test_memory_summary_strips_forbidden_history_fields_before_schema_validation() -> None:
    memory = build_memory_summary(
        recent_decisions=[
            {
                "time_s": 12.0,
                "command_summary": "hold position",
                "result": "stable",
                "offline_ttc": 0.4,
                "planned_start_s": 40.0,
            }
        ],
        recent_events=[
            {
                "event_type": "near_miss_detected",
                "time_s": 12.5,
                "summary": "inspection note",
                "details": {
                    "source_failed_task_id": "T_C1_001",
                    "future_min_distance": 0.2,
                },
            }
        ],
    )
    payload_text = str(memory.model_dump(mode="json"))

    assert "hold position" in payload_text
    assert "inspection note" in payload_text
    for forbidden in [
        "offline_ttc",
        "planned_start_s",
        "source_failed_task_id",
        "future_min_distance",
    ]:
        assert forbidden not in payload_text

