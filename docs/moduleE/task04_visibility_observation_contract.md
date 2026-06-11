# Task 04：可见度与 Observation 读取边界

## 任务目标

定义天气可见度如何影响 LLM/operator observation，同时保持职责边界：模块 E 只提供可见度等级、profile 和 deterministic sampling 输入，模块 F 才构造完整 observation 并决定具体邻塔信息如何呈现。

权威来源：`群塔LLM仿真系统开发方案_v0.4_完整版.md` 中 `0.5.9`、`0.5.10`、`0.5.17`、`0.6.5`、`0.7.2`、`模块 F`。

## 任务范围

本任务定义：

- `WeatherVisibilityContext`
- 可见度 profile 如何进入 observation builder。
- visibility 对邻塔半径、距离噪声、hook 隐藏概率的影响。
- poor visibility 下 online risk hint 的 uncertainty 合同。
- F/E 的职责分界。
- observation 可见信息与禁止信息。

本任务不实现：

- 完整 `Observation` schema。
- prompt 模板。
- 邻塔选择算法。
- online risk 计算。
- LLM provider 调用。

## 建议代码位置

```text
backend/app/schemas/weather.py
backend/app/sim/weather.py
backend/app/tests/test_weather_visibility_contract.py
```

F 模块后续消费位置建议：

```text
backend/app/sim/observation.py
backend/app/tests/test_observation_weather_visibility.py
```

## WeatherVisibilityContext

建议字段：

```text
schema_version: str
time_s: float
visibility_level: "good" | "medium" | "poor"
neighbor_visibility_radius_m: float
distance_noise_m: float
hide_hook_prob: float
visibility_confidence: float
distance_precision_m: float
noise_seed: int
profile_source: "default" | "config"
```

派生规则：

- 所有 profile 字段来自当前 `WeatherState`。
- `noise_seed` 由 `seeds.weather`、`time_s` 的 decision bucket、`visibility_level` 派生。
- `noise_seed` 只给 F 做 deterministic observation noise/hide 使用，E 不使用它读取塔吊状态。

## E/F 职责分界

模块 E 负责：

- 生成 `visibility_level`。
- 提供当前 level 的 profile。
- 提供 deterministic noise seed 或 seed salt。
- 提供 visibility confidence。
- 记录 poor visibility warning 或 event payload。

模块 F 负责：

- 根据 `WorldSnapshot` 中的当前塔吊几何判断邻塔是否在可见半径内。
- 根据 `distance_noise_m` 对可见距离做 deterministic noise。
- 根据 `hide_hook_prob` 决定是否隐藏某个邻塔 hook 信息。
- 控制 observation 中数值精度和文本表达。
- 保证 observation 不包含未来轨迹、离线标签或邻塔未来意图。

模块 E 不得：

- 读取 `CraneState[]` 后输出具体 visible neighbors。
- 判断某个 hook 是否被隐藏。
- 构造完整 prompt。
- 暴露邻塔任务队列、未来路径或 offline label。

## observation 可见度语义

默认语义：

```text
good:
  邻塔可见半径大，距离噪声小，可显示到约 0.5m。

medium:
  邻塔可见半径中等，距离噪声中等，可显示到约 1-2m。

poor:
  邻塔可见半径小，距离噪声大，可只给 near / medium / far 或粗略距离。
```

F 可以将距离表达为：

```text
good: 34.5m
medium: 约 34m
poor: near / medium / far，或约 35m 但标注不确定
```

具体文案归 F/G prompt，不归 E。

## hook 隐藏规则合同

E 提供：

```text
hide_hook_prob
noise_seed
```

F 应使用稳定 key 进行 sampling：

```text
hash(noise_seed, observer_crane_id, target_crane_id, decision_time_bucket, "hook_visibility")
```

规则：

- 同一 decision time、同一 observer/target 的 hook hide 结果必须稳定。
- 不同 observer 可以看到不同结果。
- hide hook 只影响 observation，不影响 `CraneState`、risk 计算或 recorder 真值。
- 隐藏 hook 不等于隐藏整台邻塔；F 可以仍展示邻塔大致方向或塔臂信息。

## 距离噪声规则合同

E 提供：

```text
distance_noise_m
distance_precision_m
noise_seed
```

F 应使用稳定 key：

```text
hash(noise_seed, observer_crane_id, target_crane_id, decision_time_bucket, "distance_noise")
```

规则：

- noise 只进入 observation。
- recorder 和 risk label 必须保留真实距离。
- noise 不得改变在线风险模块的几何计算。
- poor visibility 下 R1 online risk 可以仍然出现，但必须附加 confidence/uncertainty。

## R0/R1 边界

R0：

- LLM 看到任务、自身状态、可见邻塔、天气等信息。
- 不看到 online risk hint。
- visibility 仍影响邻塔观察信息。

R1：

- LLM 额外看到 online risk hint。
- poor visibility 下 risk hint 仍可给出，但必须包含 confidence/uncertainty。
- uncertainty 来源可以读取 `WeatherState.visibility_confidence`。

模块 E 只提供 confidence；risk hint 文案和 risk level 由 H/F/G 负责。

## 禁止进入 observation 的信息

天气相关 observation 禁止包含：

- future_min_distance。
- offline risk label。
- 真实未来天气片段，如果当前司机不应知道。
- 邻塔未来任务目标。
- 邻塔完整任务队列。
- random weather generator 内部未发生的未来抽样结果。

允许包含：

- 当前风速、阵风、风向。
- 当前 visibility level。
- 当前 rain/fog level。
- 当前可见度导致的不确定性说明。
- 当前 strong wind / gust advisory。

## schedule/random 未来天气可见性

默认：

- operator 只看到当前天气。
- 可选展示短时 forecast 必须作为单独配置开启，并明确 forecast horizon。
- random future segment 默认不可进入 observation，因为这会向 LLM 泄漏未来环境扰动。

MVP 建议：

```text
不提供 future weather forecast。
```

## 验收标准

- `WeatherVisibilityContext` 可从 `WeatherState` 派生。
- good/medium/poor 的 radius/noise/hide/confidence 符合默认 profile。
- 同一 seed、decision bucket、observer/target 的 sampling key 稳定。
- E 不导入或读取 `CraneState` 来筛选可见邻塔。
- E 不构造 `Observation`。
- poor visibility 能提供 uncertainty/confidence 输入。
- observation 真值与 recorder/risk 真值保持隔离。
