# Task 06：Tests And Acceptance

## 任务目标

补齐 Module K 的单元测试、验收测试和相邻模块回归测试，验证离线标签只依赖真实轨迹、可配置未来窗口、硬性在线/离线隔离和统计报告能力。

## 范围：做什么 / 不做什么

做：

- 新增 `backend/app/tests/test_offline_label.py`。
- 新增 `backend/app/tests/test_moduleK_acceptance.py`。
- 覆盖 Task 01-05 的 schema、几何、未来窗口、生成器和报告。
- 覆盖在线/离线隔离，确保离线标签不进入 observation、prompt、online risk 或 scheduler snapshot。
- 覆盖 L/O/P 需要的结构化导出合同：K 产出对象可序列化为 Parquet-friendly dict，但不实际写文件。
- 覆盖长 episode、多塔多对、缺失帧、crane_id mismatch 等错误路径。
- 跑通 `目标.md` 指定的测试命令和相邻模块回归。

不做：

- 不在 K 测试中真实调用 L 写 Parquet。
- 不真实构建 O/P 训练 dataset 或 STGNN 图。
- 不启动仿真主循环或 LLM provider。
- 不引入慢速大数据性能测试；使用可控规模的确定性 fixture。

## 接口与测试文件

新增测试文件：

```text
backend/app/tests/test_offline_label.py
backend/app/tests/test_moduleK_acceptance.py
```

必须跑通的命令：

```bash
pytest backend/app/tests/test_offline_label.py -v
```

```bash
pytest backend/app/tests/test_offline_label.py \
       backend/app/tests/test_moduleK_acceptance.py -v
```

```bash
pytest backend/app/tests/test_collision.py \
       backend/app/tests/test_risk_online.py \
       backend/app/tests/test_safety_risk_schema.py \
       backend/app/tests/test_physics.py -v
```

最终整体回归建议：

```bash
pytest backend/app/tests/test_offline_label.py \
       backend/app/tests/test_moduleK_acceptance.py \
       backend/app/tests/test_collision.py \
       backend/app/tests/test_risk_online.py \
       backend/app/tests/test_safety_risk_schema.py \
       backend/app/tests/test_physics.py \
       backend/app/tests/test_scheduler.py \
       backend/app/tests/test_observation.py \
       backend/app/tests/test_prompt_builder.py -v
```

## 必测场景

### Schema

- `OfflineRiskLabel` 完整 payload 校验通过。
- `OfflineRiskLabel` 拒绝 extra 字段、NaN/Inf、`used_future_truth=False`。
- `OfflinePairRiskRecord` 拒绝混合 pair 或混合 episode 的 labels。
- `OfflineRiskReport` 可 JSON dump。
- `RiskConfig.future_windows_s` 默认包含 `5/10/15`，非法窗口失败。
- 在线 `RiskPairResult(used_future_truth=True)` 仍失败。

### 几何距离

- `segment_distance_3d()` 或 K 包装后的精确距离覆盖相交线段、平行线段、斜交不相交线段。
- `point_segment_distance_3d()` 覆盖投影在线段内和在线段外。
- jib-jib、jib-hook、hook-hook raw distance 与 clearance 分别正确。
- clearance 为负时不截断。
- min distance 对应最小 clearance 的对象类型。

### 未来窗口

- 5s/10s/15s 窗口可配置并输出。
- 5s 无碰撞、10s 有碰撞的已知序列能产生不同 collision label。
- TTC 使用首次进入 `d_safe_effective_m` 的真实时间差。
- 窗口超出 episode 尾部时不外推。
- 当前帧已碰撞时 TTC 为 0，risk level 为 collision。

### 完整生成器

- 完整 episode 输入：两塔三帧生成三条 labels。
- 多塔输入：三塔四帧生成十二条 labels。
- labels 排序稳定，pair_id 稳定。
- `generate_many()` 保持 episode 之间隔离。
- 缺失帧、重复 frame/crane、crane_id mismatch、空轨迹都有明确错误码。

### 报告和统计

- 正负样本比例按 5s/10s 分别统计。
- risk level 分布按 5s/10s 分别统计。
- 按 episode/scenario/crane_pair 聚合统计。
- 正样本比例低于 1% 时产生 `OFFLINE_LABEL_W_LOW_POSITIVE_RATIO` warning。
- 空 labels 返回可序列化 report，并产生 warning。

### 在线 / 离线隔离

- `Observation`、`WorldSnapshot`、prompt builder 序列化结果中不包含 `OfflineRiskLabel`、`future_min_distance`、`offline_ttc`、`collision_label`。
- `backend.app.sim.risk` 不导入 `backend.app.sim.offline_label`。
- `backend.app.sim.prompt_builder` 不导入 `OfflineRiskLabel`。
- `FORBIDDEN_OBSERVATION_FIELDS` 继续覆盖 offline/future 字段。
- K 模块不导入 LLM provider、operator orchestrator、prompt builder 或 observation builder。

### 导出合同

- `OfflineRiskLabel.model_dump(mode="json")` 包含 K.2 固定列，且值为 JSON/Parquet 友好类型。
- `OfflinePairRiskRecord` 能展开为 row dict 列表，L 可写 `pair_risks.parquet`。
- K 不调用 `to_parquet()`、`jsonlines` writer 或文件系统写入。

## 验收标准（具体、可测试）

- `pytest backend/app/tests/test_offline_label.py -v` 通过。
- `pytest backend/app/tests/test_offline_label.py backend/app/tests/test_moduleK_acceptance.py -v` 通过。
- `pytest backend/app/tests/test_collision.py backend/app/tests/test_risk_online.py backend/app/tests/test_safety_risk_schema.py backend/app/tests/test_physics.py -v` 通过。
- 静态扫描证明在线 risk、observation、prompt、scheduler snapshot 不依赖 K 离线标签。
- 所有新增 K schema 使用 `extra="forbid"` 和 `allow_inf_nan=False`。
- `OfflineRiskLabel` 中 `used_future_truth=True`，在线 `RiskPairResult` 中 `used_future_truth=False`。
- 没有新增真实 Parquet 文件、JSONL 文件或数据集输出文件。

## 覆盖总结模板

阶段四完成后输出简短覆盖总结：

```text
已覆盖：
- schema 合同：
- 几何距离：
- 未来窗口/TTC：
- 完整生成器：
- 报告统计：
- 在线/离线隔离：
- 相邻模块回归：

未覆盖及原因：
- 真实 Parquet 写入：归 Module L，本阶段只验证 K 输出可序列化。
- O/P 真实 dataset/STGNN 构建：归 Module O/P，本阶段用结构化消费合同 smoke 覆盖。
```

## 依赖关系

依赖 Task 01-05。该任务是 Module K 阶段三和阶段四的最终验收入口。
