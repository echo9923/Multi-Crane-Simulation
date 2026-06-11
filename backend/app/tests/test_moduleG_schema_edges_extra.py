from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from backend.app.schemas.command import (
    FORBIDDEN_COMMAND_SECRET_FIELDS,
    LLMMessage,
    OperatorDecisionResult,
    OperatorSession,
    RawLLMResponse,
    TokenUsage,
    build_neutral_stop_command,
)
from backend.app.schemas.enums import LLMProviderName, OperatorProfile, RiskPromptMode
from backend.app.schemas.observation import (
    AvailableActions,
    AxisCommand as ObservationAxisCommand,
    JoystickCommandSummary,
    LeftJoystickCommand as ObservationLeftJoystickCommand,
    MemorySummary,
    Observation,
    RightJoystickCommand as ObservationRightJoystickCommand,
    SelfStateSummary,
    TaskObservationSummary,
    WeatherObservationSummary,
)


def _observation() -> Observation:
    return Observation(
        observation_id="obs-001",
        source_snapshot_id="snap-001",
        operator_id="op-001",
        crane_id="C1",
        time_s=12.5,
        operator_profile=OperatorProfile.NORMAL,
        risk_prompt_mode=RiskPromptMode.R0,
        task=TaskObservationSummary(stage="idle", has_active_task=False),
        self_state=SelfStateSummary(
            slew_angle_deg=35.0,
            slew_motion="hold",
            trolley_r_m=20.0,
            hook_h_m=12.0,
            load_attached=False,
            load_weight_t=0.0,
            current_command=JoystickCommandSummary(
                left_joystick=ObservationLeftJoystickCommand(
                    slew=ObservationAxisCommand(direction="neutral", gear=0),
                    trolley=ObservationAxisCommand(direction="neutral", gear=0),
                ),
                right_joystick=ObservationRightJoystickCommand(
                    hoist=ObservationAxisCommand(direction="neutral", gear=0)
                ),
            ),
        ),
        weather=WeatherObservationSummary(
            wind_speed_m_s=3.0,
            gust_m_s=5.0,
            wind_direction_deg=90.0,
            visibility="good",
            visibility_confidence=0.9,
        ),
        available_actions=AvailableActions(),
        memory=MemorySummary(),
    )


def _raw_response(**overrides) -> RawLLMResponse:
    payload = {
        "response_id": "resp-001",
        "provider": LLMProviderName.MOCK,
        "model": "mock-command-v1",
        "observation_id": "obs-001",
        "source_snapshot_id": "snap-001",
        "operator_id": "op-001",
        "crane_id": "C1",
        "time_s": 12.5,
        "content": "{}",
        "raw_payload": {},
    }
    payload.update(overrides)
    return RawLLMResponse.model_validate(payload)


def _neutral_command():
    return build_neutral_stop_command(
        observation_id="obs-001",
        source_snapshot_id="snap-001",
        operator_id="op-001",
        crane_id="C1",
        time_s=12.5,
        command_id="cmd-neutral-001",
        response_id="resp-001",
        command_duration_s=1.0,
        reason="fallback",
    )


@pytest.mark.parametrize("field_name", sorted(FORBIDDEN_COMMAND_SECRET_FIELDS))
def test_llm_message_rejects_every_forbidden_secret_marker(field_name: str) -> None:
    with pytest.raises(ValidationError) as exc_info:
        LLMMessage(role="user", content=f"do not persist {field_name} here")

    assert "forbidden secret marker" in str(exc_info.value)
    assert field_name in str(exc_info.value).lower()


@pytest.mark.parametrize(
    ("usage_payload", "field_path"),
    [
        ({"prompt_tokens": -1}, ("prompt_tokens",)),
        ({"completion_tokens": -1}, ("completion_tokens",)),
        ({"total_tokens": -1}, ("total_tokens",)),
    ],
)
def test_token_usage_rejects_negative_counts(
    usage_payload: dict[str, int],
    field_path: tuple[str, ...],
) -> None:
    with pytest.raises(ValidationError) as exc_info:
        TokenUsage.model_validate(usage_payload)

    assert field_path in [error["loc"] for error in exc_info.value.errors()]


@pytest.mark.parametrize(
    ("session_payload", "field_path"),
    [
        ({"consecutive_failures": -1}, ("consecutive_failures",)),
        ({"decision_index": -1}, ("decision_index",)),
    ],
)
def test_operator_session_rejects_negative_counters(
    session_payload: dict[str, int],
    field_path: tuple[str, ...],
) -> None:
    payload = {
        "operator_id": "op-001",
        "crane_id": "C1",
        "profile": OperatorProfile.NORMAL,
        **session_payload,
    }

    with pytest.raises(ValidationError) as exc_info:
        OperatorSession.model_validate(payload)

    assert field_path in [error["loc"] for error in exc_info.value.errors()]


@pytest.mark.parametrize(
    "raw_payload",
    [
        {"outer": {"authorization": "Bearer value"}},
        {"choices": [{"message": {"token": "value"}}]},
        {"metadata": [{"nested": {"raw_api_key": "value"}}]},
    ],
)
def test_raw_response_rejects_nested_secret_field_names(raw_payload: dict) -> None:
    with pytest.raises(ValidationError) as exc_info:
        _raw_response(raw_payload=raw_payload)

    message = str(exc_info.value)
    assert "forbidden secret field" in message
    assert any(field in message.lower() for field in FORBIDDEN_COMMAND_SECRET_FIELDS)


def test_raw_response_allows_secret_like_values_when_field_names_are_safe() -> None:
    response = _raw_response(
        raw_payload={
            "id": "chatcmpl-001",
            "choices": [{"message": {"content": "sk-value only inside model text"}}],
        }
    )

    assert response.raw_payload["id"] == "chatcmpl-001"


@pytest.mark.parametrize("duration", [0.49, 3.01])
def test_neutral_stop_factory_reuses_parsed_command_duration_bounds(
    duration: float,
) -> None:
    with pytest.raises(ValidationError) as exc_info:
        build_neutral_stop_command(
            observation_id="obs-001",
            source_snapshot_id="snap-001",
            operator_id="op-001",
            crane_id="C1",
            time_s=12.5,
            command_id="cmd-neutral-001",
            command_duration_s=duration,
            reason="fallback",
        )

    assert ("command_duration_s",) in [error["loc"] for error in exc_info.value.errors()]


def test_operator_decision_result_rejects_unknown_episode_failure_reason() -> None:
    payload = {
        "observation": _observation().model_dump(mode="json"),
        "parsed_command": _neutral_command().model_dump(mode="json"),
        "call_records": [],
        "validation_errors": [],
        "provider": LLMProviderName.MOCK,
        "model": "mock-command-v1",
        "fallback_applied": True,
        "episode_failure_reason": "provider_unavailable",
    }

    with pytest.raises(ValidationError) as exc_info:
        OperatorDecisionResult.model_validate(payload)

    assert ("episode_failure_reason",) in [
        error["loc"] for error in exc_info.value.errors()
    ]


def test_operator_decision_result_forbids_extra_fields() -> None:
    payload = {
        "observation": _observation().model_dump(mode="json"),
        "parsed_command": _neutral_command().model_dump(mode="json"),
        "call_records": [],
        "validation_errors": [],
        "provider": LLMProviderName.MOCK,
        "model": "mock-command-v1",
        "fallback_applied": False,
        "uncontracted_metric": 123,
    }

    with pytest.raises(ValidationError) as exc_info:
        OperatorDecisionResult.model_validate(payload)

    assert ("uncontracted_metric",) in [error["loc"] for error in exc_info.value.errors()]


def test_command_schema_models_remain_json_serializable_at_edges() -> None:
    result = OperatorDecisionResult(
        observation=_observation(),
        parsed_command=_neutral_command(),
        call_records=[],
        validation_errors=[],
        provider=LLMProviderName.MOCK,
        model="mock-command-v1",
        fallback_applied=True,
        episode_failure_reason="llm_failed",
    )

    dumped = result.model_dump(mode="json")
    assert dumped["episode_failure_reason"] == "llm_failed"
    json.dumps(dumped, sort_keys=True)
