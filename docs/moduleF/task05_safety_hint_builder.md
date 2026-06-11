# Task 05：Safety Hint Builder

## 任务目标

消费模块 H 的在线风险提示输入，按 `RiskPromptMode` 构造 observation 中的 `safety_hint`。

## 范围

做：

- 实现 `build_safety_hint()`。
- `R0` 输出 `None`。
- `R1` 在存在 `OnlineRiskHint` 时输出 `SafetyHint`。
- 按 observation precision 圆整 clearance 数值。
- 将天气可见度置信度合入最终 confidence 上限。

不做：

- 不计算 online risk、near-miss、collision 或 TTC。
- 不读取离线标签。
- 不写风险事件。

## 接口与数据结构

```python
def build_safety_hint(
    *,
    risk_prompt_mode: RiskPromptMode,
    online_risk: OnlineRiskHint | None,
    visibility: WeatherVisibilityContext,
    distance_precision_m: float,
) -> SafetyHint | None:
    ...
```

## 前置依赖

- Task 01 schema。
- 模块 E 可见度 confidence。
- 模块 H 后续提供与 `OnlineRiskHint` 等价的输入。

## 验收标准

- `R0` 不暴露风险提示，即使传入 online risk。
- `R1` 无 online risk 时输出 `None`。
- `R1` 有 online risk 时输出 nearest neighbor、clearance、relative motion、confidence、suggestion。
- poor visibility 下 confidence 不超过 `visibility_confidence`。
- 输出中不包含 offline TTC、future min distance、risk label。

## 测试要点

- 正常：R1 + risk hint。
- 边界：R0 + risk hint、R1 + None、confidence 高于 visibility confidence。
- 异常：非法 risk confidence 由 schema 拒绝。

