from __future__ import annotations

import copy
import json

from backend.app.schemas.command import (
    CommandValidationError,
    ParsedCommand,
)
from backend.app.schemas.enums import OperatorProfile, RiskPromptMode
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
from backend.app.sim.prompt_builder import (
    build_operator_messages,
    build_retry_prompt,
    build_system_prompt,
    build_user_prompt,
    get_profile_behavior_params,
    get_profile_prompt,
)


def _observation(
    *,
    risk_prompt_mode: RiskPromptMode = RiskPromptMode.R0,
    safety_hint: SafetyHint | None = None,
) -> Observation:
    return Observation(
        observation_id="obs-001",
        source_snapshot_id="snap-001",
        operator_id="op-001",
        crane_id="C1",
        time_s=12.5,
        operator_profile=OperatorProfile.NORMAL,
        risk_prompt_mode=risk_prompt_mode,
        task=TaskObservationSummary(
            stage="move_to_pickup",
            has_active_task=True,
            type="easy_task",
            priority="high",
            deadline_s=60.0,
            current_target_relative_direction="right_front",
            current_target_distance_m=18.5,
            current_target_height_delta_m=-2.0,
            signal_hint="请低速接近取货点",
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
        memory=MemorySummary(event_summary=["上一轮未发生风险事件"]),
    )


def _extract_json_block(prompt: str, label: str) -> dict:
    start_marker = f"<{label}>"
    end_marker = f"</{label}>"
    start = prompt.index(start_marker) + len(start_marker)
    end = prompt.index(end_marker)
    return json.loads(prompt[start:end].strip())


def test_profile_prompts_exist_for_all_profiles_and_are_distinct() -> None:
    prompts = {
        profile: get_profile_prompt(profile)
        for profile in [
            OperatorProfile.NORMAL,
            OperatorProfile.CONSERVATIVE,
            OperatorProfile.AGGRESSIVE,
            OperatorProfile.NOVICE,
            OperatorProfile.FATIGUED,
        ]
    }

    assert all(prompt.strip() for prompt in prompts.values())
    assert len(set(prompts.values())) == 5
    assert "保守" in prompts[OperatorProfile.CONSERVATIVE]
    assert "效率优先" in prompts[OperatorProfile.AGGRESSIVE]

    behavior = get_profile_behavior_params(OperatorProfile.FATIGUED)
    assert behavior["decision_interval_multiplier"] == 1.5
    assert behavior["ignore_hint_prob"] == 0.20


def test_system_prompt_contains_role_boundary_schema_language_and_profile() -> None:
    profile_prompt = get_profile_prompt(OperatorProfile.NORMAL)
    behavior = get_profile_behavior_params(OperatorProfile.NORMAL)

    prompt = build_system_prompt(
        profile=OperatorProfile.NORMAL,
        profile_prompt=profile_prompt,
        behavior_params=behavior,
    )

    assert "真实塔吊司机" in prompt
    assert "局部观测" in prompt
    assert "不能输出目标坐标" in prompt
    assert "严格 JSON" in prompt
    assert "JSON 字段名和枚举值必须使用英文" in prompt
    assert "reason 字段可以使用中文" in prompt
    assert profile_prompt in prompt
    assert "risk_sensitivity" in prompt


def test_user_prompt_embeds_parseable_observation_actions_duration_and_schema() -> None:
    observation = _observation()
    original_dump = copy.deepcopy(observation.model_dump(mode="json"))
    schema = ParsedCommand.model_json_schema()

    prompt = build_user_prompt(
        observation,
        command_schema=schema,
        command_duration_min_s=0.5,
        command_duration_max_s=3.0,
        command_duration_default_s=1.0,
    )

    observation_json = _extract_json_block(prompt, "observation_json")
    schema_json = _extract_json_block(prompt, "command_schema_json")

    assert observation_json["observation_id"] == "obs-001"
    assert observation_json["available_actions"]["slew_direction"] == [
        "left",
        "neutral",
        "right",
    ]
    assert schema_json["properties"]["task_action"]["enum"] == [
        "none",
        "request_attach",
        "request_release",
    ]
    assert "command_duration_s" in prompt
    assert "0.5" in prompt
    assert "1.0" in prompt
    assert "3.0" in prompt
    assert observation.model_dump(mode="json") == original_dump


def test_retry_prompt_lists_validation_error_paths_and_messages() -> None:
    prompt = build_retry_prompt(
        [
            CommandValidationError(
                error_code="LLM_E_002",
                field_path="left_joystick.slew.direction",
                message="Input should be left, neutral or right",
                raw_fragment='"左"',
            ),
            CommandValidationError(
                error_code="LLM_E_002",
                field_path="command_duration_s",
                message="Input should be less than or equal to 3",
            ),
        ]
    )

    assert "left_joystick.slew.direction" in prompt
    assert "Input should be left, neutral or right" in prompt
    assert "command_duration_s" in prompt
    assert "只返回修正后的严格 JSON" in prompt

    errors_json = _extract_json_block(prompt, "validation_errors_json")
    assert errors_json[0]["raw_fragment"] == '"左"'


def test_build_operator_messages_adds_retry_message_only_when_errors_exist() -> None:
    observation = _observation()

    messages = build_operator_messages(
        observation,
        command_schema=ParsedCommand.model_json_schema(),
        command_duration_min_s=0.5,
        command_duration_max_s=3.0,
        command_duration_default_s=1.0,
    )

    assert [message.role for message in messages] == ["system", "user"]

    messages_with_retry = build_operator_messages(
        observation,
        command_schema=ParsedCommand.model_json_schema(),
        command_duration_min_s=0.5,
        command_duration_max_s=3.0,
        command_duration_default_s=1.0,
        retry_errors=[
            CommandValidationError(
                error_code="LLM_E_002",
                field_path="task_action",
                message="Input should be none/request_attach/request_release",
            )
        ],
    )

    assert [message.role for message in messages_with_retry] == [
        "system",
        "user",
        "user",
    ]
    assert "task_action" in messages_with_retry[-1].content


def test_prompt_text_does_not_leak_forbidden_future_or_secret_fields() -> None:
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
    observation = _observation(
        risk_prompt_mode=RiskPromptMode.R1,
        safety_hint=safety_hint,
    )

    messages = build_operator_messages(
        observation,
        command_schema=ParsedCommand.model_json_schema(),
        command_duration_min_s=0.5,
        command_duration_max_s=3.0,
        command_duration_default_s=1.0,
    )
    combined = "\n".join(message.content for message in messages)

    for forbidden in [
        "future_min_distance",
        "offline_ttc",
        "offline_label",
        "planned_start_s",
        "neighbor_task_id",
        "api_key",
        "authorization",
        "token",
        "secret",
    ]:
        assert forbidden not in combined

    assert "左" not in combined
    assert "右" not in combined
    assert "请求挂载" not in combined
    assert "left" in combined
    assert "neutral" in combined
    assert "request_attach" in combined
