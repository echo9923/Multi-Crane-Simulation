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
from backend.app.schemas.enums import (
    LLMProviderName,
    OperatorProfile,
    RiskPromptMode,
)
from backend.app.schemas.observation import (
    AvailableActions,
    AxisCommand as ObservationAxisCommand,
    JoystickCommandSummary,
    LeftJoystickCommand as ObservationLeftJoystickCommand,
    MemorySummary,
    Observation,
    RecentDecisionSummary,
    RightJoystickCommand as ObservationRightJoystickCommand,
    SelfStateSummary,
    TaskObservationSummary,
    WeatherObservationSummary,
)
from backend.app.sim.llm_provider import ProviderRequest, ProviderResult
from backend.app.sim.operator_decision import (
    OperatorDecisionOrchestrator,
    OperatorDecisionOrchestratorError,
    decide_with_retry,
)
from backend.app.tests.test_config_schema import load_fixture


class ScriptedProvider:
    provider_name = LLMProviderName.MOCK

    def __init__(self, outcomes: list[RawLLMResponse | ParsedCommand | Exception]) -> None:
        self.outcomes = list(outcomes)
        self.requests: list[ProviderRequest] = []

    def generate(self, request: ProviderRequest) -> ProviderResult:
        self.requests.append(request)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        if isinstance(outcome, ParsedCommand):
            return ProviderResult(replay_command=outcome)
        return ProviderResult(raw_response=outcome)


class CountingProvider:
    provider_name = LLMProviderName.MOCK

    def __init__(self) -> None:
        self.requests: list[ProviderRequest] = []

    def generate(self, request: ProviderRequest) -> ProviderResult:
        self.requests.append(request)
        return ProviderResult(raw_response=_raw_response(_valid_content(), request.observation))


def _config(
    *,
    max_retries: int = 1,
    max_consecutive_failures: int = 2,
    history_mode: str = "none",
    recent_decisions_full: int = 2,
):
    raw = load_fixture("experiment_valid.yaml")
    raw["llm"]["provider"] = "mock"
    raw["llm"]["model"] = "mock-command-v1"
    raw["llm"]["max_retries"] = max_retries
    raw["llm"]["max_consecutive_failures"] = max_consecutive_failures
    raw["llm"]["context"]["history_mode"] = history_mode
    raw["llm"]["context"]["recent_decisions_full"] = recent_decisions_full
    return ExperimentConfig.model_validate(raw).llm


def _observation(
    crane_id: str = "C1",
    *,
    operator_id: str | None = None,
    profile: OperatorProfile = OperatorProfile.NORMAL,
    time_s: float = 12.5,
) -> Observation:
    return Observation(
        observation_id=f"obs-{crane_id}",
        source_snapshot_id="snap-001",
        operator_id=operator_id or f"op-{crane_id}",
        crane_id=crane_id,
        time_s=time_s,
        operator_profile=profile,
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
        memory=MemorySummary(
            task_history_summary="one completed task",
            recent_decisions=[
                RecentDecisionSummary(
                    time_s=10.0,
                    command_summary="recent neutral",
                    result="stable",
                )
            ],
            event_summary=["risk cleared"],
        ),
    )


def _session(*, consecutive_failures: int = 0, decision_index: int = 0) -> OperatorSession:
    return OperatorSession(
        operator_id="op-C1",
        crane_id="C1",
        profile=OperatorProfile.NORMAL,
        consecutive_failures=consecutive_failures,
        decision_index=decision_index,
    )


def _valid_payload(*, crane_id: str = "C1", attention_target: str = "pickup_area") -> dict:
    return {
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
        "attention_target": attention_target,
        "confidence": 0.8,
        "reason": f"command for {crane_id}",
    }


def _valid_content(**overrides) -> str:
    payload = _valid_payload()
    payload.update(overrides)
    return json.dumps(payload, ensure_ascii=False)


def _raw_response(
    content: str,
    observation: Observation | None = None,
    *,
    response_id: str = "resp-001",
) -> RawLLMResponse:
    observation = observation or _observation()
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


def _replay_command(observation: Observation | None = None) -> ParsedCommand:
    observation = observation or _observation()
    payload = _valid_payload(
        crane_id=observation.crane_id,
        attention_target=f"replay-{observation.crane_id}",
    )
    payload.update(
        {
            "command_id": "cmd-replay-001",
            "response_id": "resp-replay-001",
            "observation_id": observation.observation_id,
            "source_snapshot_id": observation.source_snapshot_id,
            "operator_id": observation.operator_id,
            "crane_id": observation.crane_id,
            "time_s": observation.time_s,
        }
    )
    return ParsedCommand.model_validate(payload)


def test_decide_with_retry_honors_max_retries_as_additional_attempts() -> None:
    provider = ScriptedProvider(
        [
            _raw_response("not json", response_id="resp-bad-0"),
            _raw_response("not json", response_id="resp-bad-1"),
            _raw_response("not json", response_id="resp-bad-2"),
        ]
    )
    session = _session()

    result = decide_with_retry(
        _observation(),
        provider=provider,
        config=_config(max_retries=2, max_consecutive_failures=3),
        session=session,
    )

    assert result.fallback_applied is True
    assert [request.attempt_index for request in provider.requests] == [0, 1, 2]
    assert [record.attempt_index for record in result.call_records] == [0, 1, 2]
    assert session.consecutive_failures == 1
    assert session.decision_index == 1


def test_decide_with_retry_accepts_replay_command_without_raw_parse() -> None:
    observation = _observation()
    replay_command = _replay_command(observation)
    provider = ScriptedProvider([replay_command])

    result = decide_with_retry(
        observation,
        provider=provider,
        config=_config(max_retries=2),
        session=_session(),
    )

    assert result.fallback_applied is False
    assert result.parsed_command == replay_command
    assert result.call_records[0].raw_response is None
    assert result.call_records[0].parsed_command == replay_command
    assert len(provider.requests) == 1


def test_context_messages_are_inserted_after_system_message_on_every_attempt() -> None:
    context_message = LLMMessage(role="assistant", content="prior neutral summary")
    provider = ScriptedProvider(
        [
            _raw_response("not json", response_id="resp-bad"),
            _raw_response(_valid_content(), response_id="resp-good"),
        ]
    )

    result = decide_with_retry(
        _observation(),
        provider=provider,
        config=_config(max_retries=1),
        session=_session(),
        context_messages=[context_message],
    )

    assert result.fallback_applied is False
    for request in provider.requests:
        assert request.messages[0].role == "system"
        assert request.messages[1] == context_message
        assert request.messages[2].role == "user"
    for record in result.call_records:
        assert record.messages[1] == context_message


def test_fallback_command_keeps_last_raw_response_id_from_parse_failure() -> None:
    provider = ScriptedProvider([_raw_response("not json", response_id="resp-last")])

    result = decide_with_retry(
        _observation(),
        provider=provider,
        config=_config(max_retries=0, max_consecutive_failures=1),
        session=_session(),
    )

    assert result.fallback_applied is True
    assert result.parsed_command.response_id == "resp-last"
    assert result.parsed_command.command_id == "cmd-neutral-obs-C1"


def test_success_after_previous_failures_resets_counter_and_increments_index() -> None:
    provider = ScriptedProvider([_raw_response(_valid_content(), response_id="resp-good")])
    session = _session(consecutive_failures=2, decision_index=7)

    result = decide_with_retry(
        _observation(),
        provider=provider,
        config=_config(max_retries=0),
        session=session,
    )

    assert result.fallback_applied is False
    assert session.consecutive_failures == 0
    assert session.decision_index == 8


def test_orchestrator_empty_batch_returns_empty_without_provider_call() -> None:
    provider = CountingProvider()
    orchestrator = OperatorDecisionOrchestrator(
        config=_config(),
        provider=provider,
        operator_profiles={"C1": OperatorProfile.NORMAL},
    )

    assert orchestrator.decide([], llm_decision_interval_s=1.0) == []
    assert provider.requests == []


@pytest.mark.parametrize("interval", [0.0, -1.0])
def test_orchestrator_rejects_non_positive_decision_interval(interval: float) -> None:
    orchestrator = OperatorDecisionOrchestrator(
        config=_config(),
        provider=CountingProvider(),
        operator_profiles={"C1": OperatorProfile.NORMAL},
    )

    with pytest.raises(OperatorDecisionOrchestratorError):
        orchestrator.should_decide(
            crane_id="C1",
            time_s=12.0,
            llm_decision_interval_s=interval,
        )
    with pytest.raises(OperatorDecisionOrchestratorError):
        orchestrator.decide([_observation()], llm_decision_interval_s=interval)


def test_orchestrator_session_profile_uses_assignment_not_observation_profile() -> None:
    orchestrator = OperatorDecisionOrchestrator(
        config=_config(),
        provider=CountingProvider(),
        operator_profiles={"C1": OperatorProfile.AGGRESSIVE},
    )

    session = orchestrator.get_session("C1", "op-C1")

    assert session.profile is OperatorProfile.AGGRESSIVE
    assert _observation(profile=OperatorProfile.CONSERVATIVE).operator_profile is OperatorProfile.CONSERVATIVE


def test_orchestrator_trims_session_history_to_configured_limit() -> None:
    provider = CountingProvider()
    orchestrator = OperatorDecisionOrchestrator(
        config=_config(history_mode="short", recent_decisions_full=1),
        provider=provider,
        operator_profiles={"C1": OperatorProfile.NORMAL},
    )

    orchestrator.decide([_observation(time_s=12.0)], llm_decision_interval_s=1.0)
    orchestrator.decide([_observation(time_s=13.0)], llm_decision_interval_s=1.0)
    session = orchestrator.get_session("C1", "op-C1")

    assert len(session.history) == 1
    assert "time_s=13.0" in session.history[0].content
    assert "fallback=False" in session.history[0].content
