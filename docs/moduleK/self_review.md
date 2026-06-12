# Module K 阶段二自审

## 审查范围

本次自审覆盖以下阶段一产物：

- `docs/moduleK/overview.md`
- `docs/moduleK/task01_offline_label_schema.md`
- `docs/moduleK/task02_pair_geometry_distance.md`
- `docs/moduleK/task03_future_window_labeler.md`
- `docs/moduleK/task04_offline_label_generator.md`
- `docs/moduleK/task05_label_report_and_stats.md`
- `docs/moduleK/task06_tests_and_acceptance.md`

本阶段只产出文档，没有写实现代码、测试代码或运行时配置。

## 任务重叠检查

结论：任务之间有衔接但职责边界清楚，没有重复实现同一能力。

- Task 01 只定义 schema、错误码和 future windows 配置合同，不实现算法。
- Task 02 只计算单帧单对塔吊的几何 raw distance 与 clearance，不看未来轨迹。
- Task 03 只基于已计算的 pair distance 时序扫描未来窗口，不遍历 episode 或组装完整标签。
- Task 04 是完整生成器，负责校验 episode 输入、遍历帧和 pair，并组装 `OfflineRiskLabel`。
- Task 05 只消费 labels 做统计和 warning，不修改标签。
- Task 06 只定义和实现测试验收，不新增生产接口。

## 任务遗漏检查

结论：`目标.md` 列出的 Module K 能力均已覆盖。

- `OfflineRiskLabel`、`OfflinePairRiskRecord`、`OfflineRiskReport` schema：Task 01。
- `OFFLINE_LABEL_*` 错误码：Task 01。
- K.2 固定输出字段：Task 01 定义，Task 04 组装，Task 06 验收。
- jib-jib、jib-hook、hook-hook 几何距离：Task 02。
- raw distance 与 clearance 区分：Task 02。
- 吊物摆动包络距离增强版预留：overview 和 Task 02 记录扩展点，MVP 不加入 K.2 固定列。
- 5s/10s/15s 未来窗口可配置：Task 01 扩展 `RiskConfig.future_windows_s`，Task 03/04 计算，Task 06 验收。
- `min_clearance_future`、TTC、risk level、collision label：Task 03。
- 使用真实未来轨迹并标记 `used_future_truth=True`：Task 01、Task 03、Task 04、Task 06。
- 完整 episode 后离线生成，不影响仿真主循环：overview、Task 04、Task 06。
- 标签不进入 LLM observation：overview、Task 01、Task 06。
- 碰撞/临界接近事件自动记录为 collision label：Task 03、Task 04、Task 06。
- Parquet 可导出：Task 01 schema 可 JSON/Parquet 友好序列化，Task 06 验证结构化导出合同；真实写入归 L。
- 正负样本比例统计和低正样本 warning：Task 05。
- 按 episode/scenario/crane_pair 聚合统计：Task 05。
- 轨迹缺失帧、crane_id 不匹配等明确错误：Task 04、Task 06。
- offline vs online 差异分析输入：overview 和 Task 04 保留 `online_risks` 可选输入，但不让其影响真值标签。

## 依赖顺序检查

结论：依赖顺序合理且无环。

```text
Task 01 offline label schema
  -> Task 02 pair geometry distance
  -> Task 03 future window labeler
  -> Task 04 offline label generator
  -> Task 05 label report and stats
  -> Task 06 tests and acceptance
```

说明：

- Task 02 依赖 Task 01 的 distance schema 和错误码。
- Task 03 依赖 Task 01 的 window label schema，也消费 Task 02 输出的 pair distance 时序。
- Task 04 依赖 Task 02 和 Task 03，是唯一完整遍历 episode 的任务。
- Task 05 依赖 Task 04 生成的 labels，也依赖 Task 01 的 report schema。
- Task 06 依赖所有前置任务，用于最终验收。

## 验收标准可测性检查

结论：每个验收标准都可以通过 pytest、Pydantic schema 校验、确定性几何 fixture、静态 import/name 扫描或相邻模块回归命令验证。

- schema 验收可通过 `model_validate()`、`model_dump(mode="json")`、extra 字段和 NaN/Inf fixture 验证。
- 几何验收可用手工构造的 3D 点、线段和 `CraneState` fixture 验证。
- 未来窗口验收可用确定性 clearance 序列验证 min、TTC、risk level、collision label。
- 完整生成器验收可用两塔/三塔短 episode fixture 验证 label 数量、排序和错误路径。
- 报告验收可用人工 labels 验证比例、分布、聚合和 warning。
- 防泄漏验收可通过已有 F/G/J/H 测试、`FORBIDDEN_OBSERVATION_FIELDS` 和静态扫描验证。
- Parquet 验收在 K 中限定为结构化对象可序列化；真实写入由 L 后续覆盖，避免越界。

## 与阶段一背景一致性检查

结论：文档与 `目标.md` 和当前代码合同一致。

- K 是 `OfflineRiskLabel` 的 owner，消费者是 L/O/P。
- K 读取完整真实轨迹、几何参数和 risk config；不在 episode 运行期间计算。
- K 的失败边界是 dataset build error/warning，不修改原 episode。
- K 不构造 observation，不调用 LLM，不做在线风险干预。
- 在线 H 的 `RiskPairResult` 继续拒绝 `used_future_truth=True`，离线 K 的 `OfflineRiskLabel` 必须标记 `used_future_truth=True`。
- 当前 `RiskConfig` 还没有 `future_windows_s` 字段；Task 01 将其作为最小必要 schema 扩展，解决 `目标.md` 对可配置 5s/10s/15s 的要求。
- 当前几何 helper 已存在于 `collision.py` 和 `risk.py`；Task 02 要求复用或提取，避免重复造轮子，同时用回归测试保护 H。

## 调整记录

- 保留 `目标.md` 建议的 6 个任务，并补充 `overview.md` 和 `self_review.md` 作为阶段一/二闸口记录。
- 在 Task 01 中增加 `OfflineFutureWindowLabel`，让 K.2 的固定 5s/10s 字段和可配置 15s/自定义窗口同时成立。
- 在 Task 01 中明确扩展 `RiskConfig.future_windows_s`，因为当前代码尚未包含该字段。
- 在 Task 02 中规定 `distance_min_raw_now_m` 对应最小 clearance 的对象，避免 raw distance 与包络 clearance 的最近对象不一致。
- 在 Task 03 中明确窗口超出 episode 尾部时只使用剩余真实帧，不补点、不外推。
- 在 Task 05 中明确 warning 阈值默认 1%，并建议按所有聚合组生成 warning。
- 在 Task 06 中把真实 Parquet 写入和 O/P dataset 构建列为非目标，只验证 K 输出的结构化消费合同。

## 阶段闸口

阶段一和阶段二已完成。根据 `目标.md` 的硬性要求，现在应停下等待确认；收到确认后再进入阶段三逐任务实现、测试和提交。
