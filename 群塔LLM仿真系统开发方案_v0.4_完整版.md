# 群塔 LLM-in-the-loop 仿真系统开发

> 版本：v0.4（实施合同完整版，2026-06-10）  
> 项目定位：为“基于物理先验时空动态图的群塔起重臂轨迹预测与碰撞风险预警研究”生成合理、可控、可标注的仿真数据。  




---

## 0. 给 AI 的总角色设定

你是一名同时具备以下能力的高级工程师：

1. 机器人/工程机械仿真架构师；
2. Python 后端与数据工程师；
3. Web 3D 可视化工程师；
4. 多智能体仿真与 LLM Agent 工程师；
5. 时空图轨迹预测研究辅助工程师。

你需要为“群塔起重臂轨迹预测与碰撞风险预警研究”设计并实现一个可复现、可批量运行、可导出训练数据、可进行 3D 展示的仿真系统。系统必须支持多个塔吊、任务驱动的取货/卸货流程、天气与可见度扰动、LLM 操作员决策、基础塔吊安全设施、风险影子评估、轨迹与风险标签导出，并能通过前端 3D 页面展示仿真过程。

请严格遵循本 prompt 中的模块划分、接口定义、数据格式和验收标准。不要把系统做成仅能演示的动画；必须优先保证数据生成、复现性、接口稳定性和实验可用性。

---

## 0.5 已确认设计决策

以下决策是当前版本已经确认的系统边界。后续实现、验收和模块拆分必须以本节为准；如果后文旧示例与本节冲突，以本节为准并同步更新后文。

### 0.5.1 系统主线

系统核心不是为了强行编排危险轨迹，而是构建：

```text
真实可靠的塔吊物理/任务仿真平台
        +
受限手柄式 LLM 塔吊司机
        +
全过程轨迹、风险、操作、事件数据记录
```

风险样本应主要来自 LLM 司机在完成真实任务过程中的自然操作结果。系统负责执行机械约束、记录轨迹、计算风险、生成标签和可视化回放，不应通过违反机械极限或人为穿模来制造风险。

### 0.5.2 MVP 物理真实度

MVP 采用“参数化塔吊运动学 + 真实机械约束”作为主物理引擎：

- 回转角、回转速度、角加速度受限；
- 小车幅度、小车速度、小车行程受限；
- 吊钩高度、起升速度、高度范围受限；
- 载重、力矩、机械限位必须硬执行；
- LLM 只能输出受限操作命令，不能直接修改物理状态；
- 仿真必须稳定、可复现、可批量运行。

MVP 暂不实现真实吊物摆动、绳索动力学、风载动力学和结构弹性，但必须预留字段与接口：

```text
load_attached
load_weight_t
hook_position          # [x, y, z]，吊钩世界坐标
load_position          # MVP 无摆动时可等于 hook_position 或为 null，后续用于吊物质心
cable_length_m          # root_z - hook_h_m
swing_angle_rad         # MVP 默认为 0
swing_velocity_rad_s    # MVP 默认为 0
wind_effect_on_swing    # MVP 可为 null，后续扩展
```

后续加入简化吊物摆动时，不得推翻任务系统、数据格式、前端回放和风险模块接口。

### 0.5.3 塔吊布局与塔吊型号

系统必须同时支持：

```text
layout.mode = "auto"   自动生成塔吊布局，默认模式
layout.mode = "manual" YAML 手写塔吊布局，用于复现和指定 demo
```

自动布局生成不是简单随机撒点，而应作为正式模块实现：

```text
候选布局生成
  -> 几何约束过滤
  -> 禁区/边界检查
  -> 作业半径重叠分析
  -> 高度错层/混合高度检查
  -> 任务可达性检查
  -> 布局质量评分
  -> 选择满足目标的布局
```

默认高度策略：

```text
height_strategy = "mixed"
```

含义：

- 部分塔吊保持合理高度错层；
- 部分重叠塔吊允许高度接近；
- easy/普通任务倾向错层；
- stress/压力任务允许较小高度差；
- 所有高度仍必须满足塔吊参数、工地边界和安全约束。

自动布局生成器必须支持三个高层布局目标：

```yaml
layout:
  overlap_level: "medium"      # low / medium / high
  height_strategy: "mixed"     # staggered / same_level / mixed
  coverage_target: "balanced"  # balanced / wide_coverage / dense_overlap
```

含义：

```text
overlap_level:
  控制作业半径重叠程度。
  low = 少量重叠；
  medium = 有明显重叠但不过分拥挤；
  high = 重叠明显，更容易产生高风险。

height_strategy:
  控制塔吊高度关系。
  staggered = 尽量错层；
  same_level = 允许同层或近似同层；
  mixed = 部分错层、部分接近，默认。

coverage_target:
  控制整体布局风格。
  balanced = 覆盖和重叠平衡，默认；
  wide_coverage = 覆盖更大工地区域；
  dense_overlap = 更集中，交互更多。
```

塔吊参数采用：

```text
内置通用塔吊型号库 + YAML 覆盖/新增真实型号
```

内置型号参数应符合常见平臂塔吊工程常识，但不强制绑定具体厂家。用户获得真实塔吊参数后，可以在配置中覆盖型号库，系统必须把最终采用的型号和参数落盘以保证复现。

塔吊载重限制必须采用半径相关 load chart / 力矩约束，而不是单一 `load_capacity_t`：

```yaml
crane_models:
  - model_id: "generic_flat_top_55m"
    max_load_t: 6.0
    max_load_radius_m: 15.0
    tip_load_t: 1.5
    jib_length_m: 55.0
    rated_moment_t_m: 90.0
```

要求：

- `load_weight_t * trolley_r_m` 不得超过 `rated_moment_t_m`；
- 当前载重不得超过 `capacity_at_radius(trolley_r_m)`；
- 任务生成阶段必须避免天然超载任务；
- 运行时基础安全设施必须硬执行力矩限制；
- 如果载重状态下小车继续向外会超力矩，控制器必须限制该动作并记录 `moment_limit` 或 `overload_prevented` 事件。

`capacity_at_radius(r)` 的 MVP 默认计算规则必须明确写入代码和 resolved config：

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

如果后续 YAML 提供更细的 load chart 点表，应使用点表分段线性插值，并仍然与 `rated_moment_t_m` 取更严格限制。

### 0.5.4 Site Zones 与材料库

场景必须支持工地 zone：

```text
material_zones:
  材料区/取货区，例如钢筋堆场、模板堆场、构件堆场。

work_zones:
  作业区/卸货区，例如楼层施工面、核心筒附近、卸料平台。

forbidden_zones:
  禁区，例如建筑核心筒、不可穿越区域、危险区域。
```

任务生成规则：

- pickup 从 `material_zones` 中采样；
- dropoff 从 `work_zones` 中采样；
- `load_type` 必须被 pickup zone 和 dropoff zone 支持；
- pickup/dropoff 高度来自 zone；
- 仍需检查塔吊可达性、载重/力矩限制、禁区、task_type 目标。

MVP 必须支持简化 load type 材料库：

```yaml
load_types:
  rebar_bundle:
    display_name: "钢筋束"
    weight_range_t: [1.0, 3.0]
    size_m: [6.0, 1.0, 1.0]
    shape: "box_long"

  formwork:
    display_name: "模板"
    weight_range_t: [0.5, 2.0]
    size_m: [4.0, 2.0, 0.3]
    shape: "flat_box"

  concrete_bucket:
    display_name: "混凝土吊斗"
    weight_range_t: [1.5, 4.0]
    size_m: [1.5, 1.5, 2.0]
    shape: "cylinder"

  steel_beam:
    display_name: "钢梁"
    weight_range_t: [2.0, 5.0]
    size_m: [8.0, 0.5, 0.5]
    shape: "beam"
```

任务对象和轨迹数据必须记录 `load_type`、`load_weight_t`、`load_size_m`。前端用 `shape` 和 `size_m` 显示简化吊物。后续吊物摆动模型可使用这些尺寸近似吊物包络。

禁区策略分两级：

```text
task_only:
  默认模式。pickup/dropoff 不能落入禁区；
  吊钩/载荷运动过程中进入禁区时记录 forbidden_zone_violation；
  不默认终止 episode。

hard:
  吊钩/载荷进入禁区时由基础安全层阻止，或标记 episode 失败；
  用于后续安全实验。
```

### 0.5.5 塔吊数量

系统不得硬编码 3 台塔吊。塔吊数量由配置决定：

```text
layout.num_cranes 或 cranes 列表长度决定仿真塔吊数量
```

MVP 示例场景至少覆盖 3 台塔吊，以验证多塔交互；第一版推荐性能验收范围为 2-6 台塔吊，但架构和数据结构必须按 N 台塔吊设计。

### 0.5.6 任务系统

MVP 采用“每台塔吊独立任务队列”：

- 每台塔吊有自己的任务队列；
- 每个 LLM 司机只驾驶自己的塔吊；
- 每个任务只分配给一台塔吊；
- 取货点和卸货点允许被多台塔吊的作业半径覆盖；
- 第一版不做多塔抢同一任务，也不做双机抬吊。

MVP 必须支持三类任务：

```text
easy_task:
  基础可达任务，用于验证单塔驾驶、挂载、卸载流程。

overlap_task:
  取货点或卸货点位于多塔作业半径重叠区域附近，用于制造自然交互。

stress_task:
  多台塔吊在时间和空间上同时进入重叠区域，可设置更紧 deadline、
  更近路径或相邻任务点，用于产生 high-risk、near-miss、collision 等事件。
```

`stress_task` 允许任务生成器在目标点和时序上制造压力，但不得预设操作轨迹。允许做法包括：

- C1 的卸货点和 C2 的取货点都在重叠区附近；
- 多台塔吊任务开始时间接近；
- deadline 更紧；
- 任务路径更容易交叉；
- 具体驾驶、避让、等待、误判和风险结果仍由 LLM 司机自然产生。

`priority` 和 `deadline_s` 必须保留：

- `priority` 表示任务紧急程度，进入 LLM observation 和 prompt，不改变物理规则；
- `deadline_s` 表示建议完成时间，进入 LLM observation 和 prompt；
- 任务超时不判定失败，不终止任务；
- 超时必须记录 `deadline_missed=true` 和 `overtime_s`；
- prompt 必须说明超时会降低任务表现，但不能为了赶时间违反安全和机械约束。

任务队列启动策略必须支持：

```text
simultaneous:
  episode 开始时，每台塔吊立即开始第一个任务。

staggered:
  每台塔吊第一个任务启动时间随机错开，默认推荐。

scheduled:
  每个任务可显式配置 planned_start_s，适合 demo、stress_task 和复现实验。
```

完成当前任务后：

- 如果下一任务有 `planned_start_s`，到时间后开始；若当前时间已超过 planned_start_s，则立即开始；
- 如果下一任务没有 `planned_start_s`，等待 `inter_task_delay_s` 后开始。

无 active task 时，塔吊进入 `idle` 阶段，但仍然按 LLM 决策频率调用 LLM。observation 必须明确说明当前没有 active task，但不得提前告知下一任务是否存在、下一任务开始时间或下一任务目标。合理操作应为所有运动轴 neutral、`task_action=none`。系统不静默替 LLM 接管为 neutral；如果 LLM 在 idle 状态下输出无目的动作，必须如实执行机械安全允许的部分，并记录 `idle_unnecessary_motion` 事件，作为操作行为数据。

任务级失败默认不终止 episode：

```text
failed_attach_timeout:
  长时间无法完成挂载，当前任务失败，塔吊等待后切换下一任务。

failed_release_timeout:
  长时间无法完成卸载，当前任务失败，塔吊等待后切换下一任务。

failed_unreachable / failed_overload:
  应在任务生成或配置校验阶段发现，不应进入正常 episode。
```

`deadline_missed` 不算任务失败，不切换任务，继续完成当前任务。

### 0.5.7 挂载/卸载与信号工抽象

MVP 不单独实现信号工 Agent。挂载/卸载由“LLM 请求 + 任务系统判定 + 延迟完成”抽象：

```text
LLM 司机：
  驾驶吊钩靠近取货点/卸货点；
  到位后输出 request_attach 或 request_release。

任务系统：
  检查 xy 对准误差；
  检查高度误差；
  检查当前速度是否足够低或停稳；
  检查载重/力矩限制；
  满足条件后进入 attach_pending 或 release_pending；
  延迟 attach_delay_s / release_delay_s 后完成挂载/卸载；
  条件不满足则拒绝请求并记录失败原因。
```

observation 中可包含系统生成的“地面信号提示”，例如“吊钩略偏右，请小车向内并缓慢下降”。该提示用于模拟真实工地信号工/司索工信息，但不等同于全局路线规划。

LLM 在错误阶段请求 attach/release 时：

```text
idle 时 request_attach/request_release；
未到取货点 request_attach；
已挂载时 request_attach；
未挂载时 request_release；
远离卸货点 request_release；
速度未降到允许阈值时 request_attach/request_release；
```

任务系统必须拒绝请求，不改变 `load_attached`，记录 `attach_request_rejected`、`release_request_rejected` 或 `invalid_task_action`，并把失败原因写入后续 observation history。该类事件不默认终止 episode。

任务阶段只能由任务系统状态机推进，LLM 不能直接指定、覆盖或跳转 `task_stage`。LLM 只能通过手柄操作和 `task_action=request_attach/request_release` 间接影响任务阶段。

### 0.5.8 LLM 操作接口

LLM 司机必须模拟真实塔吊操作台的“双手柄 + 档位 + 安全开关”模式，而不是输出连续速度或直接目标点。

MVP 命令结构：

```json
{
  "left_joystick": {
    "slew": {
      "direction": "left",
      "gear": 2
    },
    "trolley": {
      "direction": "out",
      "gear": 1
    }
  },
  "right_joystick": {
    "hoist": {
      "direction": "neutral",
      "gear": 0
    }
  },
  "deadman_pressed": true,
  "emergency_stop": false,
  "horn": false,
  "command_duration_s": 1.0,
  "task_action": "none",
  "attention_target": "pickup_area",
  "confidence": 0.76,
  "reason": "取货点在右前方，低速右转并向外移动小车，同时观察邻塔。"
}
```

含义：

```text
left_joystick.slew.direction:
  left    = 回转左
  right   = 回转右
  neutral = 不主动回转

left_joystick.trolley.direction:
  out     = 小车向臂端移动
  in      = 小车向塔身移动
  neutral = 不主动移动小车

right_joystick.hoist.direction:
  up      = 吊钩上升
  down    = 吊钩下降
  neutral = 不主动起升/下降

gear:
  0 = 中位/停止
  1 = 微速
  2 = 低速
  3 = 中速
  4 = 高速
  5 = 最高速

deadman_pressed:
  true  = 司机保持有效操作状态
  false = 手柄输入无效，进入安全停止

emergency_stop:
  true = 当前命令周期执行紧急停止。MVP 暂不实现复杂急停锁存和复位流程

task_action:
  none | request_attach | request_release
```

`horn=true` 表示司机鸣笛提醒，只记录 `horn_event`，可供前端提示，不影响物理状态。

`command_duration_s` 表示本次手柄状态持续保持的仿真时间。MVP 默认 1.0 秒，允许范围建议为 0.5-3.0 秒。它不是任务耗时，也不是 episode 时长，而是“司机把手柄推到某方向/档位并保持多久”。若模型省略该字段或字段非法，按 schema retry；replay 时必须使用当时实际执行的 `command_duration_s`。

每个运动轴都有独立 `direction + gear`，模拟真实二维手柄每个轴的开度/档位。允许多轴同时动作，例如同时回转、小车变幅和起升/下降。MVP 不限制某些性格只能单轴操作。

校验规则：

```text
如果 direction = neutral，则 gear 必须为 0；
如果 gear = 0，则 direction 应为 neutral。
```

低层控制器负责将手柄方向和档位转换为速度目标，并处理加速度限制、渐进换档、机械限位和自动制动。手柄回中不代表瞬间停止，而是按减速度平滑停下。急停才代表紧急制动。

### 0.5.9 LLM 观测边界

LLM observation 必须是“人类驾驶员可见/可获知”的局部信息，不得暴露完整全局真值和真实未来标签。

允许给 LLM：

- 当前任务阶段、优先级、deadline 和超时状态；
- 取货点/卸货点相对方向、距离、高度差、对准误差提示；
- 自身塔吊状态、当前手柄状态、是否挂载；
- 可见邻塔 ID、相对方向、距离等级或带噪声距离；
- 可见邻塔运动状态、是否挂载、当前任务阶段；
- 天气、风速、阵风、可见度；
- R1 模式下的在线风险提示；
- 本 episode 内较长操作记忆、任务历史摘要、关键事件摘要。

禁止给 LLM：

- 邻塔完整任务目标；
- 邻塔任务队列；
- 邻塔未来意图；
- 邻塔未来路径；
- 离线 future_min_distance / offline TTC；
- 完整全局真值坐标；
- 任何基于 episode 真实未来轨迹生成的信息。

目标距离和高度差可以用米级数值；角度主要使用相对偏差，如“目标偏右约 15 度”，不应把全局绝对角度作为主要决策依据。

observation 数值精度必须控制，避免把仿真全精度真值直接交给 LLM：

```text
自身任务目标:
  相对水平距离可给米级数值，但应四舍五入到 0.1m 或 0.5m；
  相对角度偏差应四舍五入到 5 度；
  高度差应四舍五入到 0.1m 或 0.5m；
  同时给 left_front / right_front / front / back 等方向描述。

邻塔信息:
  默认给 distance_level + 粗略距离；
  good visibility 下距离噪声较小，可显示到 0.5m；
  medium visibility 下显示到 1-2m；
  poor visibility 下只给 near / medium / far 或较大噪声距离。

R1 风险提示:
  clearance_now_m 和 estimated_clearance_next_5s_m 可以给；
  但也必须按系统精度圆整，不输出过高精度小数。
```

### 0.5.10 风险提示模式

基础机械安全始终硬执行。多塔风险提示必须可配置：

```text
R0 无风险提示模式:
  LLM 只看到任务、自身状态、可见邻塔、天气等信息；
  风险模块仍后台计算并记录；
  online_risk 不进入 observation。

R1 风险提示模式:
  LLM 在 observation 中收到 online_risk 预警；
  系统不强制修改命令；
  是否听从提示由 LLM 决定。
```

R1 风险提示可以比较具体，但必须来自 online estimate，不得来自真实未来：

```text
risk_level:
  safe / low / medium / high / near_miss

nearest_neighbor:
  最近相关塔吊 ID

nearest_object_type:
  jib-jib / jib-hook / hook-hook

clearance_now_m:
  当前估计净空距离

estimated_clearance_next_5s_m:
  按当前状态、速度和手柄命令短时外推的未来 5 秒估计净空

relative_motion:
  opening / closing / stable

suggestion:
  observe / reduce_gear / hold / slow_down
```

R0/R1 是 observation 提示模式；S0/S1/S2/S3 是安全干预等级。二者应分开配置，避免把“是否提示”与“是否强制干预”混在一起。

### 0.5.11 风险对象与标签

MVP 风险对象必须包含三类：

```text
jib-jib:
  起重臂线段与起重臂线段距离。

jib-hook:
  一台塔吊起重臂线段与另一台塔吊吊钩点距离，双向都计算。

hook-hook:
  两台塔吊吊钩点之间距离。
```

当前最小距离：

```text
distance_min_raw_m = min(all raw distances)
clearance_min_m = min(all clearances)
```

距离记录必须同时保存：

```text
distance_*_raw_m:
  几何中心线/点之间的原始距离。

clearance_*_m:
  扣除对象几何包络后的净空距离。
  clearance <= 0 表示碰撞。
```

风险等级主要基于 `clearance_min_m`。

碰撞和风险阈值采用两层定义：

```yaml
risk:
  geometry_envelope:
    jib_radius_m: 0.75
    hook_radius_m: 0.5
    load_radius_m: 1.0

  thresholds_m:
    low: 8.0
    medium: 5.0
    high: 3.0
    near_miss: 1.8
```

碰撞判定：

```text
jib-jib collision:
  segment_distance <= jib_radius_i + jib_radius_j

jib-hook collision:
  segment_point_distance <= jib_radius_i + hook_radius_j

hook-hook collision:
  point_distance <= hook_radius_i + hook_radius_j
```

后续加入吊物摆动后，再扩展 `load-load`、`jib-load`、`load_swing_envelope`。

风险计算必须分为：

```text
online_risk:
  仿真运行时基于当前状态、当前速度/手柄命令做短时外推；
  可进入 R1 observation；
  不能使用真实未来轨迹。

offline_label:
  episode 完成后基于已记录真实轨迹计算 future_min_distance、TTC、risk_label；
  只用于训练数据和论文指标；
  禁止进入 LLM observation。
```

### 0.5.12 碰撞与 episode 状态

临界接近、near-miss、高风险事件继续仿真并记录；几何碰撞发生后，MVP 必须立即终止当前 episode：

```text
collision event
  -> 记录碰撞对象、时间、距离、塔吊对
  -> episode_status = failed_collision
  -> 终止 episode
  -> 不生成碰撞后的不可信轨迹
```

episode 状态至少包括：

```text
completed:
  所有塔吊任务队列完成，且无碰撞。
  若 stop_when_all_tasks_done=true，则完成后继续记录 completion_cooldown_s，
  用于观察停稳和风险解除，然后结束 episode。

timeout:
  达到最大仿真时长，还有任务未完成。

failed_collision:
  发生几何碰撞并终止。

failed_invalid_state:
  出现 NaN、Inf、状态越界或仿真器内部错误。

llm_failed:
  LLM 连续失败超过阈值。

failed_replay_mismatch:
  replay 模式下配置 hash、命令序列或浮点状态复现结果超过容差。

stopped_by_user:
  用户或 API 主动停止。
```

事件系统必须记录风险事件：

```text
risk_entered:
  某塔吊对风险等级从 safe/low 进入 medium/high。

near_miss:
  clearance 低于 near_miss_threshold，但尚未发生碰撞。

risk_resolved:
  medium/high 风险解除，回到 low/safe。

collision:
  发生几何碰撞，记录后终止 episode。

ignored_risk_hint:
  R1 模式下系统提示 high risk 或 near-miss，
  但 LLM 仍输出高档位、继续接近或未减速的动作。
  这是启发式行为标记，不代表绝对违规。

emergency_stop_triggered:
  LLM 输出 emergency_stop=true，或安全层触发急停。

horn_event:
  LLM 输出 horn=true，仅记录提示事件，不影响物理状态。

intervention_applied:
  S2/S3 模式下系统修改了 LLM 原始命令。

idle_unnecessary_motion:
  task_stage=idle 且 LLM 输出任一运动轴非 neutral 或 gear>0。
  该事件只记录，不默认终止 episode。
```

overlap zone 交互事件也必须记录：

```text
overlap_zone_entered:
  某台塔吊吊钩、小车或吊臂进入多塔作业半径重叠区域。

overlap_zone_exited:
  离开重叠区域。

overlap_zone_shared:
  两台或多台塔吊同时在同一重叠区域作业。

overlap_task_conflict:
  多台塔吊当前任务目标都靠近同一重叠区域。
```

这些事件不一定代表危险，只代表多塔交互背景。风险等级仍由 clearance、TTC、near-miss 等计算。

### 0.5.13 坐标系、角度与回转模式

统一坐标：

```text
坐标系：ENU 右手坐标系
x：East / 工地平面向右
y：North / 工地平面向前
z：Up / 高度向上
单位：m、s、rad；配置和展示可使用 deg
```

塔吊几何：

```text
base = [base_x, base_y, base_z]
root = [base_x, base_y, base_z + mast_height]
theta = 0 时起重臂指向 +x
theta 正方向为从 +x 朝 +y 逆时针
hook_h_m 表示吊钩世界高度 z，不是绳长
```

起升/吊钩高度统一采用以下约定，避免 `hoist_h_max_m` 与塔身高度混淆：

```text
root_z = base_z + mast_height_m
cable_length_m = root_z - hook_h_m
hook_h_m = root_z - cable_length_m
```

MVP 型号库应优先配置 `cable_length_min_m`、`cable_length_max_m` 和 `hoist_speed_max_m_s`。若旧配置仍使用 `hoist_h_min_m` / `hoist_h_max_m`，解析器必须转换为 resolved config 中的 `hook_h_min_world_m` / `hook_h_max_world_m`，并校验 `hook_h_max_world_m <= root_z - cable_length_min_m`。新实现不得让吊钩高度超过起重臂根部高度。

MVP 默认：

```yaml
slew:
  mode: "continuous"
```

`theta_rad` 内部可以连续累积；几何计算使用 `sin(theta)` 和 `cos(theta)`；导出必须同时保存 `theta_rad`、`theta_sin`、`theta_cos`。如需模拟回转限位，可配置：

```yaml
slew:
  mode: "limited"
  theta_limit_deg: [-270, 270]
```

### 0.5.14 操作员性格

MVP 必须支持 5 种 operator profile，并通过 prompt 与行为参数产生明显差异：

```text
normal:
  安全和效率平衡；高风险时减速。

conservative:
  更早减速；中等风险也可能等待或低档操作；deadline 压力下仍优先安全。

aggressive:
  更偏向效率；更常用高档位；低/中风险时可能继续操作；高风险才明显减速。

novice:
  动作更犹豫；更频繁回中；对准时容易小幅反复修正；可能过早或过晚请求挂载/卸载。

fatigued:
  反应更慢；更容易保持上一条命令；偶尔忽略提示；档位变化不够及时。
```

每台塔吊必须可独立配置 operator profile，也可按分布随机分配。性格差异应主要通过 profile prompt、观察节奏、历史记忆、提示文本和可配置行为参数影响 LLM，不应通过后处理随意篡改 LLM 命令来伪造性格。后处理只负责格式校验、机械安全和可配置安全干预。

MVP 先使用一版固定 profile prompt，后续根据实际 episode 轨迹、命令日志、任务完成率和风险事件统计再迭代调整。

### 0.5.15 LLM Provider、真实 API 与重放

第一版必须支持真实调用用户指定的大模型 API，默认支持：

```text
deepseek
minimax
```

同时保留：

```text
mock:
  用于无网络开发和单元测试。

replay:
  读取历史 command_replay.jsonl，不调用 LLM，用于复现。
```

LLM provider 必须做成可扩展抽象，支持多个厂商和多个模型。配置文件允许：

```text
api_key:
  直接在本地 YAML 中写真实 key。

api_key_env:
  从环境变量读取 key。
```

如果两者同时存在，优先使用 `api_key`。运行日志、run metadata 和 dataset_summary 不得保存完整 key，只保存 `key_source` 和脱敏 `key_masked`。

LLM 输出必须通过 Pydantic/JSON Schema 校验。输出非法时，同一次决策 retry 中必须把具体 validation error 反馈给模型纠错；超过最大重试次数后当前司机进入 `neutral_stop`，连续失败超过阈值则 episode 标记 `llm_failed` 并终止。

LLM 每次调用必须完整保存 messages：

```text
system prompt
operator profile prompt
user prompt
observation JSON
retry correction prompt
raw response
parsed command
executed command
validation errors
provider / model / latency / token_usage
```

`reason`、`attention_target`、`confidence` 必须保留。它们不参与物理执行，只用于日志、调试、论文案例和行为分析。

Prompt 语言策略：

```text
业务说明、司机身份、任务语义、安全说明使用中文；
JSON 字段名、枚举值、schema 约束固定使用英文；
禁止让模型把枚举翻译成中文；
reason 可以使用中文。
```

### 0.5.16 LLM 决策频率与上下文

MVP 默认：

```text
physics_hz = 20
dt = 0.05s
llm_decision_interval_s = 1.0
command_duration_s = 1.0
```

每台塔吊每 1 秒构造一次 observation，LLM 输出一次双手柄命令。命令包含 `command_duration_s`，表示本次手柄状态保持多久；默认情况下该值等于 `llm_decision_interval_s`。即使塔吊没有 active task、处于 `idle` 阶段，也仍然调用 LLM，让司机自行决定保持 neutral。低层控制器在命令保持期间连续执行，并处理平滑加减速和机械约束。

`command_duration_s` 的边界：

```text
min_command_duration_s = 0.5
max_command_duration_s = 3.0
默认 command_duration_s = llm_decision_interval_s
```

若某条命令的 `command_duration_s` 短于下一次计划 LLM 决策间隔，则命令到期后默认进入 neutral_stop，等待下一次决策；若长于下一次计划决策间隔，则下一次 LLM 决策返回后覆盖旧命令。实时模式下如果 LLM 超时，可按 stale policy 短暂保持旧命令，但不得无限延续。

离线 LLM 生成数据时，仿真时间允许暂停等待 LLM 返回：

```text
offline_wait:
  到达决策点后冻结仿真时间；
  等待同一时刻所有需要决策的 LLM 返回；
  同时应用这一批命令；
  API latency 只记录到日志，不影响仿真时间。

realtime_async:
  用于前端实时观看；
  LLM 慢时最多保持上一条命令一小段时间；
  超过 stale_command_max_hold_s 后 neutral_stop；
  超过 response_timeout_s 记录 timeout。
```

同一仿真决策时刻，多塔 LLM 必须并行决策：

```text
冻结当前 world snapshot；
为所有需要决策的塔吊分别构造 observation；
并行请求各自 LLM；
所有 observation 基于同一时刻状态；
后决策的塔吊不能看到前一塔吊在同一时刻刚输出的命令；
收齐或超时后同时应用命令。
```

不依赖厂商 conversation state。每次 LLM 调用都是独立 API 请求，由系统自行构造完整 messages，包含当前 observation、历史摘要、最近操作、operator profile 和输出 schema。

LLM 可以使用较长 episode 内上下文：

- 当前完整 observation；
- 当前任务历史摘要；
- 近期完整操作记录；
- 更早历史压缩摘要；
- 已完成/超时/失败任务摘要；
- 风险、挂载失败、释放失败、near-miss 等关键事件摘要。

原始完整操作日志必须落盘；进入 prompt 的历史内容可按配置进行摘要，以保证上下文可读。

历史摘要器：

```text
默认可使用 LLM summarizer；
保留 rule summarizer fallback；
摘要器只能看已经发生的 observation、commands、任务阶段变化、挂载/卸载失败、
风险事件和超时事件；
摘要器不能看未来轨迹、offline_label、未来最小距离、未来 TTC 或邻塔未来目标/路径。
```

摘要记录要求：

- 原始日志完整保存；
- LLM summary 保存 `summary_id`、`source`、`input_range`、`raw_response`、`parsed_summary`；
- replay 时读取已保存 summary，不重新调用摘要 LLM；
- 摘要 LLM 调用失败时使用 rule summarizer。

LLM cache 与 replay 必须分开：

```text
llm_cache:
  用于开发调试、省钱、省时间；
  key = hash(provider, model, prompts, observation_json, output_schema_version)；
  命中时仍记录 cache_hit=true。

command_replay:
  用于完全复现 episode；
  不调用 LLM；
  按 episode_id + frame/time_s + crane_id + decision_index 读取 executed_command。
```

### 0.5.17 天气模块

MVP 天气模块必须存在，但影响分层：

```text
观测/行为影响:
  风速、阵风、风向、可见度、雨/雾等级进入 LLM observation；
  可见度影响邻塔信息可见性和模糊程度；
  风大时 prompt 和 online_risk 提醒谨慎操作。

物理/风险影响:
  暂不模拟真实风载动力学；
  暂不模拟吊物摆动；
  风速和阵风可提高 effective_safe_distance；
  为后续吊物摆动模型预留字段。
```

可见度影响 observation：

```yaml
visibility:
  levels:
    good:
      neighbor_visibility_radius_m: 120
      distance_noise_m: 0.5
      hide_hook_prob: 0.0
    medium:
      neighbor_visibility_radius_m: 80
      distance_noise_m: 2.0
      hide_hook_prob: 0.2
    poor:
      neighbor_visibility_radius_m: 45
      distance_noise_m: 5.0
      hide_hook_prob: 0.5
```

R1 模式下，即使可见度 poor，online_risk 仍可给出，但必须附带 confidence/uncertainty 提示。

风速和阵风进入 prompt 并影响操作建议：

- 大风时建议降低档位、谨慎起升/下降、扩大观察；
- 阵风时建议低档、暂停或保持观察；
- MVP 不默认硬限制档位；
- 是否在大风下仍使用高档位必须记录，便于后续行为分析。

### 0.5.18 记录与回放

数据记录分四层：

```text
frame-level truth data:
  每帧真实仿真状态。

pair-level risk data:
  每帧每对塔吊的距离、TTC、风险等级和标签。

decision-level operator data:
  每次 LLM 决策的 observation、raw response、parsed command、
  executed command、latency、失败原因。

event-level data:
  任务开始/完成、挂载/卸载、超时、near-miss、collision、
  LLM timeout、emergency_stop 等离散事件。
```

LLM observation 只在决策时刻记录，不每帧重复保存。轨迹、风险和天气仍按仿真帧记录。前端离线回放必须使用 `visual/frames.jsonl`，它与 WebSocket 实时推送共用同一 `SimFrame` schema。

### 0.5.19 前端定位

前端第一优先级是离线回放和数据质量检查，其次支持实时展示：

```text
必须：
  加载已生成 episode；
  播放、暂停、倍速、拖动时间轴；
  按配置展示 N 台塔吊；
  显示塔身、起重臂、平衡臂、小车、吊钩；
  显示任务点、禁区、作业半径、风险连线、任务阶段；
  显示 LLM 命令日志和事件日志；
  点击塔吊/塔吊对查看状态和风险。

应支持：
  WebSocket 实时观看正在运行的仿真；
  实时帧与离线帧使用同一 SimFrame schema。
```

先做离线回放不会阻碍实时仿真；二者必须共享统一帧结构和前端渲染组件。

前端必须显示：

```text
material_zones
work_zones
forbidden_zones
overlap_zones
```

并能看出当前任务 pickup/dropoff 属于哪个 zone、吊钩/载荷是否进入禁区、风险事件是否发生在 overlap zone。

MVP 塔吊和吊物使用程序几何模型，不要求真实 glTF/GLB 资源：

- 塔身、起重臂、平衡臂、小车、吊绳、吊钩用 Three.js 基础几何体搭建；
- 吊物根据 `load_type.shape` 和 `load_size_m` 简化显示；
- 坐标准确、回放稳定、风险线清楚优先；
- 预留 `model_asset_url` / `gltf_model_id` 供后续替换真实模型。

前端 LLM 日志：

```text
默认显示：
  简洁命令日志和事件日志。

点击展开：
  observation、messages、raw_response、parsed_command、executed_command、validation_errors。
```

简洁命令日志至少显示 time、crane_id、operator_profile、provider/model、三轴方向与档位、task_action、attention_target、confidence、reason、是否被 intervention 修改。

前端事件日志支持点击跳转：

- 点击事件跳到 `event.frame` / `event.time_s`；
- 高亮相关塔吊或塔吊对；
- 用于快速查看 near_miss、collision、forbidden_zone_violation、ignored_risk_hint 等关键片段。

其他复杂前端功能可暂缓，避免偏离数据平台主线。

### 0.5.20 Summary 指标

episode_summary 和 dataset_summary 至少统计：

```text
episode 基础:
  episode_status
  duration_s
  num_cranes
  num_tasks_total
  num_tasks_completed
  num_tasks_failed
  task_completion_rate

任务效率:
  mean_task_duration_s
  deadline_missed_count
  overtime_mean_s

风险:
  risk_frame_ratio_by_level
  near_miss_count
  collision_count
  min_clearance_over_episode
  high_risk_duration_s

LLM 行为:
  num_llm_calls
  llm_invalid_output_count
  llm_timeout_count
  mean_latency_ms
  cache_hit_count
  operator_profile_distribution

事件:
  ignored_risk_hint_count
  emergency_stop_count
  forbidden_zone_violation_count
  overlap_zone_shared_count

数据质量:
  has_nan
  has_inf
  max_state_jump
  replay_available
```

dataset_summary 聚合 episode_summary，并按 scenario、task_type、operator_profile、risk_prompt_mode、safety_mode、provider/model 进行可选分组统计。

### 0.5.21 运行层级与配置分层

运行层级定义：

```text
run:
  一次执行任务的总目录。例如一次 batch_generate 或一次实验运行。

scenario:
  一个工地场景配置，包括 site boundary、塔吊布局、任务生成策略、天气策略等。

episode:
  某个 scenario 下的一次具体仿真序列。
  由具体 seed、operator profile 分配、LLM provider/model、天气随机序列等共同决定。
  一个 scenario 可以运行多个 episode。

dataset:
  从多个 run / scenario / episode 中整理出来的训练数据集合。
  包含 train/val/test 划分、统计 summary 和窗口切片结果。
```

配置分三层：

```text
scenario.yaml:
  描述工地场景本身。
  site boundary、forbidden zones、layout、crane_models、task generation policy、weather policy。

experiment.yaml:
  描述怎么运行 scenario。
  sim duration / dt / physics_hz、episode seeds、operator profile 分配、LLM provider/model/key、
  risk_prompt_mode、safety_mode、replay/cache/retry 策略。

dataset.yaml:
  描述如何批量生成和整理数据集。
  scenario 列表、每类 scenario 生成多少 episode、train/val/test split、
  STGNN window 参数、数据统计和导出策略。
```

每次运行必须保存原始配置和 resolved config。resolved config 必须包含默认值补全、自动布局结果、operator 分配、seed 固化、LLM provider、风险/安全模式等完整信息。

第一版同时支持命令行运行和 FastAPI 服务运行。命令行用于批量生成、复现和构建数据集；FastAPI 用于前端展示、交互启动 episode、查询状态和下载数据。二者必须调用同一个 simulation engine，不得各写一套仿真逻辑。

### 0.5.22 不做全局协调员 Agent

MVP 不实现全局调度员/协调员 Agent。第一版只包含：

```text
每台塔吊一个独立 LLM 司机；
任务系统负责分配和推进当前任务；
地面信号提示由任务系统生成；
online_risk 可作为 R1 风险提示；
S2/S3 可选安全干预；
没有中央 Agent 告诉各塔吊谁让谁。
```

全局协调员可作为后续增强实验，用于比较 no_coordinator vs coordinator 对效率和风险的影响。

### 0.5.23 规则司机能力边界

规则司机保留，但不作为系统主线。它的定位是：

```text
任务生成合理性验证；
无 LLM 单元测试；
mock 数据生成；
LLM vs rule vs random 的对照实验；
前端 demo 的确定性回放样例。
```

规则司机第一版只需要能用简单几何策略完成 easy_task，并尽量在 overlap_task 中避开明显碰撞；不要求模拟真实司机性格，不要求复杂多塔协商，不要求处理所有 stress_task。主 LLM 数据生成模式下，LLM 输出非法、超时或连续失败时，默认执行 retry、neutral_stop 和 `llm_failed` 终止流程，不自动由规则司机接管。若后续实验需要 rule takeover，必须作为单独 safety/intervention 模式显式开启，并在数据中记录。

规则司机可以读取完整当前几何状态用于任务生成合理性验证，但不得读取真实未来轨迹、offline label、future_min_distance 或未来 TTC。用于对照实验时，必须在 metadata 中标记 `operator_mode=rule` 与其观测边界，避免把它误写成人类等价观测 baseline。

---


## 0.6 本轮修订统一约定

本节用于消解旧文档中容易让实现产生分歧的地方。后续实现、测试和验收必须优先遵循本节。

### 0.6.1 配置文件归属

推荐配置分为三类：

```text
scenario.yaml     描述工地、塔吊型号、布局、zone、任务生成策略、天气策略、风险几何阈值。
experiment.yaml   描述如何运行 scenario，包括 sim runtime、episode seeds、LLM provider、operator 分配、R0/R1、S0-S3、cache/replay/retry。
dataset.yaml      描述批量生成、数据集划分、窗口切片和统计导出。
```

允许提供 `configs/demo.yaml` 作为单文件入口，但它只能是便捷封装。加载后必须被解析为 `ScenarioConfig`、`ExperimentConfig`、`DatasetConfig` 或相应 resolved config，不得在内部长期使用混合配置对象。

### 0.6.2 任务状态与塔吊阶段分离

旧文档中 `pending` 同时出现在任务对象和 `task_stage` 中，容易混淆。本修订版统一为：

```text
Task.status:
  pending / active / completed / failed / skipped

Crane.task_stage:
  idle / move_to_pickup / align_pickup / lower_for_attach / attach_pending /
  lift_load / move_to_dropoff / align_dropoff / lower_for_release / release_pending /
  recovery_release
```

`idle` 是塔吊没有 active task 或等待启动时间时的阶段；`pending` 是任务队列状态，不再作为塔吊阶段。

### 0.6.3 deadline 与阶段 timeout 分离

`deadline_s` 是建议完成时间，只影响效率评价：

```text
deadline_missed=true 不导致任务失败，不导致 episode 终止。
```

挂载/卸载阶段 timeout 是任务流程失败条件：

```text
attach_stage_timeout_s / release_stage_timeout_s 超过后，默认 failed 当前任务；
默认不终止 episode。若未带载，塔吊进入 idle 或等待下一任务；若仍带载，进入 recovery_release，不得直接开始普通下一任务。
```

字段命名统一为：

```yaml
deadline_policy:
  deadline_miss_is_task_failure: false
state_machine:
  stage_timeout_policy:
    fail_current_task: true
    terminate_episode: false
```

### 0.6.4 起升变量命名

内部控制可以控制 `cable_length_m` 或 `hoist_v_m_s`，但导出和几何计算必须始终给出 `hook_h_m`、`hook_x/y/z`。MVP 中：

```text
无吊物摆动：load_position = hook_position 或 null，按配置决定；
有吊物摆动：load_position 表示吊物质心，风险模块可扩展 load-load / jib-load 距离。
```

### 0.6.5 R0/R1 与 S0-S3 的边界

```text
R0/R1 = 是否把 online_risk 放进 LLM observation。
S0-S3 = 是否根据多塔风险修改 LLM 命令。
```

基础机械安全、力矩限制、行程限制、非法状态检测和碰撞终止始终生效，不受 R0/R1 或 S0-S3 关闭。

### 0.6.6 在线提示、离线标签与前端显示边界

- LLM observation 永远不得包含 offline future label。
- 实时 WebSocket 只能推送当前状态和 online estimate。
- 离线回放前端可以显示 `min_clearance_future_5s_m` 等 offline label，但 UI 必须标注为“离线标签/事后分析”，避免与实时可用预警混淆。

### 0.6.7 数据 schema 版本

所有 JSONL、manifest、Parquet 必须包含 `schema_version`。Parquet 可采用列字段或文件 metadata；若采用 metadata，也建议保留 `schema_version` 列，便于下游 Pandas 读取和合并。

### 0.6.8 运行结束时间

```text
max duration = sim.duration_s
min duration = sim.min_duration_s
```

当 `stop_when_all_tasks_done=true` 时：

```text
如果所有任务已完成但 time_s < min_duration_s：继续以 idle 阶段记录到 min_duration_s；
到达 min_duration_s 后，再记录 completion_cooldown_s；
随后 episode_status=completed。
```

如果发生 collision、failed_invalid_state、llm_failed、failed_replay_mismatch 或 stopped_by_user，则立即结束，不受 `min_duration_s` 限制。

---

## 0.7 工程合同统一约定

本节把 A-P 模块从“功能罗列”收束为可开工的接口合同。后续实现优先按本节拆分代码、写单元测试和定义模块输入输出；如果后文模块说明与本节不一致，以本节为准。

### 0.7.1 模块合同总原则

1. **每个模块必须有唯一主要责任对象**：模块可以读取多个对象，但只能写入自己拥有或被调度器授权写入的对象。
2. **所有跨模块交互必须通过显式数据对象**：不得让 LLM、前端、风险标签器或 recorder 直接修改 `CraneState`。
3. **命令链路必须单向流动**：

```text
RawLLMResponse
  -> ParsedCommand
  -> ExecutedCommand
  -> ControlTarget
  -> CraneState
  -> FrameRecord / SimFrame / TrajectoryRow
```

4. **失败必须显式分类**：失败不得只写日志后继续静默运行；必须落为 startup error、episode event、task failed、episode failed、warning 或 diagnostic。
5. **在线可用信息和离线标签必须硬隔离**：任何进入 LLM observation、实时 WebSocket 或在线风险提示的信息都不得读取真实未来轨迹。
6. **Recorder 只能观察和落盘**：recorder 不得改变任务状态、塔吊状态、命令或风险等级。
7. **前端只能展示后端状态**：前端不得生成训练真值，不得把 display-only 距离计算回写到数据集。

### 0.7.2 核心对象表与权威归属

| 对象 | 主要 owner | 允许写入/修改者 | 主要只读消费者 | 权威性与边界 |
|---|---|---|---|---|
| `ScenarioConfig` | 模块 A | 配置加载器 | B/D/E/H/M/O | 描述工地、zone、布局目标、塔吊型号、任务生成与天气策略。不得包含 LLM API key。 |
| `ExperimentConfig` | 模块 A | 配置加载器 | F/G/H/J/M | 描述运行参数、operator、provider、R/S 模式、retry/cache/replay。 |
| `DatasetConfig` | 模块 A/O | 配置加载器、dataset builder | O/P | 描述批量生成、划分、窗口切片、统计策略。 |
| `ResolvedConfig` | 模块 A | 配置解析器、B/D/E/G 的 resolve 阶段 | 全部模块 | 配置权威。包含默认值、自动布局结果、任务种子、operator 分配、schema version、hash。运行后不可变。 |
| `CraneModelSpec` | 模块 B | 型号库加载器 | B/C/H/I | 型号参数权威。包含 load chart、速度/加速度/行程/高度限制。 |
| `CraneConfig` | 模块 B | 布局生成器或 manual layout validator | C/D/F/H/I/N | 单台塔吊静态配置权威。运行中不可变。 |
| `Task` | 模块 D | 任务生成器、任务状态机 | F/G/J/L/N/O | 任务语义权威。`Task.status` 只能由任务系统推进。 |
| `WeatherState` | 模块 E | 天气模块 | F/H/J/L/N | 当前天气权威。MVP 主要影响 observation 与风险冗余，不直接写物理状态。 |
| `CraneState` | 模块 C | 物理/运动学 step；任务系统只可在挂载/卸载完成时修改载荷字段 | F/H/I/J/L/N/K | 运行时物理状态权威。LLM、前端、recorder、offline label 不得写入。 |
| `WorldSnapshot` | 模块 J | 调度器冻结生成 | F/G/H/L | 决策时刻只读快照。用于保证同一 decision time 多塔 observation 一致。 |
| `Observation` | 模块 F | observation builder | G/L | LLM 可见信息权威。不得包含未来标签、邻塔未来目标或完整全局真值。 |
| `RawLLMResponse` | 模块 G | LLM provider/mock/replay provider | G/L | 原始模型返回。只用于解析、审计和日志。 |
| `ParsedCommand` | 模块 G | command parser / Pydantic validator | H/L | schema 合法的司机意图。不得直接送入 physics。 |
| `ExecutedCommand` | 模块 H | safety/intervention pipeline；replay provider 可直接提供历史 executed command | I/J/L | 执行命令权威。保存到 `commands.jsonl` 和 `command_replay.jsonl`。 |
| `ControlTarget` | 模块 I | low-level controller | C/J/L | 连续速度/制动目标。不得包含任务语义或 LLM reason。 |
| `OnlineRisk` | 模块 H | online risk evaluator | F/H/J/L/N | 在线估计权威。可进入 R1 observation；不得使用真实未来。 |
| `OfflineRiskLabel` | 模块 K | offline label generator | L/O/P | 训练标签权威。只在 episode 后生成，禁止进入 LLM observation。 |
| `SimFrame` | 模块 L/J | frame builder/recorder | N/M | 展示帧权威。实时 WebSocket 与离线 `visual/frames.jsonl` 共用。 |
| `Event` | 模块 D/H/G/I/J | 各模块通过事件接口提交，EventSink 分配 ID | L/N/O | 离散事件权威。持续事件需按 enter/update/exit 或冷却策略去重。 |
| `EpisodeSummary` | 模块 L/O | recorder/summary builder | M/N/O/P | 单 episode 指标权威。 |
| `DatasetSummary` | 模块 O | dataset builder | M/P | 数据集聚合指标权威。 |

### 0.7.3 A-P 模块合同总表

| 模块 | 只读输入 | 产出对象 | 允许修改 | 不允许越界 | 失败边界 |
|---|---|---|---|---|---|
| A 配置与实验管理 | 原始 YAML、CLI/API 参数 | `ScenarioConfig`、`ExperimentConfig`、`DatasetConfig`、`ResolvedConfig`、run 目录 | 仅配置对象与 run metadata | 不生成物理状态；不调用 LLM；不做风险标签 | 配置错误为 startup error，episode 不启动 |
| B 布局与型号库 | `ScenarioConfig`、型号库、site zones、seed | `CraneModelSpec`、`CraneConfig[]`、layout diagnostics | 仅 layout resolve 结果 | 不生成任务轨迹；不写 `CraneState` | 找不到合格布局为 startup error |
| C 运动学/物理 | `CraneConfig`、`ControlTarget`、上一帧 `CraneState` | 下一帧 `CraneState` | 物理运动字段；载荷位置派生字段 | 不读 LLM raw；不做多塔干预；不推进任务语义 | NaN/Inf/越界为 `failed_invalid_state` |
| D 任务系统 | `Task[]`、`CraneState`、`ExecutedCommand.task_action`、时间 | `Task.status`、`Crane.task_stage`、任务事件 | 任务状态；挂载/卸载完成时的 `load_attached/load_*` | 不做多塔避碰；不修改手柄命令 | attach/release/no-progress timeout 默认 task failed |
| E 天气 | 天气配置、seed、time | `WeatherState` | 天气状态 | 不直接改塔吊运动，除非后续显式启用风载模型 | 天气生成失败为 startup error 或 episode warning，按配置决定 |
| F Observation | `WorldSnapshot`、`WeatherState`、`OnlineRisk`、历史摘要 | `Observation` | observation 文本/JSON | 不泄漏 future labels、邻塔未来意图或完整全局真值 | schema 构造失败为 episode `failed_invalid_state` |
| G LLM 操作员 | `Observation`、profile prompt、provider config、schema | `RawLLMResponse`、`ParsedCommand`、validation errors | operator 日志、parsed command | 不写 `CraneState`；不越过 safety 直接执行 | invalid/timeout 先 retry/neutral_stop，连续超限为 `llm_failed` |
| H 安全与风险 | `ParsedCommand`、`CraneState`、`CraneConfig`、`WeatherState`、R/S config | `ExecutedCommand`、`OnlineRisk`、intervention/risk events | 命令安全改写；online risk 结果 | S0/S1 不改多塔风险命令；不得使用 offline label | 碰撞为 `failed_collision`；机械限制为 event+clamp |
| I 低层控制器 | `ExecutedCommand`、`CraneState`、`CraneModelSpec` | `ControlTarget`、controller diagnostics | 连续目标与数值限幅诊断 | 不做任务阶段；不做 LLM retry；不做多塔风险判断 | 数值异常为 `failed_invalid_state` |
| J 调度器 | 全部模块公开接口 | episode clock、`WorldSnapshot`、episode_status | 调用顺序、时间推进、episode 状态 | 不在调度器里内嵌模块业务规则 | 统一把模块失败映射为 episode/task/run 状态 |
| K 离线标签 | `trajectories.parquet`、几何参数、risk config | `OfflineRiskLabel`、pair future columns | 离线标签文件 | 不影响已运行轨迹；不进入 observation | 标签生成失败为 dataset build error，不改原 episode |
| L 记录与导出 | `CraneState`、`Task`、`Event`、commands、risk、weather | Parquet/JSONL/manifest/summary | 文件系统与 summary | 不修改仿真状态；不纠正命令 | 写入失败为 data export error；不得产出半截权威数据 |
| M 后端 API | HTTP/WS 请求、配置文件、run metadata | API response、WebSocket `SimFrame` | episode lifecycle 请求状态 | 不实现第二套仿真逻辑；不做权威前端校验 | API 错误返回统一错误结构 |
| N 前端展示 | `SimFrame`、manifest、summary、logs | UI 状态、display-only 辅助信息 | 前端视图状态 | 不参与物理计算；不生成训练真值 | 渲染错误不改变 episode/data |
| O 数据集生成 | 多个 run/episode 数据、`DatasetConfig` | dataset split、dataset_summary | dataset 目录 | 不按滑窗随机泄漏；不改原始 run | 数据不足/比例不达标为 dataset build warning/error |
| P STGNN 转换 | trajectories、pair_risks、graph_edges、tasks | 训练窗口张量与 metadata | 派生训练样本 | 不重算权威轨迹；不跨 episode 泄漏 | schema 不兼容为 conversion error |

### 0.7.4 安全层能力边界

安全相关逻辑必须按层拆分，避免 controller、risk、task system 中重复写同一类规则。

| 层 | 是否始终启用 | 可以修改什么 | 不负责什么 | 典型事件 |
|---|---:|---|---|---|
| 机械安全层 | 是 | 轴向速度/加速度/行程/高度/载重/力矩/deadman/emergency_stop 对应的命令或控制目标 | 不判断多塔让行；不推进任务阶段 | `moment_limit`、`overload_prevented`、`deadman_released`、`emergency_stop_triggered` |
| 任务安全层 | 是 | attach/release 合法性、pending 取消、`Task.status`、`Crane.task_stage`、挂载字段 | 不做多塔避碰；不改非任务相关手柄 | `attach_request_rejected`、`release_request_rejected`、`attach_pending_cancelled`、`task_failed` |
| 禁区策略层 | 是 | `task_only` 只记录；`hard` 可阻止动作或按配置失败 episode | 不把禁区 violation 当作多塔 collision | `forbidden_zone_violation`、`forbidden_zone_blocked` |
| 在线风险评估层 | 是 | 只产出 `OnlineRisk` 和风险事件 | 不修改命令；不使用真实未来轨迹 | `risk_entered`、`near_miss`、`risk_resolved` |
| 多塔风险干预层 | 仅 S2/S3 修改 | S2 限速/限制接近轴；S3 强制减速/停车 | S0/S1 下不得修改命令 | `intervention_applied` |
| 碰撞终止层 | 是 | `episode_status=failed_collision`，终止 episode | 不生成碰撞后轨迹；不尝试自动恢复 | `collision` |

### 0.7.5 统一失败分类体系

| 分类 | 示例 | 默认处理 | 是否继续运行 | 必须落盘 |
|---|---|---|---:|---|
| `startup_error` | YAML 缺字段、枚举非法、API key 配置缺失、layout 失败、任务天然不可达/超载 | 不启动 episode；返回明确错误 | 否 | validation report |
| `episode_event` | horn、risk_entered、deadline_missed、forbidden_zone_violation(task_only) | 记录事件，继续 | 是 | `events.jsonl` |
| `task_failed` | attach timeout、release timeout、active task 无进展超时 | 当前任务失败，按任务失败后处理规则进入 idle/recovery | 是 | task/event/summary |
| `operator_runtime_failure` | LLM timeout、API 失败、invalid output 超过单次 retry | 当前决策 neutral_stop；累计计数 | 是，直到连续失败超限 | commands/events/logs |
| `episode_failed` | collision、NaN/Inf、LLM 连续失败超限、replay mismatch、内部不一致 | 标记 terminal status，立即结束 | 否 | event、summary、manifest |
| `warning` | dataset 风险比例不足、旧 schema 自动迁移、可选字段缺失 | 继续，但 summary 标记 | 是 | warning report |
| `diagnostic` | command expired 后 neutral_stop、controller clamp 细节、cache hit | 继续 | 是 | logs/metrics |

默认 episode terminal status 扩展为：

```text
completed / timeout / failed_collision / failed_invalid_state /
llm_failed / failed_replay_mismatch / stopped_by_user
```

### 0.7.6 静止失效 / 无动作失效规则

“静止失效”指系统不得因为没有命令、命令过期、LLM 卡住、司机长期 neutral 或任务失败而进入不可控或含糊状态。MVP 统一规则如下：

1. `neutral_stop` 表示所有运动轴回中、gear=0，并按普通减速度平滑停下；它不是急停。
2. `emergency_stop=true` 表示按紧急减速度制动。MVP 默认 `emergency_stop_latched=false`，即本命令周期生效；若配置 `emergency_stop_latched=true`，必须收到显式 `reset_emergency_stop` API/测试指令后才允许恢复。
3. `deadman_pressed=false` 默认只使当前命令周期手柄输入无效并进入 `neutral_stop`；若配置 `deadman_latched=true`，才进入锁定状态。
4. `command_duration_s` 到期且没有新命令时，立即生成系统 `neutral_stop`，不得无限保持旧命令。
5. LLM timeout、invalid output 重试失败、provider 临时错误时，当前决策生成 `neutral_stop`，并记录原因。
6. idle 阶段长期 neutral 是合法行为，不构成失败；idle 阶段无目的运动只记录 `idle_unnecessary_motion`。
7. active task 长期 neutral 或反复无效动作导致任务无进展时，使用 `task_no_progress_timeout_s` 判定 `task_failed`，而不是让 episode 无限卡住。
8. 规则司机无法计算命令属于实现错误，默认 `failed_invalid_state`；规则司机能输出命令但任务无进展，则按普通任务 timeout 处理为 `task_failed`。

建议默认配置：

```yaml
tasks:
  state_machine:
    task_no_progress_timeout_s: 180
    no_progress_is_task_failure: true

llm:
  fallback_policy: "neutral_stop"
  max_consecutive_failures: 3

safety:
  emergency_stop_latched: false
  deadman_latched: false
```

### 0.7.7 任务失败后的载荷与阶段处理

任务失败后不得简单清空状态，否则会破坏数据真实性和 replay 一致性。MVP 采用以下规则：

| 情况 | 默认处理 | 后续任务是否可开始 |
|---|---|---:|
| `attach_pending` 期间对准/高度/速度条件漂出阈值 | 记录 `attach_pending_cancelled`，回到 `lower_for_attach`，pending 计时清零 | 当前任务继续 |
| `release_pending` 期间对准/高度/速度条件漂出阈值 | 记录 `release_pending_cancelled`，回到 `lower_for_release`，pending 计时清零 | 当前任务继续 |
| 错误阶段 request_attach/request_release | 拒绝请求并记录原因，不改变 `load_attached` | 当前任务继续 |
| `failed_attach_timeout` 且 `load_attached=false` | 当前任务 `failed`，塔吊进入 idle/inter_task_delay | 是 |
| `failed_attach_timeout` 但 `load_attached=true` | 视为状态机不一致，`failed_invalid_state` | 否 |
| `failed_release_timeout` 且 `load_attached=true` | 当前任务 `failed`，塔吊进入 `recovery_release`，禁止开始普通下一任务 | 否，直到卸载成功 |
| `failed_release_timeout` 且 `load_attached=false` | 记录 diagnostic，若释放已完成则修正为 completed，否则 `failed_invalid_state` | 视状态而定 |
| 任意任务失败但仍带载 | 保留真实载荷，生成 recovery unload 目标，或保持 blocked-with-load 状态等待超时 | 否 |

`recovery_release` 是任务系统的内部恢复阶段，不属于正常任务队列。默认 recovery 目标优先使用当前任务 dropoff；若配置了 `safe_unload_zones`，可选择最近可达安全卸载点。研究数据默认不得使用 `auto_clear_load_on_task_failure=true`；该选项只能用于调试，并必须在 summary 中标记。

### 0.7.8 单帧生命周期

每个仿真帧必须按固定顺序执行。推荐把初始状态记录为 `frame=0,time_s=0`；循环内从 `state_t` 积分到 `state_{t+dt}`，并把后验状态记录为下一帧。

```text
0. 已有 state_t，若 t=0 先记录初始 frame。
1. update_weather(t)。
2. task scheduler 激活到达 planned_start_s / inter_task_delay 的任务。
3. 判断哪些 crane 到达 LLM/rule 决策时刻；idle 阶段也参与判断。
4. 冻结 WorldSnapshot_t，所有同一 decision_time 的 observation 基于同一快照。
5. 基于 snapshot 计算 online_risk_predecision_t，R1 时进入 observation。
6. 并行构造 observation，并行请求 LLM / rule / replay。
7. 解析 raw response，执行 schema retry；失败则生成 neutral_stop ParsedCommand。
8. safety/intervention pipeline 同步生成所有 crane 的 ExecutedCommand。
9. 对未重新决策的 crane 检查 command expiry / stale policy，必要时 neutral_stop。
10. low-level controller 将 ExecutedCommand 转成 ControlTarget。
11. physics/kinematics step 到 state_{t+dt}。
12. task state machine 基于 state_{t+dt} 更新阶段、挂载/卸载、任务事件。
13. risk_now 与 collision detection 基于 state_{t+dt} 计算；collision 生成 terminal event。
14. recorder 写入 frame、trajectory、pair risk、events、commands，WebSocket 推送 SimFrame。
15. 若 terminal status 或 completion cooldown 满足条件则结束；否则 t += dt。
```

约定：

- LLM observation 使用 step 前的 frozen snapshot。
- `trajectories.parquet` 和 `visual/frames.jsonl` 中的普通帧默认表示 step 后状态。
- 任务完成、collision、near_miss 等事件的 `time_s/frame` 归属为检测到该事件的 step 后帧。
- offline future label 在 episode 完成后批量回填，不影响在线记录。

### 0.7.9 Replay 严格复现合同

Replay 不是“重新问一遍 LLM”，而是按历史执行命令重放。

1. `command_replay.jsonl` 保存 `ExecutedCommand`，不是 raw command，也不是 ParsedCommand。
2. replay 默认要求 `resolved_config_hash`、`command_schema_version`、`physics_schema_version`、`operator_assignment_hash` 一致；不一致则 startup error。
3. replay 不调用 LLM，也不调用 summary LLM；历史 summary 只作为日志/展示读取，不影响命令。
4. replay 时可以运行机械安全校验，但必须是 audit-only。若 audit 结果会改变历史 `ExecutedCommand`，记录 `replay_mismatch` 并按 `failed_replay_mismatch` 终止。
5. S2/S3 干预结果已固化在历史 `ExecutedCommand` 中，replay 不得再次叠加干预。
6. replay 必须检查每个 `decision_index + time_s + crane_id` 是否存在唯一命令；缺失或重复为 replay mismatch。
7. replay 的浮点确定性按容差判断，例如：

```yaml
replay:
  strict: true
  require_resolved_config_hash_match: true
  position_tolerance_m: 1.0e-5
  angle_tolerance_rad: 1.0e-7
  velocity_tolerance: 1.0e-6
```

8. 若允许 `allow_config_mismatch=true`，该 replay 只能用于调试展示，不得标记为可复现实验数据。

### 0.7.10 前端与后端责任边界

1. 后端 simulation engine 是唯一物理与风险权威。
2. 前端只能渲染 `SimFrame`、manifest、summary、commands、events。
3. 前端可以计算鼠标悬停距离、屏幕辅助线、局部 display-only clearance，但必须标记为 `display_only`，不得保存为训练标签。
4. 前端不得把实时 UI 计算的风险等级作为 `pair_risks.parquet` 真值。
5. 实时 WebSocket 不得包含 offline future labels。
6. 离线回放可以显示 `future_min_clearance`、future risk label，但 UI 必须标注“离线标签/事后分析”。
7. 前端上传配置只触发后端 validate；权威校验、默认值补全、schema migration 都在后端完成。
8. 前端不能直接写 run 目录中的权威数据文件；用户标注或备注必须写入单独 annotation 文件。

### 0.7.11 数据 schema 演进与权威文件

Schema 采用 `major.minor.patch` 或等价版本策略：

- patch：文档说明、非结构性修正；
- minor：向后兼容字段新增、可空字段新增、summary 指标新增；
- major：字段删除、单位改变、枚举语义改变、坐标含义改变。

字段与枚举要求：

1. 所有枚举集中定义在 `schemas/enums.py` 和 `docs/data_schema.md`，前后端通过生成代码或共享 schema 同步。
2. nullable 字段必须明确为 JSON `null` 或 Parquet nullable column；不得用空字符串混代 null。
3. 旧 Parquet 缺失新增列时，loader 可按 schema migration 填充 null/default，并记录 migration warning。
4. 任何单位改变必须升 major version。
5. 同一语义字段跨文件重复时，必须指定权威来源。

权威文件划分：

| 文件 | 权威内容 |
|---|---|
| `config/resolved_config.yaml` | 配置、默认值、自动布局、operator 分配、seed、provider 脱敏信息 |
| `data/trajectories.parquet` | 每帧每塔吊训练用物理状态权威 |
| `data/pair_risks.parquet` | 每帧每塔吊对距离、TTC、风险标签权威 |
| `data/graph_edges.parquet` | STGNN 物理先验边特征权威 |
| `logs/commands.jsonl` | 操作行为、parsed/executed command、intervention 权威 |
| `replay/command_replay.jsonl` | replay 执行命令权威 |
| `logs/events.jsonl` | 离散事件权威 |
| `visual/frames.jsonl` | 前端展示帧权威，不作为训练真值替代 trajectories |
| `visual/episode_manifest.json` | 回放索引、资源路径、帧范围、UI 元数据权威 |
| `metadata/episode_summary.json` | 单 episode 指标权威 |
| `metadata/dataset_summary.json` | 数据集聚合指标权威 |

坐标重复时：训练与标签以 `trajectories.parquet` / `pair_risks.parquet` 为准；展示以 `visual/frames.jsonl` 为准；静态几何以 `resolved_config.yaml` 为准。若三者冲突，质量检查必须报错。

### 0.7.12 规则司机能力边界

`rule_operator` 第一版定位为工程验证和 baseline，不是人类观测等价 baseline。

```text
rule_operator_v1 保证：
  - easy_task 可完成率达到验收目标；
  - overlap_task 尽量避开明显碰撞；
  - stress_task 不保证完成；
  - 不模拟 operator profile 性格；
  - 不使用未来标签、offline TTC 或 future_min_distance；
  - 可以使用比 LLM 更干净的当前几何观测，但必须记录 operator_mode=rule。
```

若用于 LLM 对照实验，报告中必须说明 rule baseline 的观测边界；若用于任务生成合理性验证，可以允许其读取完整当前几何状态，但不能读取未来真实轨迹。

### 0.7.13 MVP 拆分为 M0-M5

MVP 总范围不删减，但开发交付应拆成更小 milestone，避免一次性实现后端、前端、LLM、数据集和 STGNN 转换导致边界发散。

| Milestone | 目标 | 可验收产物 |
|---|---|---|
| M0 配置 + 运动学 + controller + recorder 骨架 | 跑通无任务单塔/多塔状态更新和基础导出 | fixed/manual layout、CraneState、ControlTarget、trajectories、visual frames、基础测试 |
| M1 布局 + 任务 + 规则司机 + 当前风险距离 | 形成无 LLM 可完成任务仿真 | auto layout、easy/overlap/stress task、rule_operator、risk_now、events |
| M2 episode 调度 + replay + visual frames | 形成可复现 episode 数据闭环 | single-frame lifecycle、command_replay、resolved_config_hash、offline replay、manifest |
| M3 LLM observation / command / provider | 接入真实 LLM 并稳定失败策略 | observation schema、DeepSeek/MiniMax/mock/replay、retry、neutral_stop、commands log |
| M4 FastAPI + 前端离线回放 | 支持可视化质检与交互启动 | REST/WS、React/Three.js、timeline、event jump、command panel |
| M5 dataset builder + STGNN window | 支撑论文训练数据 | train/val/test split、offline labels、graph_edges、window slicing、dataset_summary |

每个 milestone 都必须能运行测试并产生可检查文件，不允许只提交不可运行的中间代码。

---


## 0.8 实施级补充合同

本节把 v0.3 中仍偏原则性的内容进一步压成可落代码的工程规则。实现时若 A-P 模块章节和本节出现差异，以本节为准，并在对应模块章节同步更新。

### 0.8.1 领域对象与 schema 单一事实源

后端 Pydantic model 是领域对象 schema 的唯一事实源。所有 JSON Schema、OpenAPI schema、TypeScript 类型、前端校验类型、离线回放帧类型都必须从同一套 Pydantic model 或其导出的 JSON Schema 派生，不得在前端和后端分别手写一套结构。

推荐生成链路：

```text
backend/app/schemas/*.py
  -> pydantic model_json_schema()
  -> schemas/json/*.schema.json
  -> frontend/src/types/generated/*.ts
  -> frontend runtime validators
```

实现规则：

- Pydantic model 必须集中定义枚举值；
- `schema_version` 必须是所有落盘对象和 WebSocket 对象的必填字段；
- 前端只能消费生成的 TypeScript 类型，业务代码不得重新定义同名接口；
- schema 变更必须更新 `docs/data_schema.md` 和迁移说明；
- 训练数据转换脚本只读取公开 schema 字段，不能依赖 Python 内部对象私有字段；
- 所有外部输入先进入 `Raw*` 对象，再转换为 `Resolved*` 或 `Parsed*` 对象。

最低对象层级：

```text
RawScenarioConfig -> ScenarioConfig -> ResolvedScenarioConfig
RawExperimentConfig -> ExperimentConfig -> ResolvedExperimentConfig
RawLLMResponse -> ParsedCommand -> ExecutedCommand -> ControlTarget
WorldState -> WorldSnapshot -> Observation -> LLM messages
FrameRecord -> SimFrame -> visual/frames.jsonl 或 WebSocket frame
EpisodeRecords -> OfflineRiskLabel -> DatasetWindow
```

### 0.8.2 写权限、读权限与不可越权规则

每个模块只允许写自己负责的对象。需要跨模块使用的信息时，只能读取对方公开对象，不能调用对方内部状态。

```text
ConfigManager:
  写 ScenarioConfig / ExperimentConfig / DatasetConfig / ResolvedConfig。
  禁止写 CraneState、Task runtime、FrameRecord。

LayoutBuilder:
  读 ScenarioConfig.site / crane_models / layout。
  写 CraneConfig、layout_diagnostics、overlap_zones。
  禁止写 runtime CraneState。

TaskManager:
  读 ResolvedConfig、CraneConfig、CraneState、ExecutedCommand。
  写 Task.status、Crane.task_stage、load_attached、task events。
  禁止修改几何物理状态 theta/trolley/hook。

Operator / LLMProvider:
  读 Observation。
  写 RawLLMResponse 与 ParsedCommand。
  禁止写 ExecutedCommand、ControlTarget、CraneState。

SafetyPipeline:
  读 ParsedCommand、CraneState、Task、OnlineRisk。
  写 ExecutedCommand、intervention events。
  禁止直接积分物理状态。

Controller:
  读 ExecutedCommand、CraneState、CraneModelSpec。
  写 ControlTarget。
  禁止修改 Task.status。

PhysicsEngine:
  读 ControlTarget、CraneModelSpec、dt。
  写 CraneState。
  禁止读取 LLM raw response 或 future label。

RiskEngine:
  online 模式读当前 WorldSnapshot 与 ExecutedCommand，写 OnlineRisk。
  offline 模式读完整轨迹，写 OfflineRiskLabel。
  禁止把 OfflineRiskLabel 传回 Observation。

Recorder:
  读公开 runtime 对象并落盘。
  禁止改变仿真结果。

Frontend:
  读 SimFrame / summaries / logs。
  禁止重算训练真值，禁止修改物理状态。
```

### 0.8.3 统一错误码命名空间

所有错误、warning、diagnostic 都必须使用稳定错误码。错误码只新增不复用；废弃错误码保留说明，不重新赋义。

命名格式：

```text
{DOMAIN}_{SEVERITY}_{NNN}
```

其中 `DOMAIN` 建议取值：

```text
CFG     配置与 schema
LAY     布局与型号
TASK    任务生成与任务状态机
OP      rule/mock/operator 抽象
LLM     LLM provider、结构化输出、超时、重试
SAFE    基础机械安全、deadman、emergency_stop、intervention
RISK    online risk / offline label / 碰撞距离
PHYS    物理积分、状态越界、NaN、Inf
REC     记录器、文件写入、Parquet/JSONL
REPLAY  replay 一致性与 hash
API     FastAPI 请求响应
DATA    dataset builder / STGNN window
UI      前端展示与 WebSocket
```

`SEVERITY` 建议取值：

```text
E  error，导致启动失败、task failed、operator failure 或 episode failed
W  warning，继续运行但必须记录
D  diagnostic，调试信息，不影响状态
```

最低错误矩阵：

```text
CFG_E_001  scenario.yaml schema 校验失败 -> startup_error，不启动。
CFG_E_002  experiment.yaml schema 校验失败 -> startup_error，不启动。
CFG_E_003  resolved_config_hash 缺失或不可计算 -> startup_error，不启动。
LAY_E_001  auto layout 在 max_sampling_attempts 内失败 -> startup_error，不启动 episode。
LAY_E_002  manual crane 越界或落入 forbidden zone -> startup_error，不启动 episode。
TASK_E_001 task pickup/dropoff 不可达 -> startup_error 或 task skipped，取决于 generation 阶段。
TASK_E_002 task 天然超载或超力矩 -> startup_error 或重新采样；不得进入正常 episode。
TASK_E_101 attach_stage_timeout -> task_failed，默认 episode 继续。
TASK_E_102 release_stage_timeout 且 load_attached=false -> task_failed，episode 继续。
TASK_E_103 release_stage_timeout 且 load_attached=true -> task_failed，并进入 recovery_release。
TASK_W_201 deadline_missed -> episode_event，继续运行。
LLM_E_001 provider timeout -> operator_runtime_failure，本周期 neutral_stop。
LLM_E_002 invalid structured output -> retry；超过 retry 后 neutral_stop。
LLM_E_003 consecutive failures 超阈值 -> episode_failed，episode_status=llm_failed。
SAFE_W_001 moment_limit / overload_prevented -> episode_event，动作被限制。
SAFE_E_002 emergency_stop_latched 且未 reset -> command rejected，保持停止。
RISK_W_001 near_miss -> episode_event，继续运行。
RISK_E_002 collision -> episode_failed，episode_status=failed_collision。
PHYS_E_001 NaN/Inf -> episode_failed，episode_status=failed_invalid_state。
PHYS_E_002 state jump 超阈值 -> episode_failed 或 data_quality_failed，按配置。
REPLAY_E_001 resolved_config_hash mismatch -> replay startup_error。
REPLAY_E_002 executed_command mismatch -> failed_replay_mismatch。
REC_E_001 required output file write failed -> episode_failed 或 run_failed。
DATA_E_001 train/val/test 存在 episode 泄漏 -> dataset build failed。
API_E_001 invalid request payload -> HTTP 422，使用统一错误响应结构。
UI_W_001 WebSocket dropped frame -> display warning，不影响后端 truth。
```

### 0.8.4 失败处理决策树

实现时先判断失败发生位置，再决定影响范围：

```text
配置解析、schema 校验、manual layout 校验、任务天然不可达、天然超载:
  startup_error，episode 不启动。

LLM 单次 timeout / invalid output / provider 5xx:
  operator_runtime_failure，当前决策 neutral_stop，记录 retry 与失败原因。

LLM 连续失败超过 max_consecutive_failures:
  episode_failed，episode_status=llm_failed。

attach/release 请求条件不满足:
  episode_event，拒绝请求，任务继续。

attach/release 阶段长时间无进展:
  task_failed，默认 episode 继续；若仍带载进入 recovery_release。

deadline missed:
  warning/event，不改变任务状态。

forbidden zone task_only violation:
  episode_event，继续运行。

forbidden zone hard violation:
  按配置阻止动作或 episode_failed。

near_miss / high risk:
  episode_event，继续运行。

geometry collision:
  episode_failed，立即终止。

NaN / Inf / 物理状态不可恢复越界:
  episode_failed，立即终止。

recorder 写入失败:
  默认 episode_failed，避免生成不完整训练数据。

前端显示错误:
  不影响后端 truth，除非 API 主动 stop episode。
```

### 0.8.5 事件生命周期、去重与聚合

事件分为三类：

```text
instant:
  单点事件，例如 task_started、task_completed、horn_event、llm_timeout。

stateful:
  有进入、持续、解除过程的事件，例如 risk_entered、near_miss、forbidden_zone_violation、overlap_zone_shared。

sampled:
  每帧都可计算的状态，例如 risk_level_now、clearance_min_now_m，不应每帧都重复写成 event。
```

stateful event 必须使用统一 lifecycle：

```json
{
  "schema_version": "1.0",
  "event_id": "EVT_000123",
  "event_type": "near_miss",
  "lifecycle": "enter",
  "event_key": "near_miss:C1:C2:jib-hook",
  "episode_id": "E001",
  "frame": 120,
  "time_s": 6.0,
  "crane_ids": ["C1", "C2"],
  "severity": "warning",
  "details": {
    "clearance_min_now_m": 1.1,
    "nearest_object_type": "jib-hook"
  }
}
```

聚合规则：

- `event_key` 决定同一持续事件是否已经存在；
- 进入阈值与解除阈值应允许 hysteresis，避免风险等级抖动导致大量 enter/exit；
- 持续事件可每 `event_update_interval_s` 写一次 `lifecycle=update`，默认 1s；
- 解除时写 `lifecycle=exit`，记录 duration；
- instant event 不需要 exit；
- cooldown 用于防止同一瞬时事件在短时间内重复刷屏；
- Parquet 主表仍是逐帧权威，events.jsonl 只记录离散解释性事件。

建议默认：

```yaml
events:
  stateful_update_interval_s: 1.0
  duplicate_cooldown_s:
    horn_event: 1.0
    ignored_risk_hint: 2.0
    idle_unnecessary_motion: 5.0
  hysteresis_m:
    risk_level: 0.3
    near_miss_exit_margin: 0.5
```

### 0.8.6 任务失败恢复与 recovery_release 合同

只要 `load_attached=true`，塔吊不得直接开始普通下一任务。当前任务失败但仍带载时，TaskManager 必须创建或激活恢复阶段：

```text
Crane.task_stage = recovery_release
Task.status = failed
RecoveryTask.status = active
```

`recovery_release` 的目标是把当前载荷安全卸下，而不是完成原任务。恢复目标选择顺序：

```text
1. 当前任务 dropoff 点，如果仍可达、未进入 hard forbidden zone，且力矩允许；
2. 当前 load_type 可接受的最近 work_zone 安全点；
3. 当前 load_type 可接受的最近 material_zone 安全点；
4. 配置中的 emergency_drop_zone；
5. 若以上都不存在，episode_status=failed_recovery_blocked。
```

恢复规则：

- recovery task 必须写入 tasks.parquet，字段 `task_type=recovery_release`；
- recovery task 的 `source_failed_task_id` 必填；
- LLM observation 必须明确“当前处于恢复卸载，不再追求原任务 deadline”；
- recovery task 不计入普通任务完成率，但计入 recovery 成功率；
- recovery_release 成功后 `load_attached=false`，塔吊进入 idle，之后才能启动下一普通任务；
- 若 recovery_release 也 timeout，默认 episode_status=failed_recovery_timeout；
- 可配置 `recovery_policy=terminate_episode`，用于不希望产生恢复片段的数据集。

建议配置：

```yaml
tasks:
  recovery:
    enabled: true
    policy: "attempt_safe_release"  # attempt_safe_release / terminate_episode
    recovery_release_timeout_s: 180
    emergency_drop_zones: []
```

### 0.8.7 neutral_stop、deadman 与 emergency_stop 精确定义

`neutral_stop` 是平滑制动命令，不是急停。它应被转换为：

```json
{
  "schema_version": "1.0",
  "command_source": "system_neutral_stop",
  "left_joystick": {
    "slew": {"direction": "neutral", "gear": 0},
    "trolley": {"direction": "neutral", "gear": 0}
  },
  "right_joystick": {
    "hoist": {"direction": "neutral", "gear": 0}
  },
  "deadman_pressed": true,
  "emergency_stop": false,
  "horn": false,
  "command_duration_s": 1.0,
  "task_action": "none",
  "attention_target": "hold_position",
  "confidence": 1.0,
  "reason": "system neutral stop"
}
```

规则：

- command 到期且无新命令：进入 neutral_stop；
- LLM 单次失败并超过 retry：进入 neutral_stop；
- `deadman_pressed=false`：当前命令周期所有运动轴无效，控制器按安全制动减速；默认不锁存；
- `emergency_stop=true`：使用 emergency deceleration；默认只影响当前命令周期；
- 若配置 `emergency_stop_latched=true`，必须收到 `reset_emergency_stop` API 或 episode reset 后才能接受非 neutral 命令；
- `task_action=request_attach/release` 在 neutral_stop 中一律为 none；
- neutral_stop 不改变 Task.status，也不自动完成任务。

### 0.8.8 Replay 与确定性容差

Replay 的目标是复现执行后的仿真结果，而不是复现 LLM 文本生成过程。

硬规则：

- `command_replay.jsonl` 保存 `ExecutedCommand`，不是 `ParsedCommand`；
- replay 默认要求 `resolved_config_hash` 完全一致；
- replay 不调用 operator LLM，也不调用 summary LLM；
- replay 可重新运行机械安全层做 audit，但 audit 不得改变命令；
- replay 中 `ExecutedCommand` 与历史文件不一致时，立即 `failed_replay_mismatch`；
- replay 输出轨迹与原轨迹超过容差时，立即 `failed_replay_mismatch`。

建议默认容差：

```yaml
replay:
  require_resolved_config_hash_match: true
  audit_safety_pipeline: true
  allow_command_rewrite: false
  tolerances:
    time_s_abs: 1.0e-9
    theta_rad_abs: 1.0e-7
    trolley_r_m_abs: 1.0e-6
    hook_h_m_abs: 1.0e-6
    position_m_abs: 1.0e-5
    clearance_m_abs: 1.0e-4
```

`resolved_config_hash` 计算时必须排除：run 创建时间、输出目录、脱敏后的 API key 字符串、日志路径等不影响仿真的字段；必须包含：布局结果、任务队列、operator 分配、weather seed、risk/safety mode、controller 参数、schema version。

### 0.8.9 数据质量门禁

每个 episode 结束后必须运行数据质量检查。未通过的数据不得进入正式 dataset，只能进入 quarantine 目录。

最低门禁：

```text
schema_valid:
  所有 JSONL / Parquet / manifest 能按 schema 读取。

time_monotonic:
  frame 单调递增，time_s = frame * dt 或在容差内一致。

frame_completeness:
  每帧有 N 条 trajectories，每帧有 N*(N-1)/2 条 pair_risks。

no_nan_inf:
  所有核心浮点字段无 NaN / Inf。

mechanical_limits_respected:
  theta_dot、trolley_r、hook_h、load moment 不越界。

geometry_consistency:
  root/tip/hook 坐标和 theta/trolley/hook_h 可重构一致。

online_offline_separation:
  observation 和实时 SimFrame 不含 offline future labels。

replay_ready:
  命令日志、resolved_config_hash、command_replay 完整。

event_consistency:
  collision event 与 episode_status 对齐；task_completed 与 Task.status 对齐。

dataset_leak_check:
  train/val/test 按 episode 或 scenario 切分，无窗口级随机泄漏。
```

输出：

```json
{
  "schema_version": "1.0",
  "episode_id": "E001",
  "quality_status": "passed",
  "failed_checks": [],
  "warnings": ["high_risk_ratio_lower_than_target"],
  "metrics": {
    "num_frames": 12000,
    "num_cranes": 4,
    "max_state_jump_m": 0.12,
    "min_clearance_over_episode_m": 1.9
  }
}
```

### 0.8.10 dataset 风险比例目标与采样策略

数据集构建器可以配置目标风险比例，但目标是“生成后筛选与重采样的统计目标”，不是强行制造风险的物理规则。

建议配置：

```yaml
dataset_targets:
  episode_status:
    completed_min_ratio: 0.70
    failed_collision_max_ratio: 0.10
    llm_failed_max_ratio: 0.10
  risk_frame_ratio:
    high_min: 0.03
    high_max: 0.20
    near_miss_min: 0.005
    near_miss_max: 0.08
  task_mix:
    easy_task: 0.35
    overlap_task: 0.40
    stress_task: 0.25
  operator_mix:
    normal: 0.30
    conservative: 0.20
    aggressive: 0.20
    novice: 0.15
    fatigued: 0.15
  quarantine:
    include_llm_failed: false
    include_failed_invalid_state: false
```

实现规则：

- batch generator 可通过 layout overlap、task_type、deadline、operator profile、visibility 调整分布；
- 不得通过穿模、关闭机械限制或伪造标签提高正样本比例；
- collision episode 可以保留用于碰撞预警研究，但必须上限控制，避免训练集被异常终止轨迹主导；
- dataset_summary 必须报告目标值、实际值、差距和被 quarantine 的 episode 数量。

### 0.8.11 FastAPI 统一错误响应

所有 REST API 错误响应使用同一结构：

```json
{
  "schema_version": "1.0",
  "error": {
    "code": "CFG_E_001",
    "message": "scenario.yaml schema validation failed",
    "severity": "error",
    "category": "startup_error",
    "details": {
      "field": "layout.num_cranes",
      "reason": "must be >= 1"
    },
    "correlation_id": "REQ_20260610_000001"
  }
}
```

规则：

- 422 用于请求 payload/schema 错误；
- 409 用于 episode 状态冲突，例如已停止 episode 不能 resume；
- 500 只用于未捕获内部错误，内部错误也必须落盘；
- API 不返回完整 API key、完整 LLM prompt 或原始大文件内容；
- 下载接口只返回 run artifact，不动态拼接未校验路径；
- WebSocket 错误也使用同样 error payload。

### 0.8.12 配置与密钥治理

配置治理规则：

- `api_key` 和 `api_key_env` 同时存在时，优先 `api_key`，但落盘只保存 `key_source=inline` 与脱敏 `key_masked`；
- 不允许把完整 key 写入 `resolved_config.yaml`、logs、dataset_summary、frontend payload；
- 所有路径必须解析到 run workspace 内部，防止路径穿越；
- run metadata 保存代码版本、schema version、git commit、python/package lock 摘要；
- demo 配置不得包含真实 API key；
- 若使用真实 API 生成数据，dataset_summary 必须记录 provider/model/temperature，但不记录 key。

### 0.8.13 测试分层与 CI 门禁

测试分为五层：

```text
unit:
  几何、控制器、状态机、schema、错误码、risk threshold。

contract:
  Pydantic schema、TypeScript schema、API error response、SimFrame 兼容性。

integration:
  M0-M5 每个阶段的最小 episode、replay、导出、离线回放。

data_quality:
  Parquet/JSONL 读取、字段完整、无泄漏、risk 分布、replay mismatch。

visual_smoke:
  前端加载 demo_episode，时间轴、风险线、事件跳转、命令展开可用。
```

最低 CI 门禁：

```text
pytest backend/app/tests
python scripts/run_episode.py --scenario configs/scenario_smoke.yaml --experiment configs/experiment_rule_smoke.yaml
python scripts/replay_episode.py --run runs/smoke/latest
python scripts/validate_run_artifacts.py --run runs/smoke/latest
npm run typecheck
npm run test
```

### 0.8.14 M0-M5 退出条件

M0-M5 不只是开发顺序，还必须作为验收闸门。后续阶段不得绕过前一阶段失败。

```text
M0 退出条件:
  1 台塔吊、规则 neutral、20Hz、300s，无 NaN/Inf；
  controller 档位、限位、moment limit 单元测试通过；
  trajectories.parquet 和 visual/frames.jsonl 可读。

M1 退出条件:
  3 台塔吊 auto layout，可复现；
  easy_task 规则司机完成率 >= 80%；
  当前风险距离与 overlap events 可记录。

M2 退出条件:
  episode scheduler 固化单帧生命周期；
  command_replay 使用 ExecutedCommand 完成严格 replay；
  SimFrame 离线回放可加载；
  quality_report passed。

M3 退出条件:
  mock/replay/deepseek/minimax provider contract 完成；
  LLM schema retry、timeout、neutral_stop、consecutive failure 流程可测；
  observation 不含 offline label 的自动测试通过。

M4 退出条件:
  FastAPI 可启动/停止/下载 episode；
  React 离线回放稳定；
  WebSocket 与 frames.jsonl 共用同一 SimFrame schema；
  前端显示的 display-only 计算不会写回训练数据。

M5 退出条件:
  batch_generate 可生成多 scenario 多 episode；
  train/val/test 按 episode/scenario 划分；
  dataset_summary、quality_summary、STGNN windows 可生成；
  dataset_leak_check passed。
```

### 0.8.15 仍需后续补充但不阻塞 M0-M2 的事项

以下内容建议保留为后续迭代，不应阻塞第一轮工程骨架：

```text
真实塔吊厂家 load chart 与参数来源；
简化吊物摆动模型；
真实风载动力学；
更高保真禁区几何和建筑 BIM 导入；
多塔全局协调员 Agent；
真实工地数据校准；
强化学习或 imitation learning operator；
更复杂的人类视觉遮挡模型；
论文最终模型的窗口长度、采样比例和具体损失函数。
```

但以下内容不能后移，必须在 M0-M2 中完成：

```text
schema_version；
resolved_config_hash；
命令链路对象；
单帧生命周期；
基础机械安全；
replay；
数据质量门禁；
online/offline 严格隔离；
前端只读边界。
```

---

## 1. 技术路线总览

### 1.1 推荐总体架构

采用“后端仿真核心 + 数据导出 + Web 3D 前端展示”的前后端分离方案。

```text
scenario.yaml / experiment.yaml
        ↓
Python Simulation Core
        ├── 塔吊运动学/动力学模型
        ├── 任务生成模块
        ├── 天气与可见度模块
        ├── LLM 操作员 Agent
        ├── 基础安全设施层
        ├── 风险影子评估层
        ├── 低层控制器
        ├── 数据记录器
        └── 风险标签生成器
        ↓
FastAPI Backend
        ├── REST：创建场景、运行仿真、查询数据
        ├── WebSocket：实时推送仿真帧
        └── 文件服务：轨迹 Parquet / JSONL / 元数据
        ↓
React + TypeScript + Three.js Frontend
        ├── 3D 塔吊场景展示
        ├── 实时播放/离线回放
        ├── 风险距离线、风险等级、轨迹尾迹
        ├── LLM 指令日志展示
        └── 数据集导出入口
```

### 1.2 推荐技术栈

#### 后端与仿真核心

- Python 3.11+
- NumPy / SciPy：运动学、几何计算、距离计算
- Pydantic：配置、状态、命令、数据 Schema 校验
- FastAPI：后端 API 与 WebSocket 服务
- asyncio / Celery / RQ：异步 LLM 请求与仿真任务调度
- PyArrow / Pandas：Parquet 数据导出
- SQLite 或 PostgreSQL：实验元数据管理
- Hydra 或 YAML 配置系统，用于批量实验配置
- PyTorch / PyTorch Geometric，用于后续轨迹预测模型训练接口

#### 物理/仿真引擎建议

优先级从高到低：

1. **自建参数化运动学/动力学仿真器**  
   推荐作为主数据生成器。塔吊起重臂运动主要受回转角、回转速度、角加速度、臂长、塔高和小车幅度约束，自建模型速度快、可控性强、易于生成大规模训练数据。

2. **PyBullet / Bullet**  
   用于几何碰撞、刚体检测、简单可视化或结果校核。适合 Python 快速原型，但不建议把所有数据生成完全依赖 PyBullet。

3. **MuJoCo**  
   适合需要更稳定的多关节刚体动力学、接触、绳索/摆动近似建模时使用。适合作为增强实验或吊物摆动验证。


#### 前端

推荐：

- React + TypeScript + Vite
- Three.js 或 React Three Fiber
- Zustand / Redux Toolkit：前端状态管理
- ECharts / Plotly：曲线、风险指标、轨迹误差展示
- WebSocket：实时接收仿真帧
- glTF/GLB：塔吊模型资源格式

备选：

- Babylon.js：如果希望前端具备更完整的 3D 引擎能力、GUI、物理插件和 WebXR 支持，可用 Babylon.js 替代 Three.js。
- Unity WebGL：如果已有 Unity 资源和熟悉 Unity，可作为展示端，但与 Python 后端数据管道集成复杂度更高。

#### LLM 接入

- 必须使用结构化输出：JSON Schema / Pydantic Schema；
- 第一版必须真实调用 DeepSeek 与 MiniMax API；
- 必须支持可扩展 provider 抽象，便于后续增加更多厂商和模型；
- 必须支持异步调用、超时、重试、缓存与重放；
- 必须支持 mock provider 和 replay provider，用于测试与复现；
- 必须保存 LLM observation、messages、raw response、parsed command、executed command、latency、token_usage、validation_errors；
- 禁止让 LLM 直接输出连续力矩、连续速度或直接修改物理状态。

---

## 2. 系统核心设计原则

### 2.1 LLM 只做低频高层决策

不要让 LLM 每一帧控制塔吊。采用：

```text
物理仿真频率：20 Hz 或 50 Hz
低层控制器频率：5 Hz 或 10 Hz
LLM 决策频率：0.5 Hz 或 1 Hz，或事件触发
```

LLM 输出真实塔吊风格的高层手柄操作意图，例如：

```json
{
  "left_joystick": {
    "slew": {"direction": "right", "gear": 2},
    "trolley": {"direction": "out", "gear": 1}
  },
  "right_joystick": {
    "hoist": {"direction": "neutral", "gear": 0}
  },
  "deadman_pressed": true,
  "emergency_stop": false,
  "horn": false,
  "command_duration_s": 1.0,
  "task_action": "none",
  "attention_target": "pickup_area",
  "confidence": 0.76,
  "reason": "取货点在右前方，但2号塔吊接近重叠区，因此低速右转并保持观察。"
}
```

低层控制器负责将该离散手柄命令转换为连续速度/加速度指令。

### 2.2 保留基础安全设施，但不要过度过滤多塔风险

系统必须区分：

```text
基础塔吊安全设施：硬约束，必须执行
多塔碰撞风险评估：默认只提示、记录和标注，不强制干预
```

基础安全设施包括：

- 最大回转速度限制
- 最大角加速度限制
- 小车行程范围
- 起升高度范围
- 起重量/力矩限制
- 机械限位
- 任务挂载/卸载判定

多塔碰撞风险包括：

- 未来最小距离
- TTC
- 风险等级
- 是否进入临界接近
- 是否发生碰撞

这些风险默认只进入“风险影子评估层”，用于提示 LLM、记录日志和生成标签，不默认强制停车。可通过安全等级配置启用软干预或强干预。

### 2.3 支持不同安全干预等级

```text
S0 基础安全设施：只保留机械与基础安全约束，不强制修改多塔命令
S1 记录模式：计算风险并记录，不强制干预
S2 软干预模式：高风险时限制速度或限制部分动作
S3 强干预模式：高风险时强制减速/停车
```

是否把风险提示给 LLM 由 R0/R1 observation 模式控制；S0/S1/S2/S3 只描述安全干预等级。主要训练数据建议来自“R0 或 R1 + S1”，S2/S3 用于安全干预对照实验。

### 2.4 数据必须可复现

- 所有随机过程必须可设置 seed
- 所有 LLM 输入输出必须落盘
- 可通过 `replay_mode=true` 使用已保存 LLM 指令复现完全相同轨迹
- 规则司机必须可用于任务合理性验证、mock 数据和对照实验；
- 主 LLM 数据生成模式下，LLM 连续失败默认终止 episode，不默认由规则司机接管。

---

## 3. 模块设计与验收标准

---

### 模块 A：场景配置与实验管理模块

#### A.1 功能

负责读取、校验、保存仿真场景与实验配置。

输入：

- `scenario.yaml`
- `experiment.yaml`
- 命令行参数或 API 参数

输出：

- 标准化场景对象 `ScenarioConfig`
- 标准化实验对象 `ExperimentConfig`
- 运行目录 `runs/{experiment_id}/`

#### A.2 配置文件示例

本修订版推荐使用三文件分层配置。`configs/demo.yaml` 可以作为单文件便捷入口，但加载后必须解析为下面三类配置并写入 resolved config。

##### A.2.1 scenario.yaml 示例

```yaml
schema_version: "1.0"
scenario_id: "site_001"
seed: 20260101

site:
  coordinate_system: "ENU"
  boundary:
    x_min: -100
    x_max: 100
    y_min: -100
    y_max: 100
    z_min: 0
    z_max: 80
  forbidden_zones:
    - zone_id: "building_core"
      type: "box"
      center: [0, 0, 20]
      size: [20, 20, 40]
  material_zones:
    - zone_id: "rebar_yard"
      type: "polygon"
      z_range_m: [0.0, 2.0]
      load_types: ["rebar_bundle", "steel_beam"]
      points:
        - [-80, -80]
        - [-40, -80]
        - [-40, -40]
        - [-80, -40]
  work_zones:
    - zone_id: "floor_10_workface"
      type: "box"
      center: [20, 20, 30]
      size: [30, 30, 4]
      z_range_m: [28, 32]
      accepted_load_types: ["rebar_bundle", "formwork", "concrete_bucket"]
  forbidden_zone_policy:
    mode: "task_only"
    record_violation: true

load_types:
  rebar_bundle:
    display_name: "钢筋束"
    weight_range_t: [1.0, 3.0]
    size_m: [6.0, 1.0, 1.0]
    shape: "box_long"
  formwork:
    display_name: "模板"
    weight_range_t: [0.5, 2.0]
    size_m: [4.0, 2.0, 0.3]
    shape: "flat_box"
  concrete_bucket:
    display_name: "混凝土吊斗"
    weight_range_t: [1.5, 4.0]
    size_m: [1.5, 1.5, 2.0]
    shape: "cylinder"
  steel_beam:
    display_name: "钢梁"
    weight_range_t: [2.0, 5.0]
    size_m: [8.0, 0.5, 0.5]
    shape: "beam"

crane_models:
  - model_id: "generic_flat_top_55m"
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

layout:
  mode: "auto"
  num_cranes: 4
  overlap_level: "medium"
  height_strategy: "mixed"
  coverage_target: "balanced"
  slew_mode_default: "continuous"
  max_sampling_attempts: 500

# layout.mode = "manual" 时使用 cranes 列表。
# cranes:
#   - crane_id: "C1"
#     model_id: "generic_flat_top_55m"
#     base: [0, 0, 0]
#     mast_height_m: 45
#     theta_init_deg: 20
#     slew:
#       mode: "continuous"

tasks:
  assignment_mode: "per_crane_queue"
  generation_mode: "auto"
  num_tasks_per_crane: 5
  queue_policy:
    start_mode: "staggered"
    initial_start_jitter_s: [0, 30]
    inter_task_delay_s: [2, 10]
  task_type_distribution:
    easy_task: 0.4
    overlap_task: 0.35
    stress_task: 0.25
  # pickup/dropoff 高度默认从 material_zones/work_zones 的 z_range_m 采样；
  # 以下字段仅作为 zone 未提供高度时的 fallback。
  fallback_pickup_z_m: 1.5
  fallback_dropoff_z_range_m: [10, 40]
  attach_delay_s: [2, 5]
  release_delay_s: [2, 5]
  priority_distribution:
    low: 0.3
    medium: 0.5
    high: 0.2
  deadline_policy:
    enabled: true
    deadline_miss_is_task_failure: false
  state_machine:
    align_xy_threshold_m: 2.0
    attach_xy_threshold_m: 0.8
    attach_height_threshold_m: 0.5
    release_xy_threshold_m: 1.0
    release_height_threshold_m: 0.7
    safe_transport_height_m: 8.0
    lift_clearance_m: 5.0
    attach_stage_timeout_s: 120
    release_stage_timeout_s: 120
    task_no_progress_timeout_s: 180
    recovery_release_timeout_s: 180
    stage_timeout_policy:
      fail_current_task: true
      terminate_episode: false

weather:
  mode: "schedule"
  wind:
    base_speed_m_s: 6
    gust_speed_m_s: 12
    direction_deg: 90
  visibility:
    base_level: "medium"

risk:
  geometry_envelope:
    jib_radius_m: 0.75
    hook_radius_m: 0.5
    load_radius_m: 1.0
  thresholds_m:
    low: 8.0
    medium: 5.0
    high: 3.0
    near_miss: 1.8
  ttc_threshold_level: "high"
  wind_safe_distance_factor:
    enabled: true
    extra_clearance_per_10m_s_wind_m: 0.5
```

##### A.2.2 experiment.yaml 示例

```yaml
schema_version: "1.0"
experiment_id: "exp_2026_001"
scenario_ref: "configs/scenario_site_001.yaml"
seed: 20260101

sim:
  dt: 0.05
  duration_s: 600
  min_duration_s: 120
  stop_when_all_tasks_done: true
  completion_cooldown_s: 8
  physics_hz: 20
  controller_hz: 20
  llm_decision_interval_s: 1.0

risk_prompt_mode: "R1"   # R0 / R1
safety_mode: "S1"        # S0 / S1 / S2 / S3

runtime:
  mode: "offline_batch"  # offline_batch / offline_replay / interactive_server
  replay_mode: false
  replay_file: null
  llm_cache_enabled: true

operators:
  assignment_mode: "random"
  profile_distribution:
    normal: 0.35
    conservative: 0.2
    aggressive: 0.2
    novice: 0.15
    fatigued: 0.1

llm:
  enabled: true
  provider: "deepseek"
  model: "deepseek-chat"
  base_url: "https://api.deepseek.com"
  api_key_env: "DEEPSEEK_API_KEY"
  api_key: null
  temperature: 0.4
  timeout_s: 8
  max_retries: 2
  max_consecutive_failures: 3
  fallback_policy: "neutral_stop"
  command_duration:
    default_s: 1.0
    min_s: 0.5
    max_s: 3.0
  scheduling:
    mode: "offline_wait"
    stale_command_max_hold_s: 0.5
  structured_output:
    mode: "json_object"
  context:
    history_mode: "long"
    recent_decisions_full: 30
    include_task_history_summary: true
    include_completed_task_summary: true
    include_failed_request_history: true
    include_risk_event_history: true
    summarizer:
      mode: "llm"
      provider: "same_as_operator"
      fallback: "rule"
      trigger:
        every_n_decisions: 20
        context_over_tokens: 12000

output:
  run_root: "runs"
  save_visual_frames: true
  save_parquet: true
  save_replay: true
```

##### A.2.3 dataset.yaml 示例

```yaml
schema_version: "1.0"
dataset_id: "tower_crane_llm_dataset_v1"
run_root: "runs"

sources:
  - scenario_ref: "configs/scenario_site_001.yaml"
    experiment_template_ref: "configs/experiment_llm_s1.yaml"
    num_episodes: 50
  - scenario_ref: "configs/scenario_site_002.yaml"
    experiment_template_ref: "configs/experiment_rule_baseline.yaml"
    num_episodes: 50

split:
  strategy: "by_scenario_and_episode"
  train_ratio: 0.7
  val_ratio: 0.15
  test_ratio: 0.15
  holdout:
    unseen_layout: true
    unseen_num_cranes: true

windows:
  input_steps: 40
  pred_steps: 60
  stride_steps: 5
  risk_label_horizons_s: [5, 10, 15]
  negative_positive_sampling:
    enabled: true
    max_negative_to_positive_ratio: 5

export:
  format: "pt"
  include_metadata: true
  write_dataset_summary: true
```

#### A.3 验收标准

- 能读取并校验 YAML 配置；
- 缺失必要字段时给出明确错误；
- 所有默认值可追溯；
- 每次运行自动生成独立 run 目录；
- 同一 seed + 同一 replay 指令文件可复现相同轨迹；
- 支持 layout.mode = auto 自动生成塔吊布局；
- 支持 layout.mode = manual 手写塔吊布局；
- 不硬编码塔吊数量，按配置创建 N 台塔吊；
- 示例配置至少覆盖 3 台塔吊、每台至少 5 个任务；
- 支持 DeepSeek、MiniMax、mock、replay 四类 LLM provider 配置，并明确其属于 experiment.yaml；
- 支持直接配置 `api_key` 或通过 `api_key_env` 读取 key，运行产物只保存脱敏 key。

---

### 模块 B：塔吊布局与型号库模块

#### B.1 功能

负责生成或读取塔吊布局，并将塔吊型号参数实例化为可仿真的 CraneConfig。

输入：

- 工地区域边界；
- 禁区/建筑区域；
- 塔吊数量；
- 塔吊型号库；
- 布局模式：auto / manual；
- 重叠程度目标：low / medium / high；
- 高度策略：staggered / same_level / mixed；
- seed。

输出：

- 标准化塔吊配置列表；
- 每台塔吊的型号、base、mast_height、jib_length、counter_jib_length、初始角；
- 每对塔吊的作业半径重叠率、根部距离、高度差；
- 布局质量评分和采样诊断信息。

#### B.2 自动布局生成要求

自动布局必须执行：

```text
候选布局生成
  -> site boundary 检查
  -> forbidden_zones 检查
  -> 塔身间距检查
  -> 作业半径覆盖和重叠率计算
  -> mixed 高度策略生成
  -> 任务可达性预检查
  -> 布局质量评分
  -> 重采样或接受
```

自动布局不得只随机生成点后直接使用。若在 `max_sampling_attempts` 内无法找到合格布局，必须给出明确错误，说明失败约束。

#### B.3 手写布局要求

manual 模式下，用户可以在 YAML 中显式给出每台塔吊：

```yaml
cranes:
  - crane_id: "C1"
    model_id: "generic_flat_top_55m"
    base: [0, 0, 0]
    mast_height_m: 45
    theta_init_deg: 20
    slew:
      mode: "continuous"
```

系统必须校验手写布局是否越界、落入禁区、违反塔身最小距离、型号参数不合法等问题。

#### B.4 验收标准

- 支持 auto 和 manual 两种布局模式；
- 默认使用 auto 布局；
- 支持 N 台塔吊，不硬编码 C1/C2/C3；
- 自动布局能生成 low / medium / high 三档重叠程度；
- 默认 `height_strategy=mixed`；
- 支持 `coverage_target=balanced/wide_coverage/dense_overlap`；
- 内置通用塔吊型号库，并允许 YAML 覆盖；
- 输出布局诊断信息，包括 overlap_ratio、height_delta、quality_score；
- 所有自动布局在同一 seed 下可复现；
- 塔吊型号支持半径相关 load chart / rated moment；
- 任务生成与运行时均能校验载重/力矩限制；
- 布局失败时错误信息明确指出失败约束。

---

### 模块 C：塔吊运动学与简化动力学模块

#### C.1 功能

建立塔吊状态更新模型，将 LLM 高层指令通过低层控制器转化为符合塔吊运动约束的连续运动。

#### C.2 状态变量

每台塔吊状态：

```json
{
  "crane_id": "C1",
  "theta_rad": 0.5236,
  "theta_dot_rad_s": 0.01,
  "theta_ddot_rad_s2": 0.0,
  "theta_sin": 0.5,
  "theta_cos": 0.866,
  "trolley_r_m": 25.0,
  "trolley_v_m_s": 0.1,
  "hook_h_m": 20.0,
  "hoist_v_m_s": 0.0,
  "hook_position": [21.65, 12.5, 20.0],
  "cable_length_m": 25.0,
  "load_position": null,
  "swing_angle_rad": 0.0,
  "swing_velocity_rad_s": 0.0,
  "wind_effect_on_swing": null,
  "load_attached": false,
  "load_weight_t": 0.0,
  "task_id": "T_C1_001",
  "task_stage": "move_to_pickup"
}
```

`hook_h_m` 表示吊钩世界坐标高度 z，不是绳长。`cable_length_m`、`load_position`、`swing_angle_rad`、`swing_velocity_rad_s` 在 MVP 中可以为预留字段或简化计算字段，后续用于吊物摆动模型。

#### C.3 坐标系与几何重构

统一坐标系：

```text
ENU 右手坐标系；
x 向右/东，y 向前/北，z 向上；
theta = 0 指向 +x；
theta 正方向为逆时针转向 +y；
内部角度使用 rad，配置和展示可使用 deg。
```

根部坐标：

```math
p_{root,i} = (base_x, base_y, base_z + H_i)
```

臂端坐标：

```math
p_{tip,i}(t) = p_{root,i} + L_i[\cos\theta_i(t), \sin\theta_i(t), 0]
```

吊钩坐标：

```math
p_{hook,i}(t) = [x_i+r_i(t)\cos\theta_i(t), y_i+r_i(t)\sin\theta_i(t), h_i(t)]
```

起重臂线段：

```math
S_i(t) = [p_{root,i}, p_{tip,i}(t)]
```

#### C.4 状态更新

回转角：

```math
\dot{\theta}_{t+\Delta t} = clip(\dot{\theta}_t + a_\theta \Delta t, -\dot{\theta}_{max}, \dot{\theta}_{max})
```

```math
\theta_{t+\Delta t} = \theta_t + \dot{\theta}_{t+\Delta t}\Delta t
```

小车与起升同理：

```math
r_{t+\Delta t}=clip(r_t+v_r\Delta t, r_{min}, r_{max})
```

```math
h_{t+\Delta t}=clip(h_t+v_h\Delta t, h_{min}, h_{max})
```

回转模式：

```text
continuous:
  默认模式，theta_rad 内部连续累积；导出 theta_rad、theta_sin、theta_cos。

limited:
  使用 theta_limit_deg，触及限位时基础安全设施硬限制。
```

#### C.5 验收标准

- 在无控制输入时状态保持稳定；
- 回转角、角速度、角加速度不超过配置限制；
- 小车位置不越界；
- 吊钩高度不越界；
- 臂端坐标与公式一致，单元测试误差小于 `1e-6`；
- 支持至少 20 Hz 仿真频率；
- 支持配置决定的 N 台塔吊同时仿真，MVP 推荐测试范围 2-6 台；
- 运行 600 秒仿真不出现 NaN、Inf 或状态爆炸。

---

### 模块 D：任务生成模块

#### D.1 功能

生成取货点、卸货点、载荷、优先级、截止时间等任务，但不预设完整操作路线。LLM 操作员需要根据任务目标自主完成操作。

#### D.2 任务对象格式

```json
{
  "task_id": "T_C1_001",
  "crane_id": "C1",
  "task_type": "overlap_task",
  "pickup": {"x": 25.0, "y": 20.0, "z": 1.5},
  "dropoff": {"x": -15.0, "y": 40.0, "z": 30.0},
  "pickup_zone_id": "rebar_yard",
  "dropoff_zone_id": "floor_10_workface",
  "planned_start_s": 12.0,
  "load_type": "rebar_bundle",
  "load_weight_t": 2.5,
  "load_size_m": [6.0, 1.0, 1.0],
  "priority": "medium",
  "deadline_s": 180,
  "deadline_missed": false,
  "overtime_s": 0.0,
  "status": "pending"
}
```

#### D.3 任务类型

MVP 必须支持：

```text
easy_task
overlap_task
stress_task
```

任务点允许被多台塔吊作业半径覆盖，但每个任务只分配给一台塔吊。任务生成必须保证任务对被分配塔吊可达，并检查载重/力矩限制。

#### D.4 任务状态与塔吊阶段

为避免任务队列状态和塔吊执行阶段混用，本修订版统一区分两个概念。

任务对象状态 `Task.status`：

```text
pending
active
completed
failed
skipped
```

塔吊当前阶段 `Crane.task_stage`：

```text
idle
move_to_pickup
align_pickup
lower_for_attach
attach_pending
lift_load
move_to_dropoff
align_dropoff
lower_for_release
release_pending
recovery_release
```

`recovery_release` 是 release 失败且仍带载时的内部恢复阶段；该阶段不属于普通任务队列，未卸载前不得开始新的 pickup 任务。

`idle` 表示当前没有 active task，或正在等待 `planned_start_s` / `inter_task_delay_s`。idle 状态下仍然调用 LLM，observation 应提示“当前无任务，应保持塔吊安全静止并观察现场”，但不得透露下一任务信息。LLM 合理输出应为各轴 neutral、gear=0、`task_action=none`，但系统不静默替 LLM 决策。若 idle 状态下输出非 neutral 动作，记录 `idle_unnecessary_motion`。

任务阶段由任务系统状态机根据几何误差、速度、挂载状态、延迟计时和任务结果自动推进。LLM 不得输出 `task_stage`，也不得自报任务完成。LLM 只能通过手柄命令和 `task_action` 请求影响状态机。

#### D.4.1 任务状态机转移条件

```text
Task.status=pending + 到达 planned_start_s 或 inter_task_delay 结束:
  Task.status -> active；Crane.task_stage -> move_to_pickup。

Crane.task_stage=move_to_pickup -> align_pickup:
  吊钩水平距离 pickup 小于 align_xy_threshold。

align_pickup -> lower_for_attach:
  吊钩水平对准 pickup，且吊钩高度仍高于 pickup_z + attach_height_threshold。

lower_for_attach -> attach_pending:
  LLM 输出 task_action=request_attach；
  xy/h 高度误差满足 attach 阈值；
  回转、小车、起升速度均低于 attach_speed_threshold；
  载重/力矩限制满足。

attach_pending -> lift_load:
  attach_delay_s 结束；
  对准和速度条件仍满足；
  系统设置 load_attached=true。

lift_load -> move_to_dropoff:
  吊钩提升到 safe_transport_height_m 或高于 pickup_z + lift_clearance_m。

move_to_dropoff -> align_dropoff:
  吊钩水平距离 dropoff 小于 align_xy_threshold。

align_dropoff -> lower_for_release:
  吊钩水平对准 dropoff，且吊钩高度仍高于 dropoff_z + release_height_threshold。

lower_for_release -> release_pending:
  LLM 输出 task_action=request_release；
  xy/h 高度误差满足 release 阈值；
  回转、小车、起升速度均低于 release_speed_threshold；
  当前 load_attached=true。

release_pending -> completed:
  release_delay_s 结束；
  对准和速度条件仍满足；
  系统设置 load_attached=false；
  Task.status -> completed；Crane.task_stage -> idle 或等待下一任务。

attach 相关阶段超过 attach_stage_timeout_s:
  Task.status -> failed；failure_reason=failed_attach_timeout；
  episode 默认继续，塔吊进入 idle 或等待下一任务。

release 相关阶段超过 release_stage_timeout_s:
  Task.status -> failed；failure_reason=failed_release_timeout；
  如果 load_attached=true，Crane.task_stage -> recovery_release，禁止开始普通下一任务；
  如果 load_attached=false，按 diagnostic 检查是否应修正为 completed 或 failed_invalid_state；
  episode 默认继续，除非进入 failed_invalid_state。
```

状态机阈值必须可配置，并写入 resolved config。第一版建议默认值如下：

```yaml
tasks:
  state_machine:
    align_xy_threshold_m: 2.0
    attach_xy_threshold_m: 0.8
    attach_height_threshold_m: 0.5
    release_xy_threshold_m: 1.0
    release_height_threshold_m: 0.7
    attach_speed_threshold:
      slew_deg_s: 0.3
      trolley_m_s: 0.08
      hoist_m_s: 0.05
    release_speed_threshold:
      slew_deg_s: 0.3
      trolley_m_s: 0.08
      hoist_m_s: 0.05
    safe_transport_height_m: 8.0
    lift_clearance_m: 5.0
    attach_stage_timeout_s: 120
    release_stage_timeout_s: 120
    task_no_progress_timeout_s: 180
    recovery_release_timeout_s: 180
    stage_timeout_policy:
      fail_current_task: true
      terminate_episode: false
```

这些默认值是工程仿真的初始设定，不代表真实工地强制规范。它们的设计目标是：

- 对 LLM 友好，避免因为厘米级对准导致第一版大量卡在挂钩/卸钩；
- 对任务阶段足够明确，能区分“移动到附近”“精细对准”“下降挂钩”“等待挂钩完成”；
- 给后续吊物摆动、视觉误差、吊装工种指挥信号预留调整空间；
- 每次运行必须把实际使用的 resolved threshold 写入 run config，便于复现实验。

#### D.5 任务完成判定

挂载判定：

```math
||p_{hook}^{xy}-p_{pickup}^{xy}|| < \epsilon_{xy}
```

```math
|h_{hook}-h_{pickup}| < \epsilon_h
```

同时 LLM 指令 `task_action=request_attach`，且吊钩/回转/小车速度足够低或停稳，才允许进入 `attach_pending`。等待 `attach_delay_s` 后，若条件仍满足，则 `load_attached=true`。

卸载判定：

```math
||p_{hook}^{xy}-p_{dropoff}^{xy}|| < \epsilon_{xy}
```

```math
|h_{hook}-h_{dropoff}| < \epsilon_h
```

同时 LLM 指令 `task_action=request_release`，且吊钩/回转/小车速度足够低或停稳，才允许进入 `release_pending`。等待 `release_delay_s` 后，若条件仍满足，则 `load_attached=false`，任务完成。

#### D.6 deadline 与 priority

- `priority` 进入 LLM observation 和 prompt，用于模拟任务紧急程度；
- `deadline_s` 进入 LLM observation 和 prompt；
- 超过 deadline 不判定任务失败；
- 超时任务继续执行；
- 数据中必须记录 `deadline_missed` 和 `overtime_s`；
- prompt 必须说明超时会降低任务表现，但不能为了赶时间违反安全和机械约束。

#### D.7 验收标准

- 能为每台塔吊生成多个任务；
- 能生成 easy_task、overlap_task、stress_task；
- stress_task 能在目标点和时序上制造压力，但不预设操作轨迹；
- 支持 simultaneous、staggered、scheduled 三种任务启动方式；
- 任务级 attach/release/no-progress timeout 默认使当前任务失败，但不终止 episode；
- release 失败后若仍带载，必须进入 recovery_release 或 blocked-with-load 状态，不能直接开始下一普通任务；
- pickup 从 material_zones 采样，dropoff 从 work_zones 采样；
- load_type 来自材料库，并受 zone 支持类型约束；
- 任务对象记录 pickup_zone_id、dropoff_zone_id、load_size_m；
- 任务生成必须检查载重/力矩限制，不生成天然超载任务；
- pickup/dropoff 不得落入 forbidden_zones；
- 能生成无冲突、临界接近、高风险任务；
- 不直接给出操作路线；
- 任务完成由仿真器几何条件判定，不由 LLM 自报完成；
- 记录任务开始时间、完成时间、deadline_missed、overtime_s、失败原因；
- 至少 80% 的简单任务可由规则司机完成，用于验证任务生成合理性。

---

### 模块 E：天气与可见度模块

#### E.1 功能

生成风速、风向、阵风、可见度等环境变量。天气一方面影响物理模型或安全阈值，另一方面影响 LLM 操作员的观测信息与决策风格。

#### E.2 输出格式

```json
{
  "time_s": 12.5,
  "wind_speed_m_s": 8.0,
  "wind_gust_m_s": 12.0,
  "wind_direction_deg": 90,
  "visibility_level": "medium",
  "rain_level": "none"
}
```

#### E.3 影响方式

最低要求：

- 风速影响风险提示文本；
- 风速影响吊物摆动或安全距离冗余，若尚未实现吊物摆动，则影响 `d_safe_effective`；
- 可见度影响 LLM 可观察信息，例如隐藏部分邻近吊钩信息；
- 阵风触发更保守的安全建议。

#### E.4 验收标准

- 支持固定天气、分段天气、随机天气；
- 同一 seed 下天气序列可复现；
- LLM observation 中能体现天气和可见度；
- 数据记录中包含每一帧天气状态；
- 可切换是否启用天气扰动；
- 至少支持三档可见度：good / medium / poor。

---

### 模块 F：LLM 操作员观测构造模块

#### F.1 功能

为每台塔吊构造“人类驾驶员可见”的局部观测，而不是全局真值。

#### F.2 观测内容

观测应包含：

1. 自身塔吊状态；
2. 当前任务目标；
3. 当前任务阶段；
4. 取货点/卸货点相对方位；
5. 可见邻近塔吊信息；
6. 风速与可见度；
7. R1 模式下的在线风险提示；
8. 可用双手柄操作；
9. 操作员性格或行为倾向。
10. 当前任务历史摘要、近期操作记录和关键事件摘要。

观测禁止包含邻塔未来意图、邻塔未来目标、完整全局真值、离线 future_min_distance、offline TTC 或任何基于真实未来轨迹的标签。

#### F.3 示例

```json
{
  "operator_id": "OP_C1",
  "crane_id": "C1",
  "time_s": 42.0,
  "operator_profile": "aggressive",
  "risk_prompt_mode": "R1",
  "task": {
    "stage": "move_to_pickup",
    "type": "overlap_task",
    "priority": "high",
    "deadline_s": 180,
    "elapsed_s": 42.0,
    "remaining_recommended_s": 138.0,
    "deadline_missed": false,
    "pickup_relative_direction": "right_front",
    "pickup_distance_m": 18.4,
    "pickup_height_delta_m": -22.0,
    "dropoff_relative_direction": "left_front",
    "signal_hint": "吊钩略偏左，保持低档右回转并准备下降。"
  },
  "self_state": {
    "slew_angle_relative_desc": "朝向目标偏左约15度",
    "slew_motion": "slow_right",
    "trolley_r_m": 24.0,
    "hook_h_m": 31.0,
    "load_attached": false,
  "current_command": {
      "left_joystick": {
        "slew": {"direction": "right", "gear": 1},
        "trolley": {"direction": "neutral", "gear": 0}
      },
      "right_joystick": {
        "hoist": {"direction": "neutral", "gear": 0}
      }
    }
  },
  "visible_neighbors": [
    {
      "crane_id": "C2",
      "relative_direction": "right_front",
      "distance_level": "near",
      "jib_motion": "slow_left",
      "trolley_motion": "out",
      "hoist_motion": "hold",
      "load_attached": true,
      "task_stage": "move_to_dropoff",
      "in_overlap_zone": true
    }
  ],
  "weather": {
    "wind_speed_m_s": 8.0,
    "gust_m_s": 12.0,
    "visibility": "medium"
  },
  "safety_hint": {
    "source": "online_risk",
    "risk_level": "medium",
    "nearest_neighbor": "C2",
    "nearest_object_type": "jib-hook",
    "clearance_now_m": 4.2,
    "estimated_clearance_next_5s_m": 3.1,
    "relative_motion": "closing",
    "confidence": 0.82,
    "suggestion": "slow_down_or_hold"
  },
  "available_actions": {
    "slew_direction": ["left", "neutral", "right"],
    "trolley_direction": ["in", "neutral", "out"],
    "hoist_direction": ["up", "neutral", "down"],
    "gear": [0, 1, 2, 3, 4, 5],
    "deadman_pressed": [true, false],
    "emergency_stop": [true, false],
    "task_action": ["none", "request_attach", "request_release"]
  },
  "memory": {
    "task_history_summary": "本任务开始后已右回转并向外移动小车，取货点距离由约40m降至18m。",
    "recent_decisions": [
      {
        "time_s": 41.0,
        "command_summary": "left joystick right gear2, trolley out gear1",
        "result": "closer_to_pickup"
      }
    ],
    "event_summary": ["没有发生碰撞；上一任务未超时。"]
  }
}
```

#### F.4 验收标准

- 不向 LLM 暴露完整全局真值；
- 可根据可见度隐藏或模糊邻近塔吊/吊钩信息；
- 可向 LLM 暴露邻塔当前状态和当前任务阶段；
- 不向 LLM 暴露邻塔未来意图、目标、路径和任务队列；
- R0/R1 风险提示模式可配置；
- observation 数值必须按配置圆整，并受可见度噪声/模糊影响；
- 禁止把高精度全局真值直接暴露给 LLM；
- 可配置不同操作员性格；
- 每次 LLM 调用前保存 observation；
- observation 可被离线重放；
- observation 字段通过 Pydantic 校验。

---

### 模块 G：LLM 操作员决策模块

#### G.1 功能

LLM 根据观测和任务目标输出结构化高层操作命令。该命令不直接改变仿真状态，必须经过解析、基础安全设施和低层控制器。

#### G.2 LLM Prompt 模板

Prompt 语言策略：

```text
业务说明、任务说明、安全说明、司机性格说明使用中文；
JSON 字段名和枚举值固定使用英文；
禁止输出中文枚举，例如不能把 left 输出成 左；
reason 字段允许中文，用于解释操作理由。
```

系统提示词：

```text
你正在模拟一名真实塔吊司机。你只能根据提供的局部观测、当前任务、可见邻近塔吊状态、天气信息、风险提示模式和操作历史进行决策。你的目标是在保证机械安全和现场安全的前提下尽量按时完成取货、运输和卸货任务。任务超时不会让塔吊停止，也不会让任务自动失败，但超时代表施工效率差，会降低任务表现。你不能为了赶时间违反机械限制或忽视明显碰撞风险。

你只能输出双手柄操作命令，不能输出目标坐标、连续速度、力矩、路径规划或未列出的动作。你必须返回严格 JSON，不要输出 JSON 以外的解释性文本。JSON 字段名和枚举值必须使用英文 schema 中给定的值，不能翻译。
```

用户提示词：

```text
以下是当前观测信息：
{observation_json}

请从 available_actions 中选择下一步双手柄操作，并给出 command_duration_s。你的决策默认执行约 1 秒，可在允许范围内短时微调或持续保持。请考虑任务目标、当前任务阶段、邻近塔吊状态、风速、可见度、deadline、operator profile、操作历史和风险提示。
```

#### G.3 输出 Schema

```json
{
  "type": "object",
  "required": [
    "left_joystick",
    "right_joystick",
    "deadman_pressed",
    "emergency_stop",
    "horn",
    "command_duration_s",
    "task_action",
    "attention_target",
    "confidence",
    "reason"
  ],
  "properties": {
    "left_joystick": {
      "type": "object",
      "required": ["slew", "trolley"],
      "properties": {
        "slew": {
          "type": "object",
          "required": ["direction", "gear"],
          "properties": {
            "direction": {"type": "string", "enum": ["left", "neutral", "right"]},
            "gear": {"type": "integer", "minimum": 0, "maximum": 5}
          },
          "additionalProperties": false
        },
        "trolley": {
          "type": "object",
          "required": ["direction", "gear"],
          "properties": {
            "direction": {"type": "string", "enum": ["in", "neutral", "out"]},
            "gear": {"type": "integer", "minimum": 0, "maximum": 5}
          },
          "additionalProperties": false
        }
      },
      "additionalProperties": false
    },
    "right_joystick": {
      "type": "object",
      "required": ["hoist"],
      "properties": {
        "hoist": {
          "type": "object",
          "required": ["direction", "gear"],
          "properties": {
            "direction": {"type": "string", "enum": ["up", "neutral", "down"]},
            "gear": {"type": "integer", "minimum": 0, "maximum": 5}
          },
          "additionalProperties": false
        }
      },
      "additionalProperties": false
    },
    "deadman_pressed": {"type": "boolean"},
    "emergency_stop": {"type": "boolean"},
    "horn": {"type": "boolean"},
    "command_duration_s": {"type": "number", "minimum": 0.5, "maximum": 3.0},
    "task_action": {"type": "string", "enum": ["none", "request_attach", "request_release"]},
    "attention_target": {"type": "string"},
    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    "reason": {"type": "string"}
  },
  "additionalProperties": false
}
```

#### G.4 操作员性格

MVP 必须支持：

```text
conservative：保守，风险提示中等时也减速或等待
normal：正常，风险高时减速
aggressive：激进，只有风险高或非常接近时才减速
novice：新手，动作更频繁，容易犹豫
fatigued：疲劳，反应延迟更大，偶尔忽视提示
```

每台塔吊可独立配置 operator profile，也可按分布随机分配。必须通过 profile prompt 和行为参数体现差异，不允许通过任意后处理篡改 LLM 命令来伪造性格。

##### G.4.1 Profile Prompt 初版

以下 profile prompt 作为 MVP 初版，后续根据仿真效果和数据统计迭代。

###### normal

```text
你是一名经验正常、操作稳定的塔吊司机。你的目标是在安全和效率之间保持平衡，按当前任务阶段完成取货、运输和卸货。

驾驶风格：
- 通常使用 1-3 档进行接近、对准和吊钩高度调整；
- 在目标距离较远、视野良好、邻塔风险较低时，可以短时间使用 4 档；
- 不应频繁无意义地切换方向，也不应长时间保持错误方向；
- 对准 pickup/dropoff 时应逐步降档，优先小幅修正。

风险反应：
- safe/low：可以正常推进任务，但持续观察邻塔；
- medium：降低相关运动轴档位，避免继续快速接近；
- high：停止或显著减慢导致接近的轴，必要时保持观察；
- near_miss：优先停止相关方向动作，必要时 emergency_stop。

deadline：
- 应尽量按时完成任务；
- 任务快超时时可以更积极，但不能违反机械约束、力矩限制、禁区规则或明显碰撞风险。
```

###### conservative

```text
你是一名保守型塔吊司机。你的首要目标是避免风险和保持操作平稳，即使任务接近超时，也不能为了效率冒险。

驾驶风格：
- 偏好 1-2 档，只有在视野良好、距离充足、风险为 safe/low 时才使用 3 档；
- 接近目标、邻塔、重叠区或禁区时应提前降档；
- 对准时应耐心微调，不要用高档位冲向目标；
- 如不确定当前是否安全，优先 neutral 或低档观察。

风险反应：
- safe：可以继续任务，但保持低到中低档；
- low：开始谨慎，避免多轴高档同时动作；
- medium：倾向于降档、保持或等待观察；
- high：停止导致接近的轴，必要时只保留远离风险的低档动作；
- near_miss：优先 emergency_stop 或全部轴 neutral，等待风险解除。

deadline：
- 超时不好，但安全优先级始终高于效率；
- 不要因为 high priority 或 deadline 紧而忽略风险提示。
```

###### aggressive

```text
你是一名效率优先、操作积极的塔吊司机。你倾向于更快完成任务，但仍必须遵守机械限制和基本安全底线。

驾驶风格：
- 目标距离较远且风险为 safe/low 时，可以使用 3-5 档；
- 可以更频繁使用多轴同时操作来提高效率；
- 接近目标时仍应逐步降档，避免过冲；
- 不要输出会违反载重、力矩、行程、高度或禁区策略的操作。

风险反应：
- safe：积极推进任务；
- low：通常继续推进，但观察邻塔运动；
- medium：可以继续低到中档操作，但应避免高档继续接近；
- high：必须明显降档或停止导致接近的轴；
- near_miss：必须停止接近动作，必要时 emergency_stop。

deadline：
- high priority 和接近 deadline 时，你可以更积极地选择较高档位；
- 但不能为了效率导致碰撞、超力矩、越界或忽视 near_miss。
```

###### novice

```text
你是一名新手塔吊司机。你理解基本操作，但对距离、对准和多塔交互判断不够熟练，动作更犹豫，容易反复微调。

驾驶风格：
- 通常使用 1-2 档，偶尔在目标较远且风险低时使用 3 档；
- 经常需要通过小幅动作修正方向、小车半径和吊钩高度；
- 对准 pickup/dropoff 时可能较早降档、停顿或来回微调；
- 不要随意使用 4-5 档接近目标；
- 不要在未对准时请求 attach/release。

风险反应：
- safe/low：可以推进任务，但动作偏谨慎；
- medium：容易犹豫，应优先降档并观察；
- high：停止导致接近的轴，避免继续复杂多轴操作；
- near_miss：全部轴 neutral 或 emergency_stop。

deadline：
- 你知道超时不好，但不要因为着急而粗暴操作；
- 如果不确定下一步，宁可低档微调或短暂停顿。
```

###### fatigued

```text
你是一名疲劳状态的塔吊司机。你仍然知道安全规则，但反应较慢，容易保持上一操作，偶尔对提示反应不及时。

驾驶风格：
- 通常使用 1-3 档；
- 可能在目标已经接近时没有立即降档，因此需要特别注意 observation 中的距离、signal_hint 和 risk hint；
- 不要频繁做大幅方向切换；
- 如果发现自己接近目标或风险升高，应主动回中或降档。

风险反应：
- safe：可以正常推进；
- low：继续任务但保持注意；
- medium：应降档，但可能只先降低一个相关轴；
- high：必须停止导致接近的轴，不要继续保持旧命令；
- near_miss：必须全部轴 neutral 或 emergency_stop。

deadline：
- 你可能反应慢，但仍应尽量完成任务；
- 任务快超时时不要盲目高档推进，应先确认邻塔、禁区和对准状态。
```

##### G.4.2 行为参数初版

```yaml
operator_profiles:
  normal:
    risk_sensitivity: 0.6
    preferred_max_gear: 4
    hesitation_prob: 0.05
    ignore_hint_prob: 0.05
    decision_interval_multiplier: 1.0

  conservative:
    risk_sensitivity: 0.9
    preferred_max_gear: 3
    hesitation_prob: 0.10
    ignore_hint_prob: 0.0
    decision_interval_multiplier: 1.0

  aggressive:
    risk_sensitivity: 0.35
    preferred_max_gear: 5
    hesitation_prob: 0.03
    ignore_hint_prob: 0.25
    decision_interval_multiplier: 1.0

  novice:
    risk_sensitivity: 0.7
    preferred_max_gear: 3
    hesitation_prob: 0.25
    alignment_error_prob: 0.15
    ignore_hint_prob: 0.08
    decision_interval_multiplier: 1.0

  fatigued:
    risk_sensitivity: 0.55
    preferred_max_gear: 4
    hesitation_prob: 0.15
    ignore_hint_prob: 0.20
    stale_command_bias: 0.20
    decision_interval_multiplier: 1.5
```

行为参数用于构造 prompt、调整 observation 提示强度、调节决策节奏或摘要语气，不得用于任意篡改 LLM 输出命令。

#### G.5 LLM Provider

必须支持：

```text
deepseek
minimax
mock
replay
```

DeepSeek、MiniMax 必须能真实调用 API。mock/replay 用于测试、无网络开发和复现。Provider 抽象必须支持不同 base_url、model、api_key、api_key_env、timeout、max_retries、structured_output mode。

#### G.6 验收标准

- LLM 输出必须通过 JSON Schema 校验；
- 输出不合法时自动重试；
- retry 时必须把具体 validation error 反馈给模型；
- 重试失败时默认 `neutral_stop`，连续失败超过阈值后 episode 标记 `llm_failed` 并终止；
- 每次调用保存 observation、messages、raw_response、parsed_command、executed_command、latency、token_usage、validation_errors、provider、model；
- 支持 replay 模式，不调用 LLM，直接读取历史命令；
- 支持多塔吊多个独立 operator session；
- 决策频率低于物理仿真频率；
- LLM 不能直接访问仿真全局真值；
- LLM 不能直接修改物理状态。

---

### 模块 H：基础安全设施与风险影子评估模块

#### H.1 功能

该模块分为三层：

```text
基础安全设施层：硬约束，必须执行
在线风险影子评估层：实时计算 online_risk，用于 R1 提示和记录
可配置防碰撞干预层：根据 S0/S1/S2/S3 决定是否干预
```

#### H.2 基础安全设施层

必须硬执行：

- 最大回转速度
- 最大角加速度
- 小车行程范围
- 起升高度范围
- 起重量/半径相关载重曲线/力矩限制
- 基础机械限位
- 挂载/卸载几何判定

#### H.3 在线风险影子评估层

计算但不默认干预：

```math
d_{min,ij}^{online}(t)=min(d_{jib-jib}, d_{jib_i-hook_j}, d_{jib_j-hook_i}, d_{hook-hook})
```

```math
\hat{d}_{min}^{ij}(t)=\min_{\tau \in [0,H]}dist(\hat{state}_i(t+\tau),\hat{state}_j(t+\tau))
```

```math
\widehat{TTC}_{ij}(t)=\min\{\tau: \hat{d}_{ij}(t+\tau)<d_{safe,effective}\}
```

其中 online_risk 只能使用当前状态、当前速度、当前手柄命令和短时外推，不得使用 episode 真实未来轨迹。

`d_safe_effective` 必须由配置明确计算。MVP 默认：

```text
base_threshold = risk.thresholds_m[risk.ttc_threshold_level]  # 默认 high
wind_extra = max(0, wind_speed_m_s / 10) * extra_clearance_per_10m_s_wind_m
d_safe_effective = base_threshold + wind_extra
```

风险等级示例：

```text
safe: clearance_min_m > 8 m
low: 5 m < clearance_min_m <= 8 m
medium: 3 m < clearance_min_m <= 5 m
high: 1.8 m < clearance_min_m <= 3 m
near_miss: 0 m < clearance_min_m <= 1.8 m
collision: clearance_min_m <= 0 m
```

#### H.4 风险提示与可配置干预

风险提示模式只控制 observation 是否包含 online_risk：

```yaml
risk_prompt_mode: "R1"
risk_prompt:
  R0:
    include_online_risk_in_observation: false
  R1:
    include_online_risk_in_observation: true
    include_uncertainty_when_visibility_poor: true
```

安全干预模式只控制多塔风险是否修改 LLM 命令。基础机械安全、力矩限制、机械限位、非法状态检测和碰撞终止始终生效。

```yaml
safety_mode: "S1"
intervention:
  S0:
    modify_command: false
    description: "仅执行基础机械安全；仍记录碰撞检测和离线标签所需真值。"
  S1:
    modify_command: false
    description: "主数据生成默认模式；计算并记录 online risk、risk events 和 ignored_risk_hint，但不修改命令。"
  S2:
    modify_command: true
    rule: "limit_speed_on_high_risk"
    description: "高风险时限制导致继续接近的轴或档位。"
  S3:
    modify_command: true
    rule: "force_stop_on_high_risk"
    description: "高风险或 near_miss 时强制减速/停车。"
```

`intervention_applied` 只在 S2/S3 实际修改命令时记录。S0/S1 下仍必须保存 `raw_command` 与 `executed_command`；二者通常相同，但仍可能因机械限位、力矩限制、deadman 或 emergency_stop 产生差异。

#### H.5 碰撞终止

临界接近、高风险、near-miss 事件继续仿真并记录。几何碰撞发生后，MVP 必须：

```text
记录 collision event；
episode_status = failed_collision；
立即终止 episode；
不生成碰撞后的不可信轨迹。
```

#### H.6 验收标准

- 基础安全设施始终生效；
- R0/R1 控制是否向 LLM observation 提供 online_risk；
- 多塔碰撞风险在 S1 下记录但不修改命令；
- S2/S3 下能按配置修改命令；
- 保存 raw_command 与 executed_command；
- 记录每次干预原因；
- 力矩超限动作必须被硬限制，并记录 moment_limit / overload_prevented；
- forbidden_zone_policy=task_only 时，运动进入禁区记录 forbidden_zone_violation；
- forbidden_zone_policy=hard 时，按配置阻止或标记失败；
- overlap_zone_entered/exited/shared/conflict 事件可记录；
- online_risk 不使用真实未来轨迹；
- 碰撞后 episode 终止并标记 failed_collision；
- 风险距离计算有单元测试；
- 简单线段交叉用例能正确识别高风险/碰撞；
- 可导出每一帧每一对塔吊的风险标签。

---

### 模块 I：低层控制器模块

#### I.1 功能

将 LLM 双手柄离散命令转换为连续控制目标。

例如：

```json
{
  "left_joystick": {
    "slew": {"direction": "right", "gear": 2},
    "trolley": {"direction": "out", "gear": 1}
  },
  "right_joystick": {
    "hoist": {"direction": "neutral", "gear": 0}
  },
  "deadman_pressed": true,
  "emergency_stop": false,
  "command_duration_s": 1.0
}
```

转换为：

```json
{
  "theta_dot_cmd_rad_s": 0.006,
  "trolley_v_cmd_m_s": 0.2,
  "hoist_v_cmd_m_s": 0.0
}
```

#### I.2 速度档位

```yaml
joystick_speed_levels:
  slew:
    gear_0: 0.0
    gear_1: 0.15
    gear_2: 0.3
    gear_3: 0.5
    gear_4: 0.65
    gear_5: 0.8
  trolley:
    gear_0: 0.0
    gear_1: 0.08
    gear_2: 0.15
    gear_3: 0.3
    gear_4: 0.4
    gear_5: 0.5
  hoist:
    gear_0: 0.0
    gear_1: 0.1
    gear_2: 0.2
    gear_3: 0.35
    gear_4: 0.5
    gear_5: 0.6
```

每个运动轴独立使用 direction + gear。允许多轴同时动作。`gear=0` 或 direction=neutral 表示该轴中位/停止目标，但控制器应按减速度平滑停止，不应瞬间清零速度。`command_duration_s` 表示当前离散手柄状态的保持时间；控制器在该时间内持续追踪对应速度目标，到期后若没有新命令则进入 neutral_stop 或按实时 stale policy 处理。`deadman_pressed=false` 时所有手柄输入无效并进入安全停止。`emergency_stop=true` 时执行紧急制动。

#### I.3 验收标准

- 所有双手柄指令都能转换为连续控制目标；
- 支持加速度限制和平滑过渡；
- 支持手柄回中后的平滑停止；
- 支持 command_duration_s 到期后的 neutral_stop；
- 支持 deadman_pressed=false 安全停止；
- 支持 emergency_stop=true 紧急制动；
- 控制器输出不超过塔吊机械限制；
- 保存控制命令日志；
- 支持规则司机、LLM 司机共用同一控制器。

---

### 模块 J：仿真调度与多 Agent 异步模块

#### J.1 功能

管理物理仿真步进、低层控制、LLM 决策、风险评估和数据记录。

#### J.2 单帧生命周期与推荐伪代码

模块 J 必须按 0.7.8 的单帧生命周期调度。伪代码只表达调用顺序，业务判断应留在各 owner 模块内。

```python
record_initial_frame(state_t, time_s=0.0)

while sim_time < duration_s:
    # 1-2. 环境与任务启动
    weather_t = weather.update(sim_time)
    task_system.activate_due_tasks(sim_time, state_t)

    # 3-8. 同一决策时刻并行决策，同步应用
    decision_cranes = scheduler.cranes_due_for_decision(sim_time, include_idle=True)
    if decision_cranes:
        snapshot_t = scheduler.freeze_world_snapshot(state_t, weather_t, tasks, events)
        online_risk_t = risk.compute_online(snapshot_t, current_commands)
        observations = observation_builder.build_batch(snapshot_t, online_risk_t)
        raw_responses = operator_pool.decide_parallel(observations, wait_policy)
        parsed_commands = command_parser.parse_with_retry_or_neutral(raw_responses)
        executed_commands = safety_pipeline.apply_batch(parsed_commands, snapshot_t, online_risk_t)
        command_store.replace_current_commands(executed_commands, sim_time)

    # 9. 命令过期或 stale 处理
    command_store.expire_or_neutral_stop(sim_time)

    # 10-11. 控制与物理积分
    control_targets = controller.compute_batch(command_store.current_commands, state_t)
    state_next = physics.step(state_t, control_targets, dt)

    # 12. 任务状态机只基于 step 后状态推进
    task_events = task_system.update_after_physics(state_next, command_store.current_commands, sim_time + dt)

    # 13. 当前风险与碰撞终止
    risk_now = risk.compute_now(state_next)
    collision_events = collision_detector.detect(state_next, risk_now)
    episode_status = scheduler.update_terminal_status(state_next, task_events, collision_events)

    # 14. 统一记录与推送
    recorder.record_step(
        time_s=sim_time + dt,
        state=state_next,
        weather=weather_t,
        tasks=tasks,
        risk=risk_now,
        commands=command_store.current_commands,
        events=task_events + collision_events,
        episode_status=episode_status,
    )
    websocket.broadcast_sim_frame_if_enabled()

    if scheduler.should_stop(episode_status, sim_time + dt):
        break

    state_t = state_next
    sim_time += dt
```

关键约束：

- 同一 `decision_time` 的多塔 observation 必须来自同一 `WorldSnapshot`。
- online risk 可以在决策前用于 R1 observation；offline label 只能在 episode 后生成。
- `record_frame` 记录 step 后状态，事件归属到检测到事件的 step 后帧。
- 调度器不得在伪代码中直接写任务、安全、controller 的业务规则，只能调用各模块合同接口。

#### J.3 运行模式

第一版应支持：

```text
offline_batch:
  不开前端，直接运行 episode 或 dataset，用于数据生成。

offline_replay:
  读取已有 command_replay.jsonl，复现历史轨迹。

interactive_server:
  启动 FastAPI，可通过 REST/WebSocket 启动、查看和展示仿真。
```

#### J.4 验收标准

- 仿真不会因为某个 LLM 响应慢而卡死；
- LLM 短暂延迟可保持上一命令；
- command_duration_s 到期后，如果没有新命令，默认进入 neutral_stop；
- LLM 超时后默认 neutral_stop；
- offline_wait 模式下仿真时间可暂停等待 LLM 返回；
- 同一 decision_time 的多塔 observation 基于同一个 world snapshot；
- 同一 decision_time 的多塔命令收齐后同时应用；
- LLM 连续失败超过阈值后 episode_status=llm_failed；
- 支持实时模式和加速离线模式；
- 支持无 LLM 批量生成；
- 支持 replay 模式；
- 记录每一帧状态；
- 记录每一次 LLM 决策对应的仿真时间。

---

### 模块 K：碰撞距离、TTC 与风险标签模块

#### K.1 功能

为后续轨迹预测和碰撞风险预警模型生成标签。

#### K.2 输出标签

每个时间步、每对塔吊：

```json
{
  "episode_id": "E001",
  "frame": 120,
  "time_s": 6.0,
  "crane_i": "C1",
  "crane_j": "C2",
  "distance_min_raw_now_m": 6.2,
  "clearance_min_now_m": 4.7,
  "distance_jib_jib_raw_now_m": 6.2,
  "clearance_jib_jib_now_m": 4.7,
  "distance_jib_i_hook_j_raw_now_m": 7.1,
  "clearance_jib_i_hook_j_now_m": 5.85,
  "distance_jib_j_hook_i_raw_now_m": 9.4,
  "clearance_jib_j_hook_i_now_m": 8.15,
  "distance_hook_hook_raw_now_m": 12.0,
  "clearance_hook_hook_now_m": 11.0,
  "min_clearance_future_5s_m": 3.4,
  "min_clearance_future_10s_m": 2.8,
  "ttc_5s_s": null,
  "ttc_10s_s": 8.2,
  "risk_level_5s": "medium",
  "risk_level_10s": "high",
  "collision_label_5s": 0,
  "collision_label_10s": 0
}
```

#### K.3 风险对象

MVP 必须支持：

- 塔臂—塔臂线段距离
- 塔臂—吊钩点距离
- 吊钩—吊钩距离

增强版本支持：

- 吊物摆动包络距离

#### K.4 在线风险与离线标签分离

```text
online_risk:
  运行时短时外推，可进入 R1 observation，不得使用真实未来轨迹。

offline_label:
  episode 完成后使用真实轨迹计算 future_min_distance、TTC、risk_label。
```

#### K.5 验收标准

- 塔臂线段距离、塔臂-吊钩点距离、吊钩-吊钩距离计算正确；
- 未来窗口标签可配置：5s、10s、15s；
- 标签生成不依赖模型预测，只依赖仿真真值；
- 离线标签不进入 LLM observation；
- 碰撞/临界接近事件能被自动记录；
- 风险标签可导出为 Parquet；
- 可生成正负样本比例统计；
- 支持按 episode、scenario、crane_pair 聚合统计。

---

### 模块 L：数据记录与导出模块

#### L.1 文件结构

```text
runs/
  exp_2026_001/
    config/
      scenario.yaml
      experiment.yaml
      dataset.yaml
      resolved_config.yaml
      dataset.yaml               # 批量数据集运行时存在
      resolved_config.yaml
    metadata/
      episode_metadata.json
      dataset_summary.json
    logs/
      llm_observations.jsonl
      llm_decisions.jsonl
      commands.jsonl
      interventions.jsonl
      events.jsonl
    data/
      trajectories.parquet
      pair_risks.parquet
      graph_edges.parquet
      tasks.parquet
      weather.parquet
    replay/
      command_replay.jsonl
    visual/
      frames.jsonl
      episode_manifest.json
      preview.mp4
      screenshots/
```

#### L.1.1 全局数据 schema 约定

- 所有 JSONL 每行必须包含 `schema_version`。
- 所有 Parquet 必须包含 `schema_version` 列，或写入 Parquet file metadata；为便于 Pandas 合并，MVP 建议同时保留列字段。
- 所有时间字段单位为秒，距离单位为米，角度内部为 rad，配置展示可用 deg。
- LLM observation / command / event 使用 JSONL 保留原始结构；训练主表使用 Parquet 便于批量读取。
- `offline_label` 字段只出现在 `pair_risks.parquet`、离线 dataset 切片和离线回放扩展中，不得进入 LLM observation。

#### L.2 trajectories.parquet 字段

每帧每塔吊一行：

```text
schema_version: string
episode_id: string
scenario_id: string
frame: int
time_s: float
crane_id: string

base_x: float
base_y: float
base_z: float
mast_height_m: float
jib_length_m: float

theta_rad: float
theta_sin: float
theta_cos: float
theta_dot_rad_s: float
theta_ddot_rad_s2: float

trolley_r_m: float
trolley_v_m_s: float
hook_h_m: float
hoist_v_m_s: float

root_x: float
root_y: float
root_z: float
tip_x: float
tip_y: float
tip_z: float
hook_x: float
hook_y: float
hook_z: float

load_attached: bool
load_type: string
load_weight_t: float
load_size_x_m: float
load_size_y_m: float
load_size_z_m: float
task_id: string
task_stage: string
pickup_zone_id: string
dropoff_zone_id: string
operator_mode: string        # llm / rule / mock / replay
operator_profile: string

executed_slew_direction: string
executed_slew_gear: int
executed_trolley_direction: string
executed_trolley_gear: int
executed_hoist_direction: string
executed_hoist_gear: int
executed_deadman_pressed: bool
executed_emergency_stop: bool
executed_task_action: string

wind_speed_m_s: float
wind_gust_m_s: float
wind_direction_deg: float
visibility_level: string
```

#### L.3 pair_risks.parquet 字段

每帧每塔吊对一行：

```text
schema_version: string
episode_id: string
scenario_id: string
frame: int
time_s: float
crane_i: string
crane_j: string

distance_min_raw_now_m: float
clearance_min_now_m: float
distance_jib_jib_raw_now_m: float
clearance_jib_jib_now_m: float
distance_jib_i_hook_j_raw_now_m: float
clearance_jib_i_hook_j_now_m: float
distance_jib_j_hook_i_raw_now_m: float
clearance_jib_j_hook_i_now_m: float
distance_hook_hook_raw_now_m: float
clearance_hook_hook_now_m: float

min_clearance_future_5s_m: float
min_clearance_future_10s_m: float
min_clearance_future_15s_m: float

ttc_5s_s: float | null
ttc_10s_s: float | null
ttc_15s_s: float | null

risk_level_now: string
risk_level_5s: string
risk_level_10s: string
risk_level_15s: string

collision_label_5s: int
collision_label_10s: int
collision_label_15s: int
```

#### L.4 graph_edges.parquet 字段

用于物理先验动态图训练：

```text
schema_version: string
episode_id: string
frame: int
time_s: float
src_crane_id: string
dst_crane_id: string

edge_distance_m: float
edge_overlap_ratio: float
edge_delta_height_m: float
edge_delta_theta_rad: float
edge_delta_theta_dot_rad_s: float
edge_ttc_s: float | null
edge_risk_level: string
edge_weight_physics_prior: float
```

#### L.4.1 tasks / weather / LLM observation / manifest 最低字段

`tasks.parquet` 至少包含：

```text
schema_version: string
episode_id: string
scenario_id: string
task_id: string
crane_id: string
task_type: string
status: string                  # pending / active / completed / failed / skipped
failure_reason: string | null
pickup_x/y/z: float
dropoff_x/y/z: float
pickup_zone_id: string
dropoff_zone_id: string
load_type: string
load_weight_t: float
load_size_x/y/z_m: float
planned_start_s: float | null
actual_start_s: float | null
completed_time_s: float | null
deadline_s: float | null
deadline_missed: bool
overtime_s: float
```

`weather.parquet` 至少包含：

```text
schema_version: string
episode_id: string
scenario_id: string
frame: int
time_s: float
wind_speed_m_s: float
wind_gust_m_s: float
wind_direction_deg: float
visibility_level: string
rain_level: string
```

`logs/llm_observations.jsonl` 每行至少包含：

```json
{
  "schema_version": "1.0",
  "observation_id": "OBS_000123",
  "episode_id": "E001",
  "time_s": 42.0,
  "crane_id": "C1",
  "risk_prompt_mode": "R1",
  "observation": {},
  "source_snapshot_id": "SNAP_000042"
}
```

`visual/episode_manifest.json` 至少包含：

```json
{
  "schema_version": "1.0",
  "episode_id": "E001",
  "scenario_id": "S001",
  "episode_status": "completed",
  "frame_count": 12000,
  "dt": 0.05,
  "coordinate_system": "ENU",
  "cranes": [],
  "site": {},
  "material_zones": [],
  "work_zones": [],
  "forbidden_zones": [],
  "overlap_zones": [],
  "offline_labels_available": true
}
```

#### L.5 commands.jsonl 字段

```json
{
  "schema_version": "1.0",
  "episode_id": "E001",
  "time_s": 42.0,
  "decision_index": 42,
  "crane_id": "C1",
  "operator_id": "OP_C1",
  "operator_profile": "aggressive",
  "operator_mode": "llm",
  "observation_id": "OBS_000123",
  "provider": "deepseek",
  "model": "deepseek-chat",
  "raw_llm_response": "{...}",
  "parsed_command": {
    "left_joystick": {
      "slew": {"direction": "right", "gear": 2},
      "trolley": {"direction": "out", "gear": 1}
    },
    "right_joystick": {
      "hoist": {"direction": "neutral", "gear": 0}
    },
    "deadman_pressed": true,
    "emergency_stop": false,
    "horn": false,
    "command_duration_s": 1.0,
    "task_action": "none",
    "attention_target": "pickup_area",
    "confidence": 0.76,
    "reason": "取货点在右前方，低速接近并观察2号塔吊。"
  },
  "executed_command": {
    "left_joystick": {
      "slew": {"direction": "right", "gear": 2},
      "trolley": {"direction": "out", "gear": 1}
    },
    "right_joystick": {
      "hoist": {"direction": "neutral", "gear": 0}
    },
    "deadman_pressed": true,
    "emergency_stop": false,
    "horn": false,
    "command_duration_s": 1.0,
    "task_action": "none",
    "attention_target": "pickup_area",
    "confidence": 0.76,
    "reason": "取货点在右前方，低速接近并观察2号塔吊。"
  },
  "modified_by_intervention": false,
  "modified_by_mechanical_safety": false,
  "intervention_reason": null,
  "mechanical_safety_reason": null,
  "latency_ms": 820,
  "token_usage": {"prompt_tokens": 1200, "completion_tokens": 120},
  "retry_count": 0,
  "validation_errors": [],
  "cache_hit": false,
  "confidence": 0.76,
  "attention_target": "pickup_area",
  "reason": "取货点在右前方，低速接近并观察2号塔吊。"
}
```

`parsed_command` 保存 schema 校验后的原始 LLM 命令；`executed_command` 保存经过 schema 修正、机械安全限制和 S2/S3 干预后的最终执行命令。`attention_target`、`confidence`、`reason` 既保留在 command 内，也可在顶层镜像，便于日志检索。

#### L.6 events.jsonl 字段

```json
{
  "schema_version": "1.0",
  "event_id": "EVT_000123",
  "event_type": "near_miss",
  "episode_id": "E001",
  "scenario_id": "S001",
  "frame": 120,
  "time_s": 6.0,
  "crane_ids": ["C1", "C2"],
  "risk_level": "high",
  "distance_min_raw_now_m": 2.6,
  "clearance_min_now_m": 1.1,
  "details": {
    "nearest_object_type": "jib-hook",
    "relative_motion": "closing"
  }
}
```

MVP 至少记录：

```text
risk_entered
near_miss
risk_resolved
collision
ignored_risk_hint
emergency_stop_triggered
horn_event
intervention_applied
moment_limit
overload_prevented
forbidden_zone_violation
overlap_zone_entered
overlap_zone_exited
overlap_zone_shared
overlap_task_conflict
task_started
task_completed
deadline_missed
attach_failed
release_failed
attach_request_rejected
release_request_rejected
invalid_task_action
llm_timeout
llm_invalid_output
idle_unnecessary_motion
```

#### L.7 visual/frames.jsonl 与 SimFrame

前端离线回放和 WebSocket 实时推送必须共用同一 `SimFrame` schema。`visual/frames.jsonl` 每行一个 frame：

```json
{
  "type": "sim_frame",
  "episode_id": "E001",
  "schema_version": "1.0",
  "frame": 120,
  "time_s": 6.0,
  "episode_status": "running",
  "cranes": [
    {
      "crane_id": "C1",
      "base": [0, 0, 0],
      "root": [0, 0, 45],
      "tip": [42, 18, 45],
      "hook": [20, 8, 25],
      "theta_rad": 0.40,
      "trolley_r_m": 22.0,
      "hook_h_m": 25.0,
      "load_attached": false,
      "load_type": "rebar_bundle",
      "load_size_m": [6.0, 1.0, 1.0],
      "task_id": "T_C1_001",
      "task_stage": "move_to_pickup",
      "pickup_zone_id": "rebar_yard",
      "dropoff_zone_id": "floor_10_workface",
      "operator_profile": "aggressive",
      "current_command": {
        "left_joystick": {
          "slew": {"direction": "right", "gear": 2},
          "trolley": {"direction": "out", "gear": 1}
        },
        "right_joystick": {
          "hoist": {"direction": "neutral", "gear": 0}
        }
      }
    }
  ],
  "pairs": [
    {
      "crane_i": "C1",
      "crane_j": "C2",
      "distance_min_raw_now_m": 6.0,
      "clearance_min_now_m": 4.5,
      "risk_level_now": "medium"
    }
  ],
  "tasks": [],
  "weather": {
    "wind_speed_m_s": 8.0,
    "visibility": "medium"
  },
  "events": []
}
```

离线回放版本的 `SimFrame` 可选携带 `offline_labels`，例如未来 5/10/15 秒最小净空；实时 WebSocket 推送不得携带基于真实未来轨迹的 `offline_labels`。前端 UI 必须把该类字段标注为“离线标签/事后分析”。

#### L.8 episode_summary / dataset_summary 指标

至少统计：

```text
episode_status
duration_s
num_cranes
num_tasks_total
num_tasks_completed
num_tasks_failed
task_completion_rate
mean_task_duration_s
deadline_missed_count
overtime_mean_s
risk_frame_ratio_by_level
near_miss_count
collision_count
min_clearance_over_episode
high_risk_duration_s
num_llm_calls
llm_invalid_output_count
llm_timeout_count
mean_latency_ms
cache_hit_count
operator_profile_distribution
ignored_risk_hint_count
emergency_stop_count
forbidden_zone_violation_count
overlap_zone_shared_count
has_nan
has_inf
max_state_jump
replay_available
```

dataset_summary 应聚合 episode_summary，并支持按 scenario、task_type、operator_profile、risk_prompt_mode、safety_mode、provider/model 分组。

#### L.9 验收标准

- 所有数据文件能被 Pandas/PyArrow 正常读取；
- 至少导出 trajectories、pair_risks、graph_edges、commands、metadata；
- 必须导出 visual/frames.jsonl 和 visual/episode_manifest.json 供前端离线回放；
- 必须导出 episode_summary 和 dataset_summary；
- 所有 episode 有唯一 ID；
- 所有文件包含 schema version；
- 新增字段必须向后兼容或升 major schema version；
- nullable 字段必须使用 null/nullable column，不得用空字符串混代；
- visual/frames.jsonl 是展示权威，trajectories/pair_risks 是训练权威；
- 可从导出的 replay 文件复现轨迹；
- 生成 dataset_summary，包括风险样本比例、任务完成率、碰撞次数、临界接近次数；
- 数据格式能直接用于时空图训练窗口切片。

---

### 模块 M：后端 API 模块

#### M.1 功能

提供仿真运行、数据查询、实时状态推送和前端展示支持。

#### M.2 REST API

最低要求：

```text
GET    /health
POST   /scenarios/validate
POST   /episodes/start
POST   /episodes/{episode_id}/pause
POST   /episodes/{episode_id}/resume
POST   /episodes/{episode_id}/stop
GET    /episodes/{episode_id}/state
GET    /episodes/{episode_id}/summary
GET    /episodes/{episode_id}/download
GET    /datasets
GET    /datasets/{dataset_id}/summary
```

#### M.3 WebSocket

```text
WS /ws/episodes/{episode_id}
```

WebSocket 推送帧必须与 `visual/frames.jsonl` 使用同一 `SimFrame` schema。

#### M.4 命令行运行

第一版必须支持命令行脚本运行，不能把仿真核心绑定在 Web 服务中：

```bash
python scripts/run_episode.py --config configs/demo.yaml
python scripts/replay_episode.py --run runs/exp_xxx/E001
python scripts/batch_generate.py --config configs/batch.yaml
```

#### M.5 验收标准

- API 有自动文档；
- WebSocket 能以至少 10 FPS 推送前端展示数据；
- 能启动、暂停、恢复、停止仿真；
- 能下载数据集；
- 错误响应结构统一；
- 支持本地单机运行；
- 支持无前端批量生成数据。

---

### 模块 N：前端 3D 展示模块

#### N.1 功能

展示仿真场景、塔吊运动、吊钩位置、任务点、风险距离、LLM 操作日志和天气状态。

#### N.2 页面设计

至少包含：

1. 3D 场景视图；
2. 时间轴与播放控制；
3. 塔吊状态面板；
4. 任务状态面板；
5. 风险状态面板；
6. LLM 指令日志；
7. 数据导出按钮；
8. 场景配置上传/选择入口。

#### N.3 3D 展示元素

- 地面/施工区域边界；
- 塔吊塔身；
- 起重臂；
- 平衡臂；
- 小车；
- 吊钩；
- 取货点；
- 卸货点；
- material_zones；
- work_zones；
- 禁区；
- 作业半径圆；
- 多塔重叠区域；
- 塔臂轨迹尾迹；
- 风向箭头；
- 风险连线；
- 碰撞/临界接近高亮。

#### N.4 交互功能

- 播放/暂停/倍速；
- 切换跟随某台塔吊；
- 切换风险显示；
- 切换轨迹尾迹长度；
- 点击塔吊查看状态；
- 点击塔吊对查看距离与 TTC；
- 查看 LLM 原始指令和最终执行指令；
- 点击命令日志展开 observation、messages、raw_response、parsed_command、executed_command、validation_errors；
- 点击事件日志跳转到对应时间并高亮相关塔吊/塔吊对；
- 离线加载历史 episode 回放。

#### N.5 验收标准

- 按配置展示 N 台塔吊；
- demo 至少覆盖 3 台塔吊；
- 能回放历史 episode；
- 离线回放优先稳定；
- 实时 WebSocket 使用同一 SimFrame schema；
- 风险等级颜色/样式可区分；
- 能显示取货点、卸货点和当前任务阶段；
- 能显示 material_zones、work_zones、forbidden_zones、overlap_zones；
- 能显示 LLM 指令日志；
- 默认使用程序几何模型展示塔吊和吊物，并预留 glTF/GLB 替换接口；
- 能根据 load_type.shape 和 load_size_m 显示简化吊物；
- 事件日志支持点击跳转时间轴；
- WebSocket 断开后能自动重连或显示错误；
- 前端不参与物理计算，只展示后端状态；
- 前端实时显示的辅助距离或风险只能标记为 display-only，不得作为训练真值；
- 前端配置上传只触发后端 validate，权威校验在后端完成；
- 3D 场景与导出数据中的坐标一致。

---

### 模块 O：实验与数据集生成模块

#### O.1 功能

批量生成用于轨迹预测和风险预警模型训练的数据集。

#### O.2 场景类别

至少支持：

```text
normal_independent：多塔正常独立作业
overlap_safe：作业半径重叠但不接近
crossing_near_miss：两塔交叉接近
multi_crane_yielding：多塔避让
operation_delay：操作延迟
poor_visibility：低可见度
wind_gust：阵风扰动
aggressive_operator：激进司机导致高风险
safety_intervention：软/强干预对照
easy_task：基础可达任务
overlap_task：重叠区域任务
stress_task：压力任务
mixed_operator_profiles：不同性格司机同场
```

#### O.3 数据集划分

建议：

```text
train：普通布局 + 多种任务
val：相似布局 + 新任务
test_seen_layout：已见布局 + 新任务
test_unseen_layout：新塔吊布局
test_unseen_num_cranes：不同塔吊数量
test_high_risk：高风险场景
```

#### O.4 验收标准

- 至少生成 100 个 episode；
- 数据集生成配置中每个 episode 建议至少 300 秒仿真；若任务提前完成，应设置 `min_duration_s >= 300` 或明确记录 shorter episode 的原因；
- 至少包含 3 类风险等级；
- 高风险或临界接近样本比例可配置；
- 数据集划分不按滑动窗口随机划分，必须按 episode/scenario 划分；
- 输出 dataset_summary；
- 训练窗口切片脚本可读取数据并生成 STGNN 输入。

---

### 模块 P：时空图训练数据转换模块

#### P.1 功能

将仿真导出的长序列转换为轨迹预测模型所需的窗口数据。

第一版先定义数据转换接口、输入输出格式、episode/scenario 级划分原则和禁止时间泄漏原则。具体数据切片参数暂不固化，例如 `input_steps`、`pred_steps`、`stride_steps`、风险窗口长度、正负样本采样比例等，后续根据论文实验方案和模型输入设计再确定。当前文档不得把这些参数写死为唯一标准。

#### P.2 输入

- `trajectories.parquet`
- `pair_risks.parquet`
- `graph_edges.parquet`
- `tasks.parquet`

#### P.3 输出

训练样本：

```python
X_node: [num_nodes, input_steps, node_feature_dim]
X_edge: [input_steps, num_edges, edge_feature_dim]
A_phy: [input_steps, num_nodes, num_nodes]
Y_traj: [num_nodes, pred_steps, target_dim]
Y_risk: [num_edges, risk_label_dim]
metadata: scenario_id, episode_id, start_frame
```

#### P.4 节点特征建议

```text
sin(theta)
cos(theta)
theta_dot
theta_ddot
trolley_r
trolley_v
hook_h
hoist_v
load_attached
load_weight
task_stage_onehot
wind_speed
visibility_onehot
```

#### P.5 边特征建议

```text
current_jib_jib_distance
overlap_ratio
delta_height
delta_theta
delta_theta_dot
estimated_ttc
current_risk_level_onehot
```

#### P.6 标签建议

```text
未来 theta 或 sin/cos(theta)
未来 tip_x, tip_y, tip_z
未来 hook_x, hook_y, hook_z
未来最小距离
未来风险等级
未来 TTC
```

#### P.7 验收标准

- 能生成固定长度输入和预测窗口；
- 窗口长度、预测长度和滑动步长通过 dataset.yaml 配置，不在代码中硬编码；
- 能处理不同塔吊数量；
- 能按 scenario 划分 train/val/test；
- 不发生时间泄漏；
- 输出样本数量、风险分布统计；
- 可直接接入 PyTorch Dataset。

---

## 4. 整体验收标准

系统最终必须满足以下要求。

### 4.1 功能验收

- 能通过配置文件创建多塔吊施工场景；
- 能通过自动布局生成器创建合理、多样、可复现的塔吊布局；
- 能通过手写 YAML 复现指定塔吊布局；
- 能生成取货点和卸货点任务；
- LLM 操作员能根据任务目标和局部观测发出双手柄操作指令；
- 第一版能真实调用 DeepSeek 和 MiniMax；
- 低层控制器能执行 LLM 指令；
- 基础塔吊安全设施能限制不合理机械动作；
- 在线风险影子评估能计算当前距离、短时外推风险和风险等级；
- 离线标签模块能计算未来最小距离、TTC 和风险等级；
- 能导出轨迹、风险、图边、任务、天气、LLM 指令日志；
- 能通过前端 3D 页面实时展示或离线回放。

### 4.2 数据验收

- 数据字段完整，单位明确；
- 所有数据文件包含 schema version；
- 同一 episode 可 replay；
- 风险标签可复核；
- online_risk 与 offline_label 严格分离；
- LLM observation 不包含离线未来标签；
- 能生成训练、验证、测试数据划分；
- 能生成 STGNN 所需窗口数据；
- 轨迹数据无 NaN、Inf、明显跳变；
- 高风险样本比例可控。

### 4.3 性能验收

最低要求：

```text
按配置生成 N 台塔吊，demo 至少 3 台；
推荐性能验收：3-6 台塔吊、20 Hz、600 秒 episode，可在普通笔记本上离线生成；
无 LLM 模式下仿真速度 ≥ 实时 5 倍；
LLM 模式下支持异步，不因单个 LLM 超时阻塞整个系统；
WebSocket 展示帧率 ≥ 10 FPS；
前端按配置展示 N 台塔吊，推荐验证 3-6 台。
```

### 4.4 可复现验收

- seed 固定时，规则司机数据完全一致；
- LLM 数据通过 replay 文件可完全复现；
- 每次实验保存完整配置；
- 每个数据集保存生成脚本版本和 Git commit；
- 支持 `make test` 或 `pytest` 运行核心单元测试。

### 4.5 研究验收

系统生成的数据必须能支撑以下论文实验：

1. 轨迹预测模型对比实验；
2. 物理先验动态图消融实验；
3. 风险预警指标实验；
4. 不同场景泛化实验；
5. LLM 操作员数据 vs 规则司机数据 vs 随机策略数据的合理性对比。

---

## 5. 最小可行版本 MVP

请先实现 MVP，而不是一次性实现所有增强功能。

### MVP 必须包含

- Python 自建塔吊运动学仿真器；
- 自动布局生成器，默认按配置生成 N 台塔吊；
- 手写 YAML 布局；
- 内置通用塔吊型号库和 YAML 覆盖机制；
- 半径相关载重曲线 / rated moment 力矩限制；
- material_zones / work_zones / forbidden_zones；
- 简化 load_type 材料库；
- forbidden_zone_policy=task_only/hard；
- demo 至少 3 台塔吊；
- easy_task / overlap_task / stress_task；
- 每台塔吊独立任务队列；
- 规则司机；
- 双手柄 + 0-5 档 + deadman/emergency_stop 的 LLM 操作接口；
- DeepSeek 与 MiniMax 真实 API 接入；
- mock 与 replay provider；
- 5 种 operator profile：normal、conservative、aggressive、novice、fatigued；
- 基础安全设施；
- R0/R1 风险提示模式；
- S0/S1/S2/S3 安全干预配置，主数据默认 S1 不强制干预；
- jib-jib、jib-hook、hook-hook 距离计算；
- online_risk 与 offline_label 分离；
- 碰撞后终止 episode；
- 风险事件、overlap zone 事件、禁区 violation 事件；
- 轨迹、风险、命令、事件、LLM 决策日志导出；
- visual/frames.jsonl 离线回放导出；
- FastAPI 启动仿真；
- 命令行脚本运行 episode / replay / batch；
- React + Three.js 离线回放优先，实时 WebSocket 共用 SimFrame；
- 前端显示 site zones、overlap zones、简化吊物、事件跳转；
- 数据集 summary。

### MVP 可暂缓

- 吊物摆动；
- 真实风载动力学；
- Unity/Gazebo/Isaac 集成；
- 多协调员 Agent；
- 高保真材质渲染；
- 真实塔吊参数校准；
- 强化学习训练；
- 真实工地数据接入。

---

## 6. 推荐代码目录结构

```text
tower-crane-sim/
  backend/
    app/
      main.py
      api/
        routes_episodes.py
        routes_datasets.py
        websocket.py
      core/
        config.py
        scheduler.py
        scenario.py
      sim/
        crane_model.py
        world.py
        physics.py
        controller.py
        task_generator.py
        weather.py
        risk.py
        recorder.py
      agents/
        base_operator.py
        rule_operator.py
        llm_operator.py
        prompts.py
        schemas.py
      data/
        exporters.py
        dataset_builder.py
      tests/
        test_geometry.py
        test_risk.py
        test_task.py
        test_replay.py
    pyproject.toml

  frontend/
    src/
      App.tsx
      api/
        client.ts
        websocket.ts
      components/
        Scene3D.tsx
        CraneMesh.tsx
        RiskPanel.tsx
        TaskPanel.tsx
        CommandLog.tsx
        Timeline.tsx
      store/
        simStore.ts
      types/
        sim.ts
    package.json
    vite.config.ts

  configs/
    scenario_demo.yaml
    experiment_demo.yaml

  scripts/
    run_episode.py
    batch_generate.py
    build_dataset.py
    replay_episode.py

  docs/
    architecture.md
    data_schema.md
    acceptance_tests.md
```

---

## 7. 单元测试要求

至少实现：

```text
test_geometry.py
  - test_tip_position_from_theta
  - test_segment_distance_parallel
  - test_segment_distance_crossing
  - test_hook_position

test_layout.py
  - test_auto_layout_reproducible
  - test_auto_layout_respects_boundary
  - test_auto_layout_respects_forbidden_zones
  - test_overlap_level_quality_score

test_risk.py
  - test_risk_level_safe
  - test_risk_level_high
  - test_ttc_detected
  - test_future_min_distance
  - test_jib_hook_distance
  - test_hook_hook_distance
  - test_online_offline_label_separation

test_task.py
  - test_attach_condition
  - test_release_condition
  - test_task_completion
  - test_deadline_missed_not_failed
  - test_stress_task_reachable

test_controller.py
  - test_speed_limit
  - test_acc_limit
  - test_joystick_gear_mapping
  - test_neutral_smooth_stop
  - test_deadman_stop
  - test_emergency_stop

test_llm_schema.py
  - test_valid_command
  - test_invalid_command_retry_error_feedback
  - test_replay_command
  - test_deepseek_provider_config
  - test_minimax_provider_config

test_export.py
  - test_parquet_readable
  - test_required_columns
  - test_visual_frames_jsonl_schema
```

---

## 8. 前端验收场景

请准备一个 `demo_episode`，前端必须能展示：

1. 按配置展示 N 台塔吊，demo 至少三台塔吊；
2. 每台塔吊不同任务阶段；
3. 至少一段临界接近；
4. 风速变化；
5. LLM 指令日志；
6. 当前风险等级；
7. 离线回放中显示未来 5 秒最小距离，并明确标注为离线标签；实时模式只显示 online estimate；
8. 播放、暂停、倍速、回放；
9. 点击塔吊查看状态；
10. 点击塔吊对查看风险曲线。

---

## 9. 论文写法定位

在论文中应将本系统写成：

> 面向群塔交互轨迹预测的任务驱动仿真数据生成平台。

不要写成：

> LLM 自动控制塔吊系统。

推荐表述：

> 为提高仿真数据的任务合理性和交互真实性，本文构建 LLM-in-the-loop 的群塔操作行为生成模块。该模块仅指定取货点、卸货点、载荷、优先级和建议完成时间等任务目标，不预设完整运动轨迹，而是由 LLM 操作员根据有限视野、天气条件、邻近塔吊当前状态、任务阶段和可配置风险提示生成双手柄高层操作指令。指令经由基础安全设施与低层控制器转化为塔吊可执行动作，从而生成具有任务意图、操作差异和交互冲突特征的群塔运行数据。该模块服务于仿真数据生成，本文核心研究仍为基于物理先验时空动态图的轨迹预测与碰撞风险预警方法。

---

## 10. 物理引擎与前端技术调研结论

### 10.1 物理引擎选择结论

| 方案 | 优点 | 缺点 | 建议 |
|---|---|---|---|
| 自建参数化运动学/简化动力学 | 快、可控、易生成大规模数据、易导出标签 | 不是真实多体物理引擎 | 第一阶段主方案 |
| PyBullet | Python 友好、碰撞检测方便、可加载 URDF/SDF/MJCF | 大规模数据生成和复杂场景管理需自行封装 | 几何/碰撞校核或增强方案 |
| MuJoCo | 快速、精确、适合机器人和多关节动力学 | 场景构建和 Web 展示仍需额外开发 | 吊物摆动/动力学增强方案 |
| Gazebo Sim | 机器人仿真生态完整，适合传感器与 ROS | 工程复杂，学习成本较高 | 后期工程验证 |
| Isaac Sim | 高保真、PhysX/RTX、合成数据能力强 | 硬件要求高，开发成本高 | 高保真展示或扩展 |
| Unity | 可视化强，ML-Agents 适合交互环境 | Python 数据管道和批量复现复杂 | 展示/交互增强，不作核心数据生成 |

### 10.2 前端选择结论

推荐使用：

```text
React + TypeScript + Vite + Three.js / React Three Fiber
```

原因：

- 浏览器即可运行，便于展示；
- 与 FastAPI WebSocket 兼容；
- 适合实时播放仿真状态；
- 3D 场景足够表达塔吊、轨迹、风险线和任务点；
- 不把物理仿真放到前端，减少不一致风险。

如果前端希望更像完整 3D 引擎，可考虑 Babylon.js；如果已有 Unity 经验，可使用 Unity 做展示，但不建议第一阶段使用 Unity 承担核心数据生成。

---

## 11. 交付物清单

最终应交付：

1. 可运行后端仿真服务；
2. 可运行前端 3D 展示页面；
3. 示例场景配置；
4. 示例 episode 数据；
5. 数据导出文件；
6. Replay 文件；
7. 单元测试；
8. 技术文档；
9. 数据 Schema 文档；
10. Demo 视频或截图；
11. 用于 STGNN 训练的数据转换脚本；
12. dataset_summary 统计报告。

---

## 12. 开发顺序

请按 M0-M5 分阶段实现。MVP 总功能不删减，但每个阶段必须形成可运行、可测试、可导出的产物。

### M0：配置 + 运动学 + controller + recorder 骨架

范围：

- `ScenarioConfig / ExperimentConfig / ResolvedConfig` 基础解析；
- 手写 manual layout；
- 单塔/多塔 `CraneState` 初始化；
- joystick -> `ExecutedCommand` -> `ControlTarget` -> `CraneState` 链路；
- trajectories 与 visual frames 最小导出；
- 基础单元测试。

验收：无任务、无 LLM 情况下，多塔能稳定运行 300 秒，无 NaN/Inf，导出文件可读。

### M1：布局 + 任务 + 规则司机 + 当前风险距离

范围：

- auto layout 与型号库；
- material/work/forbidden zones；
- easy_task / overlap_task / stress_task；
- 任务状态机、attach/release；
- rule_operator v1；
- jib-jib、jib-hook、hook-hook 当前距离与风险事件。

验收：demo 至少 3 台塔吊，每台独立任务队列；规则司机能完成至少 80% easy_task；导出 tasks/events/pair_risks 当前风险字段。

### M2：episode 调度 + replay + visual frames

范围：

- 严格单帧生命周期；
- command expiry、neutral_stop、deadman/emergency_stop；
- `command_replay.jsonl` 保存 executed command；
- `resolved_config_hash` 与 strict replay；
- `visual/episode_manifest.json`；
- summary 初版。

验收：同一 seed + replay 能在容差内复现；replay mismatch 能失败并记录原因；离线 frames 可播放。

### M3：LLM observation / command / provider

范围：

- observation schema 与可见度噪声；
- R0/R1 online risk 提示；
- LLM JSON Schema；
- DeepSeek / MiniMax / mock / replay provider；
- retry、validation error feedback、neutral_stop、llm_failed；
- commands 与 llm_observations 完整日志。

验收：至少一个真实 provider 能完成简单取卸货任务；非法输出、超时和连续失败路径都有测试。

### M4：FastAPI + 前端离线回放

范围：

- REST validate/start/state/summary/download；
- WebSocket 推送 SimFrame；
- React + Three.js 程序几何塔吊；
- 时间轴、事件跳转、命令日志展开；
- site zones、overlap zones、简化吊物显示。

验收：前端稳定离线回放，实时展示与离线 frames 共用同一 schema；前端不参与权威物理计算。

### M5：dataset builder + STGNN window

范围：

- offline future labels；
- graph_edges；
- dataset.yaml；
- train/val/test 按 episode/scenario 划分；
- STGNN sliding window；
- dataset_summary 与风险比例统计。

验收：能生成可用于论文实验的数据集，窗口切片无时间泄漏，支持不同塔吊数量。

### 后续增强实验

- 吊物摆动；
- 真实风载动力学；
- 不同 operator profile 对比；
- S0/S1/S2/S3 安全模式对比；
- R0/R1 风险提示模式对比；
- LLM vs 规则司机 vs 随机策略对比；
- 新布局/新塔吊数量泛化数据。

## 13. 重要限制

- 不允许宣称该系统可用于真实塔吊自动控制；
- 不允许让 LLM 直接控制真实设备；
- 不允许将仿真数据伪装成真实工地数据；
- 不允许省略数据来源说明；
- 不允许只做 3D 动画而没有可导出的训练数据；
- 不允许只保存最终轨迹而不保存 LLM 指令和风险标签；
- 不允许把安全过滤做得过强，导致完全没有风险样本；
- 不允许违反基础机械极限来制造风险。

---

## 14. 最终目标一句话

请实现一个“任务驱动、LLM 操作员参与、物理约束合理、风险可标注、数据可导出、前端可展示”的群塔仿真系统，用于支撑物理先验时空动态图轨迹预测与碰撞风险预警研究。


---

## 15. v0.4 详细实施方案

本章不是新增功能清单，而是把前文要求落成工程实施顺序、交付物、测试和接口冻结点。实现团队可以直接按本章拆 issue、排 sprint 和做验收。

### 15.1 总体开发原则

第一轮开发必须采用“纵向可运行切片”而不是“横向堆模块”。每个里程碑都要能运行一个最小 episode，并产生可检查的数据文件。

```text
可运行优先级:
  配置可解析 > 物理可稳定步进 > 数据可落盘 > replay 可复现 > LLM 接入 > 前端增强。

接口冻结优先级:
  schema > 命令链路 > 单帧生命周期 > 数据导出 > UI 展示。

风险控制优先级:
  基础机械安全始终优先于多塔风险样本数量。
```

### 15.2 M0：配置、运动学、controller、recorder 骨架

目标：先让一个最小系统稳定跑起来，验证 `ResolvedConfig -> CraneState -> ControlTarget -> FrameRecord` 链路。

交付物：

```text
backend/app/schemas/config.py
backend/app/schemas/state.py
backend/app/sim/crane_model.py
backend/app/sim/controller.py
backend/app/sim/physics.py
backend/app/sim/recorder.py
configs/scenario_m0_single_crane.yaml
configs/experiment_m0_rule_neutral.yaml
scripts/run_episode.py
```

必须完成：

- Pydantic 配置模型；
- `ResolvedConfig` 和 `resolved_config_hash`；
- 内置塔吊型号库；
- 单塔 theta/trolley/hook_h 运动学；
- 档位到速度目标映射；
- 加速度限制和平滑停止；
- mechanical limit、moment limit；
- 每帧 trajectories 和 visual frames；
- `quality_report.json` 初版。

M0 不做：

```text
LLM；
多塔风险；
复杂任务；
前端；
STGNN window。
```

M0 验收命令：

```bash
python scripts/run_episode.py \
  --scenario configs/scenario_m0_single_crane.yaml \
  --experiment configs/experiment_m0_rule_neutral.yaml
python scripts/validate_run_artifacts.py --run runs/m0/latest
pytest backend/app/tests/test_geometry.py backend/app/tests/test_controller.py
```

### 15.3 M1：布局、任务、规则司机、当前风险距离

目标：让 3 台以上塔吊在规则司机下完成 easy/overlap/stress 的基本流程，并能记录当前风险距离。

交付物：

```text
backend/app/sim/layout.py
backend/app/sim/task_generator.py
backend/app/sim/task_manager.py
backend/app/agents/rule_operator.py
backend/app/sim/risk.py
configs/scenario_m1_three_cranes.yaml
configs/experiment_m1_rule.yaml
```

必须完成：

- auto/manual layout；
- overlap zone 计算；
- material_zones/work_zones/forbidden_zones；
- load_types；
- easy_task/overlap_task/stress_task；
- attach/release 状态机；
- rule_operator_v1；
- jib-jib、jib-hook、hook-hook 当前距离；
- risk_entered/near_miss/risk_resolved 事件初版；
- tasks.parquet、pair_risks.parquet 初版。

M1 验收：

```text
同 seed 生成相同布局和任务；
3 台塔吊至少 300s rule episode 可运行；
easy_task 规则司机完成率 >= 80%；
所有 pair_risks 行数 = frame_count * N*(N-1)/2；
forbidden_zone_policy=task_only 能记录 violation；
forbidden_zone_policy=hard 能阻止或失败。
```

### 15.4 M2：调度、replay、SimFrame、离线回放数据

目标：冻结单帧生命周期和 replay 机制，为 LLM 和前端打基础。

交付物：

```text
backend/app/core/scheduler.py
backend/app/replay/command_replay.py
backend/app/data/simframe.py
backend/app/data/quality.py
scripts/replay_episode.py
scripts/validate_run_artifacts.py
```

必须完成：

- 单帧生命周期严格实现；
- decision batch 与 world snapshot；
- `ExecutedCommand` command_replay；
- replay config hash 检查；
- replay tolerance 检查；
- `visual/frames.jsonl` 与 `episode_manifest.json`；
- quality gates；
- collision 后立即终止；
- recovery_release 初版。

M2 验收：

```bash
python scripts/run_episode.py --scenario configs/scenario_m1_three_cranes.yaml --experiment configs/experiment_m1_rule.yaml
python scripts/replay_episode.py --run runs/latest
python scripts/validate_run_artifacts.py --run runs/latest --require-replay
```

### 15.5 M3：LLM observation、command、provider

目标：接入 LLM，但不让 LLM 破坏已有仿真合同。

交付物：

```text
backend/app/agents/base_operator.py
backend/app/agents/llm_operator.py
backend/app/agents/providers/deepseek.py
backend/app/agents/providers/minimax.py
backend/app/agents/providers/mock.py
backend/app/agents/providers/replay.py
backend/app/agents/prompts.py
backend/app/agents/schemas.py
```

必须完成：

- Observation Pydantic schema；
- 输出 JSON Schema；
- retry correction prompt；
- timeout、neutral_stop、consecutive failure；
- R0/R1 observation 开关；
- S0-S3 intervention pipeline；
- LLM messages 全量落盘；
- cache 与 replay 分离；
- operator profile prompt；
- observation future label 泄漏测试。

M3 验收：

```text
mock provider 可稳定完成 easy_task；
DeepSeek 或 MiniMax 至少一个真实 provider 能通过 schema 调用；
invalid output 能 retry；
provider timeout 后 neutral_stop；
连续失败后 episode_status=llm_failed；
commands.jsonl 同时保存 raw/parsed/executed；
observation 不含 offline future_min_distance / offline TTC。
```

### 15.6 M4：FastAPI 与前端离线回放

目标：把仿真结果稳定展示出来，前端只读，不参与物理和训练标签计算。

交付物：

```text
backend/app/main.py
backend/app/api/routes_episodes.py
backend/app/api/routes_datasets.py
backend/app/api/websocket.py
frontend/src/types/generated
frontend/src/components/Scene3D.tsx
frontend/src/components/Timeline.tsx
frontend/src/components/CommandLog.tsx
frontend/src/components/EventLog.tsx
frontend/src/components/RiskPanel.tsx
```

必须完成：

- REST validate/start/stop/state/summary/download；
- WebSocket 推送 SimFrame；
- 离线加载 `visual/frames.jsonl`；
- 时间轴、暂停、倍速、跳转；
- 塔吊程序几何模型；
- site zones、overlap zones；
- 简化吊物显示；
- event click-to-seek；
- command log 展开 observation/messages/raw/parsed/executed；
- offline label 标注为“离线标签/事后分析”；
- realtime 不携带 offline future labels。

M4 验收：

```text
frontend npm run typecheck 通过；
打开 demo episode 不报 schema mismatch；
点击 near_miss/collision/forbidden_zone_violation 能跳转；
WebSocket 断线有提示或重连；
前端 display-only 距离不写入后端 truth。
```

### 15.7 M5：dataset builder 与 STGNN window

目标：把 episode 变成论文训练数据，保证无泄漏、可统计、可复现。

交付物：

```text
backend/app/data/dataset_builder.py
backend/app/data/window_builder.py
backend/app/data/splits.py
scripts/batch_generate.py
scripts/build_dataset.py
docs/data_schema.md
docs/dataset_protocol.md
```

必须完成：

- batch_generate 多 scenario、多 seed；
- dataset_targets；
- quality gate + quarantine；
- train/val/test 按 episode/scenario 划分；
- STGNN window 输出；
- risk 分布统计；
- dataset_summary；
- manifest 保存生成配置、schema version、git commit。

M5 验收：

```text
至少 100 个 episode 的小规模数据集可生成；
train/val/test 无 episode 泄漏；
STGNN Dataset 能读取一个 batch；
dataset_summary 报告实际风险比例；
quarantine episode 不进入默认训练集。
```

### 15.8 Issue 拆分建议

建议按“合同对象 + 验收脚本”拆 issue，而不是按 UI 页面或算法名拆。

```text
ISSUE-001  Config schema + resolved_config_hash
ISSUE-002  CraneModelSpec + capacity_at_radius
ISSUE-003  Controller gear mapping + acceleration limits
ISSUE-004  FrameRecord + trajectories writer
ISSUE-005  Auto layout generator + diagnostics
ISSUE-006  Task state machine + attach/release thresholds
ISSUE-007  Rule operator v1
ISSUE-008  Risk geometry distances
ISSUE-009  Event lifecycle manager
ISSUE-010  Scheduler single-frame lifecycle
ISSUE-011  ExecutedCommand replay
ISSUE-012  Data quality gates
ISSUE-013  Observation schema + leakage tests
ISSUE-014  LLM provider base + mock
ISSUE-015  DeepSeek provider
ISSUE-016  MiniMax provider
ISSUE-017  Retry + neutral_stop + llm_failed
ISSUE-018  FastAPI episode routes
ISSUE-019  SimFrame generated TypeScript types
ISSUE-020  Three.js offline playback
ISSUE-021  Command/Event log panels
ISSUE-022  Dataset builder + splits
ISSUE-023  STGNN window builder
```

### 15.9 v0.4 可直接开工的冻结项

以下内容建议在第一次代码提交前冻结，除非发现严重逻辑错误，否则不要频繁改名：

```text
核心枚举:
  Task.status
  Crane.task_stage
  Episode.status
  Operator.mode
  Risk.level
  Event.lifecycle
  Error code domain

核心文件:
  resolved_config.yaml
  trajectories.parquet
  pair_risks.parquet
  commands.jsonl
  events.jsonl
  visual/frames.jsonl
  visual/episode_manifest.json
  replay/command_replay.jsonl

核心链路:
  RawLLMResponse -> ParsedCommand -> ExecutedCommand -> ControlTarget -> CraneState
  WorldState -> WorldSnapshot -> Observation
  FrameRecord -> SimFrame -> Frontend
```

### 15.10 后续需要继续完善的专项文档

v0.4 已经能支持工程开工，但后续建议拆出以下专题文档：

```text
docs/data_schema.md:
  每个 Parquet/JSONL 字段、单位、nullable、枚举、版本迁移。

docs/api_contract.md:
  REST/WebSocket 请求响应、错误码、权限和下载策略。

docs/frontend_playback.md:
  SimFrame 渲染规则、离线标签显示规范、事件跳转。

docs/provider_deepseek_minimax.md:
  按最新官方 API 固化结构化输出、错误码、限流和重试。

docs/replay_and_determinism.md:
  hash、容差、浮点确定性、mismatch 诊断。

docs/dataset_protocol.md:
  风险比例目标、quarantine、划分原则、无泄漏证明。
```

### 15.11 方案边界声明

本系统是面向研究数据生成和仿真展示的平台，不是面向真实塔吊的自动驾驶、远程控制或安全认证系统。任何论文、演示或报告必须清楚说明：

```text
数据来源为仿真；
LLM 只参与仿真操作行为生成；
基础机械安全是仿真约束，不代表真实设备安全认证；
风险标签来自仿真几何和离线轨迹，不代表真实工地传感器标签；
系统不可直接用于真实塔吊控制。
```
