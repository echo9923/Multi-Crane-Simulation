# Task 10：样本转换 Orchestrator 与 CLI

## 任务目标

串联 window reader、episode source loader、feature/label builders、variable node strategy 和 metadata/summary builder，提供可执行的 STGNN 样本转换流程和 `scripts/build_stgnn_dataset.py` CLI。

## 范围：做什么 / 不做什么

做：

- 新增 `backend/app/training/converter.py`。
- 新增 `scripts/build_stgnn_dataset.py`。
- 实现 `StgnnDatasetConverter.convert()`，按 O windows 生成样本 index、可选 tensor cache、manifest、summary 和 conversion report。
- 支持按 split 过滤和 dry-run/schema-check。
- 支持 strict 模式：任一样本失败则整体失败。
- 支持 lenient 模式：跳过失败样本并在 summary 记录原因。
- 写入 output 时使用临时路径 + replace，避免半截文件被当作完成产物。

不做：

- 不训练模型。
- 不调用 PyTorch。
- 不运行仿真或 build dataset。
- 不重新 split。
- 不修改 O/L/K 源文件。

## 接口与数据结构（签名级别）

```python
class StgnnDatasetConverter:
    def __init__(
        self,
        *,
        options: StgnnConversionOptions,
        feature_spec: StgnnFeatureSpec | None = None,
    ) -> None: ...

    def convert(
        self,
        *,
        dataset_root: Path,
        output_root: Path | None = None,
        splits: Sequence[str] | None = None,
    ) -> StgnnConversionResult: ...
```

CLI：

```text
python scripts/build_stgnn_dataset.py \
  --dataset-root runs/datasets/{dataset_id} \
  --output-root runs/datasets/{dataset_id}/training/stgnn \
  --split train --split val --split test \
  --strict
```

建议选项：

```text
--dataset-root PATH          required
--output-root PATH           optional, default dataset_root/training/stgnn
--split NAME                 repeatable; omitted means all splits
--max-nodes INT              optional explicit padding size
--strict / --lenient         default strict for tests and research reproducibility
--dry-run                    validate and summarize without writing tensor cache
--write-npz / --index-only   default index-only in first implementation if tensor cache is deferred
```

## 前置依赖

- Task 01-09。

## 验收标准（具体、可测试）

- CLI `--help` 返回 0 并列出 dataset-root/output-root/split/strict/dry-run。
- 对 tiny dataset，converter 生成 sample index、manifest、summary。
- strict 模式遇到缺字段样本时整体失败并返回非零 CLI exit。
- lenient 模式遇到缺字段样本时跳过该样本，summary 记录 skipped count 和 sanitized reason。
- dry-run 不写 tensor cache，但执行 manifest/window/source/schema/leakage 校验。
- split 过滤只转换指定 split，且不改变原 split。
- output 写入失败不会留下被 schema 读取为成功的半截 manifest/summary。
- conversion result 中所有 metadata 都可追溯到 source window row。

## 测试要点（正常 + 边界 + 异常）

正常：

- tiny dataset 从 windows 到 sample index 的完整转换。
- 只转换 `--split train`。
- dry-run 输出 summary，不写 tensors。

边界：

- 某 split 无窗口。
- index-only 模式不生成 `.npz`，但 sample metadata 完整。
- graph_edges fallback warning 写入 conversion report。

异常：

- dataset root 不存在。
- windows split leakage。
- trajectory 缺字段。
- metadata 中出现 secret-like payload。
- output root 无法写入时抛 `TRAINING_E_WRITE_FAILED`。

## 依赖关系

依赖 Task 01-09。Task 11 依赖本任务。
