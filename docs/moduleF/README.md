# 模块 F：Observation 构造模块任务索引

## 模块目标

模块 F 负责为每台塔吊构造“人类驾驶员可见”的局部 `Observation`。它从调度器冻结的 `WorldSnapshot` 中读取当前帧只读状态，结合模块 D 的任务观察上下文、模块 E 的天气与可见度上下文、模块 H 的在线风险提示和模块 A 的操作员/风险提示配置，输出可被模块 G prompt 使用、也可被模块 L 落盘回放校验的结构化 JSON。

模块 F 的核心不是“把全局状态复制给 LLM”，而是把当前司机在该决策时刻可合理知道的信息整理成受控、可复现、可校验的局部观察。

权威来源为项目根目录下的 `群塔LLM仿真系统开发方案_v0.4_完整版.md` 的 `0.7.2`、`0.7.3`、`F.2`、`F.3`、`F.4`，以及模块 D `task07` 和模块 E `task04` 的读取侧合同。

## 任务顺序

| 顺序 | 文档 | 目标 |
|---|---|---|
| 1 | [task01_observation_schema](task01_observation_schema.md) | 定义 `Observation` 及子对象 Pydantic schema，作为唯一事实源 |
| 2 | [task02_self_state_builder](task02_self_state_builder.md) | 从 `CraneState` 和 `CraneConfig` 构造自身状态摘要 |
| 3 | [task03_task_context_builder](task03_task_context_builder.md) | 消费 D 的任务观察上下文并构造任务段 |
| 4 | [task04_neighbor_visibility_filter](task04_neighbor_visibility_filter.md) | 用 E 的可见度上下文筛选邻塔、加噪声和隐藏 hook |
| 5 | [task05_safety_hint_builder](task05_safety_hint_builder.md) | 按 R0/R1 从 `OnlineRisk` 构造风险提示 |
| 6 | [task06_observation_assembly](task06_observation_assembly.md) | 组装完整 `Observation`，注入操作员性格和历史摘要 |
| 7 | [task07_tests_and_acceptance](task07_tests_and_acceptance.md) | 定义模块 F 测试清单和完整验收标准 |

## 阶段二自审

- 任务重叠检查：schema、self state、task、neighbor visibility、safety hint、assembly、acceptance 各有独立边界。Task 06 只做组装与入口函数，不重新实现 Task 02-05 的业务规则。
- 遗漏检查：目标文件要求的自身状态、任务目标、任务阶段、取货/卸货相对方位、可见邻塔、风速可见度、R1 风险提示、可用操作、操作员性格、历史摘要均已分配到具体任务。
- 依赖顺序检查：Task 01 是 schema 基础；Task 02-05 可基于 schema 独立测试；Task 06 依赖 Task 02-05；Task 07 依赖全部实现。无循环依赖。
- 可测试性检查：每个任务都指定了正常、边界、异常或防泄漏测试，且能映射到 `backend/app/tests/test_observation.py`、`test_observation_visibility.py`、`test_moduleF_acceptance.py`。
- 与阶段一背景一致性：F 只读 `WorldSnapshot` 和上游上下文，不调用 LLM、不推进任务、不计算 online/offline risk、不写 recorder 文件。
- 调整结论：由于当前代码库尚无模块 J/H 实现，Task 01/06 将先定义 F 所需的窄 `ObservationWorldSnapshot` 和 `OnlineRiskHint` 输入合同，字段只覆盖当前 F 消费面，后续 J/H 可用等价字段适配。

