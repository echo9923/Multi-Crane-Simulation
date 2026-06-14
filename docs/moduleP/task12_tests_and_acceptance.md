# Task 12：测试、集成验收与覆盖总结

## 任务目标

补齐 Module P 的单元、集成和端到端验收测试，覆盖 dataset manifest -> windows -> source Parquet -> tensor sample -> PyTorch Dataset batch 的完整链路，以及 schema、泄漏、可变塔吊和 secret 清洗错误路径。

## 范围：做什么 / 不做什么

做：

- 新增 `backend/app/tests/test_stgnn_schema.py`。
- 新增 `backend/app/tests/test_stgnn_window_reader.py`。
- 新增 `backend/app/tests/test_stgnn_episode_source.py`。
- 新增 `backend/app/tests/test_stgnn_features_labels.py`。
- 新增 `backend/app/tests/test_stgnn_converter_cli.py`。
- 新增 `backend/app/tests/test_stgnn_torch_dataset.py`。
- 新增 `docs/moduleP/coverage_summary.md`。
- 构造 tiny PyArrow fixture，不依赖真实长仿真。
- 覆盖正常链路、边界和异常路径。

不做：

- 不跑大规模 100 episode 实验作为单元测试。
- 不训练真实模型。
- 不引入外部服务或 LLM provider。
- 不用前端 display-only 文件作为训练真值。

## 接口与数据结构（签名级别）

建议 fixture：

```python
def write_tiny_module_o_dataset(
    tmp_path: Path,
    *,
    dataset_id: str = "ds_tiny",
    episodes: Sequence[TinyEpisodeSpec],
) -> Path: ...

def write_tiny_episode_parquet(
    root: Path,
    *,
    episode_id: str,
    split: str,
    num_cranes: int,
    frame_count: int,
    include_graph_edges: bool = True,
    include_risk_labels: bool = True,
    inject_secret: bool = False,
) -> dict[str, Path]: ...
```

整体 E2E 验收命令：

```bash
pytest \
  backend/app/tests/test_stgnn_schema.py \
  backend/app/tests/test_stgnn_window_reader.py \
  backend/app/tests/test_stgnn_episode_source.py \
  backend/app/tests/test_stgnn_features_labels.py \
  backend/app/tests/test_stgnn_converter_cli.py \
  backend/app/tests/test_stgnn_torch_dataset.py
```

## 前置依赖

- Task 01-11。
- pytest、PyArrow、NumPy。
- PyTorch tests 可用 `pytest.importorskip("torch")`，但 core tests 不能依赖 torch。

## 验收标准（具体、可测试）

- schema tests 覆盖 extra、NaN/Inf、secret、metadata required fields。
- window reader tests 覆盖 split leakage、dataset_id mismatch、missing windows。
- episode source tests 覆盖缺字段、时间轴不连续、episode_id mismatch、label 缺失。
- features/labels tests 覆盖 `X_node`、`X_edge`、`A_phy`、`Y_traj`、`Y_risk` shape 和 no leakage。
- variable crane tests 覆盖 1 台、2 台、4 台混合 padding 和 mask。
- converter CLI tests 覆盖 strict、lenient、dry-run、split filter、write failure。
- torch dataset tests 覆盖 dataset、collate、DataLoader batch，且 core import 在无 torch 时不失败。
- secret 清洗 tests 覆盖 metadata、summary、warning、error details。
- 生成 `docs/moduleP/coverage_summary.md`，列出测试命令、覆盖范围、已知限制。

## 测试要点（正常 + 边界 + 异常）

正常：

- 完整链路：O manifest/windows -> L/K Parquet -> one sample -> torch batch。
- 多 split 转换。
- graph_edges 存在时使用物理先验。

边界：

- 单塔吊无 risk pair。
- 某 split 0 samples。
- graph_edges 缺失但 fallback 允许。
- `ttc_s=None`。

异常：

- split 泄漏。
- 时间泄漏字段进入 feature spec。
- prediction frame 缺失。
- risk label horizon 缺失。
- `num_cranes` 超过 max_nodes。
- secret-like payload 出现在 summary。

## 依赖关系

依赖 Task 01-11。本任务用于阶段四整体验收，在逐任务实现期间也提供每个任务对应的测试文件。
