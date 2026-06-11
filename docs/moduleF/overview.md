# Module F Overview：Observation 构造边界

## 职责

模块 F 为每个待决策塔吊构造 `Observation`。这个对象代表“驾驶员在当前决策时刻能看到和被提示到的信息”，不是仿真器内部的完整全局真值。

F 聚合以下信息：

- 自身塔吊当前状态：回转、小车、吊钩、载荷、当前命令摘要。
- 自己的任务上下文：任务阶段、任务类型、优先级、deadline、取货/卸货相对方位、地面信号提示。
- 天气与可见度：当前风速、阵风、风向、雨雾等级、可见度等级、可见度置信度。
- 可见邻塔：只显示在可见半径内、被天气噪声和 hook 隐藏规则处理后的当前邻塔信息。
- 在线风险提示：仅在 `RiskPromptMode.R1` 下显示模块 H 提供的当前在线风险摘要。
- 操作员与历史：操作员 profile、可用动作空间、近期决策和已发生事件摘要。

## 输入

F 的唯一状态入口是冻结的决策时刻快照。当前代码库尚未实现模块 J 的正式 `WorldSnapshot`，因此 F 先定义最小输入合同：

```text
ObservationWorldSnapshot
  snapshot_id: str
  time_s: float
  decision_time_bucket: int
  crane_states: list[CraneState]
  crane_configs: list[CraneConfig]
  weather_state: WeatherState
  visibility_context: WeatherVisibilityContext
  neighbor_map: dict[str, list[str]]
  task_contexts: dict[str, TaskObservationContext | IdleObservationContext]
  current_commands: dict[str, ControlTarget] = {}
  recent_decisions: dict[str, list[dict]] = {}
  recent_events: dict[str, list[dict]] = {}
```

其他输入：

```text
risk_prompt_mode: RiskPromptMode
operator_profiles: dict[str, OperatorProfile]
online_risks: dict[str, OnlineRiskHint]
operator_id_by_crane_id: dict[str, str] | None
```

## 输出

F 输出 `Observation` Pydantic schema。schema 是唯一事实源，`extra="forbid"`，`allow_inf_nan=False`，并包含 `schema_version` 以支持记录、重放和审计。

模块 G 只读 `Observation` 生成 prompt 和解析 LLM 行为；模块 L 只读 `Observation` 落盘到 `observations.jsonl` 或等价记录。

## 对内依赖

- A：读取 `RiskPromptMode`、`OperatorProfile` 和运行配置中的 profile 分配结果。
- B：读取 `CraneConfig` 的静态能力边界和几何参数。
- C：读取 `CraneState` 的当前帧物理状态。
- D：读取 `TaskObservationContext` 或 `IdleObservationContext`。
- E：读取 `WeatherState`、`WeatherVisibilityContext`，使用 `build_visibility_sampling_key()` 做 deterministic noise/hide。
- H：读取 `OnlineRiskHint`，但不计算风险。
- J：读取冻结的快照；F 不冻结快照。

## 非目标

模块 F 不做以下事情：

- 不调用 LLM provider，不构造最终 prompt 模板字符串。
- 不解析 `RawLLMResponse`。
- 不修改 `CraneState`、`Task.status`、`TaskQueue` 或 `ControlTarget`。
- 不计算 collision、near-miss、online risk、offline risk label、TTC 或 future min distance。
- 不推进任务状态机。
- 不生成天气，也不改变天气状态。
- 不冻结 `WorldSnapshot`。
- 不写 Parquet、JSONL 或 WebSocket payload。
- 不决定布局层面的邻塔关系；F 只在给定 neighbor candidates 上做可见性筛选。

## 防泄漏规则

`Observation` 不得包含：

- 邻塔 `task_id`、`deadline_s`、`planned_start_s`。
- 邻塔 pickup/dropoff/current target 坐标。
- 邻塔完整任务队列或未来任务目标。
- 全局最小距离真值、offline TTC、offline future_min_distance、offline label。
- 基于真实未来轨迹的任何标签或建议。

允许显示的邻塔信息仅限当前可见状态摘要，例如相对方向、带噪声距离、运动方向、载荷是否可见、当前 `task_stage` 和是否处于重叠区域。

## 失败边界

F 发现 schema 构造失败、缺少观察所需的自身状态/配置、非法数值、重复 ID 或不可序列化字段时，应抛出 `ObservationBuildError`，其默认 episode 状态映射为 `failed_invalid_state`。

