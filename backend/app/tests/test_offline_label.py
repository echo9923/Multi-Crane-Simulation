from __future__ import annotations

import json
import math

import pytest
from pydantic import ValidationError

from backend.app.schemas.config import RiskConfig
from backend.app.schemas.risk import (
    OFFLINE_LABEL_SCHEMA_VERSION,
    RISK_E_FUTURE_TRUTH_FORBIDDEN,
    OfflineFutureWindowLabel,
    OfflinePairRiskRecord,
    OfflineRiskAggregate,
    OfflineRiskLabel,
    OfflineRiskReport,
    RiskPairResult,
)


def _risk_config_payload(**overrides):
    payload = {
        "geometry_envelope": {
            "jib_radius_m": 0.5,
            "hook_radius_m": 0.5,
            "load_radius_m": 0.8,
        },
        "thresholds_m": {
            "low": 20.0,
            "medium": 12.0,
            "high": 8.0,
            "near_miss": 3.0,
        },
        "ttc_threshold_level": "high",
        "wind_safe_distance_factor": {
            "enabled": True,
            "extra_clearance_per_10m_s_wind_m": 2.0,
        },
    }
    payload.update(overrides)
    return payload


def _future_label(
    *,
    window_s: float,
    min_clearance: float,
    ttc_s: float | None,
    risk_level: str,
    collision_label: int,
):
    return {
        "window_s": window_s,
        "min_clearance_future_m": min_clearance,
        "ttc_s": ttc_s,
        "risk_level": risk_level,
        "collision_label": collision_label,
        "used_future_truth": True,
    }


def _offline_label_payload(**overrides):
    payload = {
        "episode_id": "ep-001",
        "scenario_id": "scenario-001",
        "frame": 7,
        "time_s": 3.5,
        "crane_i": "C1",
        "crane_j": "C2",
        "pair_id": "C1-C2",
        "distance_min_raw_now_m": 5.0,
        "clearance_min_now_m": 4.0,
        "distance_jib_jib_raw_now_m": 10.0,
        "clearance_jib_jib_now_m": 9.0,
        "distance_jib_i_hook_j_raw_now_m": 5.0,
        "clearance_jib_i_hook_j_now_m": 4.0,
        "distance_jib_j_hook_i_raw_now_m": 8.0,
        "clearance_jib_j_hook_i_now_m": 7.0,
        "distance_hook_hook_raw_now_m": 12.0,
        "clearance_hook_hook_now_m": 11.0,
        "min_clearance_future_5s_m": 2.0,
        "min_clearance_future_10s_m": -0.2,
        "ttc_5s_s": 4.0,
        "ttc_10s_s": 4.0,
        "risk_level_5s": "high",
        "risk_level_10s": "collision",
        "collision_label_5s": 0,
        "collision_label_10s": 1,
        "future_window_labels": {
            "5s": _future_label(
                window_s=5.0,
                min_clearance=2.0,
                ttc_s=4.0,
                risk_level="high",
                collision_label=0,
            ),
            "10s": _future_label(
                window_s=10.0,
                min_clearance=-0.2,
                ttc_s=4.0,
                risk_level="collision",
                collision_label=1,
            ),
            "15s": _future_label(
                window_s=15.0,
                min_clearance=-0.2,
                ttc_s=4.0,
                risk_level="collision",
                collision_label=1,
            ),
        },
        "used_future_truth": True,
    }
    payload.update(overrides)
    return payload


def test_offline_risk_label_schema_serializes_and_preserves_k2_fields() -> None:
    label = OfflineRiskLabel.model_validate(_offline_label_payload())

    dumped = label.model_dump(mode="json")

    assert label.schema_version == OFFLINE_LABEL_SCHEMA_VERSION
    assert dumped["episode_id"] == "ep-001"
    assert dumped["pair_id"] == "C1-C2"
    assert dumped["distance_min_raw_now_m"] == 5.0
    assert dumped["min_clearance_future_5s_m"] == 2.0
    assert dumped["collision_label_10s"] == 1
    assert dumped["future_window_labels"]["15s"]["used_future_truth"] is True
    json.dumps(dumped, ensure_ascii=False)


def test_offline_risk_label_rejects_extra_fields_and_non_finite_values() -> None:
    with pytest.raises(ValidationError):
        OfflineRiskLabel.model_validate(
            _offline_label_payload(offline_prompt_hint="not allowed")
        )

    with pytest.raises(ValidationError):
        OfflineRiskLabel.model_validate(
            _offline_label_payload(distance_min_raw_now_m=math.nan)
        )


def test_offline_risk_label_requires_future_truth_and_matching_pair_id() -> None:
    with pytest.raises(ValidationError):
        OfflineRiskLabel.model_validate(_offline_label_payload(used_future_truth=False))

    with pytest.raises(ValidationError):
        OfflineRiskLabel.model_validate(_offline_label_payload(pair_id="C2-C1"))


def test_offline_risk_label_validates_future_window_map_against_explicit_fields() -> None:
    payload = _offline_label_payload()
    payload["future_window_labels"]["5s"]["min_clearance_future_m"] = 99.0

    with pytest.raises(ValidationError):
        OfflineRiskLabel.model_validate(payload)

    payload = _offline_label_payload()
    payload["future_window_labels"]["5.0sec"] = payload["future_window_labels"].pop("5s")

    with pytest.raises(ValidationError):
        OfflineRiskLabel.model_validate(payload)


def test_offline_pair_risk_record_requires_same_episode_and_pair() -> None:
    label = OfflineRiskLabel.model_validate(_offline_label_payload())
    record = OfflinePairRiskRecord(
        episode_id="ep-001",
        scenario_id="scenario-001",
        crane_i="C1",
        crane_j="C2",
        pair_id="C1-C2",
        labels=[label],
    )

    assert record.labels[0].pair_id == "C1-C2"

    mismatched = OfflineRiskLabel.model_validate(
        _offline_label_payload(crane_i="C1", crane_j="C3", pair_id="C1-C3")
    )
    with pytest.raises(ValidationError):
        OfflinePairRiskRecord(
            episode_id="ep-001",
            scenario_id="scenario-001",
            crane_i="C1",
            crane_j="C2",
            pair_id="C1-C2",
            labels=[mismatched],
        )


def test_offline_risk_report_schema_supports_aggregate_statistics() -> None:
    report = OfflineRiskReport(
        total_labels=10,
        aggregates=[
            OfflineRiskAggregate(
                group_by="global",
                group_key="all",
                sample_count=10,
                positive_count_5s=1,
                positive_ratio_5s=0.1,
                positive_count_10s=2,
                positive_ratio_10s=0.2,
                risk_level_counts_5s={"safe": 9, "collision": 1},
                risk_level_counts_10s={"safe": 8, "collision": 2},
            )
        ],
        warnings=[],
    )

    dumped = report.model_dump(mode="json")

    assert dumped["aggregates"][0]["positive_ratio_10s"] == 0.2
    json.dumps(dumped, ensure_ascii=False)


def test_risk_config_future_windows_default_and_normalization() -> None:
    config = RiskConfig.model_validate(_risk_config_payload())

    assert config.future_windows_s == [5.0, 10.0, 15.0]

    config = RiskConfig.model_validate(
        _risk_config_payload(future_windows_s=[10.0, 5.0, 5.0, 15.0])
    )

    assert config.future_windows_s == [5.0, 10.0, 15.0]


@pytest.mark.parametrize("windows", [[], [0.0, 5.0, 10.0], [15.0], [5.0, 15.0]])
def test_risk_config_future_windows_rejects_invalid_values(windows) -> None:
    with pytest.raises(ValidationError):
        RiskConfig.model_validate(_risk_config_payload(future_windows_s=windows))


def test_online_risk_pair_still_rejects_future_truth() -> None:
    payload = {
        "pair_id": "C1-C2",
        "crane_id_a": "C1",
        "crane_id_b": "C2",
        "time_s": 1.0,
        "d_min_online_m": 10.0,
        "d_hat_min_m": 9.0,
        "ttc_hat_s": None,
        "d_safe_effective_m": 8.0,
        "base_threshold_m": 8.0,
        "wind_extra_m": 0.0,
        "risk_level": "safe",
        "nearest_object_a": "jib",
        "nearest_object_b": "hook",
        "relative_motion": "stable",
        "used_future_truth": True,
        "confidence": 1.0,
        "reasons": [],
    }

    with pytest.raises(ValidationError) as exc_info:
        RiskPairResult.model_validate(payload)

    assert RISK_E_FUTURE_TRUTH_FORBIDDEN in str(exc_info.value)
