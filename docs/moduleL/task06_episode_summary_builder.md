# Task 06：Episode Summary Builder

## 任务目标

实现 `EpisodeSummary` 聚合，在 episode finalize 时基于已记录的数据和 warnings 计算总方案 L.8 的 25+ 指标，并写入 metadata。

## 范围：做什么 / 不做什么

做：

- 实现 `build_episode_summary()`。
- 从 recorder 已写入或已缓存的轻量统计状态计算 summary。
- 汇总任务完成率、deadline、overtime、risk level 分布、near miss、collision、LLM 调用、latency、cache、事件计数、数据质量指标。
- 计算 `has_nan`、`has_inf`、`max_state_jump`。
- 写入 `metadata/episode_summary.json`。
- 更新 `metadata/episode_metadata.json` 的 episode status、summary 路径、warning、updated_at。

不做：

- 不生成全局 `dataset_summary.json`；该文件由 O 聚合多个 episode 后生成。
- 不重新读取前端 `frames.jsonl` 作为训练统计真值。
- 不计算离线标签。
- 不改变已记录的 Parquet/JSONL 数据。

## 接口与数据结构（签名级别）

```python
class EpisodeStatsAccumulator:
    def __init__(self, *, episode_id: str, scenario_id: str | None = None) -> None: ...

    def observe_frame(
        self,
        *,
        frame_index: int,
        time_s: float,
        states: Sequence[CraneState],
        pair_rows: Sequence[PairRiskRow] = (),
        events: Sequence[EventLogEntry | Mapping[str, Any]] = (),
    ) -> None: ...

    def observe_tasks(self, tasks: Sequence[Task | TaskParquetRow]) -> None: ...

    def observe_command_logs(self, commands: Sequence[CommandLogEntry]) -> None: ...

    def observe_warning(self, warning: DataExportWarning) -> None: ...

    def build_summary(
        self,
        *,
        episode_status: EpisodeStatus | str,
        replay_available: bool,
    ) -> EpisodeSummary: ...
```

```python
def build_episode_summary(
    *,
    episode_id: str,
    scenario_id: str | None,
    episode_status: EpisodeStatus | str,
    duration_s: float,
    num_cranes: int,
    tasks: Sequence[TaskParquetRow | Task],
    pair_risk_rows: Sequence[PairRiskRow] = (),
    command_logs: Sequence[CommandLogEntry] = (),
    event_logs: Sequence[EventLogEntry] = (),
    warnings: Sequence[DataExportWarning] = (),
    state_jump_max_m: float | None = None,
    replay_available: bool = False,
) -> EpisodeSummary: ...
```

`max_state_jump` 计算：

- 对同一 `crane_id` 相邻 frame 的 hook/root/tip 坐标差取最大值。
- MVP 可用 hook position jump 作为代表，并在 summary 字段说明；后续可扩展为 root/tip/hook max。
- 若缺少相邻帧，不报错，返回 `None` 或 `0.0`；实现阶段需选择并测试。

risk frame ratio：

- 分母为有 pair risk 记录的 `(frame, pair)` 数量。
- 按 `risk_level_now` 计数。
- 没有 pair risk 时返回空 dict。

LLM 指标：

- `num_llm_calls` 来自 command/decision 日志。
- `llm_invalid_output_count` 和 `llm_timeout_count` 可来自 event type 或 validation errors。
- `mean_latency_ms` 忽略 null latency。
- `cache_hit_count` 统计 `cache_hit=True`。

## 前置依赖

- Task 01 的 `EpisodeSummary`、row/log schema。
- Task 02 的 metadata 路径。
- Task 03、04、05 的 writer/recording 过程向 accumulator 提供输入。

## 验收标准（具体、可测试）

- 完成 4 个任务中的 3 个时，`task_completion_rate == 0.75`。
- `num_tasks_completed`、`num_tasks_failed`、`deadline_missed_count`、`overtime_mean_s` 计算正确。
- risk level 计数转换为 ratio，总和在有数据时等于 1.0。
- `near_miss_count`、`collision_count` 来自事件统计。
- `min_clearance_over_episode` 取 pair rows 中最小 `clearance_min_now_m`。
- `high_risk_duration_s` 基于 high/near_miss/collision 风险帧和 dt 估算。
- LLM latency 均值忽略 null。
- `has_nan`、`has_inf` 从 warnings 计算。
- `max_state_jump` 对同一 crane 相邻 frame 计算正确。
- `write_episode_summary()` 生成 JSON 文件，可被 `EpisodeSummary.model_validate()` 读回。
- `metadata/episode_metadata.json` 被更新为最终 episode status。

## 测试要点（正常 + 边界 + 异常）

- 正常：构造 tasks、pair risk rows、command logs、events，验证全部核心指标。
- 正常：warning 包含 `nan_to_null` 和 `inf_to_null`，summary 标记 `has_nan=True`、`has_inf=True`。
- 边界：没有任务时 completion rate 为 `0.0`，不除零。
- 边界：没有 LLM 调用时 `mean_latency_ms=None`。
- 边界：没有 pair risk rows 时 risk ratio 为空，`min_clearance_over_episode=None`。
- 异常：summary 输出含 extra 字段失败。
- 异常：metadata 写入失败抛出 `DataExportError`。

## 依赖关系

Task 06 依赖 Task 01 和 Task 02，并消费 Task 03-05 的统计输入。Task 07 的 `finalize()` 依赖 Task 06。
