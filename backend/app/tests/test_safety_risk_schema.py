from __future__ import annotations

import json
import math

import pytest
from pydantic import ValidationError

from backend.app.schemas.command import (
    ExecutedCommand,
    ParsedCommand,
    build_neutral_stop_command,
)
from backend.app.schemas.enums import ForbiddenZonePolicyMode, SafetyMode
from backend.app.schemas.observation import OnlineRiskHint
from backend.app.schemas.risk import (
    COLLISION_E_GEOMETRY_OVERLAP,
    RISK_E_FUTURE_TRUTH_FORBIDDEN,
    SAFETY_E_INVALID_STATE,
    CollisionEvent,
    ForbiddenZoneResult,
    InterventionRecord,
    MechanicalLimitResult,
    OnlineRisk,
    RiskPairResult,
    SafetyEvent,
    SafetyPipelineResult,
)


def _raw_command() -> ParsedCommand:
    return ParsedCommand(
        command_id="cmd-raw-001",
        response_id="resp-001",
        observation_id="obs-001",
        source_snapshot_id="snap-001",
        operator_id="op-001",
        crane_id="C1",
        time_s=12.5,
        left_joystick={
            "slew": {"direction": "left", "gear": 2},
            "trolley": {"direction": "out", "gear": 1},
        },
        right_joystick={"hoist": {"direction": "neutral", "gear": 0}},
        deadman_pressed=True,
        emergency_stop=False,
        horn=False,
        command_duration_s=1.0,
        task_action="none",
        attention_target="pickup",
        confidence=0.8,
        reason="normal operation",
    )


def _mechanical_result(*, modified: bool = False) -> MechanicalLimitResult:
    return MechanicalLimitResult(
        crane_id="C1",
        modified=modified,
        applied_limits=["trolley_limit"] if modified else [],
        blocked_axes=["trolley"] if modified else [],
        clamped_axes=["trolley"] if modified else [],
        events=[
            SafetyEvent(
                event_id="evt-mech-001",
                event_type="mechanical_limit",
                time_s=12.5,
                crane_id="C1",
                reason="trolley_limit",
            )
        ]
        if modified
        else [],
    )


def _risk_pair(**overrides) -> RiskPairResult:
    payload = {
        "pair_id": "C1-C2",
        "crane_id_a": "C1",
        "crane_id_b": "C2",
        "time_s": 12.5,
        "d_min_online_m": 9.5,
        "d_hat_min_m": 7.0,
        "ttc_hat_s": 3.0,
        "d_safe_effective_m": 8.0,
        "base_threshold_m": 6.0,
        "wind_extra_m": 2.0,
        "risk_level": "high",
        "nearest_object_a": "hook",
        "nearest_object_b": "jib",
        "relative_motion": "closing",
        "confidence": 0.75,
        "reasons": ["short_horizon_closing"],
    }
    payload.update(overrides)
    return RiskPairResult.model_validate(payload)


def _online_risk() -> OnlineRisk:
    return OnlineRisk(
        risk_id="risk-001",
        source_snapshot_id="snap-001",
        time_s=12.5,
        pairs=[_risk_pair()],
        global_risk_level="high",
        nearest_pair_id="C1-C2",
        nearest_neighbor_by_crane={"C1": "C2", "C2": "C1"},
        hint_by_crane={
            "C1": OnlineRiskHint(
                source="online_risk",
                risk_level="high",
                nearest_neighbor="C2",
                nearest_object_type="hook",
                clearance_now_m=9.5,
                estimated_clearance_next_5s_m=7.0,
                relative_motion="closing",
                confidence=0.75,
                suggestion="slow down",
            )
        },
    )


def test_executed_command_preserves_raw_command_and_serializes() -> None:
    raw = _raw_command()
    command = ExecutedCommand(
        command_id="exec-001",
        raw_command_id=raw.command_id,
        observation_id=raw.observation_id,
        source_snapshot_id=raw.source_snapshot_id,
        operator_id=raw.operator_id,
        crane_id=raw.crane_id,
        time_s=raw.time_s,
        raw_command=raw,
        left_joystick={
            "slew": {"direction": "left", "gear": 2, "source": "raw"},
            "trolley": {"direction": "out", "gear": 1, "source": "raw"},
        },
        right_joystick={
            "hoist": {"direction": "neutral", "gear": 0, "source": "raw"}
        },
        deadman_pressed=True,
        emergency_stop=False,
        horn=False,
        command_duration_s=1.0,
        task_action="none",
        modified=False,
    )

    assert command.raw_command_id == raw.command_id
    assert command.raw_command.command_id == raw.command_id
    assert command.modified is False
    assert command.modification_reasons == []
    json.dumps(command.model_dump(mode="json"), ensure_ascii=False)


def test_executed_command_requires_reasons_when_modified() -> None:
    raw = _raw_command()

    with pytest.raises(ValidationError):
        ExecutedCommand(
            command_id="exec-001",
            raw_command_id=raw.command_id,
            observation_id=raw.observation_id,
            source_snapshot_id=raw.source_snapshot_id,
            operator_id=raw.operator_id,
            crane_id=raw.crane_id,
            time_s=raw.time_s,
            raw_command=raw,
            left_joystick={
                "slew": {"direction": "neutral", "gear": 0, "source": "mechanical_limit"},
                "trolley": {
                    "direction": "neutral",
                    "gear": 0,
                    "source": "mechanical_limit",
                },
            },
            right_joystick={
                "hoist": {"direction": "neutral", "gear": 0, "source": "mechanical_limit"}
            },
            deadman_pressed=True,
            emergency_stop=False,
            horn=False,
            command_duration_s=1.0,
            task_action="none",
            modified=True,
        )


def test_executed_command_forbids_extra_fields_recursively() -> None:
    raw = _raw_command()
    payload = {
        "command_id": "exec-001",
        "raw_command_id": raw.command_id,
        "observation_id": raw.observation_id,
        "source_snapshot_id": raw.source_snapshot_id,
        "operator_id": raw.operator_id,
        "crane_id": raw.crane_id,
        "time_s": raw.time_s,
        "raw_command": raw.model_dump(mode="json"),
        "left_joystick": {
            "slew": {
                "direction": "left",
                "gear": 2,
                "source": "raw",
                "unexpected": "nope",
            },
            "trolley": {"direction": "out", "gear": 1, "source": "raw"},
        },
        "right_joystick": {
            "hoist": {"direction": "neutral", "gear": 0, "source": "raw"}
        },
        "deadman_pressed": True,
        "emergency_stop": False,
        "horn": False,
        "command_duration_s": 1.0,
        "task_action": "none",
        "modified": False,
    }

    with pytest.raises(ValidationError):
        ExecutedCommand.model_validate(payload)


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("time_s", math.nan),
        ("command_duration_s", math.inf),
    ],
)
def test_executed_command_rejects_nan_and_inf(field_name: str, value: float) -> None:
    raw = _raw_command()
    payload = {
        "command_id": "exec-001",
        "raw_command_id": raw.command_id,
        "observation_id": raw.observation_id,
        "source_snapshot_id": raw.source_snapshot_id,
        "operator_id": raw.operator_id,
        "crane_id": raw.crane_id,
        "time_s": raw.time_s,
        "raw_command": raw.model_dump(mode="json"),
        "left_joystick": {
            "slew": {"direction": "left", "gear": 2, "source": "raw"},
            "trolley": {"direction": "out", "gear": 1, "source": "raw"},
        },
        "right_joystick": {
            "hoist": {"direction": "neutral", "gear": 0, "source": "raw"}
        },
        "deadman_pressed": True,
        "emergency_stop": False,
        "horn": False,
        "command_duration_s": 1.0,
        "task_action": "none",
        "modified": False,
    }
    payload[field_name] = value

    with pytest.raises(ValidationError):
        ExecutedCommand.model_validate(payload)


def test_risk_pair_result_defaults_future_truth_to_false() -> None:
    pair = _risk_pair(used_future_truth=False)

    assert pair.used_future_truth is False
    assert pair.risk_level == "high"
    assert pair.ttc_hat_s == 3.0


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("d_min_online_m", -0.01),
        ("d_hat_min_m", -0.01),
        ("ttc_hat_s", -0.01),
        ("d_safe_effective_m", 0.0),
        ("base_threshold_m", 0.0),
        ("wind_extra_m", -0.01),
        ("confidence", 1.01),
        ("risk_level", "critical"),
        ("nearest_object_a", "boom"),
    ],
)
def test_risk_pair_result_rejects_out_of_contract_values(
    field_name: str, value: object
) -> None:
    with pytest.raises(ValidationError):
        _risk_pair(**{field_name: value})


def test_risk_pair_result_rejects_future_truth_marker() -> None:
    with pytest.raises(ValidationError):
        _risk_pair(used_future_truth=True)


def test_online_risk_exports_pairs_and_hint_contract() -> None:
    risk = _online_risk()

    assert len(risk.pairs) == 1
    assert risk.global_risk_level == "high"
    assert risk.nearest_neighbor_by_crane["C1"] == "C2"
    assert risk.hint_by_crane["C1"].source == "online_risk"
    json.dumps(risk.model_dump(mode="json"), ensure_ascii=False)


def test_safety_result_schemas_forbid_extra_fields() -> None:
    with pytest.raises(ValidationError):
        MechanicalLimitResult.model_validate(
            {"crane_id": "C1", "modified": False, "unexpected": True}
        )

    with pytest.raises(ValidationError):
        ForbiddenZoneResult.model_validate(
            {
                "crane_id": "C1",
                "policy_mode": "task_only",
                "violation_detected": False,
                "blocked": False,
                "unexpected": True,
            }
        )


def test_intervention_and_collision_event_contracts() -> None:
    intervention = InterventionRecord(
        intervention_id="int-001",
        crane_id="C1",
        safety_mode=SafetyMode.S2,
        risk_level="high",
        action="limit_speed_on_high_risk",
        modified=True,
        reason="closing pair",
        pair_ids=["C1-C2"],
    )
    collision = CollisionEvent(
        event_id="col-001",
        source_snapshot_id="snap-001",
        time_s=12.5,
        crane_id_a="C1",
        crane_id_b="C2",
        object_a="hook",
        object_b="hook",
        distance_m=0.0,
        reason="hook overlap",
    )

    assert intervention.safety_mode is SafetyMode.S2
    assert collision.episode_status == "failed_collision"

    with pytest.raises(ValidationError):
        CollisionEvent(
            event_id="col-001",
            source_snapshot_id="snap-001",
            time_s=12.5,
            crane_id_a="C1",
            crane_id_b="C2",
            object_a="hook",
            object_b="hook",
            distance_m=0.0,
            episode_status="running",
            reason="hook overlap",
        )


def test_safety_pipeline_result_aggregates_outputs() -> None:
    raw = build_neutral_stop_command(
        observation_id="obs-001",
        source_snapshot_id="snap-001",
        operator_id="op-001",
        crane_id="C1",
        time_s=12.5,
        command_id="cmd-raw-001",
        reason="fixture",
    )
    executed = ExecutedCommand.from_raw(
        command_id="exec-001",
        raw_command=raw,
        mechanical_limit=_mechanical_result(modified=False),
    )
    result = SafetyPipelineResult(
        source_snapshot_id="snap-001",
        time_s=12.5,
        executed_commands=[executed],
        online_risk=OnlineRisk(
            risk_id="risk-001",
            source_snapshot_id="snap-001",
            time_s=12.5,
            pairs=[],
            global_risk_level="safe",
        ),
        episode_status="running",
    )

    assert result.executed_commands[0].raw_command_id == "cmd-raw-001"
    assert result.online_risk.global_risk_level == "safe"


def test_error_code_constants_are_stable() -> None:
    assert SAFETY_E_INVALID_STATE.startswith("SAFETY_")
    assert RISK_E_FUTURE_TRUTH_FORBIDDEN.startswith("RISK_")
    assert COLLISION_E_GEOMETRY_OVERLAP.startswith("COLLISION_")
    assert SAFETY_E_INVALID_STATE == "SAFETY_E_INVALID_STATE"
    assert RISK_E_FUTURE_TRUTH_FORBIDDEN == "RISK_E_FUTURE_TRUTH_FORBIDDEN"
    assert COLLISION_E_GEOMETRY_OVERLAP == "COLLISION_E_GEOMETRY_OVERLAP"


def test_forbidden_zone_result_accepts_existing_policy_enum() -> None:
    result = ForbiddenZoneResult(
        crane_id="C1",
        policy_mode=ForbiddenZonePolicyMode.TASK_ONLY,
        violation_detected=True,
        blocked=False,
        zone_ids=["Z1"],
    )

    assert result.policy_mode is ForbiddenZonePolicyMode.TASK_ONLY
