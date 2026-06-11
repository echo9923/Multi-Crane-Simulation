# Task 05：Safety Intervention Pipeline

## 任务目标

实现可配置多塔干预层，将机械安全、禁区策略和在线风险结果组装为完整 H pipeline：S0/S1 只记录风险不因风险改命令，S2 高风险限速，S3 高风险或 near-miss 强制减速/停车，并记录实际干预。

## 范围：做什么 / 不做什么

做：

- 在 `backend/app/sim/safety.py` 中实现 `apply_safety_pipeline()`。
- 按命令顺序对每台塔吊执行机械安全层。
- 对机械安全后的命令执行禁区策略。
- 基于禁区策略后的命令执行在线风险评估。
- 根据 `SafetyMode` 应用风险干预。
- S0：不因风险修改命令，只记录 `ignored_risk_hint` 或等价非修改记录。
- S1：不因风险修改命令，但完整记录 risk。
- S2：`high/near_miss/collision` 风险时限速，action=`limit_speed_on_high_risk`。
- S3：`high/near_miss/collision` 风险时强制停车或减速到 neutral，action=`force_stop_on_high_risk`。
- 只在 S2/S3 因风险实际修改命令时记录 `intervention_applied` event。
- 保留每个 `ExecutedCommand.raw_command` 与最终 executed 手柄差异。
- 聚合 `SafetyPipelineResult`，供 J/I/L 消费。

不做：

- 不实现底层控制器。
- 不推进物理状态。
- 不构造 observation。
- 不写 recorder。
- 不决定 task attach/release 合法性。
- 不在 S0/S1 因风险修改命令。

## 接口与数据结构（签名级别）

```python
def apply_safety_pipeline(
    *,
    commands: list[ParsedCommand],
    crane_states: list[CraneState],
    crane_configs: list[CraneConfig],
    risk_config: RiskConfig,
    weather_state: WeatherState,
    safety_mode: SafetyMode,
    forbidden_zones: list[ZoneConfig],
    forbidden_zone_policy: ForbiddenZonePolicyConfig,
    source_snapshot_id: str,
    time_s: float,
    dt_s: float,
) -> SafetyPipelineResult:
    ...

def apply_risk_interventions(
    *,
    commands: list[ExecutedCommand],
    online_risk: OnlineRisk,
    safety_mode: SafetyMode,
) -> tuple[list[ExecutedCommand], list[InterventionRecord]]:
    ...

def limit_speed_on_high_risk(
    *,
    command: ExecutedCommand,
    speed_scale: float = 0.5,
    reason: str,
) -> ExecutedCommand:
    ...

def force_stop_on_high_risk(
    *,
    command: ExecutedCommand,
    reason: str,
) -> ExecutedCommand:
    ...
```

S2 限速 MVP：所有非 neutral 轴保留方向与 gear，但 `speed_scale` 不超过 0.5；若当前 schema 选择通过降档表达限速，则 gear 降至不超过 2。实现时只能选择一种表达，并在 Task 01 schema 中固化。

S3 停车 MVP：所有运动轴置 neutral/0，`task_action` 保持原值还是置 `none` 需要在实现前统一；默认建议保留 task_action 给 D 判定，但运动轴强制 neutral。

## 前置依赖

- Task 01 schema。
- Task 02 mechanical safety。
- Task 03 forbidden zone policy。
- Task 04 online risk evaluator。
- `SafetyMode` enum。

## 验收标准（具体、可测试）

- S0 下 high risk 不因风险修改命令，但仍保存 `OnlineRisk`。
- S1 下 high risk 不因风险修改命令，但记录 risk 和 ignored/non-modifying intervention record。
- S2 下 high risk 会限速，`ExecutedCommand.modified=True`，记录 `limit_speed_on_high_risk`。
- S2 下 medium risk 不限速。
- S3 下 high risk 会强制停车或 neutral，记录 `force_stop_on_high_risk`。
- S3 下 near_miss 会强制停车或 neutral。
- 机械限位在所有 safety mode 下都先于风险干预生效。
- hard forbidden zone 在所有 safety mode 下都先于风险干预生效。
- `intervention_applied` 只在 S2/S3 风险干预实际修改命令时出现。
- `raw_command` 和最终 `ExecutedCommand` 差异可通过序列化比较。
- 同一 batch 内所有 command 必须属于同一 `source_snapshot_id`，否则抛 `SAFETY_E_SNAPSHOT_MISMATCH`。
- 缺少某台 command/state/config 时抛 `SAFETY_E_INVALID_STATE`。

## 测试要点（正常 + 边界 + 异常）

- 正常：S0/S1/S2/S3 分别处理相同 high risk 场景。
- 边界：medium/high 阈值边界；只有一台塔吊；三台塔吊中只有一对高风险；命令已被机械限位修改后再进入风险干预。
- 异常：重复 command.crane_id、缺失 state/config、snapshot_id 不一致、未知 safety mode。
- 合同：R0/R1 不影响 H 的 risk 计算和 S2/S3 干预，只影响 F 是否暴露 safety_hint。
