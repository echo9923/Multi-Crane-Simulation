from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.app.schemas.command import RawLLMResponse
from backend.app.schemas.config import ExperimentConfig
from backend.app.schemas.enums import LLMProviderName, OperatorProfile, RiskPromptMode
from backend.app.schemas.observation import (
    AvailableActions,
    JoystickCommandSummary,
    LeftJoystickCommand as ObservationLeftJoystickCommand,
    MemorySummary,
    Observation,
    RecentDecisionSummary,
    RightJoystickCommand as ObservationRightJoystickCommand,
    AxisCommand as ObservationAxisCommand,
    SelfStateSummary,
    TaskObservationSummary,
    WeatherObservationSummary,
)
from backend.app.sim.llm_provider import ProviderRequest, ProviderResult
from backend.app.sim.operator_decision import (
    OperatorDecisionOrchestrator,
    OperatorDecisionOrchestratorError,
)
from backend.app.tests.test_config_schema import load_fixture


class RecordingProvider:
    provider_name = LLMProviderName.MOCK

    def __init__(self, *, fail_cranes: set[str] | None = None) -> None:
        self.fail_cranes = fail_cranes or set()
        self.requests: list[ProviderRequest] = []

    def generate(self, request: ProviderRequest) -> ProviderResult:
        self.requests.append(request)
        if request.observation.crane_id in self.fail_cranes:
            content = "not json"
        else:
            content = _valid_content(request.observation.crane_id)
        return ProviderResult(
            raw_response=RawLLMResponse(
                response_id=f"resp-{request.observation.crane_id}-{request.attempt_index}",
                provider=LLMProviderName.MOCK,
                model=request.config.model,
                observation_id=request.observation.observation_id,
                source_snapshot_id=request.observation.source_snapshot_id,
                operator_id=request.observation.operator_id,
                crane_id=request.observation.crane_id,
                time_s=request.observation.time_s,
                content=content,
            )
        )


def _config(*, history_mode: str = "none", max_retries: int = 0):
    raw = load_fixture("experiment_valid.yaml")
    raw["llm"]["provider"] = "mock"
    raw["llm"]["model"] = "mock-command-v1"
    raw["llm"]["max_retries"] = max_retries
    raw["llm"]["max_consecutive_failures"] = 1
    raw["llm"]["context"]["history_mode"] = history_mode
    raw["llm"]["context"]["recent_decisions_full"] = 2
    return ExperimentConfig.model_validate(raw).llm


def _observation(
    crane_id: str,
    *,
    operator_id: str | None = None,
    snapshot_id: str = "snap-001",
    time_s: float = 12.0,
    active: bool = True,
) -> Observation:
    return Observation(
        observation_id=f"obs-{crane_id}",
        source_snapshot_id=snapshot_id,
        operator_id=operator_id or f"op-{crane_id}",
        crane_id=crane_id,
        time_s=time_s,
        operator_profile=OperatorProfile.NORMAL,
        risk_prompt_mode=RiskPromptMode.R0,
        task=TaskObservationSummary(
            stage="move_to_pickup" if active else "idle",
            has_active_task=active,
            current_target_relative_direction="right_front" if active else None,
            current_target_distance_m=18.5 if active else None,
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
            task_history_summary="已完成一个取货任务",
            recent_decisions=[
                RecentDecisionSummary(
                    time_s=10.0,
                    command_summary="recent neutral",
                    result="stable",
                )
            ],
            event_summary=["risk resolved"],
        ),
    )


def _valid_content(crane_id: str) -> str:
    return json.dumps(
        {
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
            "attention_target": crane_id,
            "confidence": 0.8,
            "reason": f"command for {crane_id}",
        }
    )


def test_orchestrator_creates_independent_sessions_and_preserves_order() -> None:
    provider = RecordingProvider()
    orchestrator = OperatorDecisionOrchestrator(
        config=_config(history_mode="none"),
        provider=provider,
        operator_profiles={"C1": OperatorProfile.NORMAL, "C2": OperatorProfile.AGGRESSIVE},
    )
    observations = [_observation("C1"), _observation("C2")]

    results = orchestrator.decide(observations, llm_decision_interval_s=1.0)

    assert [result.parsed_command.crane_id for result in results] == ["C1", "C2"]
    assert orchestrator.get_session("C1", "op-C1").decision_index == 1
    assert orchestrator.get_session("C2", "op-C2").decision_index == 1
    assert orchestrator.get_session("C1", "op-C1") is not orchestrator.get_session("C2", "op-C2")


def test_one_operator_failure_does_not_affect_another_operator() -> None:
    provider = RecordingProvider(fail_cranes={"C1"})
    orchestrator = OperatorDecisionOrchestrator(
        config=_config(history_mode="none"),
        provider=provider,
        operator_profiles={"C1": OperatorProfile.NORMAL, "C2": OperatorProfile.NORMAL},
    )

    results = orchestrator.decide(
        [_observation("C1"), _observation("C2")],
        llm_decision_interval_s=1.0,
    )

    assert results[0].fallback_applied is True
    assert results[0].episode_failure_reason == "llm_failed"
    assert results[1].fallback_applied is False
    assert orchestrator.get_session("C1", "op-C1").consecutive_failures == 1
    assert orchestrator.get_session("C2", "op-C2").consecutive_failures == 0


def test_should_decide_uses_interval_and_updates_after_decision() -> None:
    orchestrator = OperatorDecisionOrchestrator(
        config=_config(),
        provider=RecordingProvider(),
        operator_profiles={"C1": OperatorProfile.NORMAL},
    )

    assert orchestrator.should_decide(
        crane_id="C1",
        time_s=0.0,
        llm_decision_interval_s=1.0,
    )
    orchestrator.decide([_observation("C1", time_s=0.0)], llm_decision_interval_s=1.0)
    assert not orchestrator.should_decide(
        crane_id="C1",
        time_s=0.5,
        llm_decision_interval_s=1.0,
    )
    assert orchestrator.should_decide(
        crane_id="C1",
        time_s=1.0,
        llm_decision_interval_s=1.0,
    )


def test_orchestrator_rejects_inconsistent_snapshot_duplicate_and_missing_profile() -> None:
    orchestrator = OperatorDecisionOrchestrator(
        config=_config(),
        provider=RecordingProvider(),
        operator_profiles={"C1": OperatorProfile.NORMAL},
    )

    with pytest.raises(OperatorDecisionOrchestratorError):
        orchestrator.decide(
            [_observation("C1"), _observation("C2", snapshot_id="snap-002")],
            llm_decision_interval_s=1.0,
        )

    with pytest.raises(OperatorDecisionOrchestratorError):
        orchestrator.decide(
            [_observation("C1"), _observation("C1")],
            llm_decision_interval_s=1.0,
        )

    with pytest.raises(OperatorDecisionOrchestratorError):
        orchestrator.decide([_observation("C2")], llm_decision_interval_s=1.0)


def test_history_modes_control_extra_context_in_messages() -> None:
    none_provider = RecordingProvider()
    none_orchestrator = OperatorDecisionOrchestrator(
        config=_config(history_mode="none"),
        provider=none_provider,
        operator_profiles={"C1": OperatorProfile.NORMAL},
    )
    none_orchestrator.decide([_observation("C1")], llm_decision_interval_s=1.0)
    none_messages = "\n".join(message.content for message in none_provider.requests[0].messages)
    assert "session_history" not in none_messages

    short_provider = RecordingProvider()
    short_orchestrator = OperatorDecisionOrchestrator(
        config=_config(history_mode="short"),
        provider=short_provider,
        operator_profiles={"C1": OperatorProfile.NORMAL},
    )
    short_orchestrator.decide([_observation("C1")], llm_decision_interval_s=1.0)
    short_orchestrator.decide([_observation("C1", time_s=13.0)], llm_decision_interval_s=1.0)
    short_messages = "\n".join(message.content for message in short_provider.requests[-1].messages)
    assert "session_history" in short_messages
    assert "recent neutral" in short_messages

    long_provider = RecordingProvider()
    long_orchestrator = OperatorDecisionOrchestrator(
        config=_config(history_mode="long"),
        provider=long_provider,
        operator_profiles={"C1": OperatorProfile.NORMAL},
    )
    long_orchestrator.decide([_observation("C1")], llm_decision_interval_s=1.0)
    long_messages = "\n".join(message.content for message in long_provider.requests[0].messages)
    assert "已完成一个取货任务" in long_messages
    assert "risk resolved" in long_messages

    for forbidden in ["future_min_distance", "offline_ttc", "offline_label", "api_key", "secret"]:
        assert forbidden not in short_messages
        assert forbidden not in long_messages


def test_orchestrator_does_not_import_out_of_boundary_modules() -> None:
    source = Path("backend/app/sim/operator_decision.py").read_text(encoding="utf-8")
    for forbidden in [
        "backend.app.sim.physics",
        "backend.app.sim.task_state_machine",
        "backend.app.schemas.control",
        "backend.app.schemas.state",
        "backend.app.sim.weather",
        "backend.app.sim.layout",
    ]:
        assert forbidden not in source
