# Module O 阶段二自审

## 审查范围

本次自审覆盖以下阶段一产物：

- `docs/moduleO/overview.md`
- `docs/moduleO/task01_dataset_schema.md`
- `docs/moduleO/task02_source_catalog.md`
- `docs/moduleO/task03_batch_generation.md`
- `docs/moduleO/task04_quality_gate.md`
- `docs/moduleO/task05_split_planner.md`
- `docs/moduleO/task06_window_index.md`
- `docs/moduleO/task07_dataset_assembly_summary.md`
- `docs/moduleO/task08_cli_and_api_integration.md`
- `docs/moduleO/task09_tests_and_acceptance.md`

本阶段只产出文档，并补全 `目标.md` 中 Module O 的背景占位内容。没有写 `backend/app/`、`scripts/` 实现代码、测试代码或运行时配置。

## 任务重叠检查

结论：任务之间有衔接，但职责边界清楚，没有重复实现同一能力。

- Task 01 只定义 O 的 schema、错误码、warning 和 secret 静态检查合同。
- Task 02 只发现和读取已有 episode/dataset 元数据，不判断质量、不生成 split。
- Task 03 只批量调用已有 runner factory 生成 episode，不构建正式 dataset。
- Task 04 只做 episode 质量门禁和 quarantine 判断，不决定 split。
- Task 05 只做 split 分配和泄漏检查，不生成 window。
- Task 06 只生成通用 window index，不生成 STGNN tensor 或 PyTorch Dataset。
- Task 07 只组装 dataset 目录并写 manifest/summary/index，不重新生成 episode。
- Task 08 只补 CLI 和 M 只读 dataset API 对接，不在 API route 中执行构建。
- Task 09 只定义测试、验收和覆盖总结，不新增生产能力。

## 任务遗漏检查

结论：`目标.md` 和总方案中 Module O 的核心能力已覆盖。

- Module O 职责、输入/输出、对外接口、对内依赖和 non-goals：overview。
- 数据集 schema、manifest、summary、quality report、window index：Task 01。
- 多 run/episode source 发现和 dataset summary 查询能力：Task 02。
- 批量生成 episode：Task 03。
- 每个 episode 的质量门禁和 quarantine：Task 04。
- train/val/test/test_seen_layout/test_unseen_layout/test_unseen_num_cranes/test_high_risk split：Task 05。
- 窗口长度、预测长度、滑动步长由 `dataset.yaml` 控制：Task 06。
- 不按 window 随机划分、无时间泄漏：Task 05 和 Task 06。
- dataset_summary 报告风险样本比例、任务完成率、碰撞/near miss、target actual gap 和 quarantine 数量：Task 07。
- CLI `batch_generate` 和 `build_dataset`：Task 03 和 Task 08。
- M `/datasets` 和 `/datasets/{dataset_id}/summary` 读取 O 输出：Task 08。
- 阶段四跨任务测试和覆盖总结：Task 09。
- 不生成训练真值、不修改原始 episode、不训练模型、不实现 P：overview 和各任务 non-goals。

## 依赖顺序检查

结论：依赖顺序合理且无环。

```text
Task 01 dataset schema
  -> Task 02 source catalog
  -> Task 04 quality gate
  -> Task 05 split planner
  -> Task 06 window index
  -> Task 07 dataset assembly and summary
  -> Task 08 CLI/API integration
  -> Task 09 tests and acceptance

Task 01 dataset schema
  -> Task 03 batch generation
  -> Task 08 CLI/API integration
  -> Task 09 tests and acceptance
```

说明：

- Task 03 可以与 Task 02/04/05/06 大体并行，因为质量、split 和 window index 可先用 fixture run 目录开发。
- Task 07 汇总前置产物，因此依赖 Task 02、04、05、06。
- Task 08 需要 Task 03 的 batch CLI 和 Task 07 的 build CLI。
- Task 09 依赖所有前置任务。

## 验收标准可测性检查

结论：每个验收标准都可以通过 pytest、tmp_path、PyArrow、FastAPI TestClient、subprocess/main 函数、fake runner 或静态扫描验证。

- schema 验收可通过 Pydantic `model_validate()`、extra 字段、NaN/Inf 和 JSON dump 验证。
- catalog 验收可用 tmp_path 构造 Module L run 目录和 dataset summary。
- batch generation 验收可注入 fake runner，不依赖真实外部 LLM 或长仿真。
- quality gate 验收可用 tiny Parquet/JSONL fixture 覆盖缺失文件、坏行、NaN/Inf、frame 不完整和 offline label 泄漏。
- split 验收可用内存 episode records 覆盖 ratio、holdout 和手工泄漏。
- window index 验收可用 frame_count 和 pair_risks fixture 手算窗口数量。
- builder 验收可用 index_only 模式构建 tiny dataset，回读 summary/manifest/index。
- CLI 验收可调用 `main_*` 函数或 subprocess `--help`。
- M API 验收可把 `app.state.dataset_root` 指向 O 输出目录后用 TestClient 查询。
- secret 防泄漏可静态扫描 manifest、summary、index、CLI JSON 和 API payload。

## 与阶段一背景一致性检查

结论：文档与 `目标.md`、总方案 `0.8.9`、`0.8.10`、`模块 O`、`15.7 M5` 以及当前 A/K/L/M 实现边界一致。

- 当前 A 已有 `DatasetConfig`，O 不重新定义配置来源。
- 当前 L 已预留 `metadata/dataset_summary.json`，并明确全局 dataset summary 由 O 写入。
- 当前 K 负责离线标签，O 只读取已写入标签列做统计和窗口索引。
- 当前 M 已有 `/datasets` filesystem fallback，O 只需要生成标准 dataset 目录与 summary 即可被查询。
- 当前 `scripts/batch_generate.py` 明确返回 not implemented，Task 03 将其作为 O 的实现入口。
- Module P 仍拥有 STGNN tensor/PyTorch Dataset 转换，O 只生成通用 `windows.parquet`。
- N 的 display-only 数据不得进入 O 输出，overview 与 Task 04/09 均列为防泄漏要求。

## 调整记录

- 将 O 拆为 9 个任务，而不是把 batch、quality、split、window、summary 和 CLI 合成一个大任务，便于逐任务提交和测试。
- 将 window 设计为通用索引，不在 O 中生成模型 tensor，避免和 Module P 重叠。
- 将 M API 对接限定为只读 summary/catalog，不允许 HTTP 请求触发 dataset build。
- 将 100 episode 验收放入可配置慢任务或实验验收，单元测试用 fake runner 和 tiny fixture，避免本地测试过慢。
- 将 quarantine 设为默认排除正式 split，summary 必须报告数量和原因。
- 将 dataset_targets 定义为统计目标，不允许通过关闭机械限制、穿模或伪造标签满足比例。

## 阶段闸口

阶段一和阶段二的规划文档已经写完。根据 `目标.md` 的硬性要求，现在应停下等待确认；收到确认后再进入阶段三逐任务实现、测试和提交。
