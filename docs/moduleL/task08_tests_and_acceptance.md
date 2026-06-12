# Task 08：Tests and Acceptance

## 任务目标

定义 Module L 的测试清单与验收标准，覆盖 schema、目录、Parquet/JSONL、SimFrame、EpisodeSummary、Recorder orchestrator、offline label 隔离、写入失败和端到端链路。

## 范围：做什么 / 不做什么

做：

- 新增 `backend/app/tests/test_recorder.py`。
- 新增 `backend/app/tests/test_moduleL_acceptance.py`。
- 为 Task 01-07 写单元测试和验收测试。
- 跑 `目标.md` 指定的 Module L 测试命令。
- 跑邻近模块回归测试。
- 在阶段四补充跨任务集成/端到端测试。
- 输出覆盖总结。

不做：

- 不依赖真实 LLM provider 网络。
- 不依赖真实前端浏览器渲染。
- 不生成视频或截图。
- 不要求真实磁盘满，只用 monkeypatch/mock 模拟写入失败；权限不足可用临时目录权限或 mock。

## 接口与数据结构（签名级别）

测试文件：

```text
backend/app/tests/test_recorder.py
backend/app/tests/test_moduleL_acceptance.py
```

`test_recorder.py` 建议分组：

```python
class TestRecorderSchemas: ...
class TestRunDirectorySetup: ...
class TestParquetWriters: ...
class TestJsonlWriters: ...
class TestSimFrameBuilder: ...
class TestEpisodeSummaryBuilder: ...
class TestRecorderOrchestrator: ...
```

`test_moduleL_acceptance.py` 建议分组：

```python
def test_complete_episode_exports_required_files(tmp_path): ...
def test_episode_runner_records_initial_and_step_frames_with_real_recorder(tmp_path): ...
def test_offline_labels_never_enter_realtime_frame(tmp_path): ...
def test_write_failure_raises_data_export_error_without_authoritative_partial(tmp_path): ...
def test_nan_and_inf_are_exported_as_null_and_flagged_in_summary(tmp_path): ...
```

## 前置依赖

- Task 01-07 实现。
- pytest。
- PyArrow。
- 当前 A-K 模块已有测试 fixtures，可复用 crane/weather/task/command 构造 helper。

## 验收标准（具体、可测试）

Schema：

- 新增 recorder schema 均拒绝 extra 字段。
- 新增 recorder schema 均拒绝 NaN/Inf。
- 所有 JSONL/Parquet 行 schema 都包含 `schema_version`。
- 实时 `SimFrame` 拒绝 `offline_labels`。

目录：

- `Recorder.from_config()` 或 `init_run_directory()` 创建 L.1 目录。
- `resolved_config.yaml` 和 `episode_metadata.json` 可读。
- metadata 不写完整 secret。

Parquet：

- `trajectories.parquet`、`pair_risks.parquet`、`graph_edges.parquet`、`tasks.parquet`、`weather.parquet` 可被 PyArrow 读取。
- 所有 Parquet 含 `schema_version` 列。
- append 后行数正确。
- nullable numeric 为 null。

JSONL：

- `llm_observations.jsonl`、`llm_decisions.jsonl`、`commands.jsonl`、`interventions.jsonl`、`events.jsonl` 每行可 `json.loads()`。
- 每行含 `schema_version`。
- command log 同时保存 parsed 和 executed。
- events 支持 25+ event types。

SimFrame：

- `visual/frames.jsonl` 每行可被 `SimFrame.model_validate()`。
- `visual/episode_manifest.json` 覆盖 L.4.1 最低字段。
- 离线 frame 可携带 offline labels；实时 frame 不可携带。

EpisodeSummary：

- task/risk/event/LLM/data quality 指标计算正确。
- `metadata/episode_summary.json` 可被 `EpisodeSummary.model_validate()`。
- `has_nan`、`has_inf`、`max_state_jump` 被覆盖。

Recorder orchestrator：

- initial frame 在 `time_s=0` 记录。
- step frame 在 physics 后状态记录。
- `record_step()` 兼容当前 `EpisodeRunner` 参数。
- 输入对象不被 recorder 修改。
- 写入失败抛出 `DataExportError`。

端到端：

- 完整 episode 通过 J fake dependencies -> L 逐帧记录 -> finalize -> 回读必需文件。
- 至少覆盖单塔吊、双塔吊、有 command、有 event、有 weather、有 task 的链路。

## 测试命令

recorder 单元测试：

```bash
pytest backend/app/tests/test_recorder.py -v
```

模块 L 完整验收：

```bash
pytest backend/app/tests/test_recorder.py \
       backend/app/tests/test_moduleL_acceptance.py -v
```

回归邻近模块：

```bash
pytest backend/app/tests/test_physics.py \
       backend/app/tests/test_collision.py \
       backend/app/tests/test_risk_online.py \
       backend/app/tests/test_observation.py \
       backend/app/tests/test_command_schema.py \
       backend/app/tests/test_moduleJ_acceptance.py -v
```

阶段四建议补跑更宽回归：

```bash
pytest backend/app/tests/test_moduleF_acceptance.py \
       backend/app/tests/test_moduleG_acceptance.py \
       backend/app/tests/test_moduleH_acceptance.py \
       backend/app/tests/test_moduleI_acceptance.py \
       backend/app/tests/test_moduleK_acceptance.py \
       backend/app/tests/test_moduleJ_acceptance.py -v
```

当前仓库已有 `backend/app/tests/test_risk_online.py`、`test_collision.py`、`test_observation.py`、`test_command_schema.py`、`test_moduleJ_acceptance.py`。如果实现阶段发现目标命令中某个文件改名，应使用仓库中已存在的等价测试并在覆盖总结中说明映射。

## 测试要点（正常 + 边界 + 异常）

正常：

- 双塔吊完整 episode，含 initial + 多个 step + finalize。
- 多次 append Parquet/JSONL。
- K 的 offline labels episode 后写入 pair risks。
- J 的 `EpisodeRunner` 与真实 recorder 集成。

边界：

- 单塔吊无 pair。
- 空 tasks。
- 空 events。
- 无 LLM calls。
- `scenario_id=None`。
- 最后一帧 episode status 为 terminal。

异常：

- NaN/Inf 被转 null 并进入 summary warning。
- Parquet writer 失败。
- JSONL writer 失败。
- schema mismatch。
- 实时 SimFrame offline label 泄漏。
- run root 不可写。

防越界：

- recorder 不导入 LLM provider HTTP client。
- recorder 不调用 safety/risk 计算函数生成风险。
- recorder 不调用 physics step。
- recorder 不修改传入 Pydantic 对象。

## 覆盖总结要求

阶段四完成后输出简短覆盖总结：

```text
已覆盖：
- schema / directory / parquet / jsonl / frame / manifest / summary。
- initial frame、step frame、finalize。
- offline label 隔离。
- J -> L fake episode 链路。
- NaN/Inf、写入失败、schema mismatch。

未覆盖及原因：
- 真实磁盘满：本地测试用 writer mock 替代。
- 真实前端渲染：归 N/M 集成测试。
- 真实 LLM 网络调用：归 G，L 只记录结构化对象。
```

## 依赖关系

Task 08 依赖 Task 01-07。它不新增生产能力，只定义和实现验收测试。
