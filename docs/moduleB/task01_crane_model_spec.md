# Task 01：CraneModelSpec 与型号库

## 任务目标

建立模块 B 的塔吊型号参数权威对象 `CraneModelSpec`，并实现内置通用型号库、YAML 覆盖/新增型号、半径相关载重曲线和力矩限制计算。

本任务完成后，模块 C/I/H 可以只依赖 `CraneModelSpec` 读取机械参数，不再直接读取 `ScenarioConfig.crane_models`。

权威来源：`群塔LLM仿真系统开发方案_v0.4_完整版.md` 中 `0.5.3`、`0.5.13`、`0.7.2`、`模块 B`、`15.2` 和 `15.8 ISSUE-002`。

## 任务范围

本任务实现：

- `CraneModelSpec` Pydantic schema。
- 内置通用塔吊型号库。
- YAML 型号覆盖和新增。
- 型号参数静态校验。
- `capacity_at_radius_t(r)`。
- `is_load_allowed(load_weight_t, trolley_r_m)`。
- `moment_at_radius_t_m(load_weight_t, trolley_r_m)`。
- `CraneConfig` 计算吊钩世界高度边界所需的 cable length、行程和高度范围字段。

本任务不实现：

- manual crane 布局校验。
- auto layout 采样。
- `CraneConfig` 最终实例化。
- `CraneState` 初始化或物理积分。
- controller 档位映射。
- task pickup/dropoff 可达性。

这些由 Task 02、Task 03、Task 04、Task 05、模块 C 和模块 I 实现。

## 建议代码位置

```text
backend/app/sim/crane_model.py
backend/app/tests/test_crane_model.py
```

若后续希望 schema 与 sim 分离，也可以拆为：

```text
backend/app/schemas/crane.py
backend/app/sim/crane_model.py
```

但 `CraneModelSpec` 的权威定义必须只有一处，避免 schema 与运行对象字段漂移。

## 数据结构

`CraneModelSpec` 至少包含：

```text
schema_version: str
model_id: str
jib_length_m: float
counter_jib_length_m: float
mast_height_range_m: [float, float]
max_load_t: float
max_load_radius_m: float
tip_load_t: float
rated_moment_t_m: float
slew_speed_max_rad_s: float
slew_acc_max_rad_s2: float
trolley_r_min_m: float
trolley_r_max_m: float
trolley_speed_max_m_s: float
cable_length_min_m: float
cable_length_max_m: float
hoist_speed_max_m_s: float
min_clearance_below_jib_m: float
load_chart_points: optional list[{radius_m, capacity_t}]
source: "builtin" | "yaml_override" | "yaml_new"
```

说明：

- YAML 中已有 `slew_speed_max_deg_s` 和 `slew_acc_max_deg_s2`，最终 `CraneModelSpec` 内部应保存 rad 单位字段。
- `hook_h_min_world_m` 和 `hook_h_max_world_m` 依赖具体 `base_z` 与 `mast_height_m`，不属于 `CraneModelSpec` 的权威字段，必须由 Task 03 的 `CraneConfig` 保存。
- 如果 `load_chart_points` 缺失，使用 MVP 默认线性规则。

## 内置型号库

至少提供：

```text
generic_flat_top_55m
```

默认参数应与当前 `backend/app/tests/fixtures/configs/scenario_valid.yaml` 的字段兼容：

```yaml
model_id: "generic_flat_top_55m"
jib_length_m: 55
counter_jib_length_m: 15
mast_height_range_m: [40, 65]
max_load_t: 6
max_load_radius_m: 15
tip_load_t: 1.5
rated_moment_t_m: 90
slew_speed_max_deg_s: 0.8
slew_acc_max_deg_s2: 0.3
trolley_r_min_m: 5
trolley_r_max_m: 50
trolley_speed_max_m_s: 0.5
cable_length_min_m: 2
cable_length_max_m: 60
hoist_speed_max_m_s: 0.6
min_clearance_below_jib_m: 2
```

## YAML 覆盖规则

输入：

- 内置型号库。
- `ScenarioConfig.crane_models` 中的 `CraneModelConfigInput[]`。

合并规则：

- 如果 YAML `model_id` 与内置库相同，YAML 完整覆盖该型号，并标记 `source="yaml_override"`。
- 如果 YAML `model_id` 不存在于内置库，新增型号，并标记 `source="yaml_new"`。
- 没有被 YAML 覆盖的内置型号保留，标记 `source="builtin"`。
- 同一个 YAML 文件中重复 `model_id` 必须报错，不能静默后者覆盖前者。

## 载重与力矩规则

MVP 默认 `capacity_at_radius_t(r)`：

```text
if r <= max_load_radius_m:
  chart_capacity_t = max_load_t
else:
  chart_capacity_t = linear_interpolate(
    r,
    [max_load_radius_m, jib_length_m],
    [max_load_t, tip_load_t]
  )

moment_capacity_t = rated_moment_t_m / max(r, trolley_r_min_m)
capacity_at_radius_t = min(chart_capacity_t, moment_capacity_t)
```

边界：

- `r < trolley_r_min_m` 时，用 `trolley_r_min_m` 参与力矩分母，避免除零；是否允许小车实际到该半径由模块 C/I 的行程限制执行。
- `r > jib_length_m` 时 `capacity_at_radius_t` 可以返回 0 或抛出明确错误；建议返回 0 并让调用者将其判定为不可达/不可承载。
- 如果提供 `load_chart_points`，优先使用点表分段线性插值，再与 `rated_moment_t_m / max(r, trolley_r_min_m)` 取更严格限制。

## 输入与输出

输入：

- `ScenarioConfig.crane_models`
- 内置型号库定义

输出：

- `dict[str, CraneModelSpec]`
- 载重能力函数
- 型号库诊断信息

失败输出：

- 重复 `model_id`。
- 型号参数非法。
- `max_load_radius_m > jib_length_m`。
- `trolley_r_max_m > jib_length_m`。
- `tip_load_t > max_load_t`。
- `mast_height_range_m` 非法。
- `load_chart_points` 半径不递增或容量非正。

失败应转换为 `LAY_E_003` startup error，`details.reason="invalid_crane_model"`，并包含具体 `model_id` 与失败约束。

不得把型号库或 `CraneModelSpec` 语义错误映射为 `LAY_E_002`；`LAY_E_002` 只用于 manual crane 布局校验失败。

## 测试要求

建议测试文件：

```text
backend/app/tests/test_crane_model.py
```

必测场景：

- `generic_flat_top_55m` 内置型号存在。
- YAML 覆盖同名型号后使用 YAML 参数。
- YAML 新增型号后可通过 `model_id` 读取。
- YAML 内重复 `model_id` 报错。
- `slew_speed_max_deg_s` 正确转换为 rad/s。
- `slew_acc_max_deg_s2` 正确转换为 rad/s²。
- `capacity_at_radius_t(10)` 返回 `min(max_load_t, rated_moment_t_m / 10)`。
- `capacity_at_radius_t(max_load_radius_m)` 等于该半径下 chart 与 moment 的较小值。
- `capacity_at_radius_t(jib_length_m)` 不超过 `tip_load_t`。
- `capacity_at_radius_t(r > jib_length_m)` 返回不可承载结果。
- `is_load_allowed(2.0, 20.0)` 与 `capacity_at_radius_t(20.0)` 一致。
- `moment_at_radius_t_m(3.0, 25.0) == 75.0`。
- `trolley_r_max_m > jib_length_m` 报错。
- `tip_load_t > max_load_t` 报错。
- 型号库合并或型号语义错误映射为 `LAY_E_003`，且不复用 `LAY_E_002`。

推荐命令：

```bash
pytest backend/app/tests/test_crane_model.py -v
```

## 验收标准

- 后续模块不需要直接读取 `CraneModelConfigInput` 就能获得完整机械参数。
- 所有内部角速度、角加速度字段统一为 rad 单位。
- 载重曲线和 rated moment 同时生效。
- 型号库合并确定性稳定。
- 错误信息能指出具体 `model_id` 和失败约束。
- 不硬编码单一塔吊型号；至少支持内置型号 + YAML 覆盖 + YAML 新增。
