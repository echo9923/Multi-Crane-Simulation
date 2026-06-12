# Task 03：Parquet Writers

## 任务目标

实现 Module L 的 Parquet 写入器，支持增量记录和最终 flush，覆盖 trajectories、pair risks、graph edges、tasks、weather 五张训练主表。

## 范围：做什么 / 不做什么

做：

- 在 `pyproject.toml` 添加 Parquet 写入依赖，推荐 `pyarrow>=16,<18`。
- 在 `backend/app/sim/recorder.py` 或拆分出的 `backend/app/sim/recorder_writers.py` 中实现 Parquet writer。
- 实现 `write_trajectories(rows)`、`write_pair_risks(rows)`、`write_graph_edges(rows)`、`write_tasks(rows)`、`write_weather(rows)`。
- 支持 append 语义：调用方可多次写入同一表，最终 `flush()` 后得到单个 Parquet 文件。
- 所有表包含 `schema_version` 列。
- 使用 Task 01 的 Pydantic 行对象进行校验。
- NaN/Inf 写入前转换为 `None`，并返回或记录 `DataExportWarning`。
- 写入失败时抛出 `DataExportError`，避免把已有权威文件替换成半截文件。

不做：

- 不从上游对象构造行；只写入已经构造好的 `TrajectoryRow` 等。
- 不计算 pair risk、graph edge、summary 指标。
- 不写 JSONL。
- 不实现 recorder orchestrator。
- 不在内存中无上限累积完整 episode；writer 可按 batch 缓冲并 flush。

## 接口与数据结构（签名级别）

```python
class ParquetTableWriter:
    def __init__(
        self,
        *,
        output_path: Path,
        row_model: type[RecorderBaseModel],
        batch_size: int = 1024,
    ) -> None: ...

    def append(self, rows: Sequence[RecorderBaseModel | Mapping[str, Any]]) -> None: ...

    def flush(self) -> None: ...

    def close(self) -> None: ...
```

```python
class RecorderParquetWriters:
    trajectories: ParquetTableWriter
    pair_risks: ParquetTableWriter
    graph_edges: ParquetTableWriter
    tasks: ParquetTableWriter
    weather: ParquetTableWriter

    @classmethod
    def from_layout(cls, layout: RunDirectoryLayout) -> "RecorderParquetWriters": ...

    def write_trajectories(self, rows: Sequence[TrajectoryRow | Mapping[str, Any]]) -> None: ...
    def write_pair_risks(self, rows: Sequence[PairRiskRow | Mapping[str, Any]]) -> None: ...
    def write_graph_edges(self, rows: Sequence[GraphEdgeRow | Mapping[str, Any]]) -> None: ...
    def write_tasks(self, rows: Sequence[TaskParquetRow | Mapping[str, Any]]) -> None: ...
    def write_weather(self, rows: Sequence[WeatherParquetRow | Mapping[str, Any]]) -> None: ...
    def flush_all(self) -> None: ...
    def close_all(self) -> None: ...
```

原子性策略：

- 写入期使用临时路径，例如 `data/.trajectories.parquet.tmp` 或分片目录。
- `flush()` 成功后再 `replace()` 到正式路径。
- 如果 writer 使用 `pyarrow.parquet.ParquetWriter` 直接写正式文件，则只允许在首次创建文件时使用，写入失败时删除未完成文件并保留错误；实现阶段需在测试中证明失败不留下被误认为完整权威文件的路径。

NaN/Inf 策略：

```python
def sanitize_for_export(
    value: Any,
    *,
    episode_id: str | None,
    frame: int | None,
    file_name: str,
    field_path: str,
) -> tuple[Any, list[DataExportWarning]]: ...
```

对 float：

- finite：原样返回。
- `math.nan`：返回 `None`，warning_type=`nan_to_null`。
- `math.inf` 或 `-math.inf`：返回 `None`，warning_type=`inf_to_null`。

## 前置依赖

- Task 01 的 Parquet 行 schema。
- Task 02 的 `RunDirectoryLayout`。
- `pyarrow` 依赖。
- pytest 可用。

## 验收标准（具体、可测试）

- `write_trajectories()` 多次 append 后，`flush_all()` 生成 `data/trajectories.parquet`。
- 五张 Parquet 文件均可用 `pyarrow.parquet.read_table()` 读取。
- 每张表包含 `schema_version` 列。
- 每张表的列集合覆盖 Task 01 行 schema 的导出字段。
- append 两批数据后行数等于两批总和。
- nullable numeric 字段在 Parquet 中保持 null，不落为空字符串。
- NaN/Inf 输入转换为 null，并记录 warning。
- schema extra 字段导致写入失败。
- 写入失败抛出 `DataExportError`，不产生被读取为完整权威表的半截正式文件。
- writer `close_all()` 可重复调用，不重复写入数据。

## 测试要点（正常 + 边界 + 异常）

- 正常：每张表写 2 批、每批 2 行，读回验证行数和关键字段。
- 正常：`PairRiskRow` 只有在线风险字段，future/offline 字段为 null。
- 正常：`PairRiskRow` 带 K 生成的 5/10/15 秒字段。
- 边界：空 rows 调用不创建空权威文件，或创建带 schema 的空表；实现阶段需选择一种并写入测试。
- 边界：`scenario_id=None` 读回为 null。
- 异常：extra 字段失败。
- 异常：输出目录不存在时失败，或由 Task 02 创建后成功。
- 异常：mock `ParquetWriter.write_table()` 抛错，正式文件不存在或保持原有完整版本。

## 依赖关系

Task 03 依赖 Task 01 和 Task 02。Task 07 依赖 Task 03。Task 06 可读取 Task 03 输出计算 summary。
