# Task 02：Module O Dataset Manifest 与 Windows 读取校验

## 任务目标

读取并校验 Module O 输出的 dataset manifest、split manifest、summary 和 `windows.parquet`，保证 P 只消费 O 的 split/window 结果，不重新划分、不打散、不制造 split 泄漏。

## 范围：做什么 / 不做什么

做：

- 新增 `backend/app/training/window_reader.py`。
- 读取 `metadata/dataset_manifest.json`、`metadata/dataset_summary.json`、`metadata/split_manifest.json`、`index/windows.parquet`。
- 将每行 window 校验为 `DatasetWindowIndexRow` 或兼容结构。
- 校验 `dataset_id`、schema version、窗口参数和 split assignment 一致。
- 校验同一 `episode_id` 只能出现在一个 split。
- 校验 `start_frame + input_steps + pred_steps` 是窗口最大 exclusive frame 的唯一解释。
- 返回按 split、episode、start_frame 稳定排序的 window rows。

不做：

- 不读取 episode 源 Parquet 内容。
- 不构造训练 tensor。
- 不修改 O 输出。
- 不生成新的 split 或采样策略。

## 接口与数据结构（签名级别）

```python
class DatasetWindowBundle(TrainingBaseModel):
    dataset_root: Path
    dataset_id: str
    manifest: DatasetManifest | dict[str, Any]
    summary: DatasetSummary | dict[str, Any]
    split_assignments: dict[str, str]
    windows: list[DatasetWindowIndexRow]


class DatasetWindowReader:
    def read(self, dataset_root: Path) -> DatasetWindowBundle: ...

    def validate_bundle(self, bundle: DatasetWindowBundle) -> None: ...

    def validate_no_split_leakage(
        self,
        windows: Sequence[DatasetWindowIndexRow],
        split_assignments: Mapping[str, str],
    ) -> None: ...
```

split 校验规则：

```text
1. split manifest 中同一 episode_id 不得映射到多个 split。
2. windows.parquet 中同一 episode_id 不得出现多个 split。
3. window.split 必须等于 split manifest 中该 episode_id 的 split。
4. 所有 window.dataset_id 必须等于 dataset_manifest.dataset_id。
5. P 不允许根据 window 数量、风险比例或 num_cranes 重新分配 split。
```

## 前置依赖

- Task 01 training schema。
- Module O 的 dataset schema 和 `DatasetWindowIndexRow`。
- PyArrow 可读取 Parquet。

## 验收标准（具体、可测试）

- 可从 tiny dataset root 读取 manifest、summary、split manifest 和 windows。
- `windows.parquet` 每行都通过 schema 校验。
- 返回 windows 按 `(split, episode_id, start_frame)` 稳定排序。
- 同一 episode 出现在 train 和 val 时抛 `TRAINING_E_SPLIT_LEAKAGE`。
- window row 的 split 与 split manifest 不一致时抛 `TRAINING_E_SPLIT_LEAKAGE`。
- window row 的 `dataset_id` 与 manifest 不一致时抛 `TRAINING_E_WINDOWS_INVALID`。
- 缺少 `windows.parquet`、缺列、非法 schema version 时抛 conversion error。
- reader 不生成或写入任何新文件。

## 测试要点（正常 + 边界 + 异常）

正常：

- 一个 dataset，两个 split，两个 episode，各两个 window。
- split manifest 缺少可选 holdout 字段，但 episode/split 信息完整。

边界：

- 某个 split 没有窗口合法，summary 中 sample count 可为 0。
- `scenario_id=None` 的 window 可读取。
- `source_paths` 使用相对路径或绝对路径都可表达，后续 source resolver 决定解析方式。

异常：

- manifest 缺失。
- windows 缺少 `start_frame`。
- split manifest 中 episode 重复且 split 不同。
- windows 中同一 episode 跨 split。
- secret-like 字段出现在 manifest 或 window metadata。

## 依赖关系

依赖 Task 01。Task 03、Task 10、Task 11 依赖本任务。
