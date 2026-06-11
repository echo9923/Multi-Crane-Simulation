from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from backend.app.schemas.command import RawLLMResponse
from backend.app.schemas.enums import LLMProviderName
from backend.app.sim.command_parser import (
    CommandParseError,
    extract_json_object,
    parse_raw_llm_response,
    validation_errors_from_exception,
)


def _raw_response(content: str) -> RawLLMResponse:
    return RawLLMResponse(
        response_id="resp-001",
        provider=LLMProviderName.MOCK,
        model="mock-command-v1",
        observation_id="obs-001",
        source_snapshot_id="snap-001",
        operator_id="op-001",
        crane_id="C1",
        time_s=12.5,
        content=content,
    )


def _llm_payload(**overrides) -> dict:
    payload = {
        "left_joystick": {
            "slew": {"direction": "left", "gear": 2},
            "trolley": {"direction": "out", "gear": 1},
        },
        "right_joystick": {"hoist": {"direction": "neutral", "gear": 0}},
        "deadman_pressed": True,
        "emergency_stop": False,
        "horn": True,
        "command_duration_s": 1.0,
        "task_action": "none",
        "attention_target": "pickup_area",
        "confidence": 0.76,
        "reason": "取货点在右前方，低速接近。",
        "command_id": "model-forged-command-id",
        "response_id": "model-forged-response-id",
        "observation_id": "model-forged-observation",
        "source_snapshot_id": "model-forged-snapshot",
        "operator_id": "model-forged-operator",
        "crane_id": "model-forged-crane",
        "time_s": 999.0,
    }
    payload.update(overrides)
    return payload


def _content(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False)


def test_extract_json_object_accepts_only_plain_json_object_with_whitespace() -> None:
    assert extract_json_object('  {"task_action": "none"}\n') == {
        "task_action": "none"
    }

    for content in [
        "",
        "```json\n{}\n```",
        "explanation {}",
        "[]",
        "{}{}",
    ]:
        with pytest.raises(CommandParseError):
            extract_json_object(content)


def test_parse_raw_response_builds_command_and_uses_raw_metadata() -> None:
    parsed = parse_raw_llm_response(
        _raw_response(_content(_llm_payload())),
        command_duration_min_s=0.5,
        command_duration_max_s=3.0,
    )

    assert parsed.command_id == "cmd-resp-001"
    assert parsed.response_id == "resp-001"
    assert parsed.observation_id == "obs-001"
    assert parsed.source_snapshot_id == "snap-001"
    assert parsed.operator_id == "op-001"
    assert parsed.crane_id == "C1"
    assert parsed.time_s == 12.5
    assert parsed.reason == "取货点在右前方，低速接近。"
    assert parsed.horn is True


@pytest.mark.parametrize(
    "payload",
    [
        _llm_payload(extra_field="nope"),
        _llm_payload(task_action="请求挂载"),
        _llm_payload(left_joystick={"slew": {"direction": "neutral", "gear": 1}, "trolley": {"direction": "out", "gear": 1}}),
        _llm_payload(confidence=1.2),
        _llm_payload(command_duration_s=math.inf),
    ],
)
def test_parse_raw_response_reports_validation_errors(payload: dict) -> None:
    with pytest.raises(CommandParseError) as exc_info:
        parse_raw_llm_response(
            _raw_response(_content(payload)),
            command_duration_min_s=0.5,
            command_duration_max_s=3.0,
        )

    errors = exc_info.value.errors
    assert errors
    assert all(error.error_code == "LLM_E_002" for error in errors)
    assert all(error.retryable for error in errors)


@pytest.mark.parametrize("duration", [0.49, 3.01])
def test_parse_raw_response_enforces_runtime_command_duration_bounds(
    duration: float,
) -> None:
    with pytest.raises(CommandParseError) as exc_info:
        parse_raw_llm_response(
            _raw_response(_content(_llm_payload(command_duration_s=duration))),
            command_duration_min_s=0.5,
            command_duration_max_s=3.0,
        )

    assert exc_info.value.errors[0].field_path == "command_duration_s"


def test_validation_errors_from_exception_handles_unknown_exception() -> None:
    errors = validation_errors_from_exception(RuntimeError("provider returned junk"))

    assert len(errors) == 1
    assert errors[0].error_code == "LLM_E_002"
    assert errors[0].message == "provider returned junk"


def test_command_parser_does_not_import_out_of_boundary_modules() -> None:
    source = Path("backend/app/sim/command_parser.py").read_text(encoding="utf-8")

    for forbidden in [
        "backend.app.sim.physics",
        "backend.app.sim.task_state_machine",
        "backend.app.schemas.control",
        "backend.app.schemas.state",
        "backend.app.sim.weather",
        "backend.app.sim.layout",
    ]:
        assert forbidden not in source
