# Task 08：可变塔吊数量处理、Mask/Padding 策略

## 任务目标

实现第一版可变塔吊数量策略：按 batch 或 dataset 配置确定 `max_nodes`，对节点、边、标签进行 padding，并用 mask 明确真实塔吊与 padding 位置。

## 范围：做什么 / 不做什么

做：

- 新增 `backend/app/training/variable_nodes.py`。
- 定义 `pad_and_mask` 策略。
- 为每个 episode/window 生成稳定 `crane_order`。
- 计算 dataset/split/batch 的 `max_nodes`。
- 提供节点、边、轨迹标签、风险标签 padding helper。
- 校验 `num_cranes <= max_nodes`。

不做：

- 不按 `num_cranes` 重新划分 train/val/test。
- 不在第一版实现复杂 bucketing sampler，除非 PyTorch 适配层后续可选。
- 不改变源 episode 中的 crane_id。

## 接口与数据结构（签名级别）

```python
class VariableNodePlan(TrainingBaseModel):
    strategy: Literal["pad_and_mask"] = "pad_and_mask"
    max_nodes: int = Field(gt=0)
    crane_order_by_episode: dict[str, list[str]]


class VariableNodeStrategy:
    def plan(
        self,
        *,
        windows: Sequence[DatasetWindowIndexRow],
        episode_cranes: Mapping[str, Sequence[str]],
        configured_max_nodes: int | None = None,
    ) -> VariableNodePlan: ...

    def crane_order_for_window(
        self,
        *,
        window: DatasetWindowIndexRow,
        tables: EpisodeTables,
    ) -> list[str]: ...

    def node_mask(self, *, crane_order: Sequence[str], max_nodes: int) -> np.ndarray: ...

    def edge_mask(self, *, crane_order: Sequence[str], max_nodes: int) -> np.ndarray: ...
```

crane order 规则：

```text
1. Prefer sorted unique crane_id from trajectories for the episode.
2. If O window row num_cranes disagrees with trajectory crane count, fail.
3. Same episode must use identical crane_order for all windows.
4. Padding positions are always after real cranes.
```

## 前置依赖

- Task 01 training schema。
- Task 02 window reader。
- Task 03 episode source loader。

## 验收标准（具体、可测试）

- 2 台和 4 台塔吊 episode 共存时，`max_nodes=4`，2 台 episode padding 到 4。
- `node_mask` shape 为 `[max_nodes]`，真实节点 true，padding false。
- `edge_mask` shape 为 `[max_nodes, max_nodes]`，真实非自环 pair true，padding false。
- 同一 episode 不同窗口 crane order 完全一致。
- `window.num_cranes` 与 trajectory crane count 不一致时抛 `TRAINING_E_VARIABLE_NODES_UNSUPPORTED`。
- configured `max_nodes=3` 但出现 4 台塔吊时抛 `TRAINING_E_VARIABLE_NODES_UNSUPPORTED`。
- 该策略在 overview 和 summary 中有明确记录。

## 测试要点（正常 + 边界 + 异常）

正常：

- train 有 2 台 episode，val 有 4 台 episode，不改变 split，只 padding。
- crane id `crane_10`、`crane_2` 使用稳定排序并在 metadata 记录。

边界：

- 单塔吊 episode edge mask 全 false。
- configured_max_nodes=None 时从 windows/tables 推导最大值。
- 某 split 为空不影响全局 max_nodes。

异常：

- 同一 episode 的两个窗口推导出不同 crane order。
- trajectory 有重复 crane_id/frame 行。
- `num_cranes=0` 的 window 被拒绝。

## 依赖关系

依赖 Task 01、Task 02、Task 03。Task 04、Task 05、Task 06、Task 09、Task 10 依赖本任务。
