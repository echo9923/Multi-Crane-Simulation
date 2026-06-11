from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import pytest
from pydantic import ValidationError

from backend.app.schemas.command import LLMMessage, ParsedCommand, RawLLMResponse
from backend.app.schemas.config import ExperimentConfig
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
from backend.app.sim.llm_provider import (
    DeepSeekProvider,
    ProviderAPIError,
    ProviderRequest,
    ProviderResult,
    ReplayCommandNotFoundError,
    create_llm_provider,
)
from backend.app.tests.test_config_schema import load_fixture


def _llm_config(provider: str, *, base_url: str | None = "https://example.test/v1"):
    raw = load_fixture("experiment_valid.yaml")
    raw["llm"]["enabled"] = True
    raw["llm"]["provider"] = provider
    raw["llm"]["model"] = f"{provider}-model"
    raw["llm"]["base_url"] = base_url
    raw["llm"]["api_key"] = None
    raw["llm"]["api_key_env"] = None
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


def _request(*, config=None, attempt_index: int = 0) -> ProviderRequest:
    return ProviderRequest(
        observation=_observation(),
        messages=[
            LLMMessage(role="system", content="system prompt"),
            LLMMessage(role="user", content="user prompt"),
        ],
        config=config or _llm_config("deepseek"),
        runtime_secret=None,
        attempt_index=attempt_index,
    )


def _parsed_command() -> ParsedCommand:
    return ParsedCommand.model_validate(
        {
            "command_id": "cmd-001",
            "response_id": "resp-001",
            "observation_id": "obs-001",
            "source_snapshot_id": "snap-001",
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


def _raw_response() -> RawLLMResponse:
    return RawLLMResponse(
        response_id="resp-001",
        provider=LLMProviderName.MOCK,
        model="mock-command-v1",
        observation_id="obs-001",
        source_snapshot_id="snap-001",
        operator_id="op-001",
        crane_id="C1",
        time_s=12.5,
        content="{}",
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


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"raw_response": _raw_response(), "replay_command": _parsed_command()},
    ],
)
def test_provider_result_requires_exactly_one_result_kind(payload: dict) -> None:
    with pytest.raises(ValidationError) as exc_info:
        ProviderResult.model_validate(payload)

    assert "exactly one" in str(exc_info.value)


def test_provider_request_rejects_negative_attempt_index() -> None:
    with pytest.raises(ValidationError) as exc_info:
        _request(attempt_index=-1)

    assert ("attempt_index",) in [error["loc"] for error in exc_info.value.errors()]


def test_replay_provider_created_without_commands_reports_missing_match() -> None:
    provider = create_llm_provider(_llm_config("replay"))

    with pytest.raises(ReplayCommandNotFoundError):
        provider.generate(_request(config=_llm_config("replay")))


def test_real_provider_strips_trailing_base_url_slashes() -> None:
    http_client = FakeHTTPClient(
        FakeHTTPResponse(
            200,
            {"id": "chatcmpl-001", "choices": [{"message": {"content": "{}"}}]},
        )
    )
    provider = DeepSeekProvider(http_client=http_client)

    provider.generate(_request(config=_llm_config("deepseek", base_url="https://example.test/v1///")))

    assert http_client.calls[0]["url"] == "https://example.test/v1/chat/completions"


def test_real_provider_omits_authorization_header_without_runtime_secret() -> None:
    http_client = FakeHTTPClient(
        FakeHTTPResponse(
            200,
            {"id": "chatcmpl-002", "choices": [{"message": {"content": "{}"}}]},
        )
    )
    provider = DeepSeekProvider(http_client=http_client)

    provider.generate(_request(config=_llm_config("deepseek")))

    assert "Authorization" not in http_client.calls[0]["headers"]


def test_real_provider_accepts_missing_usage_as_no_token_usage() -> None:
    http_client = FakeHTTPClient(
        FakeHTTPResponse(
            200,
            {"id": "chatcmpl-003", "choices": [{"message": {"content": "{}"}}]},
        )
    )
    provider = DeepSeekProvider(http_client=http_client)

    result = provider.generate(_request(config=_llm_config("deepseek")))

    assert result.token_usage is None
    assert result.raw_response is not None
    assert result.raw_response.token_usage is None


def test_real_provider_rejects_non_string_message_content() -> None:
    http_client = FakeHTTPClient(
        FakeHTTPResponse(
            200,
            {"id": "chatcmpl-004", "choices": [{"message": {"content": {"bad": "shape"}}}]},
        )
    )
    provider = DeepSeekProvider(http_client=http_client)

    with pytest.raises(ProviderAPIError) as exc_info:
        provider.generate(_request(config=_llm_config("deepseek")))

    assert "content must be a string" in str(exc_info.value)


def test_real_provider_maps_oserror_to_provider_api_error() -> None:
    provider = DeepSeekProvider(http_client=FakeHTTPClient(OSError("network down")))

    with pytest.raises(ProviderAPIError) as exc_info:
        provider.generate(_request(config=_llm_config("deepseek")))

    assert "request failed" in str(exc_info.value)


def test_real_provider_payload_messages_are_json_ready_and_secret_free() -> None:
    http_client = FakeHTTPClient(
        FakeHTTPResponse(
            200,
            {"id": "chatcmpl-005", "choices": [{"message": {"content": "{}"}}]},
        )
    )
    provider = DeepSeekProvider(http_client=http_client)

    provider.generate(_request(config=_llm_config("deepseek")))

    request_payload = http_client.calls[0]["json"]
    assert request_payload["messages"] == [
        {"role": "system", "content": "system prompt"},
        {"role": "user", "content": "user prompt"},
    ]
    assert "api_key" not in json.dumps(request_payload, sort_keys=True)
