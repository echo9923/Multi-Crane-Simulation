from __future__ import annotations

from backend.app.sim.observation import build_visible_neighbors
from backend.app.tests.test_observation_visibility import _state, _visibility


def test_neighbor_at_exact_visibility_radius_is_still_visible() -> None:
    observer = _state("C1", [0.0, 0.0, 30.0])
    target = _state("C2", [30.0, 40.0, 33.0], load_attached=True)

    neighbors = build_visible_neighbors(
        observer_state=observer,
        states_by_id={"C1": observer, "C2": target},
        neighbor_ids=["C2"],
        visibility=_visibility(
            neighbor_visibility_radius_m=50.0,
            distance_noise_m=0.0,
            hide_hook_prob=0.0,
            distance_precision_m=1.0,
        ),
        decision_time_bucket=10,
    )

    assert len(neighbors) == 1
    assert neighbors[0].distance_m == 50.0
    assert neighbors[0].in_overlap_zone is True
    assert neighbors[0].hook_height_m == 33.0
    assert neighbors[0].load_attached is True


def test_neighbor_beyond_radius_is_filtered_before_distance_noise() -> None:
    observer = _state("C1", [0.0, 0.0, 30.0])
    target = _state("C2", [51.0, 0.0, 30.0])

    neighbors = build_visible_neighbors(
        observer_state=observer,
        states_by_id={"C1": observer, "C2": target},
        neighbor_ids=["C2"],
        visibility=_visibility(
            neighbor_visibility_radius_m=50.0,
            distance_noise_m=100.0,
            hide_hook_prob=0.0,
            distance_precision_m=1.0,
        ),
        decision_time_bucket=10,
    )

    assert neighbors == []


def test_neighbor_sampling_changes_when_decision_bucket_changes() -> None:
    observer = _state("C1", [0.0, 0.0, 30.0])
    target = _state("C2", [37.0, 0.0, 30.0])
    visibility = _visibility(
        neighbor_visibility_radius_m=100.0,
        distance_noise_m=10.0,
        hide_hook_prob=0.5,
        distance_precision_m=0.5,
        noise_seed=20260611,
    )

    buckets = {
        bucket: build_visible_neighbors(
            observer_state=observer,
            states_by_id={"C1": observer, "C2": target},
            neighbor_ids=["C2"],
            visibility=visibility,
            decision_time_bucket=bucket,
        )[0].model_dump(mode="json")
        for bucket in range(20, 35)
    }

    assert len({(item["distance_m"], item["hook_visible"]) for item in buckets.values()}) > 1


def test_visible_neighbors_allow_duplicate_candidate_ids_without_duplicate_output() -> None:
    observer = _state("C1", [0.0, 0.0, 30.0])
    target = _state("C2", [20.0, 0.0, 30.0])

    neighbors = build_visible_neighbors(
        observer_state=observer,
        states_by_id={"C1": observer, "C2": target},
        neighbor_ids=["C2", "C2"],
        visibility=_visibility(neighbor_visibility_radius_m=100.0),
        decision_time_bucket=10,
    )

    assert [neighbor.crane_id for neighbor in neighbors] == ["C2"]

