from __future__ import annotations

import json
import math

import pytest
from pydantic import ValidationError

from backend.app.schemas.command import (
    COMMAND_SCHEMA_VERSION,
    LLMCallRecord,
    LLMMessage,
    ParsedCommand,
    RawLLMResponse,
    build_neutral_stop_command,
)
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


def _valid_command_payload() -> dict:
    return {
        "command_id": "cmd-001",
        "response_id": "resp-001",
        "observation_id": "obs-001",
        "source_snapshot_id": "snap-001",
        "operator_id": "op-001",
        "crane_id": "C1",
        "time_s": 12.5,
        "left_joystick": {
            "slew": {"direction": "left", "gear": 2},
            "trolley": {"direction": "out", "gear": 1},
        },
        "right_joystick": {"hoist": {"direction": "neutral", "gear": 0}},
        "deadman_pressed": True,
        "emergency_stop": False,
        "horn": False,
        "command_duration_s": 1.0,
        "task_action": "none",
        "attention_target": "pickup_area",
        "confidence": 0.76,
        "reason": "取货点在右前方，低速接近。",
    }


def _valid_observation() -> Observation:
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


def test_parsed_command_accepts_g3_payload_and_serializes_to_json() -> None:
    command = ParsedCommand.model_validate(_valid_command_payload())

    assert command.schema_version == COMMAND_SCHEMA_VERSION
    assert command.left_joystick.slew.direction == "left"
    assert command.left_joystick.trolley.direction == "out"
    assert command.right_joystick.hoist.direction == "neutral"
    assert command.reason == "取货点在右前方，低速接近。"

    dumped = command.model_dump(mode="json")
    json.dumps(dumped, ensure_ascii=False)


def test_command_schema_forbids_extra_fields_recursively() -> None:
    payload = _valid_command_payload()
    payload["left_joystick"]["slew"]["unexpected"] = "nope"

    with pytest.raises(ValidationError):
        ParsedCommand.model_validate(payload)


def test_command_schema_rejects_nan_and_inf_values() -> None:
    payload = _valid_command_payload()
    payload["time_s"] = math.nan

    with pytest.raises(ValidationError):
        ParsedCommand.model_validate(payload)

    payload = _valid_command_payload()
    payload["command_duration_s"] = math.inf

    with pytest.raises(ValidationError):
        ParsedCommand.model_validate(payload)


@pytest.mark.parametrize(
    ("field_path", "value"),
    [
        (("confidence",), -0.01),
        (("confidence",), 1.01),
        (("left_joystick", "slew", "gear"), -1),
        (("left_joystick", "slew", "gear"), 6),
        (("task_action",), "请求挂载"),
    ],
)
def test_parsed_command_rejects_out_of_contract_values(
    field_path: tuple[str, ...], value: object
) -> None:
    payload = _valid_command_payload()
    target = payload
    for key in field_path[:-1]:
        target = target[key]
    target[field_path[-1]] = value

    with pytest.raises(ValidationError):
        ParsedCommand.model_validate(payload)


@pytest.mark.parametrize(
    ("axis_path", "direction", "gear"),
    [
        (("left_joystick", "slew"), "neutral", 1),
        (("left_joystick", "slew"), "left", 0),
        (("left_joystick", "trolley"), "neutral", 2),
        (("left_joystick", "trolley"), "out", 0),
        (("right_joystick", "hoist"), "neutral", 3),
        (("right_joystick", "hoist"), "down", 0),
    ],
)
def test_direction_and_gear_must_be_consistent(
    axis_path: tuple[str, str], direction: str, gear: int
) -> None:
    payload = _valid_command_payload()
    axis = payload[axis_path[0]][axis_path[1]]
    axis["direction"] = direction
    axis["gear"] = gear

    with pytest.raises(ValidationError):
        ParsedCommand.model_validate(payload)


@pytest.mark.parametrize(
    ("axis_path", "direction"),
    [
        (("left_joystick", "slew"), "up"),
        (("left_joystick", "trolley"), "left"),
        (("right_joystick", "hoist"), "out"),
    ],
)
def test_axis_directions_cannot_be_used_on_wrong_joystick_axis(
    axis_path: tuple[str, str], direction: str
) -> None:
    payload = _valid_command_payload()
    axis = payload[axis_path[0]][axis_path[1]]
    axis["direction"] = direction
    axis["gear"] = 1

    with pytest.raises(ValidationError):
        ParsedCommand.model_validate(payload)


def test_raw_response_and_call_record_reject_forbidden_secret_fields() -> None:
    raw_payload = {
        "response_id": "resp-001",
        "provider": "mock",
        "model": "mock-command-v1",
        "observation_id": "obs-001",
        "source_snapshot_id": "snap-001",
        "operator_id": "op-001",
        "crane_id": "C1",
        "time_s": 12.5,
        "content": "{}",
        "raw_payload": {"authorization": "Bearer sk-secret"},
    }

    with pytest.raises(ValidationError):
        RawLLMResponse.model_validate(raw_payload)

    command = ParsedCommand.model_validate(_valid_command_payload())
    with pytest.raises(ValidationError):
        LLMCallRecord(
            call_id="call-001",
            observation=_valid_observation(),
            messages=[LLMMessage(role="system", content="api_key should not appear")],
            raw_response=None,
            parsed_command=command,
            validation_errors=[],
            provider=LLMProviderName.MOCK,
            model="mock-command-v1",
            latency_ms=None,
            token_usage=None,
            attempt_index=0,
        )


def test_neutral_stop_factory_outputs_valid_safe_command() -> None:
    command = build_neutral_stop_command(
        observation_id="obs-001",
        source_snapshot_id="snap-001",
        operator_id="op-001",
        crane_id="C1",
        time_s=12.5,
        command_id="cmd-neutral-001",
        response_id="resp-001",
        command_duration_s=1.0,
        reason="fallback after invalid LLM output",
    )

    assert command.left_joystick.slew.direction == "neutral"
    assert command.left_joystick.slew.gear == 0
    assert command.left_joystick.trolley.direction == "neutral"
    assert command.left_joystick.trolley.gear == 0
    assert command.right_joystick.hoist.direction == "neutral"
    assert command.right_joystick.hoist.gear == 0
    assert command.deadman_pressed is True
    assert command.emergency_stop is False
    assert command.horn is False
    assert command.task_action == "none"
    assert command.attention_target == "fallback_neutral_stop"
    assert command.fallback_reason == "fallback after invalid LLM output"


def test_json_schema_does_not_expose_forbidden_secret_fields() -> None:
    schema_text = json.dumps(ParsedCommand.model_json_schema(), sort_keys=True)

    assert "api_key" not in schema_text
    assert "authorization" not in schema_text
    assert "token" not in schema_text
    assert "secret" not in schema_text
