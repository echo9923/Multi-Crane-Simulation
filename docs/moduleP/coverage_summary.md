# Module P 覆盖总结

## 验证时间

- 日期：2026-06-14
- 环境：本仓库 `.venv`，Python 3.13.13
- PyTorch 状态：当前 `.venv` 未安装 `torch`，因此 PyTorch Dataset 的实际 tensor/DataLoader 行为测试使用 `pytest.importorskip("torch")` 跳过；核心转换模块和 `torch_dataset` 的无 torch 导入/错误提示路径已覆盖。

## 本次验证命令

Module P 聚焦验收：

```bash
.venv/bin/python -m pytest \
  backend/app/tests/test_stgnn_schema.py \
  backend/app/tests/test_stgnn_window_reader.py \
  backend/app/tests/test_stgnn_episode_source.py \
  backend/app/tests/test_stgnn_variable_nodes.py \
  backend/app/tests/test_stgnn_leakage.py \
  backend/app/tests/test_stgnn_node_features.py \
  backend/app/tests/test_stgnn_edge_features.py \
  backend/app/tests/test_stgnn_labels.py \
  backend/app/tests/test_stgnn_metadata.py \
  backend/app/tests/test_stgnn_converter_cli.py \
  backend/app/tests/test_stgnn_torch_dataset.py \
  -q
```

结果：

```text
71 passed, 2 skipped in 0.40s
```

全 backend 回归：

```bash
.venv/bin/python -m pytest backend/app/tests -q
```

结果：

```text
1014 passed, 2 skipped, 1 warning in 6.87s
```

warning 来自 FastAPI/Starlette TestClient 对 `httpx` 的外部弃用提示，不是 Module P 失败。

## 覆盖范围

- `test_stgnn_schema.py`：覆盖 training schema、conversion error、feature spec、metadata required fields、shape validation、NaN/Inf、secret redaction 和 `numpy` tensor schema。
- `test_stgnn_window_reader.py`：覆盖 O dataset manifest、summary、split manifest、`windows.parquet` 读取，split 泄漏、dataset_id mismatch、missing windows 和 secret-like manifest。
- `test_stgnn_episode_source.py`：覆盖 episode Parquet/JSON source 读取、必需字段、时间轴、frame/crane 完整性、episode_id mismatch、risk horizon label 缺失、单塔吊无 pair risk 和 graph edge fallback 边界。
- `test_stgnn_variable_nodes.py`：覆盖 `pad_and_mask` 策略、全局 `max_nodes`、稳定 crane order、node/edge mask、单塔吊 edge mask 和 configured max_nodes 过小错误。
- `test_stgnn_leakage.py`：覆盖 forbidden future/offline input feature、input/prediction frame 范围、risk anchor frame、sample metadata 与 O window row 一致性。
- `test_stgnn_node_features.py`：覆盖 `X_node` shape、padding mask、bool/numeric/discrete/wind 编码、nullable 默认值、future-frame sentinel、缺字段和 future label feature 拒绝。
- `test_stgnn_edge_features.py`：覆盖 `X_edge`、`A_phy`、`edge_mask` shape，graph_edges 有向特征，pair_risks 当前字段镜像，邻接权重优先级，graph fallback，单塔吊边界和 future label feature 拒绝。
- `test_stgnn_labels.py`：覆盖 `Y_traj`、`Y_risk`、`risk_mask` shape，预测窗口切片，anchor frame 离线风险标签，horizon 顺序，risk level 编码，collision label 校验，单塔吊/缺 pair mask，以及禁止 `risk_level_now` 充当未来 label。
- `test_stgnn_metadata.py`：覆盖 sample metadata traceability、稳定 sample_id、sample index dimensions、summary split counts/skips/risk distribution 和 secret cleaning。
- `test_stgnn_converter_cli.py`：覆盖 tiny dataset 的 manifest -> windows -> source Parquet -> builders -> sample index/manifest/summary/report 链路，split filter、dry-run、strict failure、lenient skip、write failure atomicity 和 CLI help/exit code。
- `test_stgnn_torch_dataset.py`：覆盖 core converter 无 torch import、torch adapter 无 torch 清晰错误；实际 Dataset/collate/DataLoader 行为在安装 torch 的环境中会执行。

## 已知限制

- 当前第一版 converter 是 index-only 路径，不写 `.npz` tensor cache；它仍会构造并校验 `X_node`、`X_edge`、`A_phy`、`Y_traj`、`Y_risk`，确保样本可构造后再写 sample index。
- 当前 `StgnnTorchDataset(Path(...))` 明确报未实现，因为 index-only 输出还没有 tensor cache 文件；内存 `StgnnTensorSample` 路径和无 torch 错误路径已覆盖。
- 大规模 100 episode 实验不作为单元测试运行，符合 `docs/moduleP/task12_tests_and_acceptance.md` 的 non-goal。
- 没有训练模型，也没有引入外部 LLM/provider 服务。

## 结论

Module P 阶段三和阶段四的本地验收已经覆盖目标文档要求的核心路径：

- 只消费 Module O split/window，不重新划分。
- 每个样本来自单 episode 连续窗口。
- 输入 feature 不读取未来标签或预测窗口之后的数据。
- `Y_traj` 来自权威 trajectory，`Y_risk` 来自 `pair_risks.parquet` 离线标签列。
- 可变塔吊数量采用 `pad_and_mask` 策略并有 mask 测试。
- metadata、summary 和 error payload 做 secret 清洗。
- CLI 和 converter 支持 strict、lenient、dry-run、split filter 和写入失败错误路径。
