# Module L 阶段二自审

## 审查范围

本次自审覆盖以下阶段一产物：

- `docs/moduleL/overview.md`
- `docs/moduleL/task01_recorder_schema.md`
- `docs/moduleL/task02_run_directory_setup.md`
- `docs/moduleL/task03_parquet_writers.md`
- `docs/moduleL/task04_jsonl_writers.md`
- `docs/moduleL/task05_sim_frame_builder.md`
- `docs/moduleL/task06_episode_summary_builder.md`
- `docs/moduleL/task07_recorder_orchestrator.md`
- `docs/moduleL/task08_tests_and_acceptance.md`

本阶段只产出文档，没有写 `backend/app/` 实现代码、测试代码或运行时配置。

## 任务重叠检查

结论：任务之间有必要衔接，但职责边界清楚，没有重复实现同一能力。

- Task 01 只定义 schema，不写文件、不构造业务行。
- Task 02 只初始化 run 目录和 metadata 骨架，不打开数据 writer。
- Task 03 只写 Parquet 主表，不写 JSONL、不构造 frame。
- Task 04 只写 JSONL 日志，不写 Parquet、不构造业务对象。
- Task 05 只构造 `SimFrame`、`frames.jsonl` 和 manifest，不计算训练 summary。
- Task 06 只聚合 `EpisodeSummary` 和 metadata 终态，不负责逐帧记录。
- Task 07 是唯一 orchestrator，把前置能力组装给 J 调用。
- Task 08 只定义测试和验收，不新增生产接口。

## 任务遗漏检查

结论：`目标.md` 列出的 Module L 能力已覆盖。

- `docs/moduleL/overview.md` 已重述职责、文件结构、schema、输入/输出、接口、依赖和非目标。
- `SimFrame`、`EpisodeSummary`、`TrajectoryRow`、`PairRiskRow`、`GraphEdgeRow`、`CommandLogEntry`、`EventLogEntry`、`TaskParquetRow`、`WeatherParquetRow`：Task 01。
- run 目录初始化、`resolved_config.yaml` 副本、`episode_metadata.json` 骨架：Task 02。
- trajectories、pair_risks、graph_edges、tasks、weather Parquet writers：Task 03。
- observations、commands、events、interventions、decisions JSONL writers：Task 04。
- `build_sim_frame()`、`visual/frames.jsonl`、`episode_manifest.json`、offline label 隔离：Task 05。
- `EpisodeSummary` 25+ 指标、`has_nan`、`has_inf`、`max_state_jump`：Task 06。
- `Recorder.from_config()`、`record_initial_frame()`、`record_step()`、`finalize()`：Task 07。
- schema/目录/读写/SimFrame/summary/失败/端到端验收：Task 08。
- `Recorder 只能观察和落盘`：overview、Task 07、Task 08 均列为硬性验收。
- JSONL 每行 schema version、Parquet schema_version 列：Task 01、03、04、08。
- NaN/Inf 转 null 并 warning：Task 01、03、04、06、08。
- 写入失败必须 data export error，不产出半截权威数据：overview、Task 02、03、04、07、08。

## 依赖顺序检查

结论：依赖顺序合理且无环。

```text
Task 01 recorder schema
  -> Task 02 run directory setup
  -> Task 03 parquet writers
  -> Task 04 jsonl writers
  -> Task 05 sim frame builder
  -> Task 06 episode summary builder
  -> Task 07 recorder orchestrator
  -> Task 08 tests and acceptance
```

说明：

- Task 03 和 Task 04 可在 Task 02 之后并行实现；二者之间没有直接依赖。
- Task 05 依赖 Task 01/02，并可复用 Task 04 的 JSONL 编码策略，但不依赖 Parquet writer。
- Task 06 依赖 Task 01/02，并消费 Task 03-05 的统计输入。
- Task 07 依赖 Task 01-06，是 Module L 集成点。
- Task 08 依赖所有前置任务。

## 验收标准可测性检查

结论：每个验收标准都可以通过 pytest、Pydantic schema 校验、PyArrow roundtrip、JSONL roundtrip、静态扫描或 fake J 集成验证。

- schema 验收可通过 `model_validate()`、`model_dump(mode="json")`、extra 字段和 NaN/Inf fixtures 验证。
- 目录验收可通过 `tmp_path` 检查目录、YAML/JSON 可读性和 secret key 扫描验证。
- Parquet 验收可通过 `pyarrow.parquet.read_table()` 验证列集合、行数、null 和 schema_version。
- JSONL 验收可逐行 `json.loads()` 并回填 Pydantic schema。
- `SimFrame` 验收可通过在线/离线两个构造路径验证 offline label 隔离。
- summary 验收可通过小型 deterministic fixture 手算任务完成率、risk ratio、LLM latency 和 data quality。
- recorder 只读验收可在调用前后比较传入对象的 `model_dump(mode="json")`。
- 写入失败可用 monkeypatch writer 抛错验证 `DataExportError` 和半截文件策略。
- J -> L 链路可复用 `test_moduleJ_acceptance.py` 的 fake dependencies，将 FakeRecorder 替换为真实 Recorder。

## 与阶段一背景一致性检查

结论：文档与 `目标.md`、总方案 L.1-L.9 和当前代码合同一致，并显式标注了实现阶段需要补齐的依赖。

- 当前 `EpisodeRunner` 已调用 `record_initial_frame()` 和 `record_step()`；Task 07 保持兼容，并把 `online_risk`、`observations`、`llm_calls` 设计为可选扩展。
- 当前 `crane_state_to_trajectory_row()` 已提供 trajectory 基础字段；Task 07 要求复用并补齐 episode/scenario/weather/command/task 字段。
- 当前 `pyproject.toml` 尚无 PyArrow；Task 03 明确把 `pyarrow` 加入阶段三实现范围。
- 当前 K 的 `OfflineRiskLabel` 只有显式 5s/10s 字段并通过 `future_window_labels` 支持 15s；Task 03/07 要求写入 15s Parquet 列时从 `future_window_labels["15s"]` 取得。
- L 不计算 K 的离线标签，只写入 K 的对象。
- L 不构造 F 的 observation，只记录 F 的对象。
- L 不纠正 G/H 的 command，只保存 raw/parsed/executed 对照。
- L 不推送 WebSocket，N/M 消费同一 `SimFrame` schema。

## 调整记录

- 保留 `目标.md` 建议的 8 个任务，没有合并为更粗粒度任务，便于逐任务提交和测试。
- 在 Task 03 中加入 PyArrow 依赖补齐，因为当前项目依赖只有 Pydantic、PyYAML 和 pytest。
- 将 `dataset_summary.json` 标注为 O 的聚合职责，L 单 episode finalize 只写 `episode_summary.json` 和 metadata；目录中保留 dataset summary 路径。
- 明确 `visual/frames.jsonl` 是展示权威，不能替代训练 Parquet。
- 明确实时 `SimFrame` 禁止 `offline_labels`，离线回放扩展才可携带。
- 明确 NaN/Inf 处理是 L 写出前 sanitize，而不是修改上游对象。
- 明确写入失败使用 `DataExportError(category="data_export_error")`。

## 阶段闸口

阶段一和阶段二的规划文档已经写完。根据 `目标.md` 的硬性要求，现在应停下等待确认；收到确认后再进入阶段三逐任务实现、测试和提交。
