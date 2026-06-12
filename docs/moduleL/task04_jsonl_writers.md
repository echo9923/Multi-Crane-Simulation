# Task 04：JSONL Writers

## 任务目标

实现 Module L 的 JSONL 写入器，支持 observation、decision、command、intervention、event 五类日志的增量追加。

## 范围：做什么 / 不做什么

做：

- 在 `backend/app/sim/recorder.py` 或 `backend/app/sim/recorder_writers.py` 中实现 JSONL writer。
- 实现 `write_observations()`、`write_decisions()`、`write_commands()`、`write_interventions()`、`write_events()`。
- 每行写入一个 JSON object，必须包含 `schema_version`。
- 使用 Task 01 的 `ObservationLogEntry`、`DecisionLogEntry`、`CommandLogEntry`、`InterventionLogEntry`、`EventLogEntry` 校验。
- 支持 append，适合每帧或每个决策时刻增量写入。
- NaN/Inf 写入为 JSON `null`，并记录 `DataExportWarning`。
- 写入失败抛出 `DataExportError`。

不做：

- 不写 Parquet。
- 不构造 observation、command 或 risk 对象。
- 不把完整 API key、token、authorization 写入 raw payload。
- 不决定哪些事件发生；只记录上游传入事件。
- 不做日志轮转或压缩。

## 接口与数据结构（签名级别）

```python
class JsonlWriter:
    def __init__(
        self,
        *,
        output_path: Path,
        row_model: type[RecorderBaseModel],
    ) -> None: ...

    def append(self, rows: Sequence[RecorderBaseModel | Mapping[str, Any]]) -> None: ...

    def flush(self) -> None: ...

    def close(self) -> None: ...
```

```python
class RecorderJsonlWriters:
    observations: JsonlWriter
    decisions: JsonlWriter
    commands: JsonlWriter
    interventions: JsonlWriter
    events: JsonlWriter

    @classmethod
    def from_layout(cls, layout: RunDirectoryLayout) -> "RecorderJsonlWriters": ...

    def write_observations(self, rows: Sequence[ObservationLogEntry | Mapping[str, Any]]) -> None: ...
    def write_decisions(self, rows: Sequence[DecisionLogEntry | Mapping[str, Any]]) -> None: ...
    def write_commands(self, rows: Sequence[CommandLogEntry | Mapping[str, Any]]) -> None: ...
    def write_interventions(self, rows: Sequence[InterventionLogEntry | Mapping[str, Any]]) -> None: ...
    def write_events(self, rows: Sequence[EventLogEntry | Mapping[str, Any]]) -> None: ...
    def flush_all(self) -> None: ...
    def close_all(self) -> None: ...
```

JSON encoding 规则：

- 使用 `model_dump(mode="json")`。
- `ensure_ascii=False` 可保留 command reason 中文内容；文件编码固定 UTF-8。
- 每条记录单行，不写漂亮缩进。
- 末尾保留换行，便于流式读取。
- 不允许 Python `NaN`、`Infinity`、`-Infinity` 被 JSON encoder 原样写出。

秘密字段策略：

```python
FORBIDDEN_EXPORT_SECRET_KEYS = {
    "api_key",
    "resolved_full_api_key",
    "raw_api_key",
    "secret",
    "token",
    "authorization",
}
```

写出前递归扫描 dict/list。命中 secret key 时：

- 若来自 `ResolvedConfig.provider` 的脱敏字段，如 `key_masked`、`key_source`，允许。
- 其他完整 secret 字段拒绝写入并抛出 `DataExportError`。

## 前置依赖

- Task 01 的 JSONL entry schema。
- Task 02 的 `RunDirectoryLayout`。
- Python 标准库 `json`。

## 验收标准（具体、可测试）

- 五个 JSONL 文件可多次 append。
- 每一行可用 `json.loads()` 读取。
- 每一行包含 `schema_version`。
- command 日志覆盖 `observation_id`、provider/model、raw response、parsed command、executed command、modified flags、latency、token_usage、retry_count、validation_errors、cache_hit。
- events 日志支持 25+ MVP event type。
- observation 日志不含 offline label/future truth 字段。
- NaN/Inf 转成 JSON null 并记录 warning。
- extra 字段导致写入失败。
- 完整 secret key 导致写入失败。
- writer flush/close 可重复调用。

## 测试要点（正常 + 边界 + 异常）

- 正常：写入一条 observation、一条 command、一条 event，逐行读回验证字段。
- 正常：同一文件 append 两次后有两行。
- 正常：command `reason` 包含中文时 UTF-8 roundtrip 不丢失。
- 边界：空 rows 不写空行。
- 边界：`token_usage=None` 合法。
- 异常：payload 包含 `api_key` 字段失败。
- 异常：JSON 序列化遇到非结构化对象失败，并抛出 `DataExportError`。
- 异常：写入目录不可写失败。

## 依赖关系

Task 04 依赖 Task 01 和 Task 02。Task 05 写 `visual/frames.jsonl` 可复用 JSONL writer 思路，但 frame writer 使用 `SimFrame` schema。Task 07 依赖 Task 04。
