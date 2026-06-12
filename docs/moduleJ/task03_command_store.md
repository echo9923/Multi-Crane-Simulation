# Task 03：CommandStore

## 任务目标

实现 `CommandStore`，维护每台塔吊当前生效的 `ExecutedCommand`，支持同一 decision time 批量替换、命令过期检查和系统 `neutral_stop` 注入。

## 范围：做什么 / 不做什么

做：

- 在 `backend/app/sim/scheduler.py` 中实现 `CommandStore`。
- 初始化每台塔吊的 startup neutral_stop。
- 实现 `replace_current_commands(executed_commands, sim_time)` 批量替换。
- 实现 `expire_or_neutral_stop(sim_time)`。
- 实现 `get_current_commands()`。
- 实现 replay 模式按历史 `ExecutedCommand` 替换当前命令的入口。
- 记录命令来源：decision、replay、expired_neutral_stop、llm_timeout_neutral_stop、startup_neutral_stop。
- 保证同一 decision time 的多塔命令收齐后同时应用，不能逐塔边生成边生效。

不做：

- 不解析 `ParsedCommand`。
- 不调用 safety pipeline。
- 不判断 LLM 是否超时。
- 不把 joystick/gear 转成 `ControlTarget`。
- 不修改 `CraneState`。
- 不写 command replay 文件。
- 不实现 replay 文件读取器的具体 I/O，除非 Task 05 需要最小接口。

## 接口与数据结构（签名级别）

```python
class CommandStore:
    def __init__(
        self,
        *,
        crane_ids: Sequence[str],
        default_operator_ids: Mapping[str, str] | None = None,
        default_command_duration_s: float = 1.0,
    ) -> None:
        ...

    @classmethod
    def with_startup_neutral(
        cls,
        *,
        crane_ids: Sequence[str],
        time_s: float = 0.0,
        default_operator_ids: Mapping[str, str] | None = None,
        command_duration_s: float = 1.0,
    ) -> "CommandStore":
        ...

    def replace_current_commands(
        self,
        executed_commands: Sequence[ExecutedCommand],
        *,
        sim_time: float,
        source: Literal["decision", "replay"] = "decision",
    ) -> CommandStoreSnapshot:
        ...

    def expire_or_neutral_stop(
        self,
        *,
        sim_time: float,
        command_duration_s: float | None = None,
    ) -> tuple[dict[str, ExecutedCommand], list[dict[str, Any]]]:
        ...

    def get_current_commands(self) -> dict[str, ExecutedCommand]:
        ...

    def snapshot(self, *, time_s: float) -> CommandStoreSnapshot:
        ...
```

neutral stop 构造建议：

```python
def build_system_neutral_executed_command(
    *,
    crane_id: str,
    operator_id: str,
    time_s: float,
    source_snapshot_id: str,
    observation_id: str,
    reason: str,
    command_duration_s: float = 1.0,
) -> ExecutedCommand:
    ...
```

实现可复用 `backend/app/schemas/command.py::build_neutral_stop_command()` 生成 `ParsedCommand`，再用 `ExecutedCommand.from_raw()` 包装，确保 schema 一致。

过期规则：

```text
expires_at_s = command.time_s + command.command_duration_s
if sim_time >= expires_at_s:
  replace this crane's command with system neutral_stop at sim_time
```

边界应在测试中固化：`sim_time == expires_at_s` 视为过期。

批量替换规则：

- `executed_commands` 必须 crane id 唯一。
- 每个 command 的 `time_s` 应与 decision time 一致，或在容差内等于 `sim_time`。
- 替换在校验全部通过后一次性提交；若任何 command 非法，store 保持原状。
- 可以只替换 due cranes；未 due cranes 保持旧命令，然后由 `expire_or_neutral_stop()` 检查是否过期。

## 前置依赖

- Task 01 scheduler schema 中的 `StoredCommand`、`CommandStoreSnapshot`。
- `ExecutedCommand`、`ParsedCommand`、`build_neutral_stop_command()`。
- G/H 已定义 neutral_stop 语义。

## 验收标准（具体、可测试）

- 初始化时每台塔吊都有 startup neutral_stop。
- `get_current_commands()` 返回每台塔吊一个 `ExecutedCommand`。
- `replace_current_commands()` 可一次替换 C1/C2 两台命令，替换后两台命令都更新。
- 批量替换遇到重复 crane id 时抛 `SchedulerError`，原 store 不改变。
- 批量替换遇到未知 crane id 时抛 `SchedulerError`，原 store 不改变。
- `expire_or_neutral_stop(sim_time < expires_at_s)` 不替换命令。
- `expire_or_neutral_stop(sim_time == expires_at_s)` 注入 neutral_stop。
- 过期 neutral_stop 的 `time_s == sim_time`，`command_duration_s` 使用配置默认值或传入值。
- 过期 neutral_stop 的所有轴为 neutral/gear 0，`deadman_pressed=True`，`emergency_stop=False`，`task_action="none"`。
- replay source 的命令可进入 store，但不会调用 G/H。
- `snapshot()` 可 JSON 序列化并包含每条命令来源与过期时间。

## 测试要点（正常 + 边界 + 异常）

- 正常：两塔 startup neutral，C1 到期、C2 未到期，只替换 C1。
- 正常：due cranes C1/C2 同批替换后，controller 获取同一批新命令。
- 边界：只替换 C1，C2 旧命令保留，随后 C2 过期 neutral。
- 边界：`command_duration_s=0` 的 H/replay 命令立即过期并 neutral。
- 异常：命令 crane id 不在 store 初始化 crane_ids 内。
- 异常：`sim_time` 为 NaN/Inf。
- 原子性：批量中一条非法时，所有旧命令保持不变。
