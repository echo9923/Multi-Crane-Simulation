from __future__ import annotations

import pytest

from backend.app.core.config_resolver import resolve_config
from backend.app.sim.auto_layout import AutoLayoutError
from backend.app.tests.test_config_schema import load_fixture


def _auto_raw(**layout_updates) -> dict:
    raw = load_fixture("scenario_valid.yaml")
    raw["layout"].update(layout_updates)
    return raw


def _resolve(raw: dict):
    return resolve_config(raw, load_fixture("experiment_valid.yaml"))


def test_auto_layout_diagnostics_include_reachability_warning_summary() -> None:
    resolved = _resolve(_auto_raw(num_cranes=3))

    warnings = resolved.layout.layout_diagnostics["warnings"]
    assert any(warning["reason"] == "layout_reachability_report" for warning in warnings)
    assert all("task_id" not in str(warning) for warning in warnings)


def test_auto_layout_pair_diagnostics_have_stable_crane_id_pairs() -> None:
    resolved = _resolve(_auto_raw(num_cranes=4))

    pair_ids = {
        (pair["crane_id_a"], pair["crane_id_b"])
        for pair in resolved.layout.layout_diagnostics["pair_diagnostics"]
    }

    assert pair_ids == {
        ("C1", "C2"),
        ("C1", "C3"),
        ("C1", "C4"),
        ("C2", "C3"),
        ("C2", "C4"),
        ("C3", "C4"),
    }


def test_auto_layout_quality_score_matches_weighted_subscores() -> None:
    diagnostics = _resolve(_auto_raw(num_cranes=3)).layout.layout_diagnostics

    expected = (
        diagnostics["overlap_target_score"] * 0.40
        + diagnostics["coverage_score"] * 0.30
        + diagnostics["height_strategy_score"] * 0.20
        + diagnostics["boundary_margin_score"] * 0.10
    )
    assert diagnostics["quality_score"] == pytest.approx(expected)


def test_auto_layout_impossible_height_reachability_reports_failure_counts() -> None:
    raw = _auto_raw(num_cranes=2, max_sampling_attempts=3)
    raw["site"]["work_zones"][0]["z_range_m"] = [79.0, 80.0]

    with pytest.raises(AutoLayoutError) as exc_info:
        _resolve(raw)

    error = exc_info.value
    assert error.error_code == "LAY_E_001"
    assert error.details["attempts"] == 3
    failure_counts = error.details["failure_counts_by_reason"]
    assert failure_counts["task_reachability_precheck_failed"] >= 1
    assert sum(failure_counts.values()) == 3
