# Task 06：Decision Orchestrator

## 任务目标

组装模块 G 的完整多塔决策流程，管理每塔独立 operator session、历史上下文、决策频率门控和调用记录输出。

## 范围：做什么 / 不做什么

做：

- 新增 `backend/app/sim/operator_decision.py`。
- 定义 `OperatorDecisionOrchestrator`。
- 按 `Observation.crane_id/operator_id` 管理多塔独立 `OperatorSession`。
- 按 `LLMHistoryMode` 维护 prompt 可用历史：none/short/long。
- 支持 `LLMSchedulingMode.OFFLINE_WAIT` 和 `REALTIME_STALE` 的 G 侧决策到期判断；最终 episode clock 仍由 J 控制。
- 对同一 decision time 的多个 observations 并行或批量调用 provider，返回 `list[OperatorDecisionResult]`。
- 汇总每个 result 的 `LLMCallRecord`，交给 L 后续落盘。
- 确保 G 只读取 `Observation`，不读取 `WorldSnapshot` 或全局状态。

不做：

- 不冻结 `WorldSnapshot`，不构造 observation。
- 不推进仿真时间。
- 不决定哪些 physics frames 执行旧命令或新命令；J/I 负责 command expiry/stale 应用。
- 不实现真实并发框架的复杂调度；初版可用顺序 fake provider 测试，接口预留并行。
- 不写 JSONL。
- 不调用 H/I/C/D。

## 接口与数据结构（签名级别）

```python
class OperatorDecisionOrchestrator:
    def __init__(
        self,
        *,
        config: LLMConfig,
        provider: LLMProvider,
        operator_profiles: dict[str, OperatorProfile],
    ) -> None:
        ...

    def should_decide(
        self,
        *,
        crane_id: str,
        time_s: float,
        llm_decision_interval_s: float,
    ) -> bool:
        ...

    def decide(
        self,
        observations: Sequence[Observation],
        *,
        llm_decision_interval_s: float,
    ) -> list[OperatorDecisionResult]:
        ...

    def get_session(self, crane_id: str, operator_id: str) -> OperatorSession:
        ...
```

history mode：

```text
none:
  每次 prompt 只包含当前 observation、profile 和 schema。

short:
  包含 Observation.memory.recent_decisions 和当前 session 最近 N 条简短结果。

long:
  包含 Observation.memory 的 task/event summary，并保留 session 中更长摘要。
  初版不调用 summary LLM，只消费 F/J 已提供的 memory summary。
```

调度约束：

- `llm_decision_interval_s` 必须大于物理 `dt`，G 侧只做防御性检查，权威配置校验归 A/J。
- idle 阶段也按决策频率调用 G。
- 同一批 observations 必须来自同一 `source_snapshot_id` 或同一 decision bucket；若不一致，抛出 orchestrator error，避免多塔看到不同时间的状态。

## 前置依赖

- Task 01 command schema 和 `OperatorSession`。
- Task 02 prompt builder。
- Task 03 provider。
- Task 04 parser。
- Task 05 retry/fallback。
- 模块 F 的 `Observation` 和 `build_observations_for_snapshot()`。

## 验收标准（具体、可测试）

- 两台塔吊使用不同 `operator_id` 时创建两个独立 session。
- 同一塔吊连续决策复用同一 session，并递增 `decision_index`。
- 一个 operator 的 failure count 不影响另一个 operator。
- `LLMHistoryMode.NONE` 不携带 session 历史。
- `LLMHistoryMode.SHORT` 携带最近决策摘要，不携带 forbidden future/offline 字段。
- `LLMHistoryMode.LONG` 消费 `Observation.memory`，不调用 summary LLM。
- `should_decide()` 按 `llm_decision_interval_s` 控制频率，避免每个 physics frame 都调用 provider。
- idle observation 仍会进入决策流程。
- 批量 observations 的 `source_snapshot_id` 不一致时失败。
- 返回结果数量与输入 observations 数量一致，且按输入顺序稳定。
- orchestrator 不导入或调用 physics/task/safety/controller/recorder writer。

## 测试要点（正常 + 边界 + 异常）

- 正常：多塔批量决策、不同 profile、短历史模式、mock provider。
- 边界：单塔、空 observations、idle task、同一 snapshot 多塔、failure 后下一次成功清零。
- 异常：重复 crane_id、snapshot_id 不一致、缺 profile assignment、provider 连续失败触发 `llm_failed`。
- 防泄漏：序列化 messages 不含 `future_min_distance`、`offline_ttc`、`offline_label`、完整全局坐标队列或 secret 字段。
