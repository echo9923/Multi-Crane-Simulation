from __future__ import annotations

from backend.app.schemas.recorder import (
    EventLogEntry,
    ObservationLogEntry,
    SimFrame,
)


def test_module_l_schema_acceptance_surface_is_available() -> None:
    frame = SimFrame(
        episode_id="episode-001",
        scenario_id="scenario-001",
        frame=0,
        time_s=0.0,
        episode_status="running",
        cranes=[],
        pairs=[],
        tasks=[],
        weather={"wind_speed_m_s": 0.0, "visibility": "good"},
        events=[],
    )

    assert frame.type == "sim_frame"
    assert frame.schema_version == "1.0"


def test_module_l_observation_log_does_not_include_offline_truth() -> None:
    observation = ObservationLogEntry(
        observation_id="OBS-001",
        episode_id="episode-001",
        time_s=0.0,
        crane_id="C1",
        risk_prompt_mode="R1",
        observation={"self": {"crane_id": "C1"}},
        source_snapshot_id="SNAP-001",
    )

    dumped = observation.model_dump(mode="json")

    assert "offline_label" not in dumped
    assert "future_min_distance" not in dumped
    assert "future_ttc" not in dumped


def test_module_l_event_log_supports_mvp_event_catalog() -> None:
    assert len(EventLogEntry.supported_mvp_event_types) >= 25
    assert "near_miss" in EventLogEntry.supported_mvp_event_types
    assert "llm_invalid_output" in EventLogEntry.supported_mvp_event_types
