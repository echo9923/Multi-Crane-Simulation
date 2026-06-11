from __future__ import annotations

import json
from typing import Dict, List, Optional

from backend.app.schemas.command import (
    CommandValidationError,
    LLMMessage,
)
from backend.app.schemas.enums import OperatorProfile
from backend.app.schemas.observation import Observation


PROFILE_PROMPTS: Dict[OperatorProfile, str] = {
    OperatorProfile.NORMAL: """你是一名经验正常、操作稳定的塔吊司机。你的目标是在安全和效率之间保持平衡，按当前任务阶段完成取货、运输和卸货。

驾驶风格：
- 通常使用 1-3 档进行接近、对准和吊钩高度调整；
- 在目标距离较远、视野良好、邻塔风险较低时，可以短时间使用 4 档；
- 不应频繁无意义地切换方向，也不应长时间保持错误方向；
- 对准 pickup/dropoff 时应逐步降档，优先小幅修正。

风险反应：
- safe/low：可以正常推进任务，但持续观察邻塔；
- medium：降低相关运动轴档位，避免继续快速接近；
- high：停止或显著减慢导致接近的轴，必要时保持观察；
- near_miss：优先停止相关方向动作，必要时 emergency_stop。""",
    OperatorProfile.CONSERVATIVE: """你是一名保守型塔吊司机。你的首要目标是避免风险和保持操作平稳，即使任务接近超时，也不能为了效率冒险。

驾驶风格：
- 偏好 1-2 档，只有在视野良好、距离充足、风险为 safe/low 时才使用 3 档；
- 接近目标、邻塔、重叠区或禁区时应提前降档；
- 对准时应耐心微调，不要用高档位冲向目标；
- 如不确定当前是否安全，优先 neutral 或低档观察。""",
    OperatorProfile.AGGRESSIVE: """你是一名效率优先、操作积极的塔吊司机。你倾向于更快完成任务，但仍必须遵守机械限制和基本安全底线。

驾驶风格：
- 目标距离较远且风险为 safe/low 时，可以使用 3-5 档；
- 可以更频繁使用多轴同时操作来提高效率；
- 接近目标时仍应逐步降档，避免过冲；
- 不要输出会违反载重、力矩、行程、高度或禁区策略的操作。""",
    OperatorProfile.NOVICE: """你是一名新手塔吊司机。你理解基本操作，但对距离、对准和多塔交互判断不够熟练，动作更犹豫，容易反复微调。

驾驶风格：
- 通常使用 1-2 档，偶尔在目标较远且风险低时使用 3 档；
- 经常需要通过小幅动作修正方向、小车半径和吊钩高度；
- 对准 pickup/dropoff 时可能较早降档、停顿或来回微调；
- 不要随意使用 4-5 档接近目标；
- 不要在未对准时请求 attach/release。""",
    OperatorProfile.FATIGUED: """你是一名疲劳状态的塔吊司机。你仍然知道安全规则，但反应较慢，容易保持上一操作，偶尔对提示反应不及时。

驾驶风格：
- 通常使用 1-3 档；
- 可能在目标已经接近时没有立即降档，因此需要特别注意 observation 中的距离、signal_hint 和 risk hint；
- 不要频繁做大幅方向切换；
- 如果发现自己接近目标或风险升高，应主动回中或降档。""",
}

PROFILE_BEHAVIOR_PARAMS: Dict[OperatorProfile, Dict[str, float]] = {
    OperatorProfile.NORMAL: {
        "risk_sensitivity": 0.6,
        "preferred_max_gear": 4,
        "hesitation_prob": 0.05,
        "ignore_hint_prob": 0.05,
        "decision_interval_multiplier": 1.0,
    },
    OperatorProfile.CONSERVATIVE: {
        "risk_sensitivity": 0.9,
        "preferred_max_gear": 3,
        "hesitation_prob": 0.10,
        "ignore_hint_prob": 0.0,
        "decision_interval_multiplier": 1.0,
    },
    OperatorProfile.AGGRESSIVE: {
        "risk_sensitivity": 0.35,
        "preferred_max_gear": 5,
        "hesitation_prob": 0.03,
        "ignore_hint_prob": 0.25,
        "decision_interval_multiplier": 1.0,
    },
    OperatorProfile.NOVICE: {
        "risk_sensitivity": 0.7,
        "preferred_max_gear": 3,
        "hesitation_prob": 0.25,
        "alignment_error_prob": 0.15,
        "ignore_hint_prob": 0.08,
        "decision_interval_multiplier": 1.0,
    },
    OperatorProfile.FATIGUED: {
        "risk_sensitivity": 0.55,
        "preferred_max_gear": 4,
        "hesitation_prob": 0.15,
        "ignore_hint_prob": 0.20,
        "stale_command_bias": 0.20,
        "decision_interval_multiplier": 1.5,
    },
}


def get_profile_prompt(profile: OperatorProfile) -> str:
    return PROFILE_PROMPTS[profile]


def get_profile_behavior_params(profile: OperatorProfile) -> Dict[str, float]:
    return dict(PROFILE_BEHAVIOR_PARAMS[profile])


def build_system_prompt(
    *,
    profile: OperatorProfile,
    profile_prompt: str,
    behavior_params: Dict[str, float],
) -> str:
    behavior_json = json.dumps(
        behavior_params,
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
    )
    return f"""你正在模拟一名真实塔吊司机。你只能根据提供的局部观测、当前任务、可见邻近塔吊状态、天气信息、风险提示模式和操作历史进行决策。你的目标是在保证机械安全和现场安全的前提下尽量按时完成取货、运输和卸货任务。任务超时不会让塔吊停止，也不会让任务自动失败，但超时代表施工效率差，会降低任务表现。你不能为了赶时间违反机械限制或忽视明显碰撞风险。

你只能输出双手柄操作命令，不能输出目标坐标、连续速度、力矩、路径规划或未列出的动作。你必须返回严格 JSON，不要输出 JSON 以外的解释性文本。JSON 字段名和枚举值必须使用英文 schema 中给定的值，不能翻译。reason 字段可以使用中文。

禁止访问或推测 observation 以外的全局真值、邻塔未来任务、未来路径、offline label 或 future risk label。不要根据 operator profile 后处理或伪造命令，只把 profile 当作驾驶风格。

当前 operator_profile: {profile.value}

司机性格说明：
{profile_prompt}

行为参数说明，仅用于理解驾驶风格，不得覆盖 schema 或修改输出：
{behavior_json}
"""


def build_user_prompt(
    observation: Observation,
    *,
    command_schema: dict,
    command_duration_min_s: float,
    command_duration_max_s: float,
    command_duration_default_s: float,
) -> str:
    observation_json = json.dumps(
        observation.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
    )
    schema_json = json.dumps(
        command_schema,
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
    )
    return f"""以下是当前观测信息。你只能使用此 observation 中的信息做决策。
<observation_json>
{observation_json}
</observation_json>

请从 observation.available_actions 中选择下一步双手柄操作，并返回一个严格 JSON 对象。所有字段名和枚举值必须使用英文，例如 left、neutral、right、in、out、up、down、none、request_attach、request_release。不要输出 Markdown，不要输出 JSON 以外的解释。

command_duration_s 默认约 {command_duration_default_s} 秒，允许范围 [{command_duration_min_s}, {command_duration_max_s}] 秒。

输出 JSON 必须符合以下 schema：
<command_schema_json>
{schema_json}
</command_schema_json>
"""


def build_retry_prompt(
    validation_errors: List[CommandValidationError],
) -> str:
    errors = [
        {
            "error_code": error.error_code,
            "field_path": error.field_path,
            "message": error.message,
            "raw_fragment": error.raw_fragment,
        }
        for error in validation_errors
    ]
    errors_json = json.dumps(errors, ensure_ascii=False, sort_keys=True, indent=2)
    return f"""上一轮输出没有通过结构化校验。请根据以下 validation errors 修正。
<validation_errors_json>
{errors_json}
</validation_errors_json>

只返回修正后的严格 JSON 对象，不要输出 Markdown 或额外解释。字段名和枚举值必须继续使用英文 schema 值；reason 可以使用中文。
"""


def build_operator_messages(
    observation: Observation,
    *,
    command_schema: dict,
    command_duration_min_s: float,
    command_duration_max_s: float,
    command_duration_default_s: float,
    retry_errors: Optional[List[CommandValidationError]] = None,
) -> List[LLMMessage]:
    profile_prompt = get_profile_prompt(observation.operator_profile)
    behavior_params = get_profile_behavior_params(observation.operator_profile)
    messages = [
        LLMMessage(
            role="system",
            content=build_system_prompt(
                profile=observation.operator_profile,
                profile_prompt=profile_prompt,
                behavior_params=behavior_params,
            ),
        ),
        LLMMessage(
            role="user",
            content=build_user_prompt(
                observation,
                command_schema=command_schema,
                command_duration_min_s=command_duration_min_s,
                command_duration_max_s=command_duration_max_s,
                command_duration_default_s=command_duration_default_s,
            ),
        ),
    ]
    if retry_errors:
        messages.append(
            LLMMessage(role="user", content=build_retry_prompt(retry_errors))
        )
    return messages
