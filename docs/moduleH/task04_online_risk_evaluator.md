# Task 04：Online Risk Evaluator

## 任务目标

实现在线风险影子评估层，只使用当前状态、当前速度、当前命令和短时外推，计算塔吊对之间的当前最小距离、预测最小距离、TTC 和风险等级，产出每帧每对塔吊的 `RiskPairResult` 与聚合 `OnlineRisk`。

## 范围：做什么 / 不做什么

做：

- 新增 `backend/app/sim/risk.py`。
- 计算每对塔吊的 `d_min_online_m`。
- 计算短时外推 `d_hat_min_m`。
- 估计 `ttc_hat_s`。
- 计算 `d_safe_effective_m = base_threshold_m + wind_extra_m`。
- 支持 `geometry_envelope.jib_radius_m`、`hook_radius_m`、`load_radius_m`。
- 支持 jib-jib、jib-hook、hook-hook、load 相关距离的 MVP 计算。
- 将风险等级映射为 `safe/low/medium/high/near_miss/collision`。
- 为每台塔吊生成可被模块 F 消费的 `OnlineRiskHint`。
- 明确 `used_future_truth=False`，并通过测试防止使用 future/offline 字段。

不做：

- 不读取真实未来轨迹。
- 不读取离线标签。
- 不读取邻塔未来任务计划。
- 不修改命令。
- 不终止 episode。
- 不写记录文件。

## 接口与数据结构（签名级别）

```python
def evaluate_online_risk(
    *,
    crane_states: list[CraneState],
    crane_configs: list[CraneConfig],
    risk_config: RiskConfig,
    weather_state: WeatherState,
    proposed_commands: dict[str, ExecutedCommand],
    horizon_s: float = 5.0,
    sample_dt_s: float = 1.0,
) -> OnlineRisk:
    ...

def evaluate_pair_risk(
    *,
    state_a: CraneState,
    config_a: CraneConfig,
    command_a: ExecutedCommand,
    state_b: CraneState,
    config_b: CraneConfig,
    command_b: ExecutedCommand,
    risk_config: RiskConfig,
    weather_state: WeatherState,
    horizon_s: float,
    sample_dt_s: float,
) -> RiskPairResult:
    ...

def distance_between_cranes(
    *,
    state_a: CraneState,
    config_a: CraneConfig,
    state_b: CraneState,
    config_b: CraneConfig,
    envelope: GeometryEnvelopeConfig,
) -> tuple[float, RiskObjectType, RiskObjectType]:
    ...

def extrapolate_state_short_horizon(
    *,
    state: CraneState,
    config: CraneConfig,
    command: ExecutedCommand,
    dt_s: float,
) -> CraneState:
    ...

def classify_risk_level(
    *,
    d_min_online_m: float,
    d_hat_min_m: float,
    ttc_hat_s: float | None,
    thresholds_m: RiskThresholdsConfig,
    d_safe_effective_m: float,
) -> RiskLevel:
    ...
```

TTC MVP 可以通过连续采样估算：若距离序列首次低于 `d_safe_effective_m`，返回对应时间；若始终未低于阈值，返回 `None`。后续可以替换为解析几何算法。

## 前置依赖

- Task 01 的 `OnlineRisk`、`RiskPairResult` 和 `RiskLevel`。
- Task 02/03 后的 proposed `ExecutedCommand`。
- `RiskConfig.geometry_envelope`、`thresholds_m`、`ttc_threshold_level`、`wind_safe_distance_factor`。
- `WeatherState.wind_for_safety_m_s`。
- `CraneState` 和 `CraneConfig`。

## 验收标准（具体、可测试）

- 两台塔吊相距很远时风险为 `safe`。
- 当前距离进入 low/medium/high/near_miss 阈值时映射到对应风险等级。
- 几何包络相交或距离为 0 时风险为 `collision`。
- 短时外推显示闭合但当前安全时，`d_hat_min_m < d_min_online_m`，`relative_motion="closing"`。
- 远离时 `relative_motion="opening"`。
- 稳定距离时 `relative_motion="stable"`。
- `wind_safe_distance_factor.enabled=True` 时，`wind_extra_m` 随 `wind_for_safety_m_s` 增加。
- `enabled=False` 时，`wind_extra_m=0`。
- `OnlineRisk.pairs` 包含每帧每对塔吊结果，N 台塔吊应有 `N*(N-1)/2` 个 pair。
- `OnlineRisk.global_risk_level` 等于 pairs 中最高风险等级。
- `hint_by_crane` 在 R1 可用，不包含 offline/future 字段。
- 任何风险计算对象都不包含 `future_min_distance`、`offline_ttc`、`offline_label` 等字段。

## 测试要点（正常 + 边界 + 异常）

- 正常：jib-jib 接近、jib-hook 接近、hook-hook 接近、load-hook 接近。
- 边界：单塔场景；两个塔根重合但高度不同；距离正好等于阈值；`ttc_hat_s=None`。
- 异常：重复 crane_id、缺少对应 config/command、horizon_s <= 0、sample_dt_s <= 0。
- 防泄漏：用静态扫描确认 `risk.py` 不引用 future/offline label 字段；构造带额外 future 字段的输入应被 schema 拒绝。
