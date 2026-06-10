from __future__ import annotations

from copy import deepcopy

import pytest

from backend.app.core.config_resolver import resolve_config
from backend.app.tests.test_config_schema import load_fixture


def _raw_auto(**layout_updates) -> dict:
    raw = load_fixture("scenario_valid.yaml")
    raw["layout"].update(layout_updates)
    return raw


def _resolve(scenario_raw: dict):
    return resolve_config(scenario_raw, load_fixture("experiment_valid.yaml"))


def _cranes(scenario_raw: dict):
    return _resolve(scenario_raw).layout.resolved_cranes


def _avg_overlap(resolved) -> float:
    pairs = resolved.layout.layout_diagnostics["pair_diagnostics"]
    return sum(pair["overlap_ratio"] for pair in pairs) / len(pairs)


def test_same_seed_and_config_generate_same_auto_layout() -> None:
    first = _resolve(_raw_auto())
    second = _resolve(_raw_auto())

    assert first.layout.resolved_cranes == second.layout.resolved_cranes


def test_different_seed_generates_different_auto_layout() -> None:
    baseline = _cranes(_raw_auto())
    changed = _raw_auto()
    changed["seed"] = 20260102

    assert _cranes(changed) != baseline


def test_auto_layout_quantity_boundary_forbidden_and_distance_constraints() -> None:
    resolved = _resolve(_raw_auto(num_cranes=6))
    boundary = _raw_auto()["site"]["boundary"]
    cranes = resolved.layout.resolved_cranes

    assert len(cranes) == 6
    for crane in cranes:
        x, y, z = crane["base"]
        assert boundary["x_min"] <= x <= boundary["x_max"]
        assert boundary["y_min"] <= y <= boundary["y_max"]
        assert boundary["z_min"] <= z <= boundary["z_max"]
        assert not (-10 <= x <= 10 and -10 <= y <= 10 and 0 <= z <= 40)

    for pair in resolved.layout.layout_diagnostics["pair_diagnostics"]:
        assert pair["base_distance_m"] >= 8.0


def test_low_overlap_average_is_below_high_overlap_average() -> None:
    low = _resolve(_raw_auto(num_cranes=3, overlap_level="low"))
    high = _resolve(_raw_auto(num_cranes=3, overlap_level="high"))

    assert _avg_overlap(low) < _avg_overlap(high)


def test_staggered_height_strategy_uses_minimum_height_delta() -> None:
    resolved = _resolve(
        _raw_auto(num_cranes=3, overlap_level="high", height_strategy="staggered")
    )

    for pair in resolved.layout.layout_diagnostics["pair_diagnostics"]:
        if pair["overlap_ratio"] > 0:
            assert pair["height_delta_m"] >= 6.0


def test_mixed_height_strategy_allows_both_close_and_staggered_pairs() -> None:
    resolved = _resolve(
        _raw_auto(num_cranes=4, overlap_level="high", height_strategy="mixed")
    )
    deltas = [
        pair["height_delta_m"]
        for pair in resolved.layout.layout_diagnostics["pair_diagnostics"]
        if pair["overlap_ratio"] > 0
    ]

    assert any(delta < 6.0 for delta in deltas)
    assert any(delta >= 6.0 for delta in deltas)


def test_coverage_target_affects_quality_subscores() -> None:
    wide = _resolve(_raw_auto(num_cranes=4, coverage_target="wide_coverage"))
    dense = _resolve(_raw_auto(num_cranes=4, coverage_target="dense_overlap"))

    wide_score = wide.layout.layout_diagnostics["coverage_score"]
    dense_score = dense.layout.layout_diagnostics["coverage_score"]

    assert wide_score > dense_score


def test_impossible_auto_layout_returns_lay_e_001() -> None:
    raw = _raw_auto(num_cranes=6, max_sampling_attempts=1)
    raw["site"]["boundary"] = {
        "x_min": -5,
        "x_max": 5,
        "y_min": -5,
        "y_max": 5,
        "z_min": 0,
        "z_max": 80,
    }

    with pytest.raises(Exception) as exc_info:
        _resolve(raw)

    error = exc_info.value
    assert getattr(error, "error_code") == "LAY_E_001"
    assert error.details["failure_counts_by_reason"]
    assert error.details["seed"]


def test_auto_layout_supports_two_cranes() -> None:
    resolved = _resolve(_raw_auto(num_cranes=2))

    assert len(resolved.layout.resolved_cranes) == 2
    assert len(resolved.layout.layout_diagnostics["pair_diagnostics"]) == 1
