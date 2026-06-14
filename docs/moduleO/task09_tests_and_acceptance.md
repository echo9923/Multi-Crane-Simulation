# Task 09：Tests and Acceptance

## 任务目标

补齐 Module O 的单元、CLI、API 和端到端集成测试，验证 dataset builder 从 episode run 目录到质量门禁、split、window index、summary、CLI 和 M dataset 查询的完整链路。

## 范围：做什么 / 不做什么

做：

- 新增 `backend/app/tests/test_dataset_schema.py`。
- 新增 `backend/app/tests/test_dataset_catalog.py`。
- 新增 `backend/app/tests/test_dataset_quality.py`。
- 新增 `backend/app/tests/test_dataset_splits.py`。
- 新增 `backend/app/tests/test_dataset_window_index.py`。
- 新增 `backend/app/tests/test_dataset_builder.py`。
- 新增 `backend/app/tests/test_moduleO_cli_api.py`。
- 新增 `backend/app/tests/test_moduleO_acceptance.py`。
- 覆盖 Task 01-08 的正常、边界、异常路径。
- 阶段四补 `run_dir -> dataset summary -> split/window export -> M dataset API` 集成测试。
- 输出 `docs/moduleO/coverage_summary.md`。

不做：

- 不跑真实外部 LLM provider。
- 不要求真实 100 episode 长仿真作为单元测试；使用 fake runner 和 tiny fixture。
- 不训练 STGNN 模型；只验证 P 能读取 window index 和 source paths。
- 不启动前端。

## 接口与数据结构（签名级别）

建议测试命令：

```bash
pytest backend/app/tests/test_dataset_schema.py -v
pytest backend/app/tests/test_dataset_catalog.py -v
pytest backend/app/tests/test_dataset_quality.py -v
pytest backend/app/tests/test_dataset_splits.py -v
pytest backend/app/tests/test_dataset_window_index.py -v
pytest backend/app/tests/test_dataset_builder.py -v
pytest backend/app/tests/test_moduleO_cli_api.py -v
pytest backend/app/tests/test_moduleO_acceptance.py -v
```

完整 Module O 验收：

```bash
pytest backend/app/tests/test_dataset_schema.py \
       backend/app/tests/test_dataset_catalog.py \
       backend/app/tests/test_dataset_quality.py \
       backend/app/tests/test_dataset_splits.py \
       backend/app/tests/test_dataset_window_index.py \
       backend/app/tests/test_dataset_builder.py \
       backend/app/tests/test_moduleO_cli_api.py \
       backend/app/tests/test_moduleO_acceptance.py -v
```

相邻模块回归：

```bash
pytest backend/app/tests/test_moduleA_acceptance.py \
       backend/app/tests/test_moduleK_acceptance.py \
       backend/app/tests/test_moduleL_acceptance.py \
       backend/app/tests/test_moduleM_dataset_api.py \
       backend/app/tests/test_moduleM_acceptance.py -v
```

## 验收标准（具体、可测试）

Schema：

- O schema 拒绝 extra、NaN、Inf。
- O summary/manifest/window index JSON 或 Parquet 可 round-trip。
- secret-like 字段静态扫描通过。

Catalog：

- 空 root、合法 run、缺失文件、坏 JSON、dataset summary 读取均覆盖。

Quality：

- schema_valid、time_monotonic、frame_completeness、no_nan_inf、mechanical_limits_respected、geometry_consistency、online_offline_separation、replay_ready、event_consistency 均至少有一个测试。
- failed episode 进入 quarantine。

Split：

- train/val/test 无 episode 泄漏。
- holdout unseen_layout、unseen_num_cranes、test_high_risk 覆盖。
- 所有 failed quality episode 不进入正式 split。

Window index：

- 窗口数量正确。
- 窗口不跨 episode、不跨 split。
- negative/positive sampling 生效。
- P smoke 可以读取 `windows.parquet` 中的 source paths 和 frame ranges。

Builder：

- tiny dataset 构建成功。
- summary 报告 split_counts、window_counts、risk_distribution、target_gaps、quarantine。
- manifest 保存 config、schema version、git commit 或 warning。
- 写入失败不返回成功 result。

CLI/API：

- `scripts/batch_generate.py --help`、`scripts/build_dataset.py --help` 通过。
- `scripts/build_dataset.py --output-json` 输出可解析 JSON。
- M `/datasets` 和 `/datasets/{dataset_id}/summary` 能读取 O 输出。

阶段四端到端：

- 使用 fake runner 或短 episode fixture 完成 `batch_generate -> build_dataset -> dataset_summary -> M dataset API`。
- 覆盖错误路径：invalid config、source missing、quality failed、split leakage、summary missing。

## 测试要点（正常 + 边界 + 异常）

正常：

- 3 个 episode，2 个 split，一个 high risk 窗口。
- 1 个 failed episode 进入 quarantine。
- `index_only` 构建模式。

边界：

- 单塔吊 episode。
- episode 太短没有窗口。
- 所有 risk 都是 safe。
- 无 git commit 环境。

异常：

- Parquet 损坏。
- JSONL 坏行。
- observation 泄漏 offline label。
- split 手工重复 episode。
- output root 写失败。

## 覆盖总结要求

阶段四完成后新增：

```text
docs/moduleO/coverage_summary.md
```

内容模板：

```text
已覆盖：
- schema / catalog / quality / split / window index / builder / CLI / API。
- quarantine 和 warning。
- 无 episode/window 泄漏。
- dataset_summary target actual gap。
- M dataset API 读取 O 输出。

未覆盖及原因：
- 真实 100 episode 长仿真：本地验收可使用 fake runner，长跑放到实验脚本或 CI 慢任务。
- PyTorch Dataset：归 Module P。
- 真实外部 LLM provider：归 Module G 和实验环境。
```

## 依赖关系

依赖 Task 01-08。它是 Module O 阶段三完成后的总验收任务，也是阶段四整体测试和覆盖总结的来源。
