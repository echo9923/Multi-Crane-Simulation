# Task 07：时间泄漏与 Split 泄漏防护

## 任务目标

集中实现并测试 Module P 的泄漏防护：禁止 split 重分配、禁止输入 feature 读取未来标签或预测窗口之后的信息，禁止跨 episode 拼接窗口。

## 范围：做什么 / 不做什么

做：

- 新增 `backend/app/training/leakage.py`。
- 定义禁止输入字段匹配规则。
- 校验 window 的输入范围、预测范围和风险 anchor frame。
- 校验 sample metadata 与 O window row 一致。
- 校验 episode/window/split 唯一性。
- 提供可被 Node/Edge/Label/Sample Builder 调用的统一 guard。

不做：

- 不读取 Parquet。
- 不构造 tensor。
- 不做 dataset split。
- 不替代 Task 02 的 manifest/window 读取校验；本任务提供构造阶段的二次防线。

## 接口与数据结构（签名级别）

```python
FORBIDDEN_INPUT_FIELD_PATTERNS = (
    r"^min_clearance_future_",
    r"^ttc_\d",
    r"^risk_level_\d",
    r"^collision_label_",
    r"offline",
    r"future_truth",
)


class LeakageGuard:
    def validate_feature_names(self, names: Sequence[str], *, kind: str) -> None: ...

    def validate_window_ranges(
        self,
        *,
        start_frame: int,
        input_steps: int,
        pred_steps: int,
        requested_input_frames: Sequence[int],
        requested_label_frames: Sequence[int],
    ) -> None: ...

    def validate_sample_metadata(
        self,
        *,
        window: DatasetWindowIndexRow,
        metadata: StgnnSampleMetadata,
    ) -> None: ...
```

范围规则：

```text
input_frames must be subset of [start_frame, start_frame + input_steps)
traj_label_frames must equal [start_frame + input_steps, start_frame + input_steps + pred_steps)
risk_label_anchor must equal start_frame + input_steps - 1
no sample may include rows from more than one episode_id
```

## 前置依赖

- Task 01 training schema。
- Task 02 window reader。
- Task 03 episode source loader。

## 验收标准（具体、可测试）

- feature names 中包含 `min_clearance_future_5s_m` 时抛 `TRAINING_E_TIME_LEAKAGE`。
- feature names 中包含 `collision_label_10s` 时抛 `TRAINING_E_TIME_LEAKAGE`。
- input frame 请求包含 prediction frame 时抛 `TRAINING_E_TIME_LEAKAGE`。
- label frame 请求超出预测窗口时抛 `TRAINING_E_TIME_AXIS_INVALID`。
- metadata 的 split、episode_id、start_frame 与 window 不一致时抛 conversion error。
- 同一 sample 引用多个 episode_id 时抛 `TRAINING_E_SOURCE_SCHEMA_INVALID`。

## 测试要点（正常 + 边界 + 异常）

正常：

- 输入帧 `[10, 11, 12]`，预测帧 `[13, 14]` 通过。
- risk anchor frame `12` 通过。
- metadata 完全复制 window 基本字段通过。

边界：

- `input_steps=1` 时 anchor frame 等于 `start_frame`。
- `pred_steps=1` 时 label frame 只有一个。

异常：

- input frames 包含 `start_frame + input_steps`。
- metadata split 从 train 改成 val。
- feature name 使用大小写变体 `Authorization` 或 `Future_Truth`，secret/leakage scanner 仍能发现。

## 依赖关系

依赖 Task 01、Task 02、Task 03。Task 04、Task 05、Task 06、Task 10、Task 11 依赖本任务。
