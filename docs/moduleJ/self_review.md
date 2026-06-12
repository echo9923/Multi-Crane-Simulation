# Module J 阶段二自审

## 审查范围

本次自审覆盖以下阶段一产物：

- `docs/moduleJ/README.md`
- `docs/moduleJ/overview.md`
- `docs/moduleJ/task01_scheduler_schema.md`
- `docs/moduleJ/task02_world_snapshot_freezer.md`
- `docs/moduleJ/task03_command_store.md`
- `docs/moduleJ/task04_decision_timing.md`
- `docs/moduleJ/task05_frame_loop_orchestrator.md`
- `docs/moduleJ/task06_tests_and_acceptance.md`

本阶段只产出文档，没有写实现代码、测试代码或运行时配置。

## 任务重叠检查

结论：任务之间有必要衔接，但职责边界清楚，没有重复实现同一能力。

- Task 01 只定义 J 拥有的 schema、status、config、result 和错误合同，不实现运行逻辑。
- Task 02 只负责把当前运行态冻结成 `WorldSnapshot`，并派生 F 的窄输入，不构造 observation。
- Task 03 只负责当前 `ExecutedCommand` 存储、批量替换和过期 neutral_stop，不判断 due、不调用 safety/controller。
- Task 04 只负责每塔决策时刻判定，不处理 command expiry、不调用 G。
- Task 05 是唯一 frame loop orchestrator，把 Task 02-04 与上游模块接口组装起来。
- Task 06 只定义测试与验收，不新增生产接口。

## 任务遗漏检查

结论：`目标.md` 和总方案列出的 Module J 能力均已覆盖。

- `WorldSnapshot` owner、字段、冻结和不可变策略：overview、Task 01、Task 02。
- `EpisodeStatus` owner 和 terminal status：overview、Task 01、Task 05。
- `SchedulerConfig`：Task 01。
- `CommandStore` 当前命令、过期检查、neutral_stop 注入：Task 01、Task 03。
- 决策时刻判定和 idle 参与：Task 04、Task 05。
- 单帧生命周期 15 步：overview、Task 05、Task 06。
- 同一 decision time 多塔 observation 来自同一 snapshot：overview、Task 02、Task 05、Task 06。
- 同一 decision time 多塔命令收齐后同时应用：README、Task 03、Task 05、Task 06。
- `offline_batch`、`offline_replay`、`interactive_server`：overview、Task 01、Task 05、Task 06。
- `offline_wait` / `realtime_stale` LLM scheduling policy 与 RuntimeMode 分离：overview、Task 01、Task 05。
- replay 不调用 LLM、不调用 summary LLM、不重新叠加 S2/S3 干预：overview、Task 05、Task 06。
- replay hash/schema/operator assignment/command uniqueness 检查：overview、Task 01、Task 05、Task 06。
- LLM timeout neutral_stop 与连续失败 `llm_failed`：README、Task 05、Task 06。
- collision -> `failed_collision` 且不生成碰撞后轨迹：overview、Task 05、Task 06。
- NaN/Inf -> `failed_invalid_state`：overview、Task 01、Task 05、Task 06。
- `record_initial_frame(time_s=0)` 与 `record_step` 时机：overview、Task 05、Task 06。
- 事件归属到 step 后帧：overview、README、Task 05。
- 规则司机和 LLM 司机共用同一 frame loop：README、Task 04、Task 05、Task 06。
- `WorldSnapshot` 不包含 future label、offline risk label、LLM reason：overview、Task 01、Task 02、Task 06。

## 依赖顺序检查

结论：依赖顺序合理且无环。

```text
Task 01 scheduler schema
  -> Task 02 world snapshot freezer
  -> Task 03 command store
  -> Task 04 decision timing
  -> Task 05 frame loop orchestrator
  -> Task 06 tests and acceptance
```

说明：

- Task 02 依赖 Task 01 的 `WorldSnapshot`，但不依赖 Task 03/04。
- Task 03 依赖 Task 01 的 command store 状态对象，且可独立测试。
- Task 04 依赖 Task 01 的 scheduler config，且可独立测试。
- Task 05 依赖 Task 02/03/04，是唯一组合点。
- Task 06 依赖所有前置任务，负责补齐跨任务和跨模块验收。

## 验收标准可测性检查

结论：每个验收标准都可以通过 pytest、fake adapter、Pydantic schema 校验、call log 或静态扫描验证。

- schema 验收可通过 `model_validate()`、extra 字段、NaN/Inf fixtures 和 JSON 序列化验证。
- snapshot 冻结可通过构造后修改输入对象验证深拷贝/不可变效果。
- 同一 snapshot 多塔 observation 可通过 F 的 `build_observations_for_snapshot()` fixture 验证。
- command store 原子替换可通过一条非法命令导致整体不变验证。
- command expiry 可通过 `sim_time == command.time_s + command_duration_s` 边界验证。
- decision timing 可用固定 interval 和浮点边界参数化测试验证。
- frame loop 顺序可用 fake dependencies 的 call log 验证。
- replay 不调用 LLM 可用 fake operator 的 call count 验证。
- LLM timeout/连续失败可用 scripted fake operator / fake G result 验证。
- collision 和 invalid state 可用 fake adapter 抛错或返回 terminal candidate 验证。
- scheduler 不越界实现业务规则可用静态扫描辅助验证。

## 与阶段一背景一致性检查

结论：文档与 `目标.md`、总方案和当前代码合同一致，并显式标注了几个实现阶段要处理的接口适配点。

- `RuntimeMode` 只保留 `offline_batch`、`offline_replay`、`interactive_server`，没有把 `offline_wait` 写成第四种运行模式。
- `offline_wait` / `realtime_stale` 被归入 LLM scheduling policy，符合 `LLMSchedulingMode` 现有 enum。
- replay 的权威命令是历史 `ExecutedCommand`，不是 `ParsedCommand` 或 raw response。
- G 本地 replay provider 与 J 的全链路 `ExecutedCommand` replay 已在 Task 05 中分清。
- F 当前已有 `ObservationWorldSnapshot.current_commands: dict[str, ControlTarget]`，Task 02 明确 J 派生 F 窄输入时应传 `current_control_targets`，不要把 `ExecutedCommand` 塞给 F。
- H 的 safety pipeline、K 的 collision/risk、I 的 controller、C 的 physics 都被写成 adapter/公开接口调用，J 不内嵌业务规则。
- Task 06 说明目标文档中的部分回归测试文件名可能与当前仓库不同，要求实现阶段用等价现有测试并在覆盖总结中说明映射。

## 调整记录

- 在建议拆分基础上保留 6 个任务，并补充 `README.md` 作为模块索引、`self_review.md` 作为阶段二闸口记录。
- 将 `CommandStore` 的 schema 合同放在 Task 01，行为实现单独放在 Task 03，避免 Task 01 范围过大。
- 将 decision timing 单独作为 Task 04，避免与 G 的 `OperatorDecisionOrchestrator.should_decide()` 纠缠。
- 在 Task 05 明确 replay 不调用 G、不重新叠加 H 的 S2/S3 干预，只允许 audit-only。
- 在 Task 01 示例 schema 中使用 `Field(default_factory=...)` 表达默认容器，避免后续实现复制可变默认值。
- 在 Task 06 增加静态扫描类验收，防止调度器逐渐吸收任务、安全、controller、collision 的业务逻辑。

## 阶段闸口

阶段一和阶段二已完成。根据 `目标.md` 的硬性要求，现在应停下等待确认；收到确认后再进入阶段三逐任务实现、测试和提交。
