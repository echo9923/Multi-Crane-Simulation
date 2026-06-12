# Task 04：Decision Timing

## 任务目标

实现每塔决策时刻判定：基于 `llm_decision_interval_s` 和每塔上次决策时间，返回当前帧需要决策的 crane id；idle 阶段和 active 阶段使用同一逻辑。

## 范围：做什么 / 不做什么

做：

- 在 `backend/app/sim/scheduler.py` 中实现 `DecisionClock` 或调度器内等价组件。
- 跟踪每台塔吊 `last_decision_time_s` 和 `decision_index`。
- 实现 `cranes_due_for_decision(sim_time, include_idle=True)`。
- 实现 `mark_decided(crane_ids, decision_time)`。
- 支持首次决策、任务激活后的 idle/active 决策、多塔同时决策。
- 为 rule driver、LLM driver、mock driver、replay driver 使用同一 due 判定。
- 处理浮点容差，避免 `0.3 - 0.2` 这类误差导致漏判。

不做：

- 不调用 G 的 provider。
- 不构造 observation。
- 不根据 operator profile 改变 interval。
- 不做任务策略或 idle 动作判断。
- 不处理 command expiry；command expiry 属于 Task 03。

## 接口与数据结构（签名级别）

```python
class DecisionClock:
    def __init__(
        self,
        *,
        crane_ids: Sequence[str],
        llm_decision_interval_s: float,
        epsilon_s: float = 1.0e-9,
    ) -> None:
        ...

    def cranes_due_for_decision(
        self,
        *,
        sim_time: float,
        include_idle: bool = True,
        active_crane_ids: Collection[str] | None = None,
    ) -> list[str]:
        ...

    def mark_decided(
        self,
        crane_ids: Sequence[str],
        *,
        decision_time_s: float,
    ) -> None:
        ...

    def decision_index(self, crane_id: str) -> int:
        ...

    def last_decision_time(self, crane_id: str) -> float | None:
        ...
```

判定规则：

```text
if last_decision_time_s is None:
  due = True
else:
  due = sim_time - last_decision_time_s + epsilon_s >= llm_decision_interval_s
```

`include_idle`：

- `include_idle=True`：所有 crane ids 都按同一 interval 判断。
- `include_idle=False`：只判断 `active_crane_ids`。
- Module J 默认使用 `include_idle=True`，满足 idle 塔吊也参与决策的合同。

排序规则：

- 返回顺序稳定，默认与 `crane_ids` 初始化顺序一致。
- 不按 dict/hash 顺序。

与 G 的 `OperatorDecisionOrchestrator.should_decide()` 关系：

- J 的 `DecisionClock` 是 frame loop 权威 due 判定。
- G 的 `should_decide()` 可作为防御性检查或向后兼容，但 J 不应把 due 判定分散到 G 内部。
- 如果两者存在不一致，测试应暴露并优先修正 J/G 合同。

## 前置依赖

- Task 01 `SchedulerConfig`。
- 当前 `CraneConfig[]` 或 crane id 列表。
- D 的 active/idle task state 可选输入。

## 验收标准（具体、可测试）

- `sim_time=0` 时所有塔吊首次 due。
- `mark_decided(["C1", "C2"], decision_time_s=0)` 后，`sim_time < interval` 不 due。
- `sim_time == interval` 时 C1/C2 due。
- C1 决策后 C2 未决策时，下一帧只返回 C2。
- 返回顺序与初始化 crane id 顺序一致。
- `include_idle=True` 时 idle crane 也 due。
- `include_idle=False` 时 idle crane 不 due，active crane due。
- `llm_decision_interval_s <= 0` 抛 `SchedulerError`。
- 未知 crane id 传入 `mark_decided()` 抛 `SchedulerError`。
- 浮点边界：interval=0.1，sim_time=0.30000000000000004 时不会漏判。

## 测试要点（正常 + 边界 + 异常）

- 正常：两塔同频同时 due，mark 后同时更新。
- 正常：三塔中只有 C2 到期，返回 `["C2"]`。
- 边界：首次决策时 last_decision_time 为 None。
- 边界：active_crane_ids 为空但 include_idle=True，仍返回 due cranes。
- 异常：duplicate crane ids 初始化。
- 异常：sim_time 倒退小于 last_decision_time；实现应抛错或明确返回空，并在文档/测试固化。
- 合同：rule driver 和 LLM driver fixtures 都通过同一个 `DecisionClock` 得到 due cranes。
