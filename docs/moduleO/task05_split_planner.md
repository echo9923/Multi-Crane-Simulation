# Task 05：Split Planner 与泄漏检查

## 任务目标

按 episode/scenario/layout/num_cranes 维度为合格 episode 分配 train/val/test 和 holdout split，确保不发生 window 级随机泄漏，也不让同一 episode 同时出现在多个 split。

## 范围：做什么 / 不做什么

做：

- 新增 `backend/app/data/splits.py`。
- 支持 `DatasetConfig.split.strategy = "by_scenario_and_episode"`。
- 生成 `DatasetSplitAssignment` 列表。
- 支持基础 split：`train`、`val`、`test`。
- 支持扩展 holdout：`test_seen_layout`、`test_unseen_layout`、`test_unseen_num_cranes`、`test_high_risk`。
- 实现 split 泄漏检查：
  - episode 不重复。
  - 同一 `layout_hash` 可按配置进入 seen/unseen split。
  - `unseen_num_cranes` 的 num_cranes 不应出现在 train。
  - window index 后不得跨 split。
- 输出 `metadata/split_manifest.json` 和 `splits/*/episodes.jsonl` 所需结构。

不做：

- 不构造训练窗口；Task 06 处理。
- 不重采样窗口。
- 不根据模型效果调整 split。
- 不把 quarantine episode 分配到正式 split。

## 接口与数据结构（签名级别）

```python
class DatasetSplitPlanner:
    def __init__(self, *, config: DatasetConfig) -> None: ...

    def assign(
        self,
        episodes: Sequence[DatasetEpisodeRecord],
        quality_reports: Mapping[str, DatasetQualityReport],
    ) -> list[DatasetSplitAssignment]: ...

    def validate_no_leakage(
        self,
        assignments: Sequence[DatasetSplitAssignment],
        episodes: Sequence[DatasetEpisodeRecord],
    ) -> None: ...

    def build_split_manifest(
        self,
        assignments: Sequence[DatasetSplitAssignment],
        episodes: Sequence[DatasetEpisodeRecord],
    ) -> dict[str, Any]: ...
```

默认策略：

```text
1. 过滤掉 quality_status="failed" 的 episode。
2. 按 scenario_id、layout_hash、num_cranes、episode_id 稳定排序。
3. 优先分配 holdout：
   - unseen_layout: 挑选不进入 train 的 layout_hash。
   - unseen_num_cranes: 挑选不进入 train 的 num_cranes。
   - test_high_risk: 挑选 near_miss/collision/high risk 较高 episode。
4. 剩余 episode 按 train/val/test ratio 分配。
5. 运行 validate_no_leakage。
```

如果 episode 数不足以同时满足所有 holdout，构建器应失败或降级为 warning，具体由 `DatasetBuildOptions` 控制；summary 必须报告未满足项。

## 前置依赖

- Task 01 schema。
- Task 02 catalog。
- Task 04 quality gate。
- Module A 的 `DatasetSplitConfig`。

## 验收标准（具体、可测试）

- 10 个合格 episode 按 0.7/0.15/0.15 生成稳定 split。
- 任何 episode_id 不得出现在两个 split。
- failed quality episode 不进入正式 split。
- `holdout.unseen_layout=true` 时，至少一个 test_unseen_layout 的 layout_hash 不出现在 train；如果做不到，返回明确 error/warning。
- `holdout.unseen_num_cranes=true` 时，test_unseen_num_cranes 的 num_cranes 不出现在 train。
- test_high_risk 可根据 high/near_miss/collision 统计选出候选。
- split manifest 可 JSON 序列化且不包含 secret。

## 测试要点（正常 + 边界 + 异常）

正常：

- 多 scenario、多 layout、多 crane 数量的 fixture。
- 有 high risk episode 的 fixture。
- quality warning episode 可以进入 split，并在 assignment reason 标记。

边界：

- episode 数很少，ratio 四舍五入后至少 train 有数据。
- 单一 layout 无法满足 unseen_layout，返回 warning 或 failed。
- 单一 num_cranes 无法满足 unseen_num_cranes。

异常：

- split ratio 不合法由 Module A 拒绝。
- 同一 episode_id 重复输入。
- 所有 episode 都 failed quality。
- leakage validator 检测到手工构造的重复 episode。

## 依赖关系

依赖 Task 01、Task 02、Task 04。Task 06、Task 07、Task 08、Task 09 依赖本任务。
