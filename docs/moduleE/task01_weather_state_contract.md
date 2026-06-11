# Task 01：WeatherState、枚举与诊断事件合同

## 任务目标

定义模块 E 的运行时领域对象，使调度器、observation、风险模块、recorder、前端和 dataset builder 都读取同一套天气状态合同。该任务只定义对象和字段语义，不实现天气序列生成算法。

权威来源：`群塔LLM仿真系统开发方案_v0.4_完整版.md` 中 `0.5.17`、`0.7.2`、`0.7.3`、`模块 E.2-E.4`、`模块 L.4.1`。

## 任务范围

本任务定义：

- `WeatherState`
- `VisibilityLevel`
- `RainLevel`
- `FogLevel`
- `WindAdvisoryLevel`
- `VisibilityProfile`
- `WeatherGenerationReport`
- `WeatherDiagnostic`
- weather event / warning payload 基础字段
- 与 `CraneState.wind_effect_on_swing` 的预留边界

本任务不实现：

- constant/schedule/random 生成逻辑。
- WorldSnapshot 冻结。
- LLM observation 构造。
- online risk 计算。
- recorder 文件写入。
- 前端显示。

## 建议代码位置

```text
backend/app/schemas/weather.py
backend/app/sim/weather.py
backend/app/tests/test_weather_state.py
```

如果需要补充已有 enum，修改位置应为：

```text
backend/app/schemas/enums.py
backend/app/tests/test_config_schema.py
```

配置 schema 的 owner 仍是模块 A；模块 E 只是提出并消费这些字段。

## 核心枚举

`WeatherMode` 已存在：

```text
constant
schedule
random
```

`VisibilityLevel` 至少支持：

```text
good
medium
poor
```

`RainLevel` 建议支持：

```text
none
light
moderate
heavy
```

`FogLevel` 建议支持：

```text
none
light
medium
dense
```

`WindAdvisoryLevel` 建议支持：

```text
normal
caution
gusty
strong_wind
```

边界规则：

- `VisibilityLevel` 是 E/F 共享的天气观测等级，不是风险等级。
- `RainLevel` 和 `FogLevel` 在 MVP 只影响 observation/record，不改变物理。
- `WindAdvisoryLevel` 只用于提示和统计，不自动硬限制命令。

## WeatherState

最低字段：

```text
schema_version: str
time_s: float
mode: "constant" | "schedule" | "random"
wind_speed_m_s: float
wind_gust_m_s: float
wind_direction_deg: float
wind_for_safety_m_s: float
wind_advisory_level: "normal" | "caution" | "gusty" | "strong_wind"
visibility_level: "good" | "medium" | "poor"
rain_level: "none" | "light" | "moderate" | "heavy"
fog_level: "none" | "light" | "medium" | "dense"
neighbor_visibility_radius_m: float
distance_noise_m: float
hide_hook_prob: float
visibility_confidence: float
source_segment_id: str | null
generation_seed: int
generation_step: int
diagnostics: list[WeatherDiagnostic]
```

字段解释：

- `time_s` 是 episode 内绝对仿真时间，单位秒。
- `wind_speed_m_s` 是当前平均风速。
- `wind_gust_m_s` 是当前阵风峰值或短时阵风估计值，必须大于等于 `wind_speed_m_s`。
- `wind_direction_deg` 使用 ENU 平面角度，范围 `[0, 360]`；实现时应规范化 `360` 为合法值，不得出现负数。
- `wind_for_safety_m_s = max(wind_speed_m_s, wind_gust_m_s)`，供 H 模块计算安全距离冗余。
- `neighbor_visibility_radius_m`、`distance_noise_m`、`hide_hook_prob` 来自当前 `visibility_level` 的 profile。
- `visibility_confidence` 建议 good=1.0、medium=0.7、poor=0.4，可由配置覆盖。
- `source_segment_id` 标识 schedule/random 的当前天气片段；constant 模式可为 `null` 或 `"constant"`.
- `generation_step` 是天气更新离散步编号，通常为 `floor(time_s / update_interval_s)`。

## VisibilityProfile

建议字段：

```text
schema_version: str
level: "good" | "medium" | "poor"
neighbor_visibility_radius_m: float
distance_noise_m: float
hide_hook_prob: float
visibility_confidence: float
distance_precision_m: float
description_key: str
```

默认 profile：

```text
good:
  neighbor_visibility_radius_m: 120
  distance_noise_m: 0.5
  hide_hook_prob: 0.0
  visibility_confidence: 1.0
  distance_precision_m: 0.5

medium:
  neighbor_visibility_radius_m: 80
  distance_noise_m: 2.0
  hide_hook_prob: 0.2
  visibility_confidence: 0.7
  distance_precision_m: 2.0

poor:
  neighbor_visibility_radius_m: 45
  distance_noise_m: 5.0
  hide_hook_prob: 0.5
  visibility_confidence: 0.4
  distance_precision_m: 5.0
```

说明：

- E 只提供 profile，不决定某个邻塔是否可见。
- `distance_precision_m` 给 F 的 observation 文本/JSON 四舍五入使用。
- `description_key` 用于后续前端/i18n，不应直接写死 prompt 文案。

## WeatherDiagnostic

最低字段：

```text
schema_version: str
code: str
severity: "diagnostic" | "warning" | "error"
time_s: float
message: str
details: dict
```

典型 code：

```text
WEATHER_W_201
WEATHER_W_202
WEATHER_D_301
```

规则：

- diagnostic 可以随 `WeatherState` 携带，但不要求每帧都有。
- warning 必须能被 recorder/event system 捕获，不能只存在内存日志。
- error 必须由 J 映射为 startup error 或 episode failure request，不由 E 直接写 episode terminal status。

## WeatherGenerationReport

用于 episode 启动时或测试中追溯天气生成：

```text
schema_version: str
mode: str
seed: int
update_interval_s: float
timeline_segment_count: int
first_state: WeatherState
config_defaults_applied: list[str]
warnings: list[WeatherDiagnostic]
```

说明：

- report 可被 run metadata 或 summary 引用。
- report 不替代每帧 `WeatherState`。
- random 模式必须能从 report 和 resolved config 追溯生成参数。

## 与 CraneState.wind_effect_on_swing 的边界

MVP 中：

```text
CraneState.wind_effect_on_swing = null
CraneState.swing_angle_rad = 0
CraneState.swing_velocity_rad_s = 0
```

模块 E 不写这些字段。后续如新增风载或吊物摆动，应由模块 C 定义物理模型，并把 `WeatherState` 作为只读输入；不得让 E 直接修改塔吊物理状态。

## weather event payload 基础字段

最低字段：

```text
schema_version
event_type
time_s
frame_index
weather_code
severity
weather_state
reason
details
```

推荐 event types：

```text
weather_warning
weather_profile_changed
weather_runtime_error
poor_visibility_entered
poor_visibility_resolved
strong_wind_entered
strong_wind_resolved
```

EventSink 可决定是否全部落盘；E 不负责事件 ID 分配和 JSONL 写入。

## 序列化规则

- `WeatherState` 必须可 JSON 序列化。
- 所有 float 必须是有限值，不允许 NaN/Inf。
- 所有单位写在字段名中。
- `wind_direction_deg=360` 可以保留为 360，但不得在序列化后变成 0 以外的非法值；项目内应固定一种规范化策略。
- `hide_hook_prob` 必须在 `[0, 1]`。
- `visibility_confidence` 必须在 `[0, 1]`。

## 验收标准

- 能构造一个 constant weather 的 `WeatherState`。
- 能构造 good/medium/poor 三档 `VisibilityProfile`。
- `wind_gust_m_s < wind_speed_m_s` 必须在配置或生成阶段失败为 `WEATHER_E_001` / `WEATHER_E_101`，不得静默修正后进入运行态。
- NaN/Inf weather 字段被拒绝。
- `WeatherState` 可 `model_dump` / JSON 序列化。
- weather warning payload 可 JSON 序列化。
- `CraneState.wind_effect_on_swing` 在模块 E 测试中不被写入。
