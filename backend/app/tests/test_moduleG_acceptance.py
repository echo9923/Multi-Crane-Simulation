from __future__ import annotations

import json
from pathlib import Path

from backend.app.schemas.command import (
    LLMCallRecord,
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
    SafetyHint,
    SelfStateSummary,
    TaskObservationSummary,
    WeatherObservationSummary,
)
from backend.app.sim.command_parser import parse_raw_llm_response
from backend.app.sim.llm_provider import MockProvider, ProviderRequest, ProviderResult
from backend.app.sim.operator_decision import OperatorDecisionOrchestrator
from backend.app.sim.prompt_builder import build_operator_messages
from backend.app.tests.test_config_schema import load_fixture


class MixedAcceptanceProvider:
    provider_name = LLMProviderName.MOCK

    def __init__(self) -> None:
        self.requests: list[ProviderRequest] = []
        self._c1_attempts = 0

    def generate(self, request: ProviderRequest) -> ProviderResult:
        self.requests.append(request)
        crane_id = request.observation.crane_id
        if crane_id == "C1" and self._c1_attempts == 0:
            self._c1_attempts += 1
            content = "invalid json"
        elif crane_id == "C3":
            content = "invalid json"
        else:
            content = _valid_command_content(
                attention_target="idle" if not request.observation.task.has_active_task else crane_id,
                neutral=not request.observation.task.has_active_task,
            )
        return ProviderResult(
            raw_response=RawLLMResponse(
                response_id=f"resp-{crane_id}-{request.attempt_index}",
                provider=LLMProviderName.MOCK,
                model=request.config.model,
                observation_id=request.observation.observation_id,
                source_snapshot_id=request.observation.source_snapshot_id,
                operator_id=request.observation.operator_id,
                crane_id=crane_id,
                time_s=request.observation.time_s,
                content=content,
            )
        )


def _config(*, max_retries: int = 1):
    raw = load_fixture("experiment_valid.yaml")
    raw["llm"]["provider"] = "mock"
    raw["llm"]["model"] = "mock-command-v1"
    raw["llm"]["max_retries"] = max_retries
    raw["llm"]["max_consecutive_failures"] = 1
    raw["llm"]["context"]["history_mode"] = "short"
    return ExperimentConfig.model_validate(raw).llm


def _observation(
    crane_id: str,
    *,
    active: bool = True,
    risk_prompt_mode: RiskPromptMode = RiskPromptMode.R0,
) -> Observation:
    safety_hint = None
    if risk_prompt_mode is RiskPromptMode.R1:
        safety_hint = SafetyHint(
            source="online_risk",
            risk_level="medium",
            nearest_neighbor="C2",
            nearest_object_type="jib-hook",
            clearance_now_m=4.5,
            estimated_clearance_next_5s_m=3.5,
            relative_motion="closing",
            confidence=0.8,
            suggestion="降低回转速度",
        )
    return Observation(
        observation_id=f"obs-{crane_id}",
        source_snapshot_id="snap-acceptance",
        operator_id=f"op-{crane_id}",
        crane_id=crane_id,
        time_s=20.0,
        operator_profile=OperatorProfile.NORMAL,
        risk_prompt_mode=risk_prompt_mode,
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
        safety_hint=safety_hint,
        available_actions=AvailableActions(),
        memory=MemorySummary(),
    )


def _valid_command_content(*, attention_target: str, neutral: bool = False) -> str:
    slew = {"direction": "neutral", "gear": 0} if neutral else {"direction": "left", "gear": 1}
    trolley = {"direction": "neutral", "gear": 0}
    return json.dumps(
        {
            "left_joystick": {
                "slew": slew,
                "trolley": trolley,
            },
            "right_joystick": {"hoist": {"direction": "neutral", "gear": 0}},
            "deadman_pressed": True,
            "emergency_stop": False,
            "horn": False,
            "command_duration_s": 1.0,
            "task_action": "none",
            "attention_target": attention_target,
            "confidence": 0.8,
            "reason": f"command for {attention_target}",
        }
    )


def test_module_g_acceptance_schema_prompt_mock_parser_and_call_record_contract() -> None:
    observation = _observation("C1")
    config = _config()
    messages = build_operator_messages(
        observation,
        command_schema=ParsedCommand.model_json_schema(),
        command_duration_min_s=config.command_duration.min_s,
        command_duration_max_s=config.command_duration.max_s,
        command_duration_default_s=config.command_duration.default_s,
    )
    raw_response = MockProvider().generate(
        ProviderRequest(
            observation=observation,
            messages=messages,
            config=config,
        )
    ).raw_response
    assert raw_response is not None
    parsed = parse_raw_llm_response(
        raw_response,
        command_duration_min_s=config.command_duration.min_s,
        command_duration_max_s=config.command_duration.max_s,
    )
    call_record = LLMCallRecord(
        call_id="call-acceptance",
        observation=observation,
        messages=messages,
        raw_response=raw_response,
        parsed_command=parsed,
        validation_errors=[],
        provider=LLMProviderName.MOCK,
        model=config.model,
        latency_ms=raw_response.latency_ms,
        token_usage=raw_response.token_usage,
        attempt_index=0,
    )
    serialized = json.dumps(call_record.model_dump(mode="json"), ensure_ascii=False)

    assert parsed.observation_id == observation.observation_id
    assert parsed.source_snapshot_id == observation.source_snapshot_id
    assert parsed.crane_id == observation.crane_id
    for forbidden in [
        "future_min_distance",
        "offline_ttc",
        "offline_label",
        "api_key",
        "authorization",
        "secret",
    ]:
        assert forbidden not in serialized


def test_module_g_acceptance_multi_crane_retry_idle_risk_and_failure_paths() -> None:
    provider = MixedAcceptanceProvider()
    orchestrator = OperatorDecisionOrchestrator(
        config=_config(max_retries=1),
        provider=provider,
        operator_profiles={
            "C1": OperatorProfile.NORMAL,
            "C2": OperatorProfile.CONSERVATIVE,
            "C3": OperatorProfile.AGGRESSIVE,
        },
    )
    observations = [
        _observation("C1", active=True),
        _observation("C2", active=False, risk_prompt_mode=RiskPromptMode.R1),
        _observation("C3", active=True),
    ]

    results = orchestrator.decide(observations, llm_decision_interval_s=1.0)

    assert [result.observation.crane_id for result in results] == ["C1", "C2", "C3"]
    assert results[0].fallback_applied is False
    assert len(results[0].call_records) == 2
    assert "validation errors" in provider.requests[1].messages[-1].content

    assert results[1].fallback_applied is False
    assert results[1].parsed_command.attention_target == "idle"
    assert results[1].parsed_command.left_joystick.slew.direction == "neutral"

    assert results[2].fallback_applied is True
    assert results[2].episode_failure_reason == "llm_failed"
    assert orchestrator.get_session("C1", "op-C1").consecutive_failures == 0
    assert orchestrator.get_session("C2", "op-C2").consecutive_failures == 0
    assert orchestrator.get_session("C3", "op-C3").consecutive_failures == 1


def test_module_g_boundaries_remain_static() -> None:
    module_sources = "\n".join(
        Path(path).read_text(encoding="utf-8")
        for path in [
            "backend/app/schemas/command.py",
            "backend/app/sim/prompt_builder.py",
            "backend/app/sim/llm_provider.py",
            "backend/app/sim/command_parser.py",
            "backend/app/sim/operator_decision.py",
        ]
    )
    for forbidden in [
        "backend.app.sim.physics",
        "backend.app.sim.task_state_machine",
        "backend.app.schemas.control",
        "backend.app.schemas.state",
        "ControlTarget",
        "CraneState",
        "ExecutedCommand",
        "trajectories.parquet",
        "commands.jsonl",
    ]:
        assert forbidden not in module_sources
