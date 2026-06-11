# Task 06：调度器、WorldSnapshot、记录与回放接口

## 任务目标

定义模块 E 如何接入单帧生命周期、WorldSnapshot、recorder、前端帧和 replay，确保天气状态的时间归属、落盘字段和复现方式一致。

权威来源：`群塔LLM仿真系统开发方案_v0.4_完整版.md` 中 `0.5.18`、`0.7.8`、`0.7.9`、`模块 J.2`、`模块 L.2-L.4`、`模块 N`。

## 任务范围

本任务定义：

- `update_weather(t)` 在单帧生命周期中的位置。
- `WeatherState` 如何进入 `WorldSnapshot`。
- recorder 的 `weather.parquet` 最低字段。
- `visual/frames.jsonl` / WebSocket 的天气摘要。
- replay 的天气一致性要求。
- runtime failure 如何交给 J 映射。

本任务不实现：

- 完整调度器。
- recorder writer。
- WebSocket API。
- replay engine。
- 前端 UI。

## 建议代码位置

```text
backend/app/sim/weather.py
backend/app/sim/scheduler.py
backend/app/schemas/weather.py
backend/app/tests/test_weather_scheduler_contract.py
backend/app/tests/test_weather_record_contract.py
```

后续 recorder/API 消费位置建议：

```text
backend/app/data/recorder.py
backend/app/api/*
```

## 单帧生命周期位置

每帧开始：

```text
1. weather_t = weather.update(sim_time)
2. task scheduler 激活任务
3. 冻结 WorldSnapshot_t
...
11. physics step 到 state_{t+dt}
...
14. recorder 写入 frame、trajectory、pair risk、events、commands、weather
```

约定：

- `weather_t` 表示本帧 `[sim_time, sim_time + dt]` 使用的天气。
- LLM observation 使用包含 `weather_t` 的 step 前 frozen snapshot。
- recorder 的普通帧表示 step 后状态时，weather 字段仍记录本帧使用的 `weather_t`，`time_s` 应与 frame 的记录时间保持项目统一。

推荐记录时间：

```text
frame=0, time_s=0: 记录初始 state 和 weather.update(0)
frame=n, time_s=n*dt: 记录从上一帧推进后状态，并附带该帧开始时已使用的 weather
```

如果实现选择记录 `weather.update(sim_time + dt)`，必须在 J/L 文档中同步声明，并保证 observation 和 recorder 不混用两个不同天气时刻。

## WorldSnapshot 合同

`WorldSnapshot` 应包含：

```text
schema_version
time_s
crane_states
tasks
weather: WeatherState
recent_events
```

边界：

- J 冻结 snapshot。
- E 不创建 snapshot。
- F/G/H 从 snapshot 读取 `WeatherState`。
- snapshot 中的 weather 不得包含未发生的未来 random/schedule segment。

## recorder weather.parquet 合同

`weather.parquet` 至少包含：

```text
schema_version: string
episode_id: string
scenario_id: string
frame: int
time_s: float
wind_speed_m_s: float
wind_gust_m_s: float
wind_direction_deg: float
visibility_level: string
rain_level: string
```

建议补充字段：

```text
fog_level: string
wind_for_safety_m_s: float
wind_advisory_level: string
neighbor_visibility_radius_m: float
distance_noise_m: float
hide_hook_prob: float
visibility_confidence: float
source_segment_id: string | null
generation_seed: int
generation_step: int
```

规则：

- recorder 从 `WeatherState` 映射 row。
- E 不直接写 parquet。
- 每个 frame 必须有且只有一条 weather row。
- weather row 的 `frame`、`time_s` 必须能与 trajectories/pair_risks 对齐。

## frames.jsonl / WebSocket 合同

`SimFrame.weather` 建议最低字段：

```json
{
  "wind_speed_m_s": 8.0,
  "wind_gust_m_s": 12.0,
  "wind_direction_deg": 90,
  "visibility_level": "medium",
  "rain_level": "none",
  "wind_advisory_level": "gusty"
}
```

前端可展示：

- 风速。
- 阵风。
- 风向箭头。
- 可见度等级。
- 雨/雾等级。
- 大风/阵风提示。

前端不得：

- 根据 UI 自己生成天气真值。
- 把 display-only 天气影响回写到数据集。
- 用前端天气计算替代后端 `weather.parquet`。

## replay 合同

Replay 必须满足：

- `resolved_config_hash` 一致时，weather generator 可重建同一天气序列。
- replay 不调用 LLM，也不重新随机天气。
- 如果历史 run 存在 `weather.parquet`，replay 可选择校验生成 weather 与历史 row 一致。
- 校验不一致应记录 `failed_replay_mismatch` 或 weather replay mismatch，由 J 映射。

建议校验字段：

```text
frame
time_s
wind_speed_m_s
wind_gust_m_s
wind_direction_deg
visibility_level
rain_level
```

容差：

- 枚举字段必须完全一致。
- float 字段使用固定绝对容差，例如 `1e-9` 或项目统一数值容差。

## runtime failure 交给 J

`WeatherUpdateResult.failure_request` 建议字段：

```text
source_module: "E"
error_code: "WEATHER_E_101"
reason: str
time_s: float
details: dict
default_episode_status: "failed_invalid_state"
```

J 负责：

- 按 policy 转换为 warning 或 episode failure。
- 写 episode terminal status。
- 把 event 交给 EventSink。

E 不负责：

- 直接设置 `episode_status`。
- 终止循环。
- 写 summary。

## 与 run metadata 的关系

建议 run metadata 或 episode manifest 记录：

```text
weather_mode
weather_seed
weather_runtime_failure_policy
weather_profile_hash
weather_timeline_preview_hash
```

规则：

- metadata 用于追溯，不替代 resolved config。
- 如果 random timeline 预生成且较小，可以记录 timeline hash；不要求把完整 timeline 写进 metadata。

## 验收标准

- 调度器可在每帧第一步调用 `update_weather(t)`。
- `WorldSnapshot` 可包含 `WeatherState`。
- `weather.parquet` 最低字段可由 `WeatherState` 完整映射。
- 每个 frame 有一条 weather row。
- `frames.jsonl` / WebSocket 可展示天气摘要。
- replay 能用 config+seed 重建天气，或对历史 weather row 做一致性校验。
- runtime failure 不由 E 直接写 episode status。
