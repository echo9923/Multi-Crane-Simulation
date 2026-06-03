# 群塔 LLM-in-the-loop 仿真系统开发 Prompt（可直接交给 AI/工程助手执行）

> 版本：v0.1  
> 项目定位：为“基于物理先验时空动态图的群塔起重臂轨迹预测与碰撞风险预警研究”生成合理、可控、可标注的仿真数据。  
> 重要边界：本系统不是要证明 LLM 能真实安全控制塔吊；LLM 只作为“任务驱动的操作员行为生成器”，用于提高仿真轨迹的任务合理性、人类操作特征和多塔交互复杂度。论文主线仍然是：  
> **物理先验动态图构建 → 时空预测模型训练 → 未来轨迹几何重构 → 碰撞风险预警评估 → 对比实验与消融验证。**

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

## 1. 技术路线总览

### 1.1 推荐总体架构

采用“后端仿真核心 + 数据导出 + Web 3D 前端展示”的前后端分离方案。

```text
scenario.yaml / experiment.yaml
        ↓
Python Simulation Core
        ├── 塔吊运动学/简化动力学模型
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
- 可选：Hydra 或 YAML 配置系统，用于批量实验配置
- 可选：PyTorch / PyTorch Geometric，用于后续轨迹预测模型训练接口

#### 物理/仿真引擎建议

优先级从高到低：

1. **自建参数化运动学/简化动力学仿真器**  
   推荐作为主数据生成器。塔吊起重臂运动主要受回转角、回转速度、角加速度、臂长、塔高和小车幅度约束，自建模型速度快、可控性强、易于生成大规模训练数据。

2. **PyBullet / Bullet**  
   用于几何碰撞、刚体检测、简单可视化或结果校核。适合 Python 快速原型，但不建议把所有数据生成完全依赖 PyBullet。

3. **MuJoCo**  
   适合需要更稳定的多关节刚体动力学、接触、绳索/摆动近似建模时使用。适合作为增强实验或吊物摆动验证。

4. **Gazebo Sim**  
   适合 ROS/机器人生态、传感器仿真和较规范的机器人系统验证。实现成本较高，适合作为后期工程化验证，不作为第一阶段主线。

5. **NVIDIA Isaac Sim**  
   适合高保真可视化、合成传感器数据、RTX/PhysX 物理仿真。硬件要求高、工程复杂，不推荐作为硕士论文第一阶段核心。

6. **Unity / Unity ML-Agents**  
   适合三维展示、交互、游戏化仿真和 Agent 环境搭建；但若目标是批量生成训练数据，Python 核心仿真通常更稳。Unity 可作为展示端或高级可视化端，不作为第一阶段核心。

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

- 必须使用结构化输出：JSON Schema / Pydantic Schema
- 必须支持异步调用
- 必须支持缓存与重放
- 必须支持规则司机 fallback
- 必须保存 LLM observation、raw response、parsed command、最终执行 command
- 禁止让 LLM 直接输出连续力矩或直接修改物理状态

---

## 2. 系统核心设计原则

### 2.1 LLM 只做低频高层决策

不要让 LLM 每一帧控制塔吊。采用：

```text
物理仿真频率：20 Hz 或 50 Hz
低层控制器频率：5 Hz 或 10 Hz
LLM 决策频率：0.5 Hz 或 1 Hz，或事件触发
```

LLM 输出高层操作意图，例如：

```json
{
  "slew": "right",
  "slew_speed": "low",
  "trolley": "out",
  "hoist": "hold",
  "brake": false,
  "attach_or_release": "none",
  "reason": "取货点在右前方，但2号塔吊接近重叠区，因此低速右转并保持观察。"
}
```

低层控制器负责将该离散命令转换为连续速度/加速度指令。

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
S0 基础安全设施：只保留机械与基础安全约束，不提示、不干预
S1 预警提示模式：计算风险并提示 LLM，不强制干预
S2 软干预模式：高风险时限制速度或限制部分动作
S3 强干预模式：高风险时强制减速/停车
```

主要训练数据建议来自 S1；S0/S2/S3 用于对照实验。

### 2.4 数据必须可复现

- 所有随机过程必须可设置 seed
- 所有 LLM 输入输出必须落盘
- 可通过 `replay_mode=true` 使用已保存 LLM 指令复现完全相同轨迹
- 规则司机必须可替代 LLM，用于无网络/无 LLM 情况下生成数据

---

## 3. 模块设计与验收标准

---

# 模块 A：场景配置与实验管理模块

## A.1 功能

负责读取、校验、保存仿真场景与实验配置。

输入：

- `scenario.yaml`
- `experiment.yaml`
- 命令行参数或 API 参数

输出：

- 标准化场景对象 `ScenarioConfig`
- 标准化实验对象 `ExperimentConfig`
- 运行目录 `runs/{experiment_id}/`

## A.2 配置文件示例

```yaml
scenario_id: "site_001"
seed: 20260101
sim:
  dt: 0.05
  duration_s: 600
  physics_hz: 20
  controller_hz: 10
  llm_decision_hz: 1
  safety_mode: "S1"

site:
  coordinate_system: "ENU"
  boundary:
    x_min: -100
    x_max: 100
    y_min: -100
    y_max: 100
  forbidden_zones:
    - zone_id: "building_core"
      type: "box"
      center: [0, 0, 20]
      size: [20, 20, 40]

cranes:
  - crane_id: "C1"
    base: [0, 0, 0]
    mast_height: 45
    jib_length: 55
    counter_jib_length: 15
    theta_init_deg: 20
    theta_limit_deg: [-180, 180]
    slew_speed_max_deg_s: 0.8
    slew_acc_max_deg_s2: 0.3
    trolley_r_min: 5
    trolley_r_max: 50
    trolley_speed_max_m_s: 0.5
    hoist_h_min: 0
    hoist_h_max: 45
    hoist_speed_max_m_s: 0.6
    load_capacity_t: 6

tasks:
  generation_mode: "random"
  num_tasks_per_crane: 5
  pickup_z: 1.5
  dropoff_z_range: [10, 40]
  priority_distribution:
    low: 0.3
    medium: 0.5
    high: 0.2

weather:
  mode: "schedule"
  wind:
    base_speed_m_s: 6
    gust_speed_m_s: 12
    direction_deg: 90
  visibility:
    base_level: "medium"

llm:
  enabled: true
  provider: "provider_agnostic"
  model: "your-model-name"
  temperature: 0.4
  max_retries: 2
  cache_enabled: true
  fallback_policy: "rule_operator"
```

## A.3 验收标准

- 能读取并校验 YAML 配置；
- 缺失必要字段时给出明确错误；
- 所有默认值可追溯；
- 每次运行自动生成独立 run 目录；
- 同一 seed + 同一 replay 指令文件可复现相同轨迹；
- 支持至少 3 台塔吊、每台至少 5 个任务的场景配置。

---

# 模块 B：塔吊运动学与简化动力学模块

## B.1 功能

建立塔吊状态更新模型，将 LLM 高层指令通过低层控制器转化为符合塔吊运动约束的连续运动。

## B.2 状态变量

每台塔吊状态：

```json
{
  "crane_id": "C1",
  "theta_rad": 0.5236,
  "theta_dot_rad_s": 0.01,
  "theta_ddot_rad_s2": 0.0,
  "trolley_r_m": 25.0,
  "trolley_v_m_s": 0.1,
  "hook_h_m": 20.0,
  "hoist_v_m_s": 0.0,
  "load_attached": false,
  "load_weight_t": 0.0,
  "task_id": "T_C1_001",
  "task_stage": "move_to_pickup"
}
```

## B.3 几何重构

根部坐标：

```math
p_{root,i} = (x_i, y_i, H_i)
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

## B.4 状态更新

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

## B.5 验收标准

- 在无控制输入时状态保持稳定；
- 回转角、角速度、角加速度不超过配置限制；
- 小车位置不越界；
- 吊钩高度不越界；
- 臂端坐标与公式一致，单元测试误差小于 `1e-6`；
- 支持至少 20 Hz 仿真频率；
- 支持 3-6 台塔吊同时仿真；
- 运行 600 秒仿真不出现 NaN、Inf 或状态爆炸。

---

# 模块 C：任务生成模块

## C.1 功能

生成取货点、卸货点、载荷、优先级、截止时间等任务，但不预设完整操作路线。LLM 操作员需要根据任务目标自主完成操作。

## C.2 任务对象格式

```json
{
  "task_id": "T_C1_001",
  "crane_id": "C1",
  "pickup": {"x": 25.0, "y": 20.0, "z": 1.5},
  "dropoff": {"x": -15.0, "y": 40.0, "z": 30.0},
  "load_type": "rebar_bundle",
  "load_weight_t": 2.5,
  "priority": "medium",
  "deadline_s": 180,
  "status": "pending"
}
```

## C.3 任务阶段

允许阶段：

```text
pending
move_to_pickup
align_pickup
lower_for_attach
attach_load
lift_load
move_to_dropoff
align_dropoff
lower_for_release
release_load
completed
failed
```

## C.4 任务完成判定

挂载判定：

```math
||p_{hook}^{xy}-p_{pickup}^{xy}|| < \epsilon_{xy}
```

```math
|h_{hook}-h_{pickup}| < \epsilon_h
```

同时 LLM 指令为 `attach_load` 时，才允许挂载。

卸载判定：

```math
||p_{hook}^{xy}-p_{dropoff}^{xy}|| < \epsilon_{xy}
```

```math
|h_{hook}-h_{dropoff}| < \epsilon_h
```

同时 LLM 指令为 `release_load` 时，才允许卸载。

## C.5 验收标准

- 能为每台塔吊生成多个任务；
- 能生成作业半径重叠任务；
- 能生成无冲突任务、临界接近任务、高风险任务；
- 不直接给出操作路线；
- 任务完成由仿真器几何条件判定，不由 LLM 自报完成；
- 记录任务开始时间、完成时间、失败原因；
- 至少 80% 的简单任务可由规则司机完成，用于验证任务生成合理性。

---

# 模块 D：天气与可见度模块

## D.1 功能

生成风速、风向、阵风、可见度等环境变量。天气一方面影响物理模型或安全阈值，另一方面影响 LLM 操作员的观测信息与决策风格。

## D.2 输出格式

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

## D.3 影响方式

最低要求：

- 风速影响风险提示文本；
- 风速影响吊物摆动或安全距离冗余，若尚未实现吊物摆动，则影响 `d_safe_effective`；
- 可见度影响 LLM 可观察信息，例如隐藏部分邻近吊钩信息；
- 阵风触发更保守的安全建议。

## D.4 验收标准

- 支持固定天气、分段天气、随机天气；
- 同一 seed 下天气序列可复现；
- LLM observation 中能体现天气和可见度；
- 数据记录中包含每一帧天气状态；
- 可切换是否启用天气扰动；
- 至少支持三档可见度：good / medium / poor。

---

# 模块 E：LLM 操作员观测构造模块

## E.1 功能

为每台塔吊构造“人类驾驶员可见”的局部观测，而不是全局真值。

## E.2 观测内容

观测应包含：

1. 自身塔吊状态；
2. 当前任务目标；
3. 当前任务阶段；
4. 取货点/卸货点相对方位；
5. 可见邻近塔吊信息；
6. 风速与可见度；
7. 风险提示；
8. 可用操作按钮；
9. 操作员性格或行为倾向。

## E.3 示例

```json
{
  "operator_id": "OP_C1",
  "crane_id": "C1",
  "time_s": 42.0,
  "task": {
    "stage": "move_to_pickup",
    "pickup_relative": "right_front",
    "pickup_distance_m": 18.4,
    "dropoff_relative": "left_front",
    "priority": "medium"
  },
  "self_state": {
    "slew_angle_deg": 72.0,
    "slew_speed": "low_right",
    "trolley_r_m": 24.0,
    "hook_h_m": 31.0,
    "load_attached": false
  },
  "visible_neighbors": [
    {
      "crane_id": "C2",
      "relative_direction": "right_front",
      "jib_status": "slow_left",
      "risk_hint": "entering_overlap_zone"
    }
  ],
  "weather": {
    "wind_speed_m_s": 8.0,
    "gust_m_s": 12.0,
    "visibility": "medium"
  },
  "safety_hint": {
    "risk_level": "medium",
    "min_distance_next_5s_m": 4.5,
    "suggestion": "slow_down_or_hold"
  },
  "available_actions": {
    "slew": ["left", "right", "hold"],
    "slew_speed": ["stop", "low", "medium", "high"],
    "trolley": ["in", "out", "hold"],
    "hoist": ["up", "down", "hold"],
    "brake": [true, false],
    "attach_or_release": ["none", "attach_load", "release_load"]
  }
}
```

## E.4 验收标准

- 不向 LLM 暴露完整全局真值；
- 可根据可见度隐藏或模糊邻近塔吊/吊钩信息；
- 可配置不同操作员性格；
- 每次 LLM 调用前保存 observation；
- observation 可被离线重放；
- observation 字段通过 Pydantic 校验。

---

# 模块 F：LLM 操作员决策模块

## F.1 功能

LLM 根据观测和任务目标输出结构化高层操作命令。该命令不直接改变仿真状态，必须经过解析、基础安全设施和低层控制器。

## F.2 LLM Prompt 模板

系统提示词：

```text
你正在模拟一名塔吊司机。你只能根据提供的局部观测、任务目标、可见邻近塔吊状态、天气信息和安全提示进行操作决策。你的目标是在保证安全的前提下完成取货和卸货任务。你不能输出未列出的动作。你必须返回严格 JSON，不要输出解释性文本。
```

用户提示词：

```text
以下是当前观测信息：
{observation_json}

请从 available_actions 中选择下一步高层操作。你的决策将执行约 1 秒。请考虑任务目标、邻近塔吊、风速、可见度和风险提示。
```

## F.3 输出 Schema

```json
{
  "type": "object",
  "required": [
    "slew",
    "slew_speed",
    "trolley",
    "hoist",
    "brake",
    "attach_or_release",
    "attention_target",
    "confidence",
    "reason"
  ],
  "properties": {
    "slew": {"type": "string", "enum": ["left", "right", "hold"]},
    "slew_speed": {"type": "string", "enum": ["stop", "low", "medium", "high"]},
    "trolley": {"type": "string", "enum": ["in", "out", "hold"]},
    "hoist": {"type": "string", "enum": ["up", "down", "hold"]},
    "brake": {"type": "boolean"},
    "attach_or_release": {"type": "string", "enum": ["none", "attach_load", "release_load"]},
    "attention_target": {"type": "string"},
    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    "reason": {"type": "string"}
  },
  "additionalProperties": false
}
```

## F.4 操作员性格

至少支持：

```text
conservative：保守，风险提示中等时也减速或等待
normal：正常，风险高时减速
aggressive：激进，只有风险高或非常接近时才减速
novice：新手，动作更频繁，容易犹豫
fatigued：疲劳，反应延迟更大，偶尔忽视提示
```

## F.5 验收标准

- LLM 输出必须通过 JSON Schema 校验；
- 输出不合法时自动重试；
- 重试失败时使用规则司机 fallback；
- 每次调用保存 observation、raw_response、parsed_command、latency、token_usage；
- 支持 replay 模式，不调用 LLM，直接读取历史命令；
- 支持多塔吊多个独立 operator session；
- 决策频率低于物理仿真频率；
- LLM 不能直接访问仿真全局真值；
- LLM 不能直接修改物理状态。

---

# 模块 G：基础安全设施与风险影子评估模块

## G.1 功能

该模块分为三层：

```text
基础安全设施层：硬约束，必须执行
风险影子评估层：实时计算风险，用于提示、记录、标注
可配置防碰撞干预层：根据 S0/S1/S2/S3 决定是否干预
```

## G.2 基础安全设施层

必须硬执行：

- 最大回转速度
- 最大角加速度
- 小车行程范围
- 起升高度范围
- 起重量/力矩限制
- 基础机械限位
- 挂载/卸载几何判定

## G.3 风险影子评估层

计算但不默认干预：

```math
d_{ij}(t)=dist(S_i(t),S_j(t))
```

```math
d_{min}^{ij}(t)=\min_{\tau \in [1,H]}dist(S_i(t+\tau),S_j(t+\tau))
```

```math
TTC_{ij}(t)=\min\{\tau: dist(S_i(t+\tau),S_j(t+\tau))<d_{safe}\}
```

风险等级示例：

```text
safe: d_min > 8 m
low: 5 m < d_min <= 8 m
medium: 3 m < d_min <= 5 m
high: 1.5 m < d_min <= 3 m
collision: d_min <= 1.5 m 或几何相交
```

## G.4 可配置干预

```yaml
safety_mode: "S1"
intervention:
  S0:
    hint_to_operator: false
    modify_command: false
  S1:
    hint_to_operator: true
    modify_command: false
  S2:
    hint_to_operator: true
    modify_command: true
    rule: "limit_speed_on_high_risk"
  S3:
    hint_to_operator: true
    modify_command: true
    rule: "force_stop_on_high_risk"
```

## G.5 验收标准

- 基础安全设施始终生效；
- 多塔碰撞风险在 S1 下只提示不修改命令；
- S2/S3 下能按配置修改命令；
- 保存 raw_command 与 executed_command；
- 记录每次干预原因；
- 风险距离计算有单元测试；
- 简单线段交叉用例能正确识别高风险/碰撞；
- 可导出每一帧每一对塔吊的风险标签。

---

# 模块 H：低层控制器模块

## H.1 功能

将 LLM 离散高层命令转换为连续控制目标。

例如：

```json
{
  "slew": "right",
  "slew_speed": "low",
  "trolley": "out",
  "hoist": "hold"
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

## H.2 速度档位

```yaml
speed_levels:
  slew:
    stop: 0.0
    low: 0.3
    medium: 0.6
    high: 0.8
  trolley:
    low: 0.15
    medium: 0.3
    high: 0.5
  hoist:
    low: 0.2
    medium: 0.4
    high: 0.6
```

## H.3 验收标准

- 所有高层指令都能转换为连续控制目标；
- 支持加速度限制和平滑过渡；
- brake=true 时执行减速或停车；
- 控制器输出不超过塔吊机械限制；
- 保存控制命令日志；
- 支持规则司机、LLM 司机共用同一控制器。

---

# 模块 I：仿真调度与多 Agent 异步模块

## I.1 功能

管理物理仿真步进、低层控制、LLM 决策、风险评估和数据记录。

## I.2 推荐伪代码

```python
while sim_time < duration:
    update_weather(sim_time)

    for crane in cranes:
        if should_request_llm_decision(crane, sim_time):
            submit_llm_request_async(crane, build_observation(crane))

    for crane in cranes:
        if llm_response_ready(crane):
            raw_cmd = parse_llm_response(crane)
            exec_cmd = safety_and_intervention(raw_cmd, crane, world_state)
            crane.current_command = exec_cmd
        elif command_timeout(crane):
            crane.current_command = fallback_or_hold(crane)

    for crane in cranes:
        control = low_level_controller(crane.current_command, crane.state)
        crane.apply_control(control)

    physics_step(dt)
    compute_risk_shadow()
    update_task_status()
    record_frame()
    broadcast_frame_to_frontend()
    sim_time += dt
```

## I.3 验收标准

- 仿真不会因为某个 LLM 响应慢而卡死；
- LLM 超时后可保持上一指令或使用 fallback；
- 支持实时模式和加速离线模式；
- 支持无 LLM 批量生成；
- 支持 replay 模式；
- 记录每一帧状态；
- 记录每一次 LLM 决策对应的仿真时间。

---

# 模块 J：碰撞距离、TTC 与风险标签模块

## J.1 功能

为后续轨迹预测和碰撞风险预警模型生成标签。

## J.2 输出标签

每个时间步、每对塔吊：

```json
{
  "episode_id": "E001",
  "frame": 120,
  "time_s": 6.0,
  "crane_i": "C1",
  "crane_j": "C2",
  "distance_now_m": 6.2,
  "min_distance_future_5s_m": 3.4,
  "min_distance_future_10s_m": 2.8,
  "ttc_5s_s": null,
  "ttc_10s_s": 8.2,
  "risk_level_5s": "medium",
  "risk_level_10s": "high",
  "collision_label_5s": 0,
  "collision_label_10s": 1
}
```

## J.3 风险对象

最小毕业版本必须支持：

- 塔臂—塔臂线段距离

增强版本支持：

- 塔臂—吊钩点距离
- 吊钩—吊钩距离
- 吊物摆动包络距离

## J.4 验收标准

- 塔臂线段距离计算正确；
- 未来窗口标签可配置：5s、10s、15s；
- 标签生成不依赖模型预测，只依赖仿真真值；
- 碰撞/临界接近事件能被自动记录；
- 风险标签可导出为 Parquet；
- 可生成正负样本比例统计；
- 支持按 episode、scenario、crane_pair 聚合统计。

---

# 模块 K：数据记录与导出模块

## K.1 文件结构

```text
runs/
  exp_2026_001/
    config/
      scenario.yaml
      experiment.yaml
    metadata/
      episode_metadata.json
      dataset_summary.json
    logs/
      llm_observations.jsonl
      llm_raw_responses.jsonl
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
      preview.mp4
      screenshots/
```

## K.2 trajectories.parquet 字段

每帧每塔吊一行：

```text
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
load_weight_t: float
task_id: string
task_stage: string
operator_type: string

executed_slew: string
executed_slew_speed: string
executed_trolley: string
executed_hoist: string
executed_brake: bool

wind_speed_m_s: float
wind_gust_m_s: float
wind_direction_deg: float
visibility_level: string
```

## K.3 pair_risks.parquet 字段

每帧每塔吊对一行：

```text
episode_id: string
scenario_id: string
frame: int
time_s: float
crane_i: string
crane_j: string

distance_jib_jib_now_m: float
distance_jib_hook_now_m: float
distance_hook_hook_now_m: float

min_distance_future_5s_m: float
min_distance_future_10s_m: float
min_distance_future_15s_m: float

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

## K.4 graph_edges.parquet 字段

用于物理先验动态图训练：

```text
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

## K.5 commands.jsonl 字段

```json
{
  "episode_id": "E001",
  "time_s": 42.0,
  "crane_id": "C1",
  "operator_id": "OP_C1",
  "observation_id": "OBS_000123",
  "raw_llm_response": "{...}",
  "parsed_command": {
    "slew": "right",
    "slew_speed": "low",
    "trolley": "out",
    "hoist": "hold",
    "brake": false
  },
  "executed_command": {
    "slew": "right",
    "slew_speed": "low",
    "trolley": "out",
    "hoist": "hold",
    "brake": false
  },
  "modified_by_intervention": false,
  "intervention_reason": null,
  "latency_ms": 820,
  "confidence": 0.76,
  "reason": "取货点在右前方，低速接近并观察2号塔吊。"
}
```

## K.6 验收标准

- 所有数据文件能被 Pandas/PyArrow 正常读取；
- 至少导出 trajectories、pair_risks、graph_edges、commands、metadata；
- 所有 episode 有唯一 ID；
- 所有文件包含 schema version；
- 可从导出的 replay 文件复现轨迹；
- 生成 dataset_summary，包括风险样本比例、任务完成率、碰撞次数、临界接近次数；
- 数据格式能直接用于时空图训练窗口切片。

---

# 模块 L：后端 API 模块

## L.1 功能

提供仿真运行、数据查询、实时状态推送和前端展示支持。

## L.2 REST API

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

## L.3 WebSocket

```text
WS /ws/episodes/{episode_id}
```

推送帧格式：

```json
{
  "type": "sim_frame",
  "episode_id": "E001",
  "frame": 120,
  "time_s": 6.0,
  "cranes": [
    {
      "crane_id": "C1",
      "root": [0, 0, 45],
      "tip": [42, 18, 45],
      "hook": [20, 8, 25],
      "theta_rad": 0.40,
      "risk_level": "medium",
      "task_stage": "move_to_pickup"
    }
  ],
  "pairs": [
    {
      "crane_i": "C1",
      "crane_j": "C2",
      "distance_m": 4.5,
      "risk_level": "medium"
    }
  ],
  "weather": {
    "wind_speed_m_s": 8.0,
    "visibility": "medium"
  }
}
```

## L.4 验收标准

- API 有自动文档；
- WebSocket 能以至少 10 FPS 推送前端展示数据；
- 能启动、暂停、恢复、停止仿真；
- 能下载数据集；
- 错误响应结构统一；
- 支持本地单机运行；
- 支持无前端批量生成数据。

---

# 模块 M：前端 3D 展示模块

## M.1 功能

展示仿真场景、塔吊运动、吊钩位置、任务点、风险距离、LLM 操作日志和天气状态。

## M.2 页面设计

至少包含：

1. 3D 场景视图；
2. 时间轴与播放控制；
3. 塔吊状态面板；
4. 任务状态面板；
5. 风险状态面板；
6. LLM 指令日志；
7. 数据导出按钮；
8. 场景配置上传/选择入口。

## M.3 3D 展示元素

- 地面/施工区域边界；
- 塔吊塔身；
- 起重臂；
- 平衡臂；
- 小车；
- 吊钩；
- 取货点；
- 卸货点；
- 禁区；
- 作业半径圆；
- 多塔重叠区域；
- 塔臂轨迹尾迹；
- 风向箭头；
- 风险连线；
- 碰撞/临界接近高亮。

## M.4 交互功能

- 播放/暂停/倍速；
- 切换跟随某台塔吊；
- 切换风险显示；
- 切换轨迹尾迹长度；
- 点击塔吊查看状态；
- 点击塔吊对查看距离与 TTC；
- 查看 LLM 原始指令和最终执行指令；
- 离线加载历史 episode 回放。

## M.5 验收标准

- 能实时展示至少 3 台塔吊；
- 能回放历史 episode；
- 风险等级颜色/样式可区分；
- 能显示取货点、卸货点和当前任务阶段；
- 能显示 LLM 指令日志；
- WebSocket 断开后能自动重连或显示错误；
- 前端不参与物理计算，只展示后端状态；
- 3D 场景与导出数据中的坐标一致。

---

# 模块 N：实验与数据集生成模块

## N.1 功能

批量生成用于轨迹预测和风险预警模型训练的数据集。

## N.2 场景类别

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
```

## N.3 数据集划分

建议：

```text
train：普通布局 + 多种任务
val：相似布局 + 新任务
test_seen_layout：已见布局 + 新任务
test_unseen_layout：新塔吊布局
test_unseen_num_cranes：不同塔吊数量
test_high_risk：高风险场景
```

## N.4 验收标准

- 至少生成 100 个 episode；
- 每个 episode 至少 300 秒仿真；
- 至少包含 3 类风险等级；
- 高风险或临界接近样本比例可配置；
- 数据集划分不按滑动窗口随机划分，必须按 episode/scenario 划分；
- 输出 dataset_summary；
- 训练窗口切片脚本可读取数据并生成 STGNN 输入。

---

# 模块 O：时空图训练数据转换模块

## O.1 功能

将仿真导出的长序列转换为轨迹预测模型所需的窗口数据。

## O.2 输入

- `trajectories.parquet`
- `pair_risks.parquet`
- `graph_edges.parquet`
- `tasks.parquet`

## O.3 输出

训练样本：

```python
X_node: [num_nodes, input_steps, node_feature_dim]
X_edge: [input_steps, num_edges, edge_feature_dim]
A_phy: [input_steps, num_nodes, num_nodes]
Y_traj: [num_nodes, pred_steps, target_dim]
Y_risk: [num_edges, risk_label_dim]
metadata: scenario_id, episode_id, start_frame
```

## O.4 节点特征建议

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

## O.5 边特征建议

```text
current_jib_jib_distance
overlap_ratio
delta_height
delta_theta
delta_theta_dot
estimated_ttc
current_risk_level_onehot
```

## O.6 标签建议

```text
未来 theta 或 sin/cos(theta)
未来 tip_x, tip_y, tip_z
未来 hook_x, hook_y, hook_z
未来最小距离
未来风险等级
未来 TTC
```

## O.7 验收标准

- 能生成固定长度输入和预测窗口；
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
- 能生成取货点和卸货点任务；
- LLM 操作员能根据任务目标和局部观测发出操作指令；
- 低层控制器能执行 LLM 指令；
- 基础塔吊安全设施能限制不合理机械动作；
- 风险影子评估能计算当前距离、未来最小距离、TTC 和风险等级；
- 能导出轨迹、风险、图边、任务、天气、LLM 指令日志；
- 能通过前端 3D 页面实时展示或离线回放。

### 4.2 数据验收

- 数据字段完整，单位明确；
- 所有数据文件包含 schema version；
- 同一 episode 可 replay；
- 风险标签可复核；
- 能生成训练、验证、测试数据划分；
- 能生成 STGNN 所需窗口数据；
- 轨迹数据无 NaN、Inf、明显跳变；
- 高风险样本比例可控。

### 4.3 性能验收

最低要求：

```text
3 台塔吊、20 Hz、600 秒 episode，可在普通笔记本上离线生成；
无 LLM 模式下仿真速度 ≥ 实时 5 倍；
LLM 模式下支持异步，不因单个 LLM 超时阻塞整个系统；
WebSocket 展示帧率 ≥ 10 FPS；
前端可展示 3-6 台塔吊。
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
- 3 台塔吊；
- 取货点/卸货点任务；
- 规则司机；
- LLM 司机接口，但可用 mock LLM 代替；
- 基础安全设施；
- S1 风险提示模式；
- 塔臂—塔臂距离计算；
- 轨迹、风险、命令日志导出；
- FastAPI 启动仿真；
- React + Three.js 3D 回放；
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

test_risk.py
  - test_risk_level_safe
  - test_risk_level_high
  - test_ttc_detected
  - test_future_min_distance

test_task.py
  - test_attach_condition
  - test_release_condition
  - test_task_completion

test_controller.py
  - test_speed_limit
  - test_acc_limit
  - test_brake

test_llm_schema.py
  - test_valid_command
  - test_invalid_command_fallback
  - test_replay_command

test_export.py
  - test_parquet_readable
  - test_required_columns
```

---

## 8. 前端验收场景

请准备一个 `demo_episode`，前端必须能展示：

1. 三台塔吊；
2. 每台塔吊不同任务阶段；
3. 至少一段临界接近；
4. 风速变化；
5. LLM 指令日志；
6. 当前风险等级；
7. 未来 5 秒最小距离；
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

> 为提高仿真数据的任务合理性和交互真实性，本文构建 LLM-in-the-loop 的群塔操作行为生成模块。该模块仅指定取货点、卸货点、载荷和优先级等任务目标，不预设完整运动轨迹，而是由 LLM 操作员根据有限视野、天气条件、邻近塔吊状态和安全提示生成高层操作指令。指令经由基础安全设施与低层控制器转化为塔吊可执行动作，从而生成具有任务意图、操作差异和交互冲突特征的群塔运行数据。该模块服务于仿真数据生成，本文核心研究仍为基于物理先验时空动态图的轨迹预测与碰撞风险预警方法。

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

请按以下顺序实现：

### 阶段 1：无 LLM 的可复现仿真核心

- 场景配置
- 塔吊运动学
- 任务生成
- 规则司机
- 风险距离计算
- 数据导出
- 单元测试

验收：能生成 3 台塔吊、300 秒、含任务与风险标签的 Parquet 数据。

### 阶段 2：LLM 操作员接入

- observation 构造
- JSON Schema 输出
- 异步调用
- fallback
- replay
- 命令日志

验收：LLM 能完成简单取卸货任务；失败时能 fallback；所有输入输出可追溯。

### 阶段 3：Web 后端与前端展示

- FastAPI REST
- WebSocket 推送
- React + Three.js 展示
- 时间轴和日志面板

验收：能实时展示或回放 episode。

### 阶段 4：批量数据集生成

- 多场景配置
- 多 seed 运行
- train/val/test 划分
- dataset_summary
- STGNN 窗口转换

验收：能生成可用于论文实验的数据集。

### 阶段 5：增强实验

- 天气扰动
- 不同操作员性格
- S0/S1/S2/S3 安全模式对比
- LLM vs 规则司机 vs 随机策略对比
- 新布局/新塔吊数量泛化数据

验收：能支撑论文中的仿真数据合理性分析。

---

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
