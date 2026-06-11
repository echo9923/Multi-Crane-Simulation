# Module H 阶段二自审

## 审查范围

本次自审覆盖以下阶段一产物：

- `docs/moduleH/overview.md`
- `docs/moduleH/task01_safety_risk_schema.md`
- `docs/moduleH/task02_mechanical_safety_layer.md`
- `docs/moduleH/task03_forbidden_zone_policy.md`
- `docs/moduleH/task04_online_risk_evaluator.md`
- `docs/moduleH/task05_safety_intervention_pipeline.md`
- `docs/moduleH/task06_collision_detection.md`
- `docs/moduleH/task07_tests_and_acceptance.md`

本阶段只产出文档，没有写实现代码、测试代码或运行时配置。

## 任务重叠检查

结论：任务之间有必要衔接，但职责边界清楚，没有重复实现同一能力。

- Task 01 只定义 H 拥有的 schema、风险等级和错误码，不实现算法。
- Task 02 只做单塔基础机械安全，不做禁区、多塔风险或碰撞。
- Task 03 只做禁区策略，不做任务合法性、不做风险评级。
- Task 04 只做在线风险影子评估，不修改命令、不终止 episode。
- Task 05 组装机械安全、禁区、在线风险与 S0-S3 干预，是唯一修改多塔风险命令的任务。
- Task 06 只做碰撞检测和 failed collision 终止候选，不推进主循环。
- Task 07 只定义测试与验收，不新增生产接口。

## 任务遗漏检查

结论：`目标.md` 列出的 Module H 能力均已覆盖。

- `ExecutedCommand`、`OnlineRisk`、`RiskPairResult`、`RiskLevel`、`InterventionRecord`、`MechanicalLimitResult`、`ForbiddenZoneResult`、`CollisionEvent` schema：Task 01。
- `SAFETY_*`、`RISK_*`、`COLLISION_*` 错误码：Task 01。
- 回转速度/角加速度、小车行程、起升高度、载重曲线、力矩、deadman、emergency stop：Task 02。
- 禁区 `task_only` 与 `hard` 策略：Task 03。
- `d_min_online`、`d_hat_min`、`TTC_hat`、`d_safe_effective`、风险等级、不用未来轨迹：Task 04。
- R0/R1 与 S0/S1/S2/S3 的职责边界：overview、Task 04、Task 05、Task 07。
- S0/S1 记录不改命令，S2 限速，S3 强制停车/减速：Task 05。
- raw vs executed 保存、干预原因记录：Task 01、Task 05。
- 碰撞事件、`failed_collision`、立即终止候选、不生成碰撞后轨迹合同：Task 06、Task 07。
- 每帧每对塔吊风险标签可导出：Task 01、Task 04、Task 07。
- G->H->I 链路 smoke 验收：Task 07。

## 依赖顺序检查

结论：依赖顺序合理且无环。

```text
Task 01 safety/risk schema
  -> Task 02 mechanical safety
  -> Task 03 forbidden zone policy
  -> Task 04 online risk evaluator
  -> Task 05 safety intervention pipeline
  -> Task 06 collision detection
  -> Task 07 tests/acceptance
```

说明：

- Task 02、Task 03、Task 04 都依赖 Task 01 schema。
- Task 03 消费 Task 02 后的 `ExecutedCommand`，避免禁区层重复机械限位。
- Task 04 消费 Task 02/03 后的 proposed command，确保在线风险评估基于将要执行的安全命令。
- Task 05 是 pipeline 组装点，依赖 Task 02/03/04。
- Task 06 可以独立使用当前几何状态检测碰撞，但最终应接入 Task 05 的 pipeline 结果。
- Task 07 依赖所有前置任务。

## 验收标准可测性检查

结论：每个验收标准都可以通过 pytest、Pydantic schema 校验、确定性几何 fixtures、静态扫描或相邻模块 smoke test 验证。

- schema 验收可通过 `model_validate()`、`model_dump(mode="json")`、extra 字段和 NaN/Inf fixtures 验证。
- 机械安全验收可通过构造单台 `CraneState`、`CraneConfig`、`CraneModelSpec` 和 `ParsedCommand` fixture 验证。
- 禁区策略验收可通过盒形、多边形和 z_range 几何 fixture 验证。
- 在线风险验收可通过两塔/三塔固定几何和命令采样验证，不需要真实 future trajectory。
- 干预验收可通过同一 high risk fixture 在 S0/S1/S2/S3 下分别断言 raw/executed 差异。
- 碰撞验收可通过线段交叉、点线距离和包络半径阈值验证。
- 信息泄漏验收可通过序列化 payload 扫描和静态 import/name 扫描验证。
- G->H->I smoke 测试可在 I 未完成时降级为 H 输出字段合同验证，并在 I 完成后扩展为真实转换。

## 与阶段一背景一致性检查

结论：文档与 `目标.md` 和当前代码合同一致。

- H 只消费 G 的 `ParsedCommand`，不调用 provider，也不解析 raw LLM response。
- H 拥有 `ExecutedCommand` 与 `OnlineRisk`，符合总方案核心对象表。
- H 不构造 `Observation`，只产出 F 可消费的 online risk/hint 输入。
- 基础机械安全始终生效，不受 S0-S3 影响。
- R0/R1 仅决定 F 是否暴露 safety hint，不影响 H 是否计算或记录 risk。
- S0/S1 不因风险修改命令，但机械限位、力矩、deadman、emergency stop 和 hard forbidden zone 仍可修改命令。
- `intervention_applied` 被限定为 S2/S3 风险干预实际修改命令时记录，避免与机械限位和禁区事件混淆。
- 在线风险明确禁止使用真实未来轨迹、offline label 或 future TTC。
- 碰撞终止边界写成 H 返回 `failed_collision` 候选，由 J 主循环执行立即终止，符合模块职责。

## 调整记录

- 在建议拆分基础上保留 7 个任务，并补充 `self_review.md` 作为阶段二闸口记录。
- 将禁区策略单独保留为 Task 03，避免混入机械安全或风险评估。
- 将 collision detection 放在 Task 06，既可独立测试几何，也能在 Task 05 pipeline 后接入终止信号。
- 在 Task 07 增加 `test_safety_risk_schema.py` 和 `test_forbidden_zone_policy.py`，比 `目标.md` 的建议测试命令更细，便于独立验收 Task 01 和 Task 03；同时保留 `目标.md` 中的完整验收基线命令作为硬性要求。
- 明确 I 未实现时 G->H->I smoke test 的降级验收方式，避免阶段 H 被后续模块阻塞。

## 阶段闸口

阶段一和阶段二已完成。根据 `目标.md` 的硬性要求，现在应停下等待确认；收到确认后再进入阶段三逐任务实现、测试和提交。
