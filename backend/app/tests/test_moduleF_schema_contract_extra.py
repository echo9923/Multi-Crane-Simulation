from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from backend.app.schemas.observation import (
    OBSERVATION_SCHEMA_VERSION,
    Observation,
    VisibleNeighbor,
)
from backend.app.tests.test_observation import _valid_observation_payload


FORBIDDEN_OBSERVATION_KEYS = {
    "planned_start_s",
    "future_min_distance",
    "offline_ttc",
    "offline_label",
    "future_ttc",
    "source_failed_task_id",
    "neighbor_task_id",
    "pickup_zone_id",
    "dropoff_zone_id",
    "task_id",
}


def test_observation_json_dump_is_serializable_and_contains_schema_versions() -> None:
    observation = Observation.model_validate(_valid_observation_payload())

    payload = observation.model_dump(mode="json")
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    decoded = json.loads(encoded)

    assert decoded["schema_version"] == OBSERVATION_SCHEMA_VERSION
    assert decoded["task"]["schema_version"] == OBSERVATION_SCHEMA_VERSION
    assert decoded["self_state"]["schema_version"] == OBSERVATION_SCHEMA_VERSION
    assert decoded["visible_neighbors"][0]["schema_version"] == OBSERVATION_SCHEMA_VERSION
    assert decoded["weather"]["schema_version"] == OBSERVATION_SCHEMA_VERSION
    assert decoded["available_actions"]["schema_version"] == OBSERVATION_SCHEMA_VERSION
    assert decoded["memory"]["schema_version"] == OBSERVATION_SCHEMA_VERSION
    assert decoded["memory"]["recent_decisions"][0]["schema_version"] == (
        OBSERVATION_SCHEMA_VERSION
    )


def test_r0_observation_rejects_non_empty_safety_hint() -> None:
    payload = _valid_observation_payload()
    payload["risk_prompt_mode"] = "R0"

    with pytest.raises(ValidationError) as exc_info:
        Observation.model_validate(payload)

    assert "R0 observation must not include safety_hint" in str(exc_info.value)


def test_hidden_neighbor_hook_rejects_precise_hook_details() -> None:
    with pytest.raises(ValidationError) as exc_info:
        VisibleNeighbor(
            crane_id="C2",
            relative_direction="right",
            distance_m=20.0,
            distance_level="near",
            hook_visible=False,
            hook_height_m=35.0,
            jib_motion="hold",
            trolley_motion="hold",
            hoist_motion="hold",
            load_attached=True,
            task_stage="move_to_pickup",
            in_overlap_zone=True,
        )

    assert any(error["loc"] == () for error in exc_info.value.errors())


def test_observation_schema_field_names_do_not_contain_forbidden_keys() -> None:
    schema_text = json.dumps(Observation.model_json_schema(), sort_keys=True)

    for forbidden_key in FORBIDDEN_OBSERVATION_KEYS:
        assert forbidden_key not in schema_text
