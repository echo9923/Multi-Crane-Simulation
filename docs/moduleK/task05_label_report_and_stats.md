# Task 05：Label Report And Stats

## 任务目标

实现离线标签统计与报告，输出正负样本比例、risk level 分布、按 episode/scenario/crane_pair 聚合统计，并在正样本比例过低时发出 warning。

## 范围：做什么 / 不做什么

做：

- 在 `backend/app/sim/offline_label.py` 中实现 `build_offline_risk_report()`。
- 统计全局样本数、5s/10s collision positive 数和比例。
- 统计 5s/10s risk level 分布。
- 按 `episode_id` 聚合。
- 按 `scenario_id` 聚合；`scenario_id=None` 使用 `"unknown"` 或等价稳定 key。
- 按 `crane_pair` 聚合。
- 当 collision positive ratio 低于阈值时添加 `OFFLINE_LABEL_W_LOW_POSITIVE_RATIO` warning。
- 支持可配置 warning 阈值，默认 `0.01`。
- 允许空 labels，输出 total_labels=0 和 warning。

不做：

- 不修改标签本身。
- 不重采样、不欠采样、不过采样。
- 不切分 dataset。
- 不写报告文件。
- 不计算 online/offline 差异图表；可以保留 warning/detail 字段供后续扩展。

## 接口与数据结构（签名级别）

核心接口：

```python
def build_offline_risk_report(
    *,
    labels: Sequence[OfflineRiskLabel],
    positive_collision_ratio_warning_threshold: float = 0.01,
) -> OfflineRiskReport:
    ...
```

辅助接口：

```python
def aggregate_offline_labels(
    *,
    labels: Sequence[OfflineRiskLabel],
    group_by: Literal["global", "episode", "scenario", "crane_pair"],
) -> list[OfflineRiskAggregate]:
    ...
```

warning 结构：

```python
{
    "code": OFFLINE_LABEL_W_LOW_POSITIVE_RATIO,
    "group_by": "global" | "episode" | "scenario" | "crane_pair",
    "group_key": "...",
    "positive_ratio_5s": 0.0,
    "positive_ratio_10s": 0.0,
    "threshold": 0.01,
    "message": "collision positive ratio is below threshold",
}
```

聚合规则：

```text
sample_count = number of labels in group
positive_count_5s = count(label.collision_label_5s == 1)
positive_ratio_5s = positive_count_5s / sample_count if sample_count else 0.0
positive_count_10s = count(label.collision_label_10s == 1)
positive_ratio_10s = positive_count_10s / sample_count if sample_count else 0.0
risk_level_counts_5s = Counter(label.risk_level_5s)
risk_level_counts_10s = Counter(label.risk_level_10s)
```

warning 规则：

```text
if sample_count == 0:
    emit warning for global group with positive ratios 0
elif min(positive_ratio_5s, positive_ratio_10s) < threshold:
    emit warning for that group
```

实现阶段可以选择只对 global 发 warning，也可以对所有聚合组发 warning；若对所有组发 warning，测试应固定该行为。推荐对 global、episode、scenario、crane_pair 都生成 warning，便于定位数据不平衡来源。

## 前置依赖

- Task 01 的 `OfflineRiskLabel`、`OfflineRiskAggregate`、`OfflineRiskReport` 和 warning 错误码。
- Task 04 生成的 labels。

## 验收标准（具体、可测试）

- 空 labels 返回 `total_labels=0`。
- 空 labels 产生 `OFFLINE_LABEL_W_LOW_POSITIVE_RATIO` warning。
- 10 条 labels 中 1 条 `collision_label_5s=1`，`positive_ratio_5s == 0.1`。
- risk level counts 精确统计每个 level 出现次数。
- 按 episode 聚合时，不同 episode 分开统计。
- 按 scenario 聚合时，`scenario_id=None` 使用稳定 key。
- 按 crane_pair 聚合时，`C1-C2` 与 `C2-C1` 不会分裂；依赖 label 的稳定 pair_id。
- 阈值设为 `0.01` 时，正样本比例 `< 0.01` 产生 warning。
- 正样本比例等于阈值时不产生 low positive warning。
- warning 可 JSON 序列化。
- `OfflineRiskReport.model_dump(mode="json")` 可供 L 写入 sidecar manifest 或日志。

## 测试要点（正常 + 边界 + 异常）

- 正常：构造混合 safe/high/collision labels，验证全局统计。
- 正常：两个 episode、两个 scenario、两个 pair，验证聚合数量。
- 正常：`collision_label_5s` 和 `collision_label_10s` 比例不同，分别统计。
- 边界：所有 labels 都是负样本，warning 出现。
- 边界：所有 labels 都是正样本，无 low positive warning。
- 边界：`scenario_id=None`。
- 异常：`positive_collision_ratio_warning_threshold < 0` 或 `> 1` 时抛出 ValueError。
- 序列化：report JSON 中不包含 prompt、observation、LLM 或 online intervention 字段。

## 依赖关系

依赖 Task 01 和 Task 04。Task 06 使用本任务验证正负样本比例统计和聚合验收。
