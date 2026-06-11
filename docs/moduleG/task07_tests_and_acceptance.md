# Task 07：模块 G 测试清单与验收标准

## 任务目标

定义模块 G 的单元测试、合同测试、集成测试和最终验收标准，确保 LLM 操作员只读 observation、输出合法 command、失败可恢复、记录完整、可 replay 且不越权修改仿真状态。

## 范围：做什么 / 不做什么

做：

- 新增并维护 `backend/app/tests/test_command_schema.py`。
- 新增并维护 `backend/app/tests/test_prompt_builder.py`。
- 新增并维护 `backend/app/tests/test_llm_provider.py`。
- 新增并维护 `backend/app/tests/test_command_parser.py`。
- 新增并维护 `backend/app/tests/test_moduleG_acceptance.py`。
- 回归模块 F 与 secret governance 的相邻合同测试。
- 覆盖正常路径、边界路径、异常路径、信息泄漏防护、fallback、replay 和多塔独立 session。

不做：

- 不要求真实 DeepSeek/MiniMax 网络调用进入默认测试。
- 不要求模块 H/I/J/L 已完整实现。
- 不写真实 Parquet/JSONL，只校验 G 产出的 `LLMCallRecord` 可被 L 消费。

## 接口与数据结构（签名级别）

本任务不新增生产接口，只定义并维护测试入口：

```python
def test_parsed_command_accepts_g3_payload() -> None: ...
def test_parsed_command_forbids_extra_fields_recursively() -> None: ...
def test_axis_direction_and_gear_must_be_consistent() -> None: ...
def test_prompt_builder_injects_profile_observation_actions_and_schema() -> None: ...
def test_prompt_builder_forbids_secret_and_future_label_leaks() -> None: ...
def test_mock_provider_returns_deterministic_raw_command() -> None: ...
def test_replay_provider_matches_snapshot_and_crane_without_network() -> None: ...
def test_parser_converts_valid_raw_response_to_parsed_command() -> None: ...
def test_parser_reports_validation_errors_for_retry() -> None: ...
def test_retry_feedback_then_success_records_all_attempts() -> None: ...
def test_retry_exhaustion_returns_neutral_stop() -> None: ...
def test_consecutive_failures_mark_llm_failed() -> None: ...
def test_multi_crane_sessions_are_independent() -> None: ...
def test_module_g_boundaries_remain_static() -> None: ...
```

## 前置依赖

- Task 01 的 command schema。
- Task 02 的 prompt builder。
- Task 03 的 provider 抽象。
- Task 04 的 parser。
- Task 05 的 retry/fallback。
- Task 06 的 orchestrator。
- 模块 F 的 observation schema 与 builder 测试 fixtures。

## 推荐测试命令

schema 测试：

```bash
pytest backend/app/tests/test_command_schema.py -v
```

prompt 构建测试：

```bash
pytest backend/app/tests/test_prompt_builder.py -v
```

provider 测试：

```bash
pytest backend/app/tests/test_llm_provider.py -v
```

parser 测试：

```bash
pytest backend/app/tests/test_command_parser.py -v
```

模块 G 完整验收：

```bash
pytest backend/app/tests/test_command_schema.py \
       backend/app/tests/test_prompt_builder.py \
       backend/app/tests/test_llm_provider.py \
       backend/app/tests/test_command_parser.py \
       backend/app/tests/test_moduleG_acceptance.py -v
```

回归邻近模块：

```bash
pytest backend/app/tests/test_observation.py \
       backend/app/tests/test_moduleF_acceptance.py \
       backend/app/tests/test_secret_governance.py -v
```

## schema 验收

- `RawLLMResponse`、`ParsedCommand`、`LLMCallRecord` 及所有子 schema 拒绝 extra 字段。
- 所有 float 字段拒绝 NaN/Inf。
- `schema_version` 存在并等于 `"1.0"`。
- 输出 JSON Schema 对齐总方案 G.3。
- 所有枚举值使用英文。
- `direction/gear` 一致性有测试覆盖。
- `neutral_stop` fallback command schema 合法。

## prompt 验收

- 五种 operator profile prompt 都存在且内容有明显差异。
- prompt 包含局部观测边界、可用动作、输出 schema 和 command duration 范围。
- retry prompt 会包含具体 validation error。
- prompt 不包含完整 API key 或 secret。
- prompt 不包含 offline/future label 或邻塔未来任务信息。

## provider 验收

- Mock provider 可无网络运行，输出确定性合法 raw JSON。
- Replay provider 不调用 LLM，按 `source_snapshot_id + crane_id` 匹配唯一命令。
- Replay missing/duplicate 有明确错误。
- DeepSeek/MiniMax provider 请求构造可测试，真实网络调用默认跳过或显式标记。
- runtime secret 不落盘到 raw payload 或 call record。

## parser 与 retry 验收

- parser 接受合法 JSON，拒绝 Markdown/自然语言/数组/多对象。
- parser 失败会生成可读、可定位的 `CommandValidationError`。
- invalid/timeout/API error 会进入 retry。
- retry 时把 validation error 注入 prompt。
- retry 耗尽产出 `neutral_stop`。
- 连续失败达到阈值后 result 标记 `llm_failed`。
- 成功解析会清零连续失败计数。

## orchestrator 验收

- 多塔 decision 使用独立 session 和 failure counter。
- 同一 decision batch 要求同一 `source_snapshot_id`。
- 决策频率低于 physics 频率，避免每帧调用 LLM。
- idle 阶段也调用 G。
- `LLMHistoryMode` 的 none/short/long 行为可区分。
- G 不读取全局状态，不写物理状态。

## 信息泄漏与越权验收

完整 messages、raw response、parsed command、call record 中不得出现：

```text
future_min_distance
offline_ttc
offline_label
future_ttc
planned_start_s
neighbor_task_id
pickup_zone_id for neighbor
dropoff_zone_id for neighbor
api_key
authorization
secret
```

静态 import/name 扫描应确认 G 的实现不导入或调用：

```text
backend.app.sim.physics
backend.app.sim.task_state_machine
backend.app.schemas.control.ControlTarget
backend.app.schemas.state.CraneState
recorder writer
```

## 集成验收

- 构造 3 台塔吊的 Module F observations。
- 同一 snapshot 下并行/批量调用 mock provider。
- 一台 active task、一台 idle、一台带 R1 safety hint。
- 每台生成一个 `OperatorDecisionResult`，结果顺序稳定。
- active task 输出 schema 合法命令，idle 默认 neutral。
- 故意注入一次 invalid raw response 后 retry 成功。
- 故意让某塔连续失败达到阈值，只该塔 result 标记 `llm_failed`，其他塔 session 不受影响。

## 最终退出条件

- Module G 五个测试文件全部通过。
- F 与 secret governance 邻近回归命令通过。
- 至少一次检查序列化 messages 和 `LLMCallRecord`，确认不含 forbidden keys。
- 无默认真实网络依赖；真实 provider 测试必须显式 opt-in。
- 每个实现任务按顺序有独立提交，提交信息格式为 `feat(moduleG): <任务目标>`。

## 测试要点（正常 + 边界 + 异常）

- 正常：schema 构造、prompt 生成、mock provider、parser、retry 成功、多塔 session。
- 边界：idle task、R0/R1、无 neighbors、duration min/max、confidence 0/1、history none/short/long。
- 异常：invalid JSON、Markdown、中文枚举、extra 字段、timeout、API error、replay missing/duplicate、连续失败。
- 防泄漏：prompt、call record、schema 字段、静态 import 和 serialized payload 均不暴露未来真值或 secret。
