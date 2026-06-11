# 模块 C：塔吊运动学与简化动力学模块任务边界

## 为什么下一个拆模块 C

模块 A 已经提供稳定的 `ResolvedConfig`，模块 B 已经把布局和型号库解析为可仿真的 `CraneConfig[]`。模块 C 是从静态布局进入运行时仿真的第一层，它负责把上一帧塔吊状态和低层控制目标推进到下一帧塔吊状态。

最小链路是：

```text
ResolvedConfig.layout.resolved_cranes
  -> CraneConfig[]
  -> initial CraneState[]
  -> ControlTarget[]
  -> physics step
  -> next CraneState[]
```

模块 C 的边界必须保持窄。它只回答“给定机械约束和控制目标，塔吊这一帧应该处在什么物理状态”，不回答“司机想做什么”“任务是否完成”“风险要不要干预”“数据如何落盘”。

权威来源为项目根目录下的 `群塔LLM仿真系统开发方案_v0.4_完整版.md`。若本文档与总方案冲突，以总方案中 `0.5.2`、`0.6.4`、`0.7.2`、`0.7.3`、`0.7.8`、`0.8.2`、`0.8.4`、`模块 C` 和 `15.2` 的合同约定为准，并同步修订本文档。

## 模块目标

模块 C 负责建立塔吊运行时状态对象和确定性的运动学 step：

- 从 `CraneConfig[]` 初始化单塔或多塔 `CraneState[]`。
- 根据 `ControlTarget` 和 `dt` 更新回转、小车、吊钩高度等运动字段。
- 根据 ENU 坐标系重构 `root`、`tip`、`hook_position` 和起重臂线段。
- 派生 `theta_sin`、`theta_cos`、`cable_length_m`、`load_position` 等字段。
- 执行行程、速度、加速度和数值合法性校验。
- 在无输入或 neutral control 时保持状态稳定或按控制目标平滑减速。
- 对 NaN、Inf 或不可恢复越界输出明确 `PHYS_*` 错误，供调度器映射为 `failed_invalid_state`。

模块 C 不负责生成 `ControlTarget`。`ControlTarget` 属于模块 I，它已经是控制器输出后的连续控制目标。模块 C 也不负责把 LLM、规则司机或 replay 命令转为速度。

## 核心边界

模块 C 的输入：

- `CraneConfig[]`，来自模块 B 的 `resolved.layout.resolved_cranes`。
- 上一帧 `CraneState[]`。
- 当前帧 `ControlTarget[]`，来自模块 I。
- `dt`，来自调度器或实验配置中的 `sim.dt`。
- 只读的数值容差、物理 schema version 和可选的物理运行参数。

模块 C 的输出：

- 下一帧 `CraneState[]`。
- 每台塔吊的 `tip_position`、`hook_position`、`cable_length_m` 等几何派生字段。
- 可选 `PhysicsStepDiagnostic`，用于记录 clamp、限位触发、数值容差等诊断。
- `PHYS_E_001` / `PHYS_E_002` 等物理错误对象或异常，由调度器转换为 episode failure。

模块 C 允许修改：

- `theta_rad`
- `theta_dot_rad_s`
- `theta_ddot_rad_s2`
- `theta_sin`
- `theta_cos`
- `trolley_r_m`
- `trolley_v_m_s`
- `hook_h_m`
- `hoist_v_m_s`
- `hook_position`
- `cable_length_m`
- MVP 中的 `load_position`、`swing_angle_rad`、`swing_velocity_rad_s`、`wind_effect_on_swing` 派生字段

模块 C 不允许修改：

- `CraneConfig` 或型号库。
- `Task.status`。
- 普通任务阶段推进逻辑。
- `load_attached`、`load_weight_t`、`load_type` 等任务挂载权威字段；这些字段只能由任务系统在挂载/卸载完成时修改。模块 C 可以根据这些字段派生 `load_position`。
- `ExecutedCommand`、`ParsedCommand`、`RawLLMResponse`。
- `ControlTarget` 本身。
- `OnlineRisk`、`OfflineRiskLabel`、collision 终止状态。
- `FrameRecord`、`SimFrame`、`trajectories.parquet` 或任何 recorder 文件。

## 与相邻模块的接口

| 相邻模块 | 模块 C 读取什么 | 模块 C 提供什么 | 明确不做什么 |
| --- | --- | --- | --- |
| A 配置与实验管理 | `ResolvedConfig.runtime.sim.dt`、物理频率配置 | 无直接写回 | 不解析原始 YAML，不改 resolved config |
| B 布局与型号库 | `CraneConfig`、内嵌 `CraneModelSpec`、行程与速度限制 | 可用这些静态参数初始化运行时状态 | 不重新校验布局，不生成 `CraneConfig` |
| I 低层控制器 | `ControlTarget` | 下一帧 `CraneState`，供 controller 下帧继续读取 | 不把 joystick/gear 转速度，不做档位映射 |
| J 调度器 | `dt`、调用顺序 | step 后状态或物理错误 | 不推进 episode clock，不决定 terminal status |
| D 任务系统 | 当前挂载字段和任务阶段只作为状态字段保留 | 带几何位置的状态，供任务系统判定 attach/release 条件 | 不推进 `Task.status`，不完成挂载/卸载 |
| H/K 风险 | 无直接依赖 | 当前几何状态，供风险模块计算距离 | 不计算 near miss、collision 或 offline label |
| L recorder | 无直接依赖 | 可序列化的 `CraneState` | 不写 trajectories、frames、summary |
| N 前端 | 无直接依赖 | 间接通过 recorder/API 暴露状态 | 不做展示坐标转换和前端 truth |

## 数据对象边界

### CraneState

`CraneState` 是模块 C 的主要权威对象。建议放在：

```text
backend/app/schemas/state.py
```

最低字段应覆盖总方案中的状态变量：

```text
schema_version: str
crane_id: str

theta_rad: float
theta_dot_rad_s: float
theta_ddot_rad_s2: float
theta_sin: float
theta_cos: float

trolley_r_m: float
trolley_v_m_s: float
hook_h_m: float
hoist_v_m_s: float

root_position: [float, float, float]
tip_position: [float, float, float]
hook_position: [float, float, float]
cable_length_m: float

load_position: optional [float, float, float]
swing_angle_rad: float
swing_velocity_rad_s: float
wind_effect_on_swing: optional object

load_attached: bool
load_type: optional str
load_weight_t: float
load_size_m: optional [float, float, float]

task_id: optional str
task_stage: str
```

说明：

- `hook_h_m` 表示吊钩世界高度 z，不是绳长。
- `cable_length_m = root_z - hook_h_m`。
- `theta_rad` 内部允许连续累积；几何计算使用 `sin(theta_rad)` 和 `cos(theta_rad)`。
- 导出或供 recorder 使用时必须同时提供 `theta_rad`、`theta_sin`、`theta_cos`。
- MVP 不实现真实吊物摆动，`swing_angle_rad=0`、`swing_velocity_rad_s=0`、`wind_effect_on_swing=null`。
- MVP 可配置 `load_position` 为 `null` 或等于 `hook_position`。若选择等于 `hook_position`，必须在文档和测试中固定下来，避免 recorder 与风险模块解释不一致。

### ControlTarget

`ControlTarget` 的 owner 是模块 I，但模块 C 需要定义读取侧合同。建议初版支持以下连续目标字段：

```text
schema_version: str
crane_id: str
target_slew_velocity_rad_s: float
target_trolley_velocity_m_s: float
target_hoist_velocity_m_s: float
emergency_stop: bool
hold_position: bool
source_command_id: optional str
```

读取规则：

- 模块 C 只读取目标速度和停止标志，不读取 LLM reason、task_action 或 operator profile。
- 若某台塔吊本帧没有 `ControlTarget`，调度器或模块 I 应先补 neutral target。模块 C 可以防御性拒绝缺失 target，但不自行查询旧命令。
- `emergency_stop` 的制动曲线由模块 I 或安全层先转成目标速度更清晰；若仍传到模块 C，模块 C 只按物理加速度上限向 0 收敛，不负责锁存策略。

### PhysicsStepDiagnostic

诊断对象不改变物理结果，只帮助测试和 recorder 后续记录：

```text
schema_version: str
crane_id: str
time_s: optional float
clamped_axes: list[str]
limit_reasons: list[str]
numeric_tolerance_used: dict
```

M0 可先不落盘诊断，但 step 函数内部应能返回或抛出足够可测试的信息。

## 坐标与几何约定

模块 C 必须沿用模块 B 的坐标合同：

```text
ENU 右手坐标系
x 向 East / 工地平面向右
y 向 North / 工地平面向前
z 向 Up / 高度向上
theta = 0 指向 +x
theta 正方向为从 +x 朝 +y 逆时针
内部角度使用 rad，配置和展示可使用 deg
```

几何重构：

```text
root = [base_x, base_y, base_z + mast_height_m]
tip = root + jib_length_m * [cos(theta_rad), sin(theta_rad), 0]
hook = [base_x + trolley_r_m * cos(theta_rad),
        base_y + trolley_r_m * sin(theta_rad),
        hook_h_m]
cable_length_m = root_z - hook_h_m
```

注意事项：

- `root_position` 应优先来自 `CraneConfig.root`，初始化时可校验它与 `base + mast_height` 一致。
- `tip_position` 使用 `jib_length_m`，不是 `trolley_r_max_m`。
- `hook_position` 使用当前 `trolley_r_m`。
- `counter_jib` 目前不是 `CraneState` 必填几何字段，风险模块后续如果需要 counter-jib 线段，应单独扩展，不要在 C 初版里扩大范围。

## 状态更新合同

模块 C 应提供纯函数或近似纯函数接口，便于单元测试：

```text
initialize_crane_state(crane_config) -> CraneState
step_crane_state(crane_config, previous_state, control_target, dt) -> CraneState
step_world(crane_configs, previous_states, control_targets, dt) -> CraneState[]
```

推荐初始状态：

```text
theta_rad = crane_config.theta_init_rad
theta_dot_rad_s = 0
theta_ddot_rad_s2 = 0
trolley_r_m = crane_config.trolley_r_min_m
trolley_v_m_s = 0
hook_h_m = crane_config.hook_h_max_world_m
hoist_v_m_s = 0
load_attached = false
load_weight_t = 0
task_id = null
task_stage = "idle"
```

如果后续希望从配置指定初始小车半径或吊钩高度，应由模块 A/B 先扩展 resolved config 合同，再由 C 读取。C 不直接读取 YAML 输入。

MVP 更新规则：

```text
theta_dot_next = approach(
  current=theta_dot_rad_s,
  target=target_slew_velocity_rad_s,
  max_delta=crane_config.model.slew_acc_max_rad_s2 * dt
)
theta_dot_next = clip(theta_dot_next, -slew_speed_max_rad_s, slew_speed_max_rad_s)
theta_next = theta_rad + theta_dot_next * dt

trolley_v_next = clip(target_trolley_velocity_m_s, -trolley_speed_max_m_s, trolley_speed_max_m_s)
trolley_r_next = clip(trolley_r_m + trolley_v_next * dt, trolley_r_min_m, trolley_r_max_m)

hoist_v_next = clip(target_hoist_velocity_m_s, -hoist_speed_max_m_s, hoist_speed_max_m_s)
hook_h_next = clip(hook_h_m + hoist_v_next * dt, hook_h_min_world_m, hook_h_max_world_m)
```

为了使 neutral_stop 平滑，建议小车和起升也采用 `approach(current_velocity, target_velocity, axis_acc_limit * dt)`。如果型号库暂时没有小车/起升加速度字段，M0 可以先按目标速度直接限速，但文档和测试必须明确这是 M0 简化，并为后续字段扩展预留。

limited slew：

- M0 已由模块 B 拦截缺少 `theta_limit_deg` 的 limited 模式，因此 C M0 可以只支持 `slew_mode="continuous"`。
- 后续支持 limited 时，`theta_rad` 必须被限制在 `theta_limit_rad` 内，触及限位时对应角速度归零，并产生 limit diagnostic。

## 数值安全与失败边界

模块 C 的失败边界是 episode 级 invalid state，不是 startup error。

必须检测：

- 任意状态字段出现 NaN 或 Inf。
- `dt <= 0`。
- `trolley_r_m` 不在 `[trolley_r_min_m, trolley_r_max_m]` 且无法通过 clamp 恢复。
- `hook_h_m` 不在 `[hook_h_min_world_m, hook_h_max_world_m]` 且无法通过 clamp 恢复。
- `hook_h_m > root_z`。
- `cable_length_m < cable_length_min_m - tolerance` 或 `cable_length_m > cable_length_max_m + tolerance`。
- `theta_sin/theta_cos` 与 `theta_rad` 明显不一致。
- 物理一步产生超过配置阈值的异常跳变。

错误映射：

| 错误 | 触发条件 | 默认处理 |
| --- | --- | --- |
| `PHYS_E_001` | NaN/Inf | `episode_failed`，`episode_status=failed_invalid_state` |
| `PHYS_E_002` | state jump 超阈值或不可恢复越界 | `episode_failed` 或 data quality failed，按配置 |
| `PHYS_D_001` | 速度或位置被机械限位 clamp | diagnostic，episode 继续 |

注意：

- 行程限位内的普通 clamp 不是失败，应继续运行并可输出 diagnostic。
- 多塔几何碰撞不是模块 C 的职责。C 提供当前几何，模块 H 或风险/碰撞层判断 collision。
- 力矩/载重限制的硬执行更适合模块 H/I 在命令和控制目标层完成；C 可在状态自检中发现不一致，但不应实现完整任务载重策略。

## 推荐代码位置

```text
backend/app/schemas/state.py
backend/app/schemas/control.py
backend/app/sim/physics.py
backend/app/sim/geometry.py
backend/app/tests/test_crane_state.py
backend/app/tests/test_physics_step.py
backend/app/tests/test_moduleC_acceptance.py
```

说明：

- 如果已有 `backend/app/sim/layout_geometry.py` 足够通用，可以复用其中的距离函数，但 C 的运行时几何重构建议放在独立 `physics.py` 或 `geometry.py` 中。
- `schemas/control.py` 是为了给模块 I/C 的接口留出清晰边界；如果后续模块 I 文档另有命名，以模块 I 文档为准，但对象 owner 仍归 I。
- 不建议把 `CraneState` 放进 `schemas/crane.py`，因为 `schemas/crane.py` 当前属于模块 B 的静态型号和布局对象。

## 子任务划分

### Task 01：CraneState schema 与初始化

目标：建立模块 C 的权威运行时状态对象，并从 `CraneConfig` 初始化单塔/多塔状态。

实现范围：

- 新增 `CraneState` Pydantic schema。
- 定义 `physics_schema_version` 或 `schema_version`。
- 实现 `initialize_crane_state(crane_config)`。
- 实现 `initialize_world_state(crane_configs)`。
- 初始化 `root_position`、`tip_position`、`hook_position`、`theta_sin`、`theta_cos` 和 `cable_length_m`。
- 默认 `task_stage="idle"`、`load_attached=false`、`load_weight_t=0`。
- 支持任意 N 台塔吊，不硬编码 C1/C2/C3。

不实现：

- 物理 step。
- controller。
- task activate / attach / release。
- recorder 文件写入。

验收点：

- `CraneState` 只读取 `CraneConfig`，不读取原始 YAML。
- `theta_init_rad` 初始化正确。
- `hook_h_m` 默认不超过 `hook_h_max_world_m`。
- `cable_length_m = root_z - hook_h_m`。
- 多塔初始化保持输入顺序或按明确规则排序，并在测试中固定。

### Task 02：运行时几何重构

目标：把 `CraneState + CraneConfig` 稳定转换为起重臂、吊钩和派生几何字段。

实现范围：

- 实现 `compute_tip_position(crane_config, theta_rad)`。
- 实现 `compute_hook_position(crane_config, theta_rad, trolley_r_m, hook_h_m)`。
- 实现 `recompute_state_geometry(crane_config, state)`。
- 始终刷新 `theta_sin`、`theta_cos`、`tip_position`、`hook_position`、`cable_length_m`。
- MVP 中定义 `load_position` 规则：推荐 `load_attached=true` 时等于 `hook_position`，否则为 `null`。

不实现：

- 多塔距离、near miss、collision。
- front-end display 坐标。
- offline graph edge 特征。

验收点：

- `theta=0` 时 tip 和 hook 位于 +x 方向。
- `theta=pi/2` 时 tip 和 hook 位于 +y 方向。
- 几何误差小于 `1e-6`。
- `hook_h_m` 被解释为世界 z，而不是绳长。

### Task 03：单塔运动学 step

目标：实现一台塔吊在一个 `dt` 内的确定性运动学积分。

实现范围：

- 新增或接收读取侧 `ControlTarget` schema。
- 实现 `step_crane_state(crane_config, previous_state, control_target, dt)`。
- 回转速度受 `slew_speed_max_rad_s` 限制。
- 回转加速度受 `slew_acc_max_rad_s2` 限制。
- 小车半径受 `trolley_r_min_m/trolley_r_max_m` 限制。
- 小车速度受 `trolley_speed_max_m_s` 限制。
- 吊钩高度受 `hook_h_min_world_m/hook_h_max_world_m` 限制。
- 起升速度受 `hoist_speed_max_m_s` 限制。
- step 后调用几何重构。

不实现：

- joystick gear 到速度的映射。
- command expiry。
- emergency_stop latch。
- moment limit event。

验收点：

- neutral target 下状态保持稳定或速度按约定收敛到 0。
- 目标速度超过上限时被限幅。
- 小车和吊钩触及边界时位置不越界。
- 回转角可以连续累积，不强制 wrap 到 `[0, 2pi)`。
- 20 Hz (`dt=0.05`) 下连续 600 秒不会出现 NaN/Inf。

### Task 04：多塔 world step 与批量接口

目标：为调度器提供一次推进所有塔吊状态的清晰接口。

实现范围：

- 实现 `step_world(crane_configs, previous_states, control_targets, dt)`。
- 按 `crane_id` 对齐 `CraneConfig`、`CraneState` 和 `ControlTarget`。
- 对缺失、重复或未知 `crane_id` 给出明确错误。
- 保证 step 内不读取或修改其他塔吊的状态，除非后续显式扩展摆动/碰撞模型。
- 返回下一帧状态列表和可选 diagnostics。

不实现：

- 多塔避碰。
- 风险干预。
- task scheduling。
- recorder。

验收点：

- 2-6 台塔吊可同时 step。
- 输入顺序变化时，只要 `crane_id` 对齐，结果一致或输出顺序有明确约定。
- 某一台物理失败时，返回可定位到 `crane_id` 的错误。

### Task 05：状态校验、错误对象与失败映射

目标：建立 C 模块自己的数值校验和 `PHYS_*` 错误体系。

实现范围：

- 实现 `validate_crane_state(crane_config, state)`。
- 实现 `PhysicsStateError` 或等价错误对象。
- 把 NaN/Inf 映射为 `PHYS_E_001`。
- 把不可恢复越界或异常跳变映射为 `PHYS_E_002`。
- 普通 clamp 返回 diagnostic，不抛 episode failure。
- 错误 details 至少包含 `crane_id`、`field_path`、`value`、`limit` 或 `reason`。

不实现：

- 调度器里的 episode status 写入。
- recorder events 写入。
- risk collision error。

验收点：

- 错误可被调度器捕获并转换为 `failed_invalid_state`。
- 错误信息稳定、可测试。
- 物理错误不会被误报为 `CFG_*`、`LAY_*` 或 `TASK_*`。

### Task 06：与调度器、controller、recorder 的最小接口预留

目标：让模块 C 能嵌入 M0 的最小 episode 链路，但不实现相邻模块业务。

实现范围：

- 定义 C 对模块 I 的读取接口：只消费 `ControlTarget`。
- 定义 C 对模块 J 的调用接口：`state_t -> state_t+dt`。
- 定义 C 对模块 L 的输出接口：`CraneState` 可序列化为 trajectories/visual frames 所需字段。
- 明确 `frame=0,time_s=0` 是初始状态，循环内记录 step 后状态的约定。
- 保留 `physics_schema_version` 以供 replay hash 和 artifact 校验使用。

不实现：

- `scripts/run_episode.py` 的完整调度。
- Parquet/JSONL 文件写入。
- visual frame schema。
- replay。

验收点：

- `CraneState` 字段能覆盖 `trajectories.parquet` 中与物理有关的列。
- `CraneState` 中不包含 LLM raw response、risk label 或 recorder-only 字段。
- C 的公开函数不依赖 FastAPI、前端或真实 LLM。

### Task 07：模块 C 测试与验收

目标：建立 C 模块可执行的单元测试、合同测试、稳定性测试和文档验收。

建议测试文件：

```text
backend/app/tests/test_crane_state.py
backend/app/tests/test_physics_geometry.py
backend/app/tests/test_physics_step.py
backend/app/tests/test_physics_errors.py
backend/app/tests/test_moduleC_acceptance.py
```

必测场景：

- valid `CraneConfig` 初始化为 `CraneState`。
- `theta_init_rad`、`theta_sin`、`theta_cos` 一致。
- `root_position`、`tip_position`、`hook_position` 符合公式。
- `hook_h_m` 是世界高度 z。
- neutral target 不产生位置漂移。
- slew target 受速度和加速度限制。
- trolley target 受速度和半径边界限制。
- hoist target 受速度和高度边界限制。
- `dt <= 0` 失败。
- NaN/Inf 失败为 `PHYS_E_001`。
- 不可恢复越界或异常跳变失败为 `PHYS_E_002`。
- 20 Hz 下 600 秒稳定运行。
- 2-6 台塔吊同时 step，且不硬编码 crane ID。
- 模块 C 实现不导入 LLM、risk、task、recorder、FastAPI 或前端模块。

推荐命令：

```bash
pytest backend/app/tests/test_crane_state.py -v
pytest backend/app/tests/test_physics_geometry.py -v
pytest backend/app/tests/test_physics_step.py -v
pytest backend/app/tests/test_physics_errors.py -v
pytest backend/app/tests/test_moduleC_acceptance.py -v
```

完整回归：

```bash
pytest backend/app/tests -v
```

## 分阶段边界

模块 C 属于 M0 的核心交付，但可以按风险切小：

- M0a：Task 01-02，完成 `CraneState` 初始化和几何重构。
- M0b：Task 03，完成单塔运动学 step。
- M0c：Task 04-05，完成多塔批量 step 和物理错误体系。
- M0d：Task 06-07，接入 M0 最小调度链路并完成验收测试。

不建议把模块 D/H/I/L 的实现塞进模块 C。M0 的完整运行链路需要 I/J/L，但 C 的完成标准只看物理状态是否能被稳定推进和序列化。

## 模块 C 退出条件

模块 C 可进入模块 I/J/L 集成的条件：

- 可以从 `resolved.layout.resolved_cranes` 初始化 N 台 `CraneState`。
- 单塔和多塔 step 在 `dt=0.05` 下稳定运行。
- 无控制输入或 neutral target 下不会产生无原因漂移。
- 回转、小车、起升均执行速度/加速度/行程/高度限制。
- `tip_position` 和 `hook_position` 与公式一致，误差小于 `1e-6`。
- `hook_h_m` 与 `cable_length_m` 语义清晰且测试覆盖。
- NaN/Inf 与不可恢复越界能输出稳定 `PHYS_*` 错误。
- 不硬编码塔吊数量或 crane ID。
- 不导入或调用 LLM、task、risk、recorder、API、frontend 运行时逻辑。
- 所有模块 C 测试通过，并且模块 A/B 回归测试仍通过。

## 文档验收命令

文档创建完成后运行：

```bash
find docs/moduleC -maxdepth 1 -name "*.md" -print | sort
```

期望至少看到：

```text
docs/moduleC/README.md
```

检查无未完成标记：

```bash
python3 - <<'PY'
from pathlib import Path

patterns = [
    "TB" + "D",
    "TO" + "DO",
    "implement " + "later",
    "fill in " + "details",
    "<un" + "finished",
]
for path in sorted(Path("docs/moduleC").glob("*.md")):
    text = path.read_text(encoding="utf-8")
    for lineno, line in enumerate(text.splitlines(), start=1):
        if any(pattern in line for pattern in patterns):
            print(f"{path}:{lineno}:{line}")
PY
```

期望无输出。

检查关键合同字段：

```bash
rg -n "CraneState|ControlTarget|PHYS_E_001|PHYS_E_002|failed_invalid_state|hook_h_m|cable_length_m|theta_sin|theta_cos|tip_position|hook_position|step_crane_state|step_world" docs/moduleC
```

期望能检索到模块 C 的关键对象、错误码、物理字段和 step 接口。
