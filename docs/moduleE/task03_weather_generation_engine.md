# Task 03：天气序列生成器

## 任务目标

实现模块 E 的核心运行时生成器：给定 resolved weather 配置、`seeds.weather` 和 `time_s`，返回确定性的 `WeatherState`。生成器必须支持 constant、schedule、random 三种模式。

权威来源：`群塔LLM仿真系统开发方案_v0.4_完整版.md` 中 `0.5.17`、`0.7.8`、`模块 E.3-E.4`、`模块 J.2`。

## 任务范围

本任务实现：

- `WeatherGenerator`
- `WeatherTimeline`
- `WeatherGenerator.update(time_s)`
- constant mode。
- schedule mode。
- random mode。
- 风速/阵风/风向规范化。
- visibility profile 填充。
- warning/diagnostic 生成。
- runtime failure policy 的返回对象。

本任务不实现：

- 配置 schema 定义。
- observation 可见性应用。
- online risk 计算。
- physics 风载。
- recorder writer。

## 建议代码位置

```text
backend/app/sim/weather.py
backend/app/schemas/weather.py
backend/app/tests/test_weather_generation.py
```

## WeatherGenerator 接口

建议接口：

```text
WeatherGenerator.from_resolved_config(resolved_config) -> WeatherGenerator
WeatherGenerator.update(time_s: float) -> WeatherUpdateResult
WeatherGenerator.preview_timeline(duration_s: float) -> WeatherGenerationReport
```

`WeatherUpdateResult` 最低字段：

```text
weather_state: WeatherState
events: list[dict]
warnings: list[WeatherDiagnostic]
failure_request: dict | null
```

规则：

- `time_s < 0` 必须失败。
- 同一个 generator 对同一个 `time_s` 重复调用必须返回等价 `WeatherState`。
- 如果按 `update_interval_s` 离散，`time_s` 应先映射为 `generation_step = floor(time_s / update_interval_s)`。
- `WeatherState.time_s` 建议保留真实调用时间，而不是 bucket 起点。
- 实现不得依赖墙钟时间、系统随机源或调用次数。

## constant mode

输入：

```text
wind.base_speed_m_s
wind.gust_speed_m_s
wind.direction_deg
visibility.base_level
precipitation defaults
```

输出：

- 全 episode 天气不变。
- `source_segment_id = "constant"`。
- `generation_step` 随时间变化，天气数值不变。
- 如果风 advisory 阈值满足，每帧可携带 advisory 状态，但 event 是否去重由 EventSink 或 J 决定。

验收：

- `update(0)`、`update(10)`、`update(100)` 的风速、阵风、风向、可见度一致。
- `time_s` 和 `generation_step` 正确。

## schedule mode

输入：

```text
schedule.segments
```

无显式 segments 时：

```text
使用向后兼容单段 schedule。
```

segment 选择：

```text
找到 start_s <= time_s < end_s 的 segment。
最后一段 end_s=null 时覆盖到 episode 结束。
```

transition 规则：

- M1/E0 可先实现阶跃变化，即 `transition_s=0`。
- 若实现平滑 transition，只允许在当前 segment 的起始窗口内对风速/阵风/风向做确定性插值。
- visibility/rain/fog 可以阶跃变化，除非后续明确需要概率过渡。

风向插值：

- 若需要插值，必须使用最短角距离，避免 `350 -> 10` 插值绕 340 度。
- 若不实现插值，直接使用 segment 的 `wind_direction_deg`。

验收：

- 单段 schedule 与当前 fixture 兼容。
- 多段 schedule 在边界时间选择正确 segment。
- 非连续或重叠 segment 在 Task 02 阶段 startup 失败。

## random mode

random 模式必须可复现。推荐两种实现任选其一，并在实现文档中固定：

方案 A：episode 启动时预生成 `WeatherTimeline`

- 使用 `seeds.weather` 创建本地 RNG。
- 按 `change_interval_s` 生成 segment。
- 每个 segment 抽样 wind、gust extra、direction delta、visibility、rain/fog。
- `update(time_s)` 只查表，不再抽样。

方案 B：deterministic time bucket

- `generation_step = floor(time_s / update_interval_s)`。
- 使用 `hash(seed, generation_step)` 派生本地 RNG。
- 当前 step 的天气由 seed+step 直接决定。
- 若需要平滑变化，用相邻 bucket 的 deterministic 值插值。

推荐方案：

```text
方案 A。
```

原因：

- 更容易保证 gust duration 和 visibility episode 片段合理。
- replay/debug 时能输出 timeline report。
- schedule 和 random 共享 segment 查询逻辑。

random segment 生成规则：

- `wind_speed_m_s` 从 `wind_speed_range_m_s` 抽样。
- `gust_extra_m_s` 从 `gust_extra_range_m_s` 抽样。
- `wind_gust_m_s = wind_speed_m_s + gust_extra_m_s`。
- `wind_direction_deg` 从上一段方向加 deterministic delta 后规范化到 `[0, 360]`。
- `visibility_level` 按 `visibility_distribution` 抽样。
- `rain_level` / `fog_level` 按 distribution 或默认 `none`。

验收：

- 同一 seed 和 config 生成完全相同 timeline。
- 不同 seed 生成可观测差异。
- 所有生成值满足 config bounds。
- random 生成不污染 Python 全局 random state。

## 风 advisory 规则

建议阈值：

```text
normal: wind_for_safety_m_s < 8
caution: 8 <= wind_for_safety_m_s < 12
gusty: 12 <= wind_for_safety_m_s < 16
strong_wind: wind_for_safety_m_s >= 16
```

这些阈值可由配置覆盖。MVP 若不新增配置，应把默认阈值写入 resolved config。

输出规则：

- `wind_for_safety_m_s = max(wind_speed_m_s, wind_gust_m_s)`。
- `wind_advisory_level` 只影响提示/统计，不直接限制控制。
- `strong_wind` 可以生成 `WEATHER_W_201`。

## visibility 填充规则

每次生成 `WeatherState` 时必须根据 `visibility_level` 填充：

```text
neighbor_visibility_radius_m
distance_noise_m
hide_hook_prob
visibility_confidence
```

若 level 不存在：

```text
WEATHER_E_001 startup_error
```

不得在运行时悄悄回退到 medium。

## runtime failure 处理

生成后必须校验：

- 所有 float 有限。
- 风速非负。
- 阵风大于等于平均风。
- 风向合法。
- 概率字段合法。
- visibility profile 合法。

失败处理：

```text
runtime_failure_policy=fail_episode:
  WeatherUpdateResult.failure_request = WEATHER_E_101

runtime_failure_policy=warn_and_hold_last:
  若存在 last_good WeatherState，返回 last_good 的副本，并附加 WEATHER_E_101 warning。
  若不存在 last_good，返回 failure_request。

runtime_failure_policy=warn_and_use_safe_default:
  返回 safe default WeatherState，并附加 warning。
```

`safe default` 建议：

```text
wind_speed_m_s = 0
wind_gust_m_s = 0
wind_direction_deg = 0
visibility_level = good
rain_level = none
fog_level = none
```

研究数据默认不建议使用 `warn_and_use_safe_default`。

## 与调度器的调用顺序

模块 J 每帧最先调用：

```text
weather_t = weather.update(sim_time)
```

注意：

- observation 使用 step 前 frozen snapshot 中的 `weather_t`。
- recorder 普通帧默认记录 step 后状态，但天气字段使用本帧开始时 `weather_t`，实现必须在 J/L 文档中固定。
- 如果项目决定 step 后记录 `weather.update(sim_time + dt)`，必须同步调整 Task 06；不得同时混用。

## 验收标准

- constant mode 生成稳定。
- schedule mode 支持单段和多段。
- random mode 同 seed 可复现、不同 seed 有差异。
- `update(time_s)` idempotent。
- negative time 失败。
- generation 不使用全局随机。
- 风向始终在合法范围。
- `wind_gust_m_s >= wind_speed_m_s`。
- visibility profile 始终填充。
- runtime invalid value 产生 `WEATHER_E_101` failure/warning。
