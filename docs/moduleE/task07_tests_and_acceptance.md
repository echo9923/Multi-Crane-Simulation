# Task 07：模块 E 测试清单与验收标准

## 任务目标

定义模块 E 的单元测试、合同测试、集成测试和验收退出条件，确保天气状态、配置、生成器、可见度、风风险接口、调度/记录合同都可复现、可测试、边界清晰。

权威来源：`群塔LLM仿真系统开发方案_v0.4_完整版.md` 中 `0.5.17`、`0.7.2`、`0.7.3`、`0.7.8`、`0.7.9`、`模块 E.4`、`模块 L.4.1`。

## 任务范围

本任务定义：

- schema/object 测试。
- weather config/resolve/hash 测试。
- constant/schedule/random 生成测试。
- visibility observation 合同测试。
- wind risk/safety 合同测试。
- scheduler/recorder/replay 合同测试。
- 模块边界回归测试。
- 模块 E 完成定义。

本任务不要求实现：

- 真实 LLM provider。
- 完整模块 F observation。
- 完整模块 H risk。
- recorder Parquet writer。
- 前端 UI。
- 真实风载动力学。

## 建议测试文件

```text
backend/app/tests/test_weather_state.py
backend/app/tests/test_weather_config.py
backend/app/tests/test_weather_generation.py
backend/app/tests/test_weather_visibility_contract.py
backend/app/tests/test_weather_wind_contract.py
backend/app/tests/test_weather_scheduler_contract.py
backend/app/tests/test_moduleE_acceptance.py
```

## 推荐测试命令

开发中按任务运行：

```bash
pytest backend/app/tests/test_weather_state.py -v
pytest backend/app/tests/test_weather_config.py -v
pytest backend/app/tests/test_weather_generation.py -v
pytest backend/app/tests/test_weather_visibility_contract.py -v
pytest backend/app/tests/test_weather_wind_contract.py -v
pytest backend/app/tests/test_weather_scheduler_contract.py -v
```

模块 E 完整验收：

```bash
pytest backend/app/tests/test_weather_state.py \
       backend/app/tests/test_weather_config.py \
       backend/app/tests/test_weather_generation.py \
       backend/app/tests/test_weather_visibility_contract.py \
       backend/app/tests/test_weather_wind_contract.py \
       backend/app/tests/test_weather_scheduler_contract.py \
       backend/app/tests/test_moduleE_acceptance.py -v
```

回归邻近模块：

```bash
pytest backend/app/tests/test_config_schema.py \
       backend/app/tests/test_resolved_config.py \
       backend/app/tests/test_moduleA_acceptance.py \
       backend/app/tests/test_crane_state.py -v
```

## schema/object 验收

必须通过：

- `WeatherState` 可 JSON 序列化。
- `WeatherMode` 只接受 constant/schedule/random。
- `VisibilityLevel` resolved 后至少接受 canonical `good/medium/poor`；若保留旧输入，`low/high` 必须在 resolve 层映射为 `poor/good`。
- `RainLevel` / `FogLevel` 默认可表达 none。
- `wind_speed_m_s >= 0`。
- `wind_gust_m_s >= wind_speed_m_s`。
- `wind_direction_deg` 在 `[0, 360]`。
- `wind_for_safety_m_s = max(wind_speed_m_s, wind_gust_m_s)`。
- `hide_hook_prob` 在 `[0, 1]`。
- `visibility_confidence` 在 `[0, 1]`。
- 所有 weather float 字段拒绝 NaN/Inf。

## config/resolve/hash 验收

必须通过：

- 当前 fixture 中的 weather 配置继续可解析。
- 当前代码已有的 `low/medium/high` visibility 语义与总方案 `good/medium/poor` 完成迁移或兼容映射。
- `mode=schedule` 且无 segments 时 resolve 为单段 schedule。
- visibility 默认 profile 被写入 resolved config。
- precipitation 默认 `rain_level=none`、`fog_level=none` 被写入 resolved config。
- `seeds.weather` 被写入或可从 resolved config 读取。
- weather mode、seed、wind、visibility profile 变化会改变 `resolved_config_hash`。
- 非法 wind、visibility、schedule、random 配置映射为 `WEATHER_E_*` startup error。

## generation 验收

必须通过：

- constant mode 任意时间天气数值不变。
- schedule mode 支持单段 schedule。
- schedule mode 支持多段 segment 边界。
- random mode 同一 seed 完全确定。
- random mode 不同 seed 产生可观测差异。
- random mode 不污染全局 random state。
- `update(time_s)` 对同一 `time_s` idempotent。
- `time_s < 0` 失败。
- runtime invalid value 产生 `WEATHER_E_101` failure/warning。
- `WeatherGenerationReport` 可追溯 mode、seed、timeline segment count 和 defaults。

## visibility observation 合同验收

必须通过：

- good/medium/poor 默认 profile 与文档一致。
- `WeatherVisibilityContext` 可从 `WeatherState` 派生。
- 同一 seed、decision bucket、observer/target 生成稳定 sampling key。
- E 不读取 `CraneState[]` 判断具体 visible neighbors。
- E 不构造完整 `Observation`。
- poor visibility 提供 confidence/uncertainty 输入。
- visibility noise/hide 只影响 observation，不影响 recorder/risk 真值。

## wind risk/safety 合同验收

必须通过：

- strong wind/gust advisory 可由 `WeatherState` 派生。
- `wind_for_safety_m_s` 可被 H 用于 effective safe distance。
- E 不导入 risk 模块计算风险等级。
- E 不生成或修改 `ExecutedCommand`。
- E 不生成 `ControlTarget`。
- E 不写 `CraneState.wind_effect_on_swing`。
- 大风高档位行为统计边界清楚，E 只提供天气字段。

## scheduler/recorder/replay 合同验收

必须通过：

- 调度器每帧第一步可调用 `update_weather(t)`。
- `WorldSnapshot` 包含 `WeatherState`。
- observation 使用 step 前 snapshot 中的 weather。
- recorder 可从 `WeatherState` 映射 `weather.parquet` 最低字段。
- 每个 frame 有一条 weather row。
- `frames.jsonl` / WebSocket 可展示 weather summary。
- replay 可通过 resolved config + seed 重建天气序列。
- replay 可选择校验历史 `weather.parquet`，不一致时映射 replay mismatch。

## 模块边界回归

必须通过静态或单元测试确认：

- 模块 E 不调用真实 LLM provider。
- 模块 E 不导入 recorder writer。
- 模块 E 不计算 risk label、near-miss、collision。
- 模块 E 不生成 `ControlTarget`。
- 模块 E 不修改 `CraneState` 运动字段。
- 模块 E 不修改 `Task.status` 或 `TaskStage`。
- 模块 E 不直接写 episode terminal status。
- 模块 E 不读取未来轨迹或 offline label。

## 最小验收场景

建议构造一个 demo fixture：

```text
3 cranes
duration_s >= 60
weather.mode=schedule
两段 schedule：
  0-30s medium visibility, moderate wind
  30s-end poor visibility, gusty wind
risk.wind_safe_distance_factor.enabled=true
```

验收：

- 0-30s 的 `WeatherState.visibility_level=medium`。
- 30s 后 `WeatherState.visibility_level=poor`。
- gusty wind 生成 advisory。
- `WorldSnapshot.weather` 正确变化。
- `weather.parquet` 行数等于 frame 数。
- 不需要真实 LLM，也不需要真实 risk 模块完成验收。

## 完成定义

模块 E 完成后应满足：

1. 文档中 Task 01-06 的测试均通过。
2. `test_moduleE_acceptance.py` 通过。
3. 模块 A 的配置和 resolved config 回归测试仍通过。
4. 模块 C 的 `CraneState.wind_effect_on_swing` 仍保持 MVP 约定，不被 E 改写。
5. 后续 F/H/J/L/N/O/P 可以只读取 `WeatherState` 和相关合同完成自己的接入。
6. 没有把 observation、risk、physics、recorder、frontend 或 dataset 职责塞进模块 E。
