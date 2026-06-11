from __future__ import annotations

import pytest

from backend.app.schemas.state import CraneState
from backend.app.schemas.weather import WeatherVisibilityContext
from backend.app.sim.observation import (
    ObservationBuildError,
    build_visible_neighbors,
)


def _state(
    crane_id: str,
    hook_position: list[float],
    *,
    theta_dot_rad_s: float = 0.0,
    trolley_v_m_s: float = 0.0,
    hoist_v_m_s: float = 0.0,
    load_attached: bool = False,
    task_stage: str = "idle",
) -> CraneState:
    return CraneState(
        crane_id=crane_id,
        theta_rad=0.0,
        theta_dot_rad_s=theta_dot_rad_s,
        theta_sin=0.0,
        theta_cos=1.0,
        trolley_r_m=hook_position[0],
        trolley_v_m_s=trolley_v_m_s,
        hook_h_m=hook_position[2],
        hoist_v_m_s=hoist_v_m_s,
        root_position=[0.0, 0.0, 50.0],
        tip_position=[55.0, 0.0, 50.0],
        hook_position=hook_position,
        cable_length_m=50.0 - hook_position[2],
        load_attached=load_attached,
        task_stage=task_stage,
    )


def _visibility(**overrides) -> WeatherVisibilityContext:
    payload = {
        "time_s": 10.0,
        "visibility_level": "medium",
        "neighbor_visibility_radius_m": 50.0,
        "distance_noise_m": 0.0,
        "hide_hook_prob": 0.0,
        "visibility_confidence": 0.7,
        "distance_precision_m": 1.0,
        "noise_seed": 12345,
        "profile_source": "default",
    }
    payload.update(overrides)
    return WeatherVisibilityContext.model_validate(payload)


def test_visible_neighbors_are_filtered_by_weather_radius_and_summarized() -> None:
    observer = _state("C1", [0.0, 0.0, 30.0])
    near = _state(
        "C2",
        [30.0, 40.0, 32.0],
        theta_dot_rad_s=0.1,
        trolley_v_m_s=0.2,
        hoist_v_m_s=-0.1,
        load_attached=True,
        task_stage="move_to_dropoff",
    )
    far = _state("C3", [80.0, 0.0, 30.0])

    neighbors = build_visible_neighbors(
        observer_state=observer,
        states_by_id={"C1": observer, "C2": near, "C3": far},
        neighbor_ids=["C2", "C3"],
        visibility=_visibility(),
        decision_time_bucket=10,
    )

    assert [neighbor.crane_id for neighbor in neighbors] == ["C2"]
    visible = neighbors[0]
    assert visible.relative_direction == "right_front"
    assert visible.distance_m == 50.0
    assert visible.distance_level == "medium"
    assert visible.hook_visible is True
    assert visible.hook_height_m == 32.0
    assert visible.jib_motion == "slow_left"
    assert visible.trolley_motion == "out"
    assert visible.hoist_motion == "down"
    assert visible.load_attached is True
    assert visible.task_stage == "move_to_dropoff"
    assert visible.in_overlap_zone is True


def test_distance_noise_and_hook_hide_are_deterministic_and_do_not_mutate_state() -> None:
    observer = _state("C1", [0.0, 0.0, 30.0])
    target = _state("C2", [20.0, 0.0, 35.0], load_attached=True)
    states = {"C1": observer, "C2": target}
    visibility = _visibility(
        neighbor_visibility_radius_m=100.0,
        distance_noise_m=5.0,
        hide_hook_prob=1.0,
        distance_precision_m=5.0,
        noise_seed=999,
    )

    first = build_visible_neighbors(
        observer_state=observer,
        states_by_id=states,
        neighbor_ids=["C2"],
        visibility=visibility,
        decision_time_bucket=10,
    )
    second = build_visible_neighbors(
        observer_state=observer,
        states_by_id=states,
        neighbor_ids=["C2"],
        visibility=visibility,
        decision_time_bucket=10,
    )

    assert first[0].model_dump(mode="json") == second[0].model_dump(mode="json")
    assert first[0].hook_visible is False
    assert first[0].hook_height_m is None
    assert first[0].load_attached is None
    assert first[0].distance_m % 5.0 == 0.0
    assert target.hook_position == [20.0, 0.0, 35.0]


def test_visible_neighbor_payload_does_not_expose_forbidden_fields() -> None:
    observer = _state("C1", [0.0, 0.0, 30.0])
    target = _state("C2", [10.0, 0.0, 30.0])

    neighbors = build_visible_neighbors(
        observer_state=observer,
        states_by_id={"C1": observer, "C2": target},
        neighbor_ids=["C2"],
        visibility=_visibility(neighbor_visibility_radius_m=20.0),
        decision_time_bucket=10,
    )

    payload_text = str(neighbors[0].model_dump(mode="json"))

    for forbidden in [
        "task_id",
        "deadline_s",
        "planned_start_s",
        "future_min_distance",
        "offline_ttc",
        "pickup",
        "dropoff",
    ]:
        assert forbidden not in payload_text


def test_missing_neighbor_state_raises_observation_build_error() -> None:
    observer = _state("C1", [0.0, 0.0, 30.0])

    with pytest.raises(ObservationBuildError) as exc_info:
        build_visible_neighbors(
            observer_state=observer,
            states_by_id={"C1": observer},
            neighbor_ids=["C2"],
            visibility=_visibility(),
            decision_time_bucket=10,
        )

    assert exc_info.value.error_code == "OBSERVATION_E_INVALID_STATE"
    assert exc_info.value.field_path == "states_by_id.C2"

