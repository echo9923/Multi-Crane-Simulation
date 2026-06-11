# Task 03：Forbidden Zone Policy

## 任务目标

实现禁区策略层，根据 `ScenarioConfig.site.forbidden_zones` 和 `forbidden_zone_policy` 判断命令是否会让吊钩或载荷进入禁区，并按 `task_only` 或 `hard` 策略记录或阻止动作。

## 范围：做什么 / 不做什么

做：

- 在 `backend/app/sim/safety.py` 或拆分出的 `backend/app/sim/forbidden_zone.py` 中实现禁区策略。
- 支持 `ZoneConfig` 的盒形禁区：`center + size + z_range_m`。
- 支持 `ZoneConfig` 的多边形禁区：`points + z_range_m`，水平面使用点在多边形内判断。
- 根据当前状态和已通过机械安全层的命令，短时外推下一步 hook/load 位置。
- `ForbiddenZonePolicyMode.TASK_ONLY`：记录 `forbidden_zone_violation`，不修改命令。
- `ForbiddenZonePolicyMode.HARD`：阻止会进入禁区的危险动作，记录 `forbidden_zone_blocked`。
- `record_violation=False` 时不生成 violation event，但仍返回 `ForbiddenZoneResult`。

不做：

- 不验证任务 pickup/dropoff zone 合法性。
- 不修改 `ScenarioConfig` 或禁区定义。
- 不做路径规划绕行。
- 不做多帧未来预测。
- 不推进物理状态。
- 不替代碰撞检测。

## 接口与数据结构（签名级别）

```python
def apply_forbidden_zone_policy(
    *,
    command: ExecutedCommand,
    state: CraneState,
    config: CraneConfig,
    forbidden_zones: list[ZoneConfig],
    policy: ForbiddenZonePolicyConfig,
    dt_s: float,
) -> tuple[ExecutedCommand, ForbiddenZoneResult]:
    ...

def predict_next_hook_position(
    *,
    command: ExecutedCommand,
    state: CraneState,
    config: CraneConfig,
    dt_s: float,
) -> list[float]:
    ...

def point_in_forbidden_zone(
    *,
    point: list[float],
    zone: ZoneConfig,
) -> bool:
    ...

def movement_enters_forbidden_zone(
    *,
    current_point: list[float],
    next_point: list[float],
    zones: list[ZoneConfig],
) -> list[str]:
    ...
```

MVP 判断目标点和线段采样点即可，采样步长应写成常量并在测试中覆盖。后续可替换为更精确的几何库，但 Task 03 不引入重型依赖。

## 前置依赖

- Task 01 的 `ForbiddenZoneResult`。
- Task 02 输出的 mechanically safe `ExecutedCommand`。
- `ScenarioConfig.site.forbidden_zones` 和 `ForbiddenZonePolicyConfig`。
- `CraneState.hook_position`、`load_position`。

## 验收标准（具体、可测试）

- 无禁区时返回 `violation_detected=False`，不修改命令。
- hook 当前不在禁区、下一步会进入禁区时能识别 violation。
- `load_position` 存在时优先检查 load；不存在时检查 hook。
- `task_only` 模式只记录 violation，不修改 executed command。
- `hard` 模式阻止进入禁区的动作，返回 `blocked=True` 且 `modified=True`。
- `record_violation=False` 时不生成 event，但 `ForbiddenZoneResult.violation_detected=True`。
- 盒形禁区支持 `center/size/z_range_m` 判断。
- 多边形禁区支持 `points/z_range_m` 判断。
- z 不在 `z_range_m` 内时不判定为进入该禁区。
- 禁区策略修改不记录 `intervention_applied`，只记录 forbidden zone event。

## 测试要点（正常 + 边界 + 异常）

- 正常：命令进入盒形禁区；命令进入多边形禁区；禁区外移动。
- 边界：点在边界线上；z 正好等于 z_range 上下界；`load_position=None`。
- 异常：不支持的 zone 类型、缺失几何字段、command/state/config crane_id 不一致。
- 合同：S0/S1/S2/S3 下 hard forbidden zone 都可阻止危险动作。
