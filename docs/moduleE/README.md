# 模块 E：天气与可见度模块任务索引

## 模块目标

模块 E 负责在仿真时间线上生成唯一权威的 `WeatherState`，并把风速、阵风、风向、可见度、雨/雾等级等环境信息提供给 observation、online risk、调度器、recorder 和前端展示。

模块 E 的核心不是物理风载模型。MVP 中它主要回答：

- 当前时刻天气是什么。
- 天气序列是否由配置和 seed 可复现。
- 可见度会给 observation 模块哪些可用边界。
- 风速/阵风会给风险模块哪些安全冗余输入。
- recorder 每帧应该记录哪些天气字段。

权威来源为项目根目录下的 `群塔LLM仿真系统开发方案_v0.4_完整版.md`。若本文档与总方案冲突，以总方案中 `0.5.17`、`0.7.2`、`0.7.3`、`0.7.8`、`模块 E`、`模块 J`、`模块 L` 和 `15.3` 的合同约定为准，并同步修订本文档。

## 模块边界

模块 E 的输入：

- `ScenarioConfig.weather`
- `ResolvedConfig.seeds.weather`
- 当前仿真时间 `time_s`
- 可选 episode 元数据：`episode_id`、`scenario_id`、`schema_version`
- 可选风险配置读取侧：`RiskConfig.wind_safe_distance_factor`，只用于定义消费合同，不由 E 计算风险等级

模块 E 的输出：

- `WeatherState`
- `WeatherTimeline` 或等价的 deterministic schedule/random 生成结果
- `VisibilityProfile` / `WeatherVisibilityContext`
- `WindAdvisory` / `wind_for_safety_m_s` 等风险消费字段
- 天气 warning / diagnostic / error payload
- 给 recorder 的每帧 `weather.parquet` 最低字段
- 给 frontend/API 的天气展示摘要

模块 E 允许修改：

- 天气模块内部状态，例如当前天气状态、已生成随机天气片段、last good weather。
- `WeatherState` 的运行时字段。

模块 E 不允许做的事情：

- 不修改 `CraneState` 的运动字段、载荷字段或任务字段。
- MVP 不实现真实风载动力学、吊物摆动、绳索动力学或结构弹性。
- 不直接生成 `ControlTarget`，不限制 joystick/gear。
- 不构造完整 LLM observation，不决定哪些邻塔可见。
- 不计算 online risk、near-miss、collision 或 offline label。
- 不写 `weather.parquet`、`frames.jsonl` 或 WebSocket payload；这些由 recorder/API 消费 E 的对象后落盘或推送。
- 不调用 LLM provider。
- 不读取未来轨迹、future label 或离线标签。

## 拥有对象

模块 E 拥有并写入：

- `WeatherState`
- `WeatherMode` 的运行时语义
- `VisibilityLevel` 的天气侧语义
- `RainLevel` / `FogLevel` 或等价字符串枚举
- `VisibilityProfile`
- `WeatherTimeline`
- `WeatherGenerator`
- `WeatherGenerationReport`
- `WeatherDiagnostic`
- `WEATHER_*` 错误码和 warning payload

模块 E 只读取或接收接口，不拥有：

- `ScenarioConfig`、`ResolvedConfig` 和配置 schema 定义，归模块 A。若 E 需要补字段，必须作为配置合同扩展同步更新模块 A。
- `WorldSnapshot`，归模块 J。
- `Observation` 和邻塔可见性筛选结果，归模块 F。
- `OnlineRisk`、风险等级、风险事件、collision，归模块 H/K/J。
- `CraneState`，归模块 C；MVP 中 `wind_effect_on_swing` 保持 `null`。
- `FrameRecord`、`SimFrame`、Parquet/JSONL 文件，归模块 L/N。

## 与相邻模块的接口

| 相邻模块 | 模块 E 读取什么 | 模块 E 提供什么 | 明确不做什么 |
| --- | --- | --- | --- |
| A 配置与实验管理 | `weather` 配置、`seeds.weather`、schema version | 对缺失的 weather 配置合同提出 schema 扩展需求 | 不解析原始 YAML，不回写 resolved config |
| C 物理 | 无直接依赖 | 后续风载扩展所需字段预留 | MVP 不写 `wind_effect_on_swing`，不改物理 step |
| F Observation | 无直接依赖 | `WeatherState`、可见度 profile、噪声/隐藏概率合同 | 不构造 prompt，不决定具体邻塔可见列表 |
| H/K 风险 | 无直接依赖 | `wind_for_safety_m_s`、`wind_advisory_level`、可见度 confidence 提示输入 | 不计算风险距离、TTC、near-miss、collision 或离线标签 |
| J 调度器 | `time_s`、调用顺序 | `update_weather(time_s)` 的确定性结果和 failure request | 不推进 episode clock，不决定 terminal status |
| L recorder | 无直接依赖 | 可序列化天气状态和 weather row 合同 | 不写 Parquet/JSONL |
| N 前端 | 无直接依赖 | 风向、风速、可见度、雨雾等级展示字段 | 不做前端坐标转换，不计算展示风险 |
| O/P 数据集 | 无直接依赖 | 每帧天气特征字段，可用于 batch summary/STGNN features | 不切分数据集，不重算天气真值 |

## 分阶段边界

模块 E 可以拆成三层交付：

- E0：天气状态合同、配置补齐、constant/schedule 单段模式、每帧 update。完成后调度器能在 `update_weather(t)` 得到稳定天气状态。
- E1：schedule 多段和 random 模式、可见度 profile、风安全冗余接口。完成后 F/H 可消费天气扰动。
- E2：recorder/frontend/dataset 合同和完整验收。完成后 L/N/O/P 能稳定读取天气字段。

M1 中至少需要 E0，因为单帧生命周期第一步就是 `update_weather(t)`。真实风载动力学不属于 E0/E1/E2，必须作为后续独立物理扩展处理。

## 错误码边界

模块 E 最低错误码：

```text
WEATHER_E_001 weather config 语义非法 -> startup_error，不启动 episode。
WEATHER_E_002 schedule segment 非法或不连续 -> startup_error，不启动 episode。
WEATHER_E_003 random weather bounds 无法生成合法序列 -> startup_error，不启动 episode。
WEATHER_E_101 runtime weather 生成 NaN/Inf 或越界 -> 默认 episode failed_invalid_state；若显式配置 warning hold-last-good，则记录 warning 并沿用上一合法状态。
WEATHER_W_201 风速或阵风达到 advisory 阈值 -> episode_event 或 weather warning，继续运行。
WEATHER_W_202 可见度 poor -> episode_event 或 weather warning，继续运行。
WEATHER_D_301 weather update 被重复调用且返回同一 time_s 状态 -> diagnostic，可用于调试 idempotency。
```

错误边界规则：

- 配置问题必须在启动前失败，不得进入 episode 后再发现 weather mode 无法运行。
- runtime 非法数值不得静默 clamp 后继续；必须返回结构化 failure/warning，并在 summary 中可见。
- warning 不代表任务失败，也不代表 episode 失败。

## 任务顺序

| 顺序 | 文档 | 阶段 | 目标 |
|---|---|---|---|
| 1 | [task01_weather_state_contract](task01_weather_state_contract.md) | E0 | 定义 `WeatherState`、可见度/雨雾/风建议字段和事件诊断合同 |
| 2 | [task02_weather_config_resolution](task02_weather_config_resolution.md) | E0 | 明确现有 weather 配置缺口、默认值、resolve/hash 和 startup error 边界 |
| 3 | [task03_weather_generation_engine](task03_weather_generation_engine.md) | E0/E1 | 实现 constant、schedule、random 三类可复现天气序列生成 |
| 4 | [task04_visibility_observation_contract](task04_visibility_observation_contract.md) | E1 | 定义可见度如何影响 observation，但不越界构造 observation |
| 5 | [task05_wind_risk_safety_contract](task05_wind_risk_safety_contract.md) | E1 | 定义风速/阵风如何提供风险安全冗余输入，但不计算风险 |
| 6 | [task06_scheduler_recording_integration](task06_scheduler_recording_integration.md) | E2 | 定义与调度器、WorldSnapshot、recorder、前端和 replay 的接口 |
| 7 | [task07_tests_and_acceptance](task07_tests_and_acceptance.md) | E2 | 定义模块 E 的测试清单、集成合同和验收标准 |

## 全局实现约束

- 同一 resolved config、同一 `seeds.weather`、同一 `time_s` 必须得到相同 `WeatherState`。
- `WeatherGenerator.update(time_s)` 必须不依赖墙钟时间、系统随机源或调用次数。
- replay 中天气序列必须可由 resolved config 和 seed 重建，或由历史 frame/weather 数据严格校验。
- schedule 模式没有显式 segments 时，必须兼容当前配置，视为从 `t=0` 开始的单段 schedule。
- random 模式必须先由 seed 固化生成时间片段，或使用等价的 deterministic time bucket 算法；不得每帧调用全局随机。
- 可见度只给 observation 模块提供边界参数；具体邻塔可见性、距离噪声和 hook 隐藏由 F 在 observation 构造时应用。
- 风速/阵风只给风险模块和 prompt 提供输入；MVP 不因大风自动硬限制档位。
- 雨/雾等级进入 `WeatherState`，MVP 可只作为 observation/record 字段，不改物理。
- `WeatherState` 必须可 JSON 序列化，所有数值单位必须明确。
- `weather.parquet` 每帧记录的字段必须能从 `WeatherState` 无歧义派生。
- E 不得引入对 LLM provider、recorder writer、risk labeler、physics step 的反向依赖。

## 最小交付结果

完成 Task 01-07 后，后续模块应能：

1. 从 `ResolvedConfig.weather` 和 `seeds.weather` 创建确定性的 `WeatherGenerator`。
2. 在每个仿真帧开始时调用 `update_weather(time_s)` 得到 `WeatherState`。
3. 支持 constant、schedule、random 三种 weather mode。
4. 至少支持 good、medium、poor 三档可见度。
5. 将风速、阵风、风向、可见度、雨/雾等级提供给 observation。
6. 将 `wind_for_safety_m_s` 等字段提供给 online risk 的 effective safe distance 计算。
7. 每帧给 recorder 提供 `weather.parquet` 最低字段。
8. 在配置或 runtime 失败时输出稳定 `WEATHER_*` 错误、warning 或 diagnostic。
9. 保持 MVP 不实现真实风载动力学，不直接修改塔吊运动状态。
