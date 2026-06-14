# Module P 阶段二自审

## 审查范围

本次自审覆盖以下阶段一产物：

- `docs/moduleP/overview.md`
- `docs/moduleP/task01_training_schema.md`
- `docs/moduleP/task02_dataset_window_reader.md`
- `docs/moduleP/task03_episode_source_loader.md`
- `docs/moduleP/task04_node_feature_builder.md`
- `docs/moduleP/task05_edge_feature_and_adjacency.md`
- `docs/moduleP/task06_label_builder.md`
- `docs/moduleP/task07_time_and_split_leakage_guards.md`
- `docs/moduleP/task08_variable_crane_strategy.md`
- `docs/moduleP/task09_metadata_summary_secret_cleaning.md`
- `docs/moduleP/task10_sample_converter_and_cli.md`
- `docs/moduleP/task11_torch_dataset_dataloader.md`
- `docs/moduleP/task12_tests_and_acceptance.md`

本阶段只产出文档。没有新增或修改 `backend/app/`、`scripts/` 的实现代码、测试代码或运行时配置。

## 任务重叠检查

结论：任务之间有衔接，但职责边界清楚，没有重复实现同一能力。

- Task 01 只定义 P 的 schema、错误码、feature spec 和 secret 清洗合同。
- Task 02 只读取和校验 O 的 manifest/split/windows，不读取 episode 源表。
- Task 03 只读取 episode 权威文件并做字段/时间轴校验，不构造 tensor。
- Task 04 只构造节点特征和 node mask。
- Task 05 只构造边特征、物理先验邻接和 edge mask。
- Task 06 只构造轨迹标签和风险标签。
- Task 07 只提供泄漏 guard，作为各 builder 的共享防线。
- Task 08 只处理可变塔吊数量、crane order、padding 和 mask。
- Task 09 只负责 sample metadata、index、summary、manifest 和 secret 清洗。
- Task 10 只串联转换流程和 CLI，不训练模型、不导入 torch。
- Task 11 只做 PyTorch Dataset/DataLoader 适配。
- Task 12 只定义跨任务测试和覆盖总结。

## 任务遗漏检查

结论：`目标.md` 要求的 Module P 核心能力已覆盖。

- Module P schema 与 conversion error 定义：Task 01。
- Module O dataset manifest / windows 索引读取与校验：Task 02。
- episode 源 Parquet 读取、字段校验与时间轴对齐：Task 03。
- 节点特征 `X_node` 构造：Task 04。
- 边特征 `X_edge` 与物理先验邻接 `A_phy` 构造：Task 05。
- 轨迹标签 `Y_traj` 与风险标签 `Y_risk` 构造：Task 06。
- 可变塔吊数量处理、mask/padding 策略：Task 08。
- 样本 metadata、统计 summary 与 secret 清洗：Task 09。
- PyTorch Dataset / DataLoader 适配层：Task 11。
- CLI 转换脚本与验收测试：Task 10 和 Task 12。
- 无时间泄漏、无 split 泄漏：overview、Task 02、Task 07，以及 Task 04-06 的禁止字段/范围规则。
- 不重算、不篡改、不伪造训练真值：overview、Task 03、Task 06、Task 10。
- 核心转换逻辑与 PyTorch 解耦：overview、Task 10、Task 11。

## 依赖顺序检查

结论：依赖顺序合理且无环。

```text
Task 01 training schema
  -> Task 02 dataset window reader
  -> Task 03 episode source loader
  -> Task 08 variable crane strategy
  -> Task 04 node feature builder
  -> Task 05 edge feature and adjacency
  -> Task 06 label builder
  -> Task 09 metadata summary secret cleaning
  -> Task 10 sample converter and CLI
  -> Task 11 torch dataset dataloader
  -> Task 12 tests and acceptance

Task 01 training schema
  -> Task 07 leakage guards
  -> Task 04/05/06/10/11
```

说明：

- Task 07 可以在 Task 03 后与 Task 08 并行实现，但所有 feature/label/converter 任务都应调用它。
- Task 04、05、06 都依赖 Task 08 的 crane order 和 max_nodes；三者之间没有直接依赖，可以独立测试。
- Task 09 依赖 Task 08 的 max_nodes 统计和 Task 01 的 metadata schema，但不依赖 tensor builder 内部实现。
- Task 10 是 orchestrator，必须在 01-09 后实现。
- Task 11 是 PyTorch 适配层，依赖 converter 输出合同，但不反向影响核心转换。
- Task 12 作为阶段四验收，也为每个阶段三任务提供对应测试文件。

## 验收标准可测性检查

结论：每个验收标准都可以通过 pytest、tmp_path、PyArrow、NumPy、CLI main/subprocess 和可选 PyTorch 测试验证。

- schema 验收可用 Pydantic `model_validate()`、extra 字段、NaN/Inf、secret scanner 验证。
- window reader 验收可用 tmp_path 构造 O manifest/split/windows parquet。
- episode source 验收可用 tiny Parquet fixture 覆盖字段缺失、时间轴错误和 label 缺失。
- feature/label 验收可通过手算 tiny tensor shape 和 sentinel future frame 验证。
- 可变塔吊验收可用 1/2/4 台塔吊 mixed fixture 验证 padding 和 mask。
- leakage guard 验收可直接传 forbidden feature names 和非法 frame ranges。
- converter/CLI 验收可调用 `main()` 或 subprocess 覆盖 strict、lenient、dry-run、split filter。
- PyTorch 验收可用 `pytest.importorskip("torch")`，同时测试 core import 不依赖 torch。
- secret 防泄漏可静态扫描 manifest、summary、metadata、warning 和 error details。

## 与阶段一背景一致性检查

结论：文档与 `目标.md`、Module O/L/K/A 当前边界一致。

- O 拥有 split/window，P 只读取 `windows.parquet` 和 split manifest，不重新随机划分。
- L 的 `trajectories.parquet` 是轨迹真值，P 只读取并切片。
- K 写入 `pair_risks.parquet` 的离线风险列是风险标签真值，P 不重算 label。
- A 的 `DatasetConfig.windows` 提供窗口长度、预测长度、stride 和 risk horizons。
- 可变塔吊数量第一版采用 mask/padding 策略，并在 Task 08、summary 和 sample metadata 中明确记录。
- 所有 tensor、metadata 和 summary 都能追溯到 dataset_id、split、episode_id、start_frame、source paths 和 feature spec hash。
- 完整 secret 不进入样本、metadata、summary、日志或错误 payload。

## 调整记录

- 将目标文档要求的 10 类能力拆成 12 个任务，把泄漏 guard 和测试验收拆为独立任务，便于复用和逐任务提交。
- 将 PyTorch 适配拆到最后，确保核心转换逻辑只依赖 Pydantic、PyArrow 和 NumPy。
- 将 graph edge 缺失设计为显式 fallback 策略，避免静默生成错误 edge tensor。
- 将风险标签 anchor 固定为 `start_frame + input_steps - 1`，避免构造标签时扫描预测窗口之后的轨迹。
- 将第一版可变节点策略固定为 `pad_and_mask`，不引入会影响 split 的 bucketing。
- 将 secret 清洗提升为独立任务，覆盖 metadata、summary、warning、error details 和 CLI 输出。

## 阶段闸口

阶段一和阶段二的规划文档已经写完。根据 `目标.md` 的硬性要求，现在应停下等待确认；收到确认后再进入阶段三逐任务实现、测试和提交。
