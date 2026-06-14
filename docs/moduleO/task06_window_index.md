# Task 06：Window Index 与 P 模块消费合同

## 任务目标

根据 `DatasetConfig.windows` 为每个 split 内的 episode 生成通用窗口索引，保证窗口只在单个 episode 内滑动、只属于一个 split，并为 Module P 的 STGNN/轨迹预测转换提供稳定输入。

## 范围：做什么 / 不做什么

做：

- 新增 `backend/app/data/window_index.py`。
- 读取 episode 的 frame_count、dt、num_cranes、source file paths。
- 按 `input_steps`、`pred_steps`、`stride_steps` 生成 `DatasetWindowIndexRow`。
- 窗口不能跨 episode，也不能跨 split。
- 记录 `risk_label_horizons_s`。
- 支持 negative/positive sampling 的**索引级筛选**，例如限制负样本窗口数量。
- 输出 `index/windows.parquet` 所需 row。

不做：

- 不把窗口转换为 `X_node`、`X_edge`、`A_phy`、`Y_traj`、`Y_risk` tensors；这是 Module P 的职责。
- 不训练模型。
- 不读取前端 display-only 数据。
- 不重新计算 K 的 future labels。

## 接口与数据结构（签名级别）

```python
class DatasetWindowIndexer:
    def __init__(self, *, config: DatasetConfig) -> None: ...

    def build(
        self,
        *,
        episodes: Sequence[DatasetEpisodeRecord],
        assignments: Sequence[DatasetSplitAssignment],
    ) -> list[DatasetWindowIndexRow]: ...

    def validate_no_window_leakage(
        self,
        rows: Sequence[DatasetWindowIndexRow],
        assignments: Sequence[DatasetSplitAssignment],
    ) -> None: ...
```

窗口范围规则：

```text
window_start = start_frame
input frames = [start_frame, start_frame + input_steps)
prediction frames = [start_frame + input_steps, start_frame + input_steps + pred_steps)
max exclusive frame = start_frame + input_steps + pred_steps
max exclusive frame <= episode.frame_count
next start_frame += stride_steps
```

正负样本索引筛选规则：

```text
positive window: prediction horizon 内任一相关 label 为 high/near_miss/collision 或 collision_label=1。
negative window: 不满足 positive 条件。
如果 negative_positive_sampling.enabled=true，则每个 split 内 negative_count <= positive_count * max_negative_to_positive_ratio。
如果 positive_count=0，则保留一小部分 negative smoke windows 并在 summary warning 中标记。
```

## 前置依赖

- Task 01 schema。
- Task 02 source catalog。
- Task 05 split assignments。
- Module L `pair_risks.parquet` 的离线标签列。

## 验收标准（具体、可测试）

- `frame_count=100`、`input_steps=10`、`pred_steps=20`、`stride_steps=5` 生成正确数量窗口。
- 所有窗口 `start_frame + input_steps + pred_steps <= frame_count`。
- 单个 window row 的 `split` 与 episode assignment 一致。
- 没有任何 episode_id 在 windows 中跨 split。
- negative/positive sampling 限制生效。
- `index/windows.parquet` 可被 PyArrow 读取，并可逐行 `DatasetWindowIndexRow.model_validate()`。
- 不生成 tensor 文件。

## 测试要点（正常 + 边界 + 异常）

正常：

- 两个 split、两个 episode，各生成窗口。
- pair_risks 中含 high/near_miss/collision 标签，positive 识别正确。
- disabled sampling 时保留全部窗口。

边界：

- episode frame_count 刚好等于 `input_steps + pred_steps`，生成 1 个窗口。
- episode 太短，生成 0 个窗口并 warning。
- 单塔吊 episode 无 pair risk label，仍可生成轨迹窗口，但 risk label 标记不可用。

异常：

- `stride_steps <= 0` 由 A schema 拒绝。
- pair_risks 缺失而 required labels 打开时，episode failed 或窗口构建失败。
- 手工构造跨 split assignment 被 leakage validator 拒绝。

## 依赖关系

依赖 Task 01、Task 02、Task 05。Task 07、Task 08、Task 09 依赖本任务。
