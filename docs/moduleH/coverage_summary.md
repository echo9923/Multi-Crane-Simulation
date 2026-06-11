# Module H Coverage Summary

## 已覆盖内容

- Schema 合同：`ExecutedCommand`、`OnlineRisk`、`RiskPairResult`、`MechanicalLimitResult`、`ForbiddenZoneResult`、`InterventionRecord`、`CollisionEvent` 与 `SafetyPipelineResult` 都有 extra 字段拒绝、NaN/Inf 拒绝或核心合同测试。
- 基础机械安全：deadman release、emergency stop、小车/起升限位、回转加速度限制、载重曲线与力矩硬限制、非法 dt、state/config/command 身份不一致。
- 禁区策略：无禁区、`task_only` 记录不修改、`hard` 阻止进入、box/polygon、z_range、load 优先、禁用事件记录、非法 zone 类型。
- 在线风险：多塔每对风险导出、jib-jib/jib-hook/hook-hook/load 距离、短时外推、TTC、风速冗余、risk level 映射、hint_by_crane、不使用 future/offline truth。
- 多塔干预：S0/S1 记录风险但不做风险干预，S2 high 及以上限速，S3 high/near_miss/collision 停车，`intervention_applied` 只在实际修改时记录。
- 碰撞终止：线段交叉、点线/线线距离、hook-hook、jib-hook、jib-jib、高度净空、碰撞事件、`episode_status="failed_collision"`、安全管线聚合事件。
- 跨任务验收：G 的 `ParsedCommand` 输入到 H 的 `ExecutedCommand`/`OnlineRisk` 输出，raw vs executed 同时保留，R0/R1 observation hint 合同，三塔 pair 导出，H 静态边界扫描。
- 邻近模块回归：配置、塔吊模型、物理状态、天气风速合同、Observation 风险提示构建与 R0 抑制。

## 暂未覆盖或降级覆盖

- I 模块尚未提供正式的 `ExecutedCommand -> ControlTarget` 转换入口，因此 G->H->I 验收目前降级为 `ExecutedCommand` 字段满足 `ControlTarget` 所需合同的 smoke test；I 接入后应升级为真实转换测试。
- J 调度器的 episode 主循环尚未接入 Module H，因此“碰撞后不再生成控制目标或轨迹”在 H 内只验证为返回 `failed_collision` 终止信号；J/I 集成完成后应补端到端 episode 停止测试。
- L 模块 recorder 与 K 模块 offline label 尚未作为本任务实现对象，当前只验证 H 产出的每帧每对 `RiskPairResult` 可序列化导出；落盘格式和离线标签生成由 L/K 后续模块测试覆盖。
- 在线风险使用短时运动学外推，不做高精度吊载摆动仿真；这符合 Module H MVP 边界，高精度摆动碰撞需在物理模型扩展后单独验证。
