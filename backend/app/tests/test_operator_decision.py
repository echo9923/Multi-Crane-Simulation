from __future__ import annotations

import json

import pytest

from backend.app.schemas.command import (
    LLMMessage,
    OperatorSession,
    ParsedCommand,
    RawLLMResponse,
)
from backend.app.schemas.config import ExperimentConfig
from backend.app.schemas.enums import LLMProviderName, OperatorProfile, RiskPromptMode
from backend.app.schemas.observation import (
    AvailableActions,
    JoystickCommandSummary,
    LeftJoystickCommand as ObservationLeftJoystickCommand,
    MemorySummary,
    Observation,
    RightJoystickCommand as ObservationRightJoystickCommand,
    AxisCommand as ObservationAxisCommand,
    SelfStateSummary,
    TaskObservationSummary,
    WeatherObservationSummary,
)
from backend.app.sim.llm_provider import (
    ProviderAPIError,
    ProviderRequest,
    ProviderResult,
    ProviderTimeoutError,
)
from backend.app.sim.operator_decision import decide_with_retry
from backend.app.tests.test_config_schema import load_fixture


class ScriptedProvider:
    provider_name = LLMProviderName.MOCK

    def __init__(self, outcomes: list[RawLLMResponse | Exception]) -> None:
        self.outcomes = list(outcomes)
        self.requests: list[ProviderRequest] = []

    def generate(self, request: ProviderRequest) -> ProviderResult:
        self.requests.append(request)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return ProviderResult(raw_response=outcome)


def _config(*, max_retries: int = 1, max_consecutive_failures: int = 2):
    raw = load_fixture("experiment_valid.yaml")
    raw["llm"]["provider"] = "mock"
    raw["llm"]["model"] = "mock-command-v1"
    raw["llm"]["max_retries"] = max_retries
    raw["llm"]["max_consecutive_failures"] = max_consecutive_failures
    return ExperimentConfig.model_validate(raw).llm


def _observation() -> Observation:
    return Observation(
        observation_id="obs-001",
        source_snapshot_id="snap-001",
        operator_id="op-001",
        crane_id="C1",
        time_s=12.5,
        operator_profile=OperatorProfile.NORMAL,
        risk_prompt_mode=RiskPromptMode.R0,
        task=TaskObservationSummary(
            stage="move_to_pickup",
            has_active_task=True,
            current_target_relative_direction="right_front",
            current_target_distance_m=18.5,
        ),
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


def _session(*, consecutive_failures: int = 0) -> OperatorSession:
    return OperatorSession(
        operator_id="op-001",
        crane_id="C1",
        profile=OperatorProfile.NORMAL,
        consecutive_failures=consecutive_failures,
    )


def _raw_response(content: str, *, response_id: str = "resp-001") -> RawLLMResponse:
    observation = _observation()
    return RawLLMResponse(
        response_id=response_id,
        provider=LLMProviderName.MOCK,
        model="mock-command-v1",
        observation_id=observation.observation_id,
        source_snapshot_id=observation.source_snapshot_id,
        operator_id=observation.operator_id,
        crane_id=observation.crane_id,
        time_s=observation.time_s,
        content=content,
    )


def _valid_content(**overrides) -> str:
    payload = {
        "left_joystick": {
            "slew": {"direction": "left", "gear": 1},
            "trolley": {"direction": "neutral", "gear": 0},
        },
        "right_joystick": {"hoist": {"direction": "neutral", "gear": 0}},
        "deadman_pressed": True,
        "emergency_stop": False,
        "horn": False,
        "command_duration_s": 1.0,
        "task_action": "none",
        "attention_target": "pickup_area",
        "confidence": 0.8,
        "reason": "valid command",
    }
    payload.update(overrides)
    return json.dumps(payload, ensure_ascii=False)


def test_decide_with_retry_returns_success_without_retry_and_resets_failures() -> None:
    provider = ScriptedProvider([_raw_response(_valid_content())])
    session = _session(consecutive_failures=1)

    result = decide_with_retry(
        _observation(),
        provider=provider,
        config=_config(max_retries=1),
        session=session,
    )

    assert result.parsed_command.left_joystick.slew.direction == "left"
    assert result.fallback_applied is False
    assert result.episode_failure_reason is None
    assert session.consecutive_failures == 0
    assert session.decision_index == 1
    assert len(provider.requests) == 1
    assert len(result.call_records) == 1
    assert result.call_records[0].parsed_command == result.parsed_command


def test_invalid_json_retry_includes_validation_error_and_then_succeeds() -> None:
    provider = ScriptedProvider(
        [
            _raw_response("not json", response_id="resp-bad"),
            _raw_response(_valid_content(), response_id="resp-good"),
        ]
    )
    session = _session()

    result = decide_with_retry(
        _observation(),
        provider=provider,
        config=_config(max_retries=1),
        session=session,
    )

    assert result.fallback_applied is False
    assert result.parsed_command.response_id == "resp-good"
    assert len(provider.requests) == 2
    assert "validation errors" in provider.requests[1].messages[-1].content
    assert "LLM response must be a single JSON object" in provider.requests[1].messages[-1].content
    assert result.validation_errors
    assert result.call_records[0].parsed_command is None
    assert result.call_records[1].parsed_command == result.parsed_command


def test_provider_timeout_retries_and_then_succeeds() -> None:
    provider = ScriptedProvider(
        [
            ProviderTimeoutError("timeout"),
            _raw_response(_valid_content(), response_id="resp-good"),
        ]
    )

    result = decide_with_retry(
        _observation(),
        provider=provider,
        config=_config(max_retries=1),
        session=_session(),
    )

    assert result.parsed_command.response_id == "resp-good"
    assert len(provider.requests) == 2
    assert result.validation_errors[0].message == "timeout"


def test_retry_exhaustion_returns_neutral_stop_and_increments_failures() -> None:
    provider = ScriptedProvider([_raw_response("not json", response_id="resp-bad")])
    session = _session()

    result = decide_with_retry(
        _observation(),
        provider=provider,
        config=_config(max_retries=0, max_consecutive_failures=2),
        session=session,
    )

    command = result.parsed_command
    assert result.fallback_applied is True
    assert result.episode_failure_reason is None
    assert session.consecutive_failures == 1
    assert command.left_joystick.slew.direction == "neutral"
    assert command.left_joystick.slew.gear == 0
    assert command.right_joystick.hoist.direction == "neutral"
    assert command.deadman_pressed is True
    assert command.emergency_stop is False
    assert command.task_action == "none"
    assert command.fallback_reason is not None


def test_consecutive_failures_at_threshold_mark_llm_failed() -> None:
    provider = ScriptedProvider([ProviderAPIError("bad gateway")])
    session = _session(consecutive_failures=1)

    result = decide_with_retry(
        _observation(),
        provider=provider,
        config=_config(max_retries=0, max_consecutive_failures=2),
        session=session,
    )

    assert result.fallback_applied is True
    assert result.episode_failure_reason == "llm_failed"
    assert session.consecutive_failures == 2


def test_unknown_provider_exception_still_falls_back_after_retries() -> None:
    provider = ScriptedProvider([RuntimeError("unexpected provider failure")])

    result = decide_with_retry(
        _observation(),
        provider=provider,
        config=_config(max_retries=0, max_consecutive_failures=1),
        session=_session(),
    )

    assert result.fallback_applied is True
    assert result.episode_failure_reason == "llm_failed"
    assert result.validation_errors[0].message == "unexpected provider failure"
