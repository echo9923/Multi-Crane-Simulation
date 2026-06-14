# Task 09：样本 Metadata、统计 Summary 与 Secret 清洗

## 任务目标

生成可追溯的样本 metadata、sample index、conversion manifest 和 summary，并确保训练样本、metadata、summary、日志和错误 payload 中不泄漏完整 secret。

## 范围：做什么 / 不做什么

做：

- 新增 `backend/app/training/metadata.py`。
- 为每个 sample 生成稳定 `sample_id` 和 `StgnnSampleMetadata`。
- 写或返回 `StgnnSampleIndexRow`。
- 汇总 split/sample/risk/num_cranes/skip/warning 统计。
- 生成 `stgnn_manifest.json`、`stgnn_summary.json`、`conversion_report.json` 的数据对象。
- 对 metadata、summary、warning、error details 做 secret-like key 和 value 扫描。

不做：

- 不写 tensor 文件本体；Task 10 负责转换 orchestrator。
- 不改变 O 的 manifest/summary。
- 不隐藏必要的源文件引用；路径保留，但要避免 secret query string 或 raw credential。

## 接口与数据结构（签名级别）

```python
class SampleMetadataBuilder:
    def build(
        self,
        *,
        window: DatasetWindowIndexRow,
        feature_spec: StgnnFeatureSpec,
        source_paths: Mapping[str, Path],
        crane_order: Sequence[str],
    ) -> StgnnSampleMetadata: ...

    def sample_id(self, metadata: StgnnSampleMetadata) -> str: ...


class ConversionSummaryBuilder:
    def build(
        self,
        *,
        samples: Sequence[StgnnSampleIndexRow],
        feature_spec: StgnnFeatureSpec,
        warnings: Sequence[dict[str, Any]],
    ) -> StgnnConversionSummary: ...


def sanitize_training_payload(payload: Any) -> Any: ...
def assert_no_training_secret(payload: Any) -> None: ...
```

`sample_id` 建议输入：

```text
dataset_id, split, episode_id, start_frame, input_steps, pred_steps,
feature_spec_hash
```

## 前置依赖

- Task 01 training schema。
- Task 02 window reader。
- Task 08 variable node strategy。

## 验收标准（具体、可测试）

- 每个 metadata 包含 `dataset_id`、`split`、`scenario_id`、`episode_id`、`start_frame`、窗口参数、source paths、feature spec hash。
- 相同 window + feature spec 生成相同 sample_id。
- 不同 feature spec 生成不同 sample_id。
- summary 按 split 统计 sample counts。
- summary 统计 `max_nodes`、feature dims、risk distribution 和 skipped counts。
- secret-like key 在 metadata/summary 中被拒绝或脱敏。
- error details 中包含 `Authorization: Bearer ...` 时输出不包含原始 token。
- 所有 JSON 输出可被 Pydantic schema 回读。

## 测试要点（正常 + 边界 + 异常）

正常：

- 两个 split、三个 sample 的 summary。
- sample index row 指向 tensor path 和 offset。
- source path 是本地相对路径。

边界：

- tensor path 为 None。
- warnings 为空。
- skipped_counts 非空但 sample_counts 某 split 为 0。

异常：

- metadata details 含 `api_key`。
- path 或 message 含 `?token=raw-secret`。
- summary 中出现 NaN risk distribution。

## 依赖关系

依赖 Task 01、Task 02、Task 08。Task 10、Task 11 依赖本任务。
