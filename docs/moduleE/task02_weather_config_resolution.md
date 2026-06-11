# Task 02：天气配置、默认值与 resolved contract

## 任务目标

明确模块 E 需要的配置合同，补齐当前 `WeatherConfig` 只能表达最小天气的缺口，并规定默认值、向后兼容、resolved config/hash 和 startup error 边界。

权威来源：`群塔LLM仿真系统开发方案_v0.4_完整版.md` 中 `0.5.17`、`0.6.2`、`0.7.2`、`0.8.8`、`模块 E.4`。

## 当前仓库状态

当前 `backend/app/schemas/config.py` 已有：

```text
WeatherConfig:
  mode: WeatherMode
  wind: WindConfig
  visibility: VisibilityConfig

WindConfig:
  base_speed_m_s
  gust_speed_m_s
  direction_deg

VisibilityConfig:
  base_level
```

当前 `backend/app/schemas/enums.py` 已有：

```text
WeatherMode = constant / schedule / random
VisibilityLevel = low / medium / high
```

这个结构可以支持 constant 或单段 schedule，但不足以完整支持：

- schedule 多段天气。
- random 天气的范围、变化间隔和 smoothing。
- visibility levels 的 radius/noise/hide probability。
- visibility enum 命名与总方案 `good / medium / poor` 不一致。
- rain/fog 等级。
- weather update interval。
- runtime failure policy。

## visibility enum 对齐规则

总方案和模块 E 文档使用的 canonical visibility values 是：

```text
good
medium
poor
```

当前代码和模块 A 文档仍使用：

```text
low
medium
high
```

模块 E 实现前必须先和模块 A 做一次 schema 对齐，推荐做法：

```text
high -> good
medium -> medium
low -> poor
```

边界规则：

- `WeatherState.visibility_level`、`weather.parquet.visibility_level`、LLM observation 和前端展示统一使用 `good / medium / poor`。
- `low / medium / high` 只作为旧配置兼容输入；兼容映射应发生在模块 A/config resolve 层，并写入 `defaults_applied` 或 migration diagnostic。
- 如果项目不保留旧别名，则必须同步更新 `backend/app/schemas/enums.py`、模块 A 文档和 fixtures 后再实现模块 E。
- 任何经过映射后仍未知的 visibility level 都必须失败为 `WEATHER_E_001`。

## 任务范围

本任务定义：

- weather 配置扩展建议。
- 对当前 fixture 的向后兼容规则。
- `ResolvedConfig.weather` 应包含的默认值。
- `resolved_config_hash` 中 weather 的稳定性要求。
- weather 配置错误码。

本任务不实现：

- 天气生成算法。
- observation 可见性应用。
- risk effective distance 计算。
- recorder 落盘。

## 建议代码位置

```text
backend/app/schemas/config.py
backend/app/schemas/enums.py
backend/app/core/config_resolver.py
backend/app/core/config_hash.py
backend/app/tests/test_weather_config.py
backend/app/tests/test_config_schema.py
backend/app/tests/test_resolved_config.py
```

配置 owner 仍是模块 A；模块 E 的实现只能读取 resolved 后的 weather 配置。

## 建议配置结构

建议最终支持：

```yaml
weather:
  enabled: true
  mode: "schedule"
  update_interval_s: 1.0
  runtime_failure_policy: "fail_episode"

  wind:
    base_speed_m_s: 6
    gust_speed_m_s: 12
    direction_deg: 90
    speed_bounds_m_s: [0, 20]
    direction_variability_deg: 0
    gust_probability: 0.0
    gust_duration_s: [3, 10]

  visibility:
    base_level: "medium"
    levels:
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

  precipitation:
    rain_level: "none"
    fog_level: "none"

  schedule:
    segments: []

  random:
    change_interval_s: [30, 120]
    smoothing_time_s: 10
    wind_speed_range_m_s: [0, 12]
    gust_extra_range_m_s: [0, 8]
    direction_change_range_deg: [-30, 30]
    visibility_distribution:
      good: 0.5
      medium: 0.35
      poor: 0.15
```

## 向后兼容规则

当前 fixture 形态：

```yaml
weather:
  mode: "schedule"
  wind:
    base_speed_m_s: 6
    gust_speed_m_s: 12
    direction_deg: 90
  visibility:
    base_level: "medium"
```

必须继续可用。resolve 后等价于：

```text
enabled = true
update_interval_s = sim.dt；仅在脱离 ExperimentConfig 的单元测试 fixture 中可使用 1.0 作为显式测试默认值
runtime_failure_policy = fail_episode
visibility.levels = 默认 good/medium/poor profile
precipitation.rain_level = none
precipitation.fog_level = none
schedule.segments = [single segment from time_s=0 using base wind/visibility]
random.* = 默认值，但 mode 不是 random 时不参与生成
```

关键规则：

- `mode=schedule` 且没有 `schedule.segments` 时，不得失败；应按单段 schedule 处理。
- `mode=constant` 使用 `wind` 与 `visibility.base_level` 作为全程天气。
- `mode=random` 必须有足够默认值，不要求用户手写全部 random 参数。
- 所有默认值必须进入 `ResolvedConfig`，不得只存在代码内部常量。
- resolved 后的 visibility canonical value 必须是 `good / medium / poor`，不得继续向后续模块传播旧的 `low / high`。

## schedule segment 合同

建议字段：

```text
segment_id: str
start_s: float
end_s: float | null
wind_speed_m_s: float
wind_gust_m_s: float
wind_direction_deg: float
visibility_level: str
rain_level: str
fog_level: str
transition_s: float
```

规则：

- 第一段必须从 `start_s=0` 开始，除非由向后兼容单段自动补齐。
- `start_s` 必须递增。
- `end_s=null` 只允许最后一段使用。
- segment 不得重叠。
- gaps 默认不允许；若实现允许 gaps，必须明确使用上一段 hold，并记录 diagnostic。
- `transition_s` 用于平滑风速/风向变化；MVP 可为 0。

## random config 合同

建议字段：

```text
change_interval_s: [min, max]
smoothing_time_s: float
wind_speed_range_m_s: [min, max]
gust_extra_range_m_s: [min, max]
direction_change_range_deg: [min, max]
visibility_distribution: dict[VisibilityLevel, float]
rain_distribution: dict[RainLevel, float]
fog_distribution: dict[FogLevel, float]
```

规则：

- 所有 distribution 权重必须非负且总和为 1。
- `gust_extra_range_m_s` 表示 `gust - base wind`，因此必须非负。
- `wind_speed_range_m_s` 不得超过项目配置的可接受上限；若没有全局上限，建议默认上限 25 m/s。
- random 生成必须只使用 `ResolvedConfig.seeds.weather`，不得使用系统随机。

## runtime failure policy

建议枚举：

```text
fail_episode
warn_and_hold_last
warn_and_use_safe_default
```

默认建议：

```text
fail_episode
```

规则：

- `fail_episode`：runtime 生成 NaN/Inf/越界时返回 failure request，由 J 映射为 `failed_invalid_state`。
- `warn_and_hold_last`：已有 last good state 时记录 warning 并沿用上一合法状态；没有 last good state 时失败。
- `warn_and_use_safe_default`：记录 warning 并使用 resolved safe default；只能用于调试或交互演示，研究数据 summary 必须标记。

## resolved config 要求

`ResolvedConfig.weather` 必须包含：

```text
enabled
mode
update_interval_s
runtime_failure_policy
wind resolved fields
visibility resolved profile
precipitation resolved defaults
schedule resolved segments
random resolved parameters
weather_seed
defaults_applied
```

`ResolvedConfig.seeds.weather` 已存在，必须继续作为天气随机序列唯一 seed。

## hash 要求

`resolved_config_hash` 必须包含：

- weather mode。
- weather seed。
- wind base/gust/direction。
- schedule segments。
- random bounds/distribution。
- visibility profile。
- precipitation defaults。
- runtime failure policy。

`resolved_config_hash` 不应包含：

- run 创建时间。
- 输出目录。
- runtime warning 计数。
- 已生成的每帧 weather rows，除非项目选择把 random timeline 显式固化到 resolved config 中。

如果 random timeline 在 episode 启动时预生成但不写入 resolved config，则 hash 必须包含足以重建 timeline 的全部参数。

## 错误映射

配置错误：

```text
WEATHER_E_001 weather config 语义非法 -> startup_error
WEATHER_E_002 schedule segment 非法或不连续 -> startup_error
WEATHER_E_003 random weather bounds 无法生成合法序列 -> startup_error
```

典型失败：

- `wind.base_speed_m_s < 0`
- `wind.gust_speed_m_s < wind.base_speed_m_s`
- `wind.direction_deg` 不在 `[0, 360]`
- `update_interval_s <= 0`
- `hide_hook_prob` 不在 `[0, 1]`
- `visibility_confidence` 不在 `[0, 1]`
- `neighbor_visibility_radius_m <= 0`
- random distribution 总和不为 1
- schedule segments 重叠或 end/start 非法

## 验收标准

- 当前 `scenario_valid.yaml` 的 weather 配置仍可解析。
- 当前代码的 `low / medium / high` visibility 输入要么迁移到 `good / medium / poor`，要么作为旧别名在 resolve 层显式映射。
- schedule 无 segments 时 resolve 为单段 schedule。
- constant mode 解析后全程配置确定。
- random mode 解析后包含所有 bounds 和 distributions 默认值。
- visibility 默认 profile 写入 resolved config。
- `seeds.weather` 写入 resolved config。
- `resolved_config_hash` 对 weather 字段变化敏感。
- 非法 wind、visibility、schedule、random 配置都映射到 `WEATHER_E_*` startup error。
