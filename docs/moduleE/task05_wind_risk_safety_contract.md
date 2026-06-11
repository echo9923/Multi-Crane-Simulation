# Task 05：风速、阵风与风险/安全冗余接口

## 任务目标

定义风速和阵风如何作为 online risk、风险提示和行为分析的输入，同时明确模块 E 不计算风险、不修改命令、不实现真实风载动力学。

权威来源：`群塔LLM仿真系统开发方案_v0.4_完整版.md` 中 `0.5.10`、`0.5.11`、`0.5.17`、`0.7.3`、`0.7.4`、`模块 H/K`。

## 任务范围

本任务定义：

- `wind_for_safety_m_s` 字段。
- `WindAdvisory` 合同。
- 风速如何进入 risk effective safe distance 的读取接口。
- gust/strong wind warning 事件。
- 大风下高档位行为记录的边界。
- 与模块 H/I/C 的职责分界。

本任务不实现：

- online risk 距离、TTC、near-miss、collision。
- 多塔风险干预。
- joystick/gear 限制。
- 真实风载动力学或吊物摆动。
- command log writer。

## 建议代码位置

```text
backend/app/schemas/weather.py
backend/app/sim/weather.py
backend/app/tests/test_weather_wind_contract.py
```

H 模块后续消费位置建议：

```text
backend/app/sim/risk.py
backend/app/tests/test_risk_weather_factor.py
```

## 风安全输入字段

`WeatherState` 必须提供：

```text
wind_speed_m_s
wind_gust_m_s
wind_direction_deg
wind_for_safety_m_s
wind_advisory_level
```

派生规则：

```text
wind_for_safety_m_s = max(wind_speed_m_s, wind_gust_m_s)
```

原因：

- H 模块可以用单一字段计算保守安全距离冗余。
- E 不需要知道风险阈值、塔吊几何或当前塔吊对。

## effective safe distance 消费合同

风险模块 H 可读取：

```text
WeatherState.wind_for_safety_m_s
RiskConfig.wind_safe_distance_factor.enabled
RiskConfig.wind_safe_distance_factor.extra_clearance_per_10m_s_wind_m
```

建议 H 使用：

```text
extra_clearance_m =
  (wind_for_safety_m_s / 10.0) * extra_clearance_per_10m_s_wind_m

d_safe_effective_m =
  d_safe_base_m + extra_clearance_m
```

边界：

- 公式 owner 是 H，不是 E。
- E 只保证 `wind_for_safety_m_s` 合法且可复现。
- `d_safe_effective_m` 不写回 `WeatherState`，除非 H 输出 `OnlineRisk` 时作为风险诊断字段。
- S0/S1/S2/S3 是否干预命令仍由 H safety/intervention pipeline 决定。

## WindAdvisory

建议字段：

```text
schema_version: str
time_s: float
level: "normal" | "caution" | "gusty" | "strong_wind"
wind_speed_m_s: float
wind_gust_m_s: float
wind_direction_deg: float
message_key: str
recommended_behavior_keys: list[str]
```

推荐行为 key：

```text
reduce_gear
slow_hoist
avoid_sudden_slew
increase_observation
pause_if_gusty
```

规则：

- 这些 key 是提示，不是控制命令。
- prompt 文案由 F/G 根据 key 生成。
- 司机是否仍在大风下使用高档位，由 command/event/summary 记录，不由 E 判定 task failure。

## strong wind / gust warning

建议事件：

```text
strong_wind_entered
strong_wind_resolved
gust_warning
```

payload 最低字段：

```text
schema_version
event_type
time_s
frame_index
wind_speed_m_s
wind_gust_m_s
wind_direction_deg
wind_advisory_level
details
```

去重规则：

- E 可以在 `WeatherState.diagnostics` 中标出 advisory。
- 是否生成 enter/update/exit 事件由 J/EventSink 或 E 的轻量状态机决定；实现时必须固定一个 owner。
- 不得每帧无冷却地刷大量 warning 事件。

推荐 owner：

```text
E 负责检测 advisory level 变化并提交 weather event payload；
EventSink 负责分配 event_id 与落盘。
```

## 大风高档位行为记录

总方案要求：

```text
是否在大风下仍使用高档位必须记录，便于后续行为分析。
```

边界拆分：

- E 提供当前 `wind_advisory_level` 和 `wind_for_safety_m_s`。
- G/H/I/L 或 command recorder 记录 executed gear。
- L/O summary 统计 strong wind 下高档位行为。
- E 不读取 command，也不判断司机行为是否违规。

后续统计建议字段：

```text
executed_command.wind_advisory_level
executed_command.wind_for_safety_m_s
episode_summary.high_gear_under_strong_wind_count
```

这些字段 owner 不属于 E。

## 与物理模块 C 的边界

MVP：

- 不模拟真实风载动力学。
- 不模拟吊物摆动。
- `CraneState.wind_effect_on_swing = null`。
- 风不会直接改变 `theta_rad`、`trolley_r_m`、`hook_h_m`、`load_position`。

未来扩展：

- C 可以把 `WeatherState` 作为只读输入。
- C 负责定义风载/摆动方程。
- E 仍只生成环境变量。

## 与控制器 I 的边界

E 不生成：

- `ControlTarget`
- gear clamp
- emergency_stop
- neutral_stop
- deadman policy

如果 S2/S3 在大风和高风险叠加时限制速度：

- H safety/intervention pipeline 决定是否干预。
- I 只执行已生成的 `ExecutedCommand` 或 safety 后命令。
- E 只提供天气输入。

## 验收标准

- `wind_for_safety_m_s` 总是等于平均风和阵风的最大值。
- strong wind/gust advisory 可由 WeatherState 派生。
- E 不导入 risk 计算模块。
- E 不修改 command 或 control target。
- E 不写 `CraneState.wind_effect_on_swing`。
- H 后续可仅凭 `WeatherState` 和 `RiskConfig.wind_safe_distance_factor` 计算 effective safe distance。
- 大风高档位统计边界清晰，不把统计职责塞进 E。
