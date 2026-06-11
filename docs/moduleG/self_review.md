# Module G 阶段二自审

## 审查范围

本次自审覆盖以下阶段一产物：

- `docs/moduleG/overview.md`
- `docs/moduleG/task01_command_schema.md`
- `docs/moduleG/task02_prompt_builder.md`
- `docs/moduleG/task03_llm_provider.md`
- `docs/moduleG/task04_command_parser.md`
- `docs/moduleG/task05_retry_and_fallback.md`
- `docs/moduleG/task06_decision_orchestrator.md`
- `docs/moduleG/task07_tests_and_acceptance.md`

本阶段只产出文档，没有写实现代码、测试代码或运行时配置。

## 任务重叠检查

结论：任务之间存在必要接口衔接，但没有职责重叠。

- Task 01 只定义 schema 和 fallback command 事实源，不解析、不调用 provider、不 retry。
- Task 02 只构造 messages，不调用 provider、不解析命令、不后处理 LLM 输出。
- Task 03 只封装 provider 一次调用或 replay 查找，不解析 raw content、不做 retry。
- Task 04 只负责 raw JSON 解析和 Pydantic 校验，不做 retry/fallback。
- Task 05 组装单塔 retry/fallback 和连续失败计数，不管理多塔批量 session。
- Task 06 管理多塔 session、history mode、决策频率门控和批量决策，不写 recorder、不冻结 snapshot。
- Task 07 只定义测试与验收，不新增生产接口。

## 任务遗漏检查

结论：目标文档列出的 Module G 能力均已覆盖。

- `RawLLMResponse`、`ParsedCommand`、joystick/axis schema、validation error、`LLMCallRecord`：Task 01。
- system/user/retry prompt、五种 profile prompt、语言策略、available actions 约束：Task 02。
- deepseek/minimax/mock/replay provider、base_url/model/key/timeout/structured output 支持：Task 03。
- JSON 解析、schema 校验、枚举/档位/duration 校验、validation error 反馈对象：Task 04。
- invalid/timeout retry、neutral_stop、连续失败 `llm_failed`：Task 05。
- 多塔独立 session、history mode、决策频率、call record 汇总：Task 06。
- schema/prompt/provider/parser/retry/session/replay/泄漏防护测试与验收：Task 07。

## 依赖顺序检查

结论：依赖顺序合理且无环。

```text
Task 01 command schema
  -> Task 02 prompt builder
  -> Task 03 provider
  -> Task 04 parser
  -> Task 05 retry/fallback
  -> Task 06 orchestrator
  -> Task 07 tests/acceptance
```

说明：

- Task 03 和 Task 04 都依赖 Task 01，但彼此只通过 `RawLLMResponse`/`ParsedCommand` 对象衔接。
- Task 05 同时依赖 prompt/provider/parser，是第一个完整单塔决策闭环。
- Task 06 依赖 Task 05，只做多塔/session/调度层组装。
- Task 07 依赖所有前置任务。

## 验收标准可测性检查

结论：每个任务的验收标准都可以用 pytest、fake provider、mock HTTP client 或静态扫描验证。

- schema 验收可通过 Pydantic `model_validate()`、`model_dump()` 和 `model_json_schema()` 测试。
- prompt 验收可通过字符串包含、JSON 片段解析、forbidden key 扫描和 immutability 检查完成。
- provider 验收可通过 mock/replay 本地测试和 fake HTTP client 完成，默认不需要真实网络。
- parser 验收可通过 raw content fixtures 覆盖合法、invalid JSON、Markdown、中文枚举、extra 字段、duration 越界。
- retry/fallback 验收可通过 scripted fake provider 控制失败/成功序列。
- orchestrator 验收可通过多个 observation fixture 验证 session 独立、history mode 和 snapshot 一致性。
- 信息泄漏与越权验收可通过 serialized payload 扫描和静态 import 扫描完成。

## 与阶段一背景一致性检查

结论：文档与目标背景和总方案合同一致。

- G 只读取 `Observation`，不绕过 F 读取 `WorldSnapshot`、`CraneState` 或完整任务队列。
- G 只产出 `RawLLMResponse`、`ParsedCommand`、validation errors 和 call record，不产出 `ExecutedCommand` 或 `ControlTarget`。
- 性格差异通过 profile prompt、行为参数、历史摘要和决策节奏体现，禁止后处理篡改命令。
- JSON 字段名和枚举值使用英文，`reason` 允许中文。
- `neutral_stop` 被定义为普通安全停止，不是 emergency stop。
- replay provider 被限定为 Module G 本地 `ParsedCommand` replay；总方案 0.7.9 的 `ExecutedCommand` 严格复现留给 J/H/L 全链路。
- 连续失败规则已统一为 `consecutive_failures >= max_consecutive_failures` 时报告 `llm_failed`。

## 调整记录

- 统一了连续失败阈值措辞，避免“超过阈值”和“达到阈值”混用。
- 明确 `LLMConfig` 中历史模式字段来自 `context.history_mode`。
- 明确 G 本地 replay 与全链路 `ExecutedCommand` replay 的边界，防止后续实现混淆。

## 阶段闸口

阶段一和阶段二已完成。根据 `目标.md` 的硬性要求，现在应停下等待确认；收到确认后再进入阶段三逐任务实现、测试和提交。
