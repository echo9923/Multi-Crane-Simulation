from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import pytest

from backend.app.core.secret_resolver import ProviderRuntimeSecret
from backend.app.schemas.command import LLMMessage, ParsedCommand
from backend.app.schemas.config import ExperimentConfig
from backend.app.schemas.enums import (
    LLMProviderName,
    OperatorProfile,
    RiskPromptMode,
    StructuredOutputMode,
)
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
    DeepSeekProvider,
    MiniMaxProvider,
    MockProvider,
    ProviderAPIError,
    ProviderRequest,
    ProviderTimeoutError,
    ReplayCommandDuplicateError,
    ReplayCommandNotFoundError,
    ReplayProvider,
    SiliconFlowProvider,
    create_llm_provider,
)
from backend.app.tests.test_config_schema import load_fixture


def _llm_config(provider: str, *, structured_output: str = "json_object"):
    raw = load_fixture("experiment_valid.yaml")
    raw["llm"]["enabled"] = True
    raw["llm"]["provider"] = provider
    raw["llm"]["model"] = f"{provider}-model"
    raw["llm"]["base_url"] = "https://example.test/v1"
    raw["llm"]["api_key"] = None
    raw["llm"]["api_key_env"] = None
    raw["llm"]["structured_output"]["mode"] = structured_output
    return ExperimentConfig.model_validate(raw).llm


def _observation(*, active: bool = True) -> Observation:
    return Observation(
        observation_id="obs-active" if active else "obs-idle",
        source_snapshot_id="snap-001",
        operator_id="op-001",
        crane_id="C1",
        time_s=12.5,
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
        memory=MemorySummary(),
    )


def _request(config, observation: Observation | None = None) -> ProviderRequest:
    return ProviderRequest(
        observation=observation or _observation(),
        messages=[
            LLMMessage(role="system", content="system prompt"),
            LLMMessage(role="user", content="user prompt"),
        ],
        config=config,
        runtime_secret=ProviderRuntimeSecret(full_api_key="sk-runtime-secret-123456"),
    )


def _parsed_command(*, command_id: str = "cmd-001", snapshot_id: str = "snap-001"):
    return ParsedCommand.model_validate(
        {
            "command_id": command_id,
            "response_id": "resp-001",
            "observation_id": "obs-active",
            "source_snapshot_id": snapshot_id,
            "operator_id": "op-001",
            "crane_id": "C1",
            "time_s": 12.5,
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
            "reason": "replay command",
        }
    )


@dataclass
class FakeHTTPResponse:
    status_code: int
    payload: dict[str, Any]

    def json(self) -> dict[str, Any]:
        return self.payload


class FakeHTTPClient:
    def __init__(self, response: FakeHTTPResponse | Exception) -> None:
        self.response = response
        self.calls: list[dict[str, Any]] = []

    def post(self, url: str, *, headers: dict, json: dict, timeout: float):
        self.calls.append(
            {"url": url, "headers": headers, "json": json, "timeout": timeout}
        )
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def test_create_llm_provider_returns_provider_by_config_name() -> None:
    assert isinstance(create_llm_provider(_llm_config("mock")), MockProvider)
    assert isinstance(
        create_llm_provider(_llm_config("replay"), replay_commands=[]), ReplayProvider
    )
    assert isinstance(create_llm_provider(_llm_config("deepseek")), DeepSeekProvider)
    assert isinstance(create_llm_provider(_llm_config("minimax")), MiniMaxProvider)
    assert isinstance(create_llm_provider(_llm_config("siliconflow")), SiliconFlowProvider)


def test_mock_provider_returns_deterministic_active_and_idle_raw_commands() -> None:
    provider = MockProvider()
    config = _llm_config("mock")

    active_first = provider.generate(_request(config, _observation(active=True)))
    active_second = provider.generate(_request(config, _observation(active=True)))
    idle = provider.generate(_request(config, _observation(active=False)))

    assert active_first.raw_response is not None
    assert active_second.raw_response is not None
    assert idle.raw_response is not None
    assert active_first.raw_response.content == active_second.raw_response.content

    active_payload = json.loads(active_first.raw_response.content)
    idle_payload = json.loads(idle.raw_response.content)
    assert active_payload["left_joystick"]["slew"]["gear"] == 1
    assert active_payload["attention_target"] == "current_target"
    assert idle_payload["left_joystick"]["slew"] == {
        "direction": "neutral",
        "gear": 0,
    }
    assert idle_payload["attention_target"] == "idle"


def test_replay_provider_returns_unique_matching_command_without_network() -> None:
    provider = ReplayProvider(replay_commands=[_parsed_command()])
    result = provider.generate(_request(_llm_config("replay")))

    assert result.raw_response is None
    assert result.replay_command is not None
    assert result.replay_command.command_id == "cmd-001"


def test_replay_provider_reports_missing_and_duplicate_commands() -> None:
    request = _request(_llm_config("replay"))

    with pytest.raises(ReplayCommandNotFoundError):
        ReplayProvider(replay_commands=[]).generate(request)

    with pytest.raises(ReplayCommandDuplicateError):
        ReplayProvider(
            replay_commands=[
                _parsed_command(command_id="cmd-001"),
                _parsed_command(command_id="cmd-002"),
            ]
        ).generate(request)


@pytest.mark.parametrize(
    ("provider_name", "provider_class"),
    [
        ("deepseek", DeepSeekProvider),
        ("minimax", MiniMaxProvider),
        ("siliconflow", SiliconFlowProvider),
    ],
)
def test_real_provider_builds_chat_request_without_persisting_secret(
    provider_name: str, provider_class: type
) -> None:
    http_client = FakeHTTPClient(
        FakeHTTPResponse(
            200,
            {
                "id": "chatcmpl-001",
                "choices": [{"message": {"content": '{"task_action":"none"}'}}],
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 5,
                    "total_tokens": 15,
                },
            },
        )
    )
    provider = provider_class(http_client=http_client)
    config = _llm_config(provider_name, structured_output="json_schema")

    result = provider.generate(_request(config))

    assert result.raw_response is not None
    assert result.raw_response.provider is LLMProviderName(provider_name)
    assert result.raw_response.token_usage is not None
    assert result.raw_response.token_usage.total_tokens == 15
    assert "sk-runtime-secret-123456" not in json.dumps(
        result.raw_response.model_dump(mode="json")
    )

    call = http_client.calls[0]
    assert call["url"] == "https://example.test/v1/chat/completions"
    assert call["headers"]["Authorization"] == "Bearer sk-runtime-secret-123456"
    assert call["timeout"] == config.timeout_s
    assert call["json"]["model"] == f"{provider_name}-model"
    assert call["json"]["messages"][0]["role"] == "system"
    assert call["json"]["response_format"]["type"] == StructuredOutputMode.JSON_SCHEMA.value


def test_real_provider_distinguishes_json_object_structured_output() -> None:
    http_client = FakeHTTPClient(
        FakeHTTPResponse(
            200,
            {"id": "chatcmpl-002", "choices": [{"message": {"content": "{}"}}]},
        )
    )
    provider = DeepSeekProvider(http_client=http_client)

    provider.generate(_request(_llm_config("deepseek", structured_output="json_object")))

    assert http_client.calls[0]["json"]["response_format"]["type"] == "json_object"


def test_real_provider_maps_timeout_and_api_errors() -> None:
    timeout_provider = DeepSeekProvider(
        http_client=FakeHTTPClient(TimeoutError("request timed out"))
    )
    with pytest.raises(ProviderTimeoutError):
        timeout_provider.generate(_request(_llm_config("deepseek")))

    error_provider = DeepSeekProvider(
        http_client=FakeHTTPClient(FakeHTTPResponse(500, {"error": "bad gateway"}))
    )
    with pytest.raises(ProviderAPIError):
        error_provider.generate(_request(_llm_config("deepseek")))

    malformed_provider = DeepSeekProvider(
        http_client=FakeHTTPClient(FakeHTTPResponse(200, {"choices": []}))
    )
    with pytest.raises(ProviderAPIError):
        malformed_provider.generate(_request(_llm_config("deepseek")))
