# Module G 覆盖总结

## 已验证内容

本轮 Module G 实现覆盖了 `目标.md` 阶段三和阶段四要求的核心路径：

- schema：`RawLLMResponse`、`ParsedCommand`、joystick/axis、`CommandValidationError`、`LLMCallRecord`、`OperatorDecisionResult` 均由 Pydantic 管理，`extra="forbid"`，拒绝 NaN/Inf，并覆盖英文枚举、档位范围、`direction/gear` 一致性和 `neutral_stop`。
- prompt：五种 operator profile prompt、行为参数、system/user/retry prompt、`Observation` JSON 注入、`available_actions` 约束、command schema 注入、duration 范围和 validation error 反馈均有测试。
- provider：mock/replay 本地 provider 已覆盖；DeepSeek/MiniMax 通过 fake HTTP client 验证请求构造、structured output mode、timeout/API error 映射和 runtime secret 不落盘。
- parser：覆盖合法 JSON、空白包裹 JSON、invalid JSON、Markdown、数组、多对象、extra 字段、中文枚举、duration 越界、confidence 越界和权威 metadata 覆盖。
- retry/fallback：覆盖首次成功、invalid 后 retry 成功、timeout 后 retry 成功、retry 耗尽 `neutral_stop`、连续失败 `llm_failed`、未知 provider 异常 fallback。
- orchestrator：覆盖多塔独立 session、batch snapshot 一致性、重复 crane 拒绝、缺 profile 拒绝、单塔失败不影响其他塔、`should_decide()` 频率门控、idle observation 决策和 history mode none/short/long。
- 集成/验收：`test_moduleG_acceptance.py` 覆盖 schema + prompt + mock provider + parser + call record 序列化、多塔批量决策、R1 safety hint、idle neutral、invalid retry、连续失败和边界静态扫描。
- 相邻回归：模块 F observation 与 secret governance 回归命令已通过。
- 全仓回归：`pytest -v` 已通过。

## 未验证或暂不覆盖内容

- 未进行真实 DeepSeek/MiniMax 网络调用。默认测试必须无网络、可复现；真实 provider 只验证请求构造和错误映射，后续可加显式 opt-in 的集成测试。
- 未验证 H/I/J/L 真实链路，因为模块 H/I/J/L 的完整运行时集成不在本次 Module G 任务范围内。当前只验证 G 产出可供 H/L 消费的 `ParsedCommand` 和 `LLMCallRecord`。
- 未写真实 `commands.jsonl` / `command_replay.jsonl`。模块 L 是文件落盘 owner，G 只产出对象。
- 未实现总方案 0.7.9 的 `ExecutedCommand` 严格 replay。当前 replay provider 按 `source_snapshot_id + crane_id` 读取历史 `ParsedCommand`，全链路 replay 留给 J/H/L。
- 未实现 summary LLM。`LLMHistoryMode.LONG` 当前消费 `Observation.memory` 与 session 已发生摘要，不调用额外 LLM。

## 已运行命令

```bash
.venv/bin/python -m pytest backend/app/tests/test_command_schema.py \
  backend/app/tests/test_prompt_builder.py \
  backend/app/tests/test_llm_provider.py \
  backend/app/tests/test_command_parser.py \
  backend/app/tests/test_moduleG_acceptance.py -v
```

结果：48 passed。

```bash
.venv/bin/python -m pytest backend/app/tests/test_observation.py \
  backend/app/tests/test_moduleF_acceptance.py \
  backend/app/tests/test_secret_governance.py -v
```

结果：35 passed。

```bash
.venv/bin/python -m pytest -v
```

结果：458 passed。
