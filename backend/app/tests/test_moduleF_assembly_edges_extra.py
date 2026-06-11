from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.app.schemas.control import ControlTarget
from backend.app.schemas.weather import WeatherVisibilityContext
from backend.app.sim.observation import (
    ObservationBuildError,
    ObservationWorldSnapshot,
    build_observation,
    build_observations_for_snapshot,
)
from backend.app.tests.test_moduleF_acceptance import _risk, _snapshot


def test_world_snapshot_rejects_duplicate_crane_state_ids() -> None:
    snapshot = _snapshot()
    duplicate_state = snapshot.crane_states[0].model_copy()

    with pytest.raises(ValidationError) as exc_info:
        ObservationWorldSnapshot(
            snapshot_id=snapshot.snapshot_id,
            time_s=snapshot.time_s,
            decision_time_bucket=snapshot.decision_time_bucket,
            crane_states=[snapshot.crane_states[0], duplicate_state],
            crane_configs=snapshot.crane_configs,
            weather_state=snapshot.weather_state,
            visibility_context=snapshot.visibility_context,
            neighbor_map=snapshot.neighbor_map,
            task_contexts=snapshot.task_contexts,
        )

    assert "crane_states contains duplicate crane_id: C1" in str(exc_info.value)


def test_build_observation_rejects_missing_crane_config() -> None:
    snapshot = _snapshot().model_copy(update={"crane_configs": []})

    with pytest.raises(ObservationBuildError) as exc_info:
        build_observation(
            snapshot=snapshot,
            crane_id="C1",
            risk_prompt_mode="R0",
            operator_profile="normal",
        )

    assert exc_info.value.field_path == "crane_configs.C1"
    assert exc_info.value.episode_status == "failed_invalid_state"


def test_build_observation_rejects_current_command_for_wrong_crane() -> None:
    snapshot = _snapshot().model_copy(
        update={
            "current_commands": {
                "C1": ControlTarget(
                    crane_id="C2",
                    target_slew_velocity_rad_s=0.0,
                    target_trolley_velocity_m_s=0.0,
                    target_hoist_velocity_m_s=0.0,
                )
            }
        }
    )

    with pytest.raises(ObservationBuildError) as exc_info:
        build_observation(
            snapshot=snapshot,
            crane_id="C1",
            risk_prompt_mode="R0",
            operator_profile="normal",
        )

    assert exc_info.value.field_path == "current_command.crane_id"


def test_build_observations_for_snapshot_rejects_missing_operator_profile() -> None:
    with pytest.raises(ObservationBuildError) as exc_info:
        build_observations_for_snapshot(
            snapshot=_snapshot(),
            crane_ids=["C1", "C2"],
            risk_prompt_mode="R0",
            operator_profiles={"C1": "aggressive"},
        )

    assert exc_info.value.field_path == "operator_profiles.C2"


def test_build_observation_rejects_invalid_visibility_precision_at_build_boundary() -> None:
    snapshot = _snapshot()
    invalid_visibility = snapshot.visibility_context.model_construct(
        **{
            **snapshot.visibility_context.model_dump(),
            "distance_precision_m": 0.0,
        }
    )
    invalid_snapshot = snapshot.model_copy(update={"visibility_context": invalid_visibility})

    with pytest.raises(ObservationBuildError) as exc_info:
        build_observation(
            snapshot=invalid_snapshot,
            crane_id="C1",
            risk_prompt_mode="R1",
            operator_profile="normal",
            online_risk=_risk(),
        )

    assert exc_info.value.field_path == "distance_precision_m"


def test_build_observation_output_changes_with_visibility_seed_only_in_visibility_fields() -> None:
    snapshot = _snapshot()
    changed_visibility = WeatherVisibilityContext.model_validate(
        {
            **snapshot.visibility_context.model_dump(mode="json"),
            "distance_noise_m": 10.0,
            "hide_hook_prob": 0.5,
            "noise_seed": snapshot.visibility_context.noise_seed + 1,
        }
    )
    changed_snapshot = snapshot.model_copy(update={"visibility_context": changed_visibility})

    base = build_observation(
        snapshot=snapshot,
        crane_id="C1",
        risk_prompt_mode="R0",
        operator_profile="normal",
    ).model_dump(mode="json")
    changed = build_observation(
        snapshot=changed_snapshot,
        crane_id="C1",
        risk_prompt_mode="R0",
        operator_profile="normal",
    ).model_dump(mode="json")

    assert base["task"] == changed["task"]
    assert base["self_state"] == changed["self_state"]
    assert base["weather"] == changed["weather"]
    assert base["visible_neighbors"] != changed["visible_neighbors"]

