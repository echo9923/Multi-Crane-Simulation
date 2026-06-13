# Module N Overview：前端 3D 展示边界

## 职责

Module N 是仿真系统的前端 3D 展示层。它把 Module M 的 REST API 与 WebSocket、Module L 落盘的 `visual/frames.jsonl` / `episode_manifest.json`、Module A 的 `ResolvedConfig` 统一渲染成一个可在浏览器查看的 3D 仿真场景，并展示塔吊运动、吊钩位置、吊物形状、作业区域、风险距离、风向天气、LLM 决策日志和事件日志，支持离线回放和实时 WebSocket 推送。

N 的核心原则是**只展示、不计算**。它可以从后端读取状态、解析离线帧、把帧映射到 3D 场景，但绝不参与物理积分、任务状态机、安全审查、风险计算或 LLM 调用；前端展示的任何辅助距离或风险只能标记为 `display-only`，不得回流为训练真值。

## 页面结构

单一 React SPA，路由：

```text
/                  3D 场景主视图（默认）
/replay/:episodeId 加载历史 episode 离线回放
/live/:episodeId   连接 WebSocket 实时观看
/config            场景配置上传 / 选择入口（触发后端 validate）
```

主视图布局（响应式，桌面优先）：

```text
+--------------------------------------------------------------+
| 顶栏：模式(replay/live) | episode id | 连接状态 | 倍速 | 导出 |
+------------------+-------------------------------------------+
| 左：场景控制      | 中：3D 画布 (Three.js)                      |
|   - 塔吊列表      |     - 地面 / 工地边界 / zones               |
|   - 跟随/选中     |     - N 台塔吊 + 吊物 + 半径圆               |
|   - 风险显示开关  |     - 风险连线 / 重叠区 / 风向箭头          |
+------------------+-------------------------------------------+
| 右：状态面板（塔吊/任务/风险） + LLM 指令日志 + 事件日志      |
+--------------------------------------------------------------+
| 底：时间轴 + 播放/暂停/倍速/拖拽跳转                          |
+--------------------------------------------------------------+
```

`display-only` 标记统一展示：凡前端估算/插值的距离、风险、TTC 一律带 `display-only` 徽标与 tooltip 说明，禁止以训练真值形式出现。

## 3D 展示元素

- **静态场景**（来自 `ResolvedConfig`）：
  - 地面网格与工地边界（`SiteConfig.boundary` AABB）。
  - `material_zones` / `work_zones` / `forbidden_zones`（`box` 轴对齐体与 `polygon` 水平足迹 + `z_range_m` 高度范围）。
  - 每台塔吊程序几何模型：塔身（base→root）、起重臂（root→tip）、平衡臂（root→counter 方向）、小车（沿臂 `trolley_r_m`）、吊钩（`hook` 世界坐标）。
  - 作业半径圆（`trolley_r_max_m` / `jib_length_m`，base 处水平圆）。
  - 预留 glTF/GLB 替换接口（几何工厂按 `crane_id`/`model_id` 可替换为外部资产）。
- **动态更新**（来自 `SimFrame`）：
  - 塔吊姿态：用 `base/root/tip/hook` 世界坐标直接摆放（保证与导出数据坐标一致），`theta_rad` / `trolley_r_m` / `hook_h_m` 作为状态面板数值显示。
  - 吊物：按 `load_type`（查 `scenario.load_types`）的 `shape`（`box_long|flat_box|cylinder|beam`）与 `load_size_m` 程序几何渲染；`load_attached=false` 时隐藏。
  - 塔臂轨迹尾迹（最近 N 个 `tip` 位置）、风向箭头（`weather.wind_direction_deg`）。
- **风险可视化**（来自 `SimFrame.pairs`）：
  - 风险连线（`crane_i`↔`crane_j`），按 `risk_level_now` 着色。
  - 临界接近 / 碰撞高亮（`risk_level` ∈ {`near_miss`,`collision`}）。
  - 多塔重叠作业区域（`manifest.overlap_zones`）。
  - 风险显示开关（一键隐藏/显示风险层）。

## 离线回放与实时 WebSocket

- **同一 `SimFrame` schema**：离线回放逐行读取 `visual/frames.jsonl`（每行一个裸 `SimFrame` 对象，无包裹），实时 WebSocket 接收 `{type:"sim_frame", data:<SimFrame>}`，二者解包后进入同一个帧更新函数 `applyFrame(frame)`，确保渲染路径唯一。
- **离线回放优先稳定**：离线链路只依赖本地/已下载文件，不依赖网络与后端运行态；提供两种加载入口：
  1. 本地文件上传：用户选择 `frames.jsonl`（+可选 `episode_manifest.json`）。
  2. 按 episode id 下载：调用 `GET /episodes/{id}/download`（含 `visual/`）得到 zip，前端解包读取 `visual/frames.jsonl` 与 `visual/episode_manifest.json`。
- **实时 WebSocket**：连接 `WS /ws/episodes/{episode_id}`，处理 `sim_frame` / `error` / `heartbeat` 三类消息；断开后指数退避自动重连，并在 UI 显示连接状态与错误。

## 坐标系

- 后端世界系为 **ENU（X=East, Y=North, Z=Up），单位米**（`SiteConfig.coordinate_system`，`EpisodeManifest.coordinate_system`）。
- Three.js 默认 Y-up 右手系。N 内部唯一映射：`worldToThree([x,y,z]) = [x, z, -y]`，`threeToWorld([X,Y,Z]) = [X, -Z, Y]`（保持右手性，不镜像）。
- **展示一致**：所有对用户展示的坐标（悬停/点击/导出预览）一律经 `threeToWorld` 还原为 ENU 世界坐标，保证“3D 场景与导出数据中的坐标一致”。

## 输入

N 消费以下对象：

- **Module M（后端 API）**：
  - REST：`GET /episodes/{id}/state`、`/summary`、`/download`、`GET /datasets`、`POST /scenarios/validate`（配置上传触发校验）。
  - WebSocket：`WS /ws/episodes/{id}` 的 `sim_frame` 推送。
- **Module L（数据记录）**：离线回放读取 `visual/frames.jsonl`、`visual/episode_manifest.json`，以及下载 zip 中的 `metadata/episode_summary.json`。
- **Module A（配置）**：`ResolvedConfig`（展示工地边界、zones、塔吊布局、load_types 目录等静态信息）。N 通过下载 zip 的 `config/resolved_config.yaml` 或 manifest 字段获得。

## 输出

N 输出：

- 浏览器中的 3D 场景与交互 UI（React 组件）。
- 状态面板、LLM 指令日志、事件日志、时间轴/播放控制的渲染。
- `display-only` 标记的辅助距离/风险/TTC 展示。
- 触发后端 `validate` 的配置上传请求、触发后端 `download` 的导出按钮、触发 `start` 的实时观看入口。

N 不产出任何落盘数据文件、不生成训练真值、不写后端记录。

## 对外接口

N 在 `frontend/` 下新增前端工程，关键模块（签名级别）：

```text
frontend/
  package.json
  vite.config.ts            # dev proxy /api /ws -> 后端
  index.html
  src/
    main.tsx
    App.tsx
    coord.ts                # worldToThree / threeToWorld
    types/sim.ts            # SimFrame / SimFrameCrane / Pair / Weather 等（镜像后端 schema）
    types/config.ts         # ResolvedConfig / CraneConfig / ZoneConfig / LoadTypeConfig
    types/api.ts            # ApiResponse / EpisodeState / EpisodeSummary / ScenarioValidateResult
    api/rest.ts             # REST client
    api/ws.ts               # WebSocket 客户端 + 自动重连
    api/loader.ts           # frames.jsonl / manifest / zip 解包
    state/store.ts          # Zustand store（episode/playback/ws/ui 状态）
    three/model/SceneModel.ts        # 纯数据模型：由 SimFrame + 静态配置派生
    three/model/buildStaticScene.ts
    three/model/dynamicState.ts
    three/geometry/crane.ts          # 塔吊/吊物程序几何工厂（含 glTF 替换接口）
    three/geometry/zones.ts
    three/geometry/risk.ts
    three/ThreeSceneController.ts    # 持有 Scene/Camera/Renderer，applySceneModel()
    components/...
    hooks/...
  tests/                    # vitest 单元 + playwright e2e
  tests/fixtures/           # 示例 frames.jsonl / manifest / resolved config
```

对外数据类型（前端权威，必须与后端 `extra="forbid"` schema 字段一一对应）：

```typescript
type RiskLevel = "safe" | "low" | "medium" | "high" | "near_miss" | "collision";
type LoadShape = "box_long" | "flat_box" | "cylinder" | "beam";
type Vec3 = [number, number, number];

interface SimFrame {
  type: "sim_frame";
  schema_version: string;        // "1.0"
  episode_id: string;
  scenario_id: string | null;
  frame: number;
  time_s: number;
  episode_status: string;
  cranes: SimFrameCrane[];
  pairs: SimFramePair[];
  tasks: Record<string, any>[];
  weather: SimFrameWeather;
  events: Record<string, any>[];
  offline_labels: { pair_labels: Record<string, any>[] } | null; // 实时帧恒为 null
}
interface SimFrameCrane {
  crane_id: string;
  base: Vec3; root: Vec3; tip: Vec3; hook: Vec3;
  theta_rad: number; trolley_r_m: number; hook_h_m: number;
  load_attached: boolean;
  load_type: string | null;
  load_size_m: Vec3 | null;
  task_id: string | null; task_stage: string;
  pickup_zone_id: string | null; dropoff_zone_id: string | null;
  operator_profile: string | null;
  current_command: Record<string, any> | null;
}
interface SimFramePair {
  crane_i: string; crane_j: string;
  distance_min_raw_now_m: number | null;
  clearance_min_now_m: number | null;
  risk_level_now: RiskLevel | null;
}
interface SimFrameWeather {
  wind_speed_m_s: number;
  wind_gust_m_s: number | null;
  wind_direction_deg: number | null;
  visibility: string;            // "good"|"medium"|"poor"
  rain_level: string | null;
  fog_level: string | null;
}
```

> 单位/层级差异提醒（实现与测试需注意）：`SimFrameCrane.theta_rad` 为弧度；观测层 `SelfStateSummary.slew_angle_deg` 为度（N 仅在 LLM 日志展开时显示，不用于几何）。`load_weight_t` 为吨。

## 对内依赖边界

允许：

- 调用 M 的 REST 与 WebSocket。
- 读取并解析 L 产出的 `frames.jsonl`、`episode_manifest.json`、下载 zip。
- 读取并展示 A 的 `ResolvedConfig`（静态场景）。
- 在前端做坐标映射、几何摆放、状态聚合、显示用的距离/风险估算（必须 `display-only`）。
- 把帧流解包后驱动同一个渲染更新路径。

不允许：

- 在前端做物理积分、任务状态机推进、碰撞判定、风险/离线标签计算、LLM 调用或 prompt 构造。
- 把前端的辅助距离/风险/TTC 写入任何落盘或回传为训练真值的通道。
- 自定义与 `SimFrame` 不一致的帧 schema（离线与实时必须同一 schema）。
- 在前端实现后端 API（端点、CORS、运行态 registry 归 M）。
- 修改后端任何代码以满足前端需求（CORS 通过 Vite dev proxy 规避；生产由反向代理/部署解决）。

## 非目标

Module N 不做以下事情：

- 不实现仿真核心逻辑（归 J）、后端 API（归 M）、数据落盘（归 L）、风险/标签计算（归 H/K）、LLM 调用（归 G）。
- 不参与物理计算；不生成训练真值。
- 配置上传只触发后端 `validate`，权威校验在后端完成。
- 不固化塔吊数量；按配置展示 N 台塔吊。
- 不替换 Three.js 为其它渲染后端（首版）。

## 失败边界

| 失败 | 默认处理 |
| --- | --- |
| `frames.jsonl` 缺失或为空 | 显示“无可用帧”，3D 仍渲染静态场景，不崩 |
| `frames.jsonl` 单行格式错误 | 跳过该行并计数，UI 提示 skipped 行数，继续回放其余帧 |
| manifest 缺失 | 退化用首帧 `cranes` 推断静态布局，UI 提示 |
| WebSocket 连接失败/断开 | 指数退避自动重连（带上限），UI 显示连接状态与最近错误 |
| WebSocket 收到 `error` 消息 | 显示错误码与 message，保持上一帧画面 |
| 下载 zip 失败/解包失败 | UI 提示错误码（如 `M_E_DOWNLOAD_FAILED`），不进入回放 |
| 加载不存在的 episode | 显示 not found，提供返回入口 |
| WebGL 不可用 | 检测后显示降级提示，UI 面板仍可用 |
| 单塔吊 / 大量塔吊（N=6） | 按配置渲染，不硬编码数量；6 台在 demo 覆盖 |

## 权威来源

若本文档与根目录 `目标.md` 或 `群塔LLM仿真系统开发方案_v0.4_完整版.md` 冲突，以 `目标.md` 的 Module N 背景与通用约束、总方案 `0.5.19 前端定位`、以及 Module A/L/M 的已实现 schema 合同（`SimFrame`、`EpisodeManifest`、`ResolvedConfig`、M 的 REST/WS 端点）为准，并同步修订本文档。
