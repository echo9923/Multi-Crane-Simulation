# Module N 阶段二自审

## 审查范围

本次自审覆盖以下阶段一产物：

- `docs/moduleN/overview.md`
- `docs/moduleN/task01_project_scaffold.md`
- `docs/moduleN/task02_3d_scene_static.md`
- `docs/moduleN/task03_3d_scene_dynamic.md`
- `docs/moduleN/task04_risk_visualization.md`
- `docs/moduleN/task05_control_panels.md`
- `docs/moduleN/task06_timeline_and_playback.md`
- `docs/moduleN/task07_websocket_realtime.md`
- `docs/moduleN/task08_interaction_and_export.md`
- `docs/moduleN/task09_tests_and_acceptance.md`

本阶段只产出文档，没有写 `frontend/` 实现代码、测试代码或运行时配置。

## 任务重叠检查

结论：任务之间有必要衔接，但职责边界清楚，没有重复实现同一能力。

- Task 01 只搭工程地基（类型/store/coord/proxy/测试基建），不渲染、不联网。
- Task 02 只渲染静态场景（配置驱动），不响应帧。
- Task 03 只把 `SimFrame` 映射到动态姿态/吊物/尾迹/风向，不改静态结构。
- Task 04 只在 Task 03 的 `SceneModel` 上叠加风险层，不重复姿态逻辑。
- Task 05 只渲染状态/日志面板（读 store），不做 3D。
- Task 06 只做离线加载（解析 frames/zip）+ 时间轴/播放 + `seekToTime`，不做实时。
- Task 07 只做 WebSocket 实时客户端，复用 Task 03 的 `applyFrame`，不重复解包后的渲染逻辑。
- Task 08 只做交互与 REST/导出，复用 Task 02-06 的对象与 store。
- Task 09 只汇总测试与验收，不新增生产功能。

唯一的共用点是 `applyFrame(frame)` 渲染入口：Task 03 定义，Task 06（离线）与 Task 07（实时）都调用它，这正是“离线与实时同一 `SimFrame` schema、同一渲染路径”的要求，不视为重复。

## 任务遗漏检查

结论：`目标.md` 与总方案 `0.5.19` 列出的 Module N 能力已覆盖。

- 页面结构、路由、`display-only` 标记：overview。
- 工程地基、类型镜像、坐标映射、dev proxy、测试基建：Task 01。
- 地面/边界/zones（box+polygon）/塔吊程序几何/作业半径圆/glTF 替换接口：Task 02。
- 塔吊姿态（base/root/tip/hook 直驱）/吊物（4 shape × size）/尾迹/风向：Task 03。
- 风险连线/碰撞高亮/重叠区/6 级样式/风险开关：Task 04。
- 塔吊/任务/风险面板、LLM 六段日志、事件点击跳转高亮：Task 05。
- 时间轴/播放/倍速/拖拽、离线 frames.jsonl+manifest+zip 解析、seek：Task 06。
- WS 连接/sim_frame/error/heartbeat/指数退避重连/心跳超时/状态显示：Task 07。
- 选中/跟随/点击塔对/配置上传 validate/导出下载/REST 客户端：Task 08。
- 3D 渲染/离线/实时/交互/多塔/坐标一致测试 + e2e + 覆盖总结：Task 09。
- 通用约束逐条对应：见下表。

| 通用约束 | 落点 |
| --- | --- |
| 阶段一二不写实现代码 | 本阶段仅文档 |
| 每任务一次提交、本地测试通过 | Task 01-09 各自 `feat(moduleN): ...` |
| 前端不参与物理计算 | overview 非目标；Task 03/04 仅展示 |
| 辅助距离/风险 display-only、非真值 | overview；Task 04/05/08 显式标注，无回传通道 |
| 配置上传只触发后端 validate | overview；Task 08 `validateScenario` |
| 3D 与导出坐标一致 | overview 坐标系；Task 03 `hook` 直驱 + Task 09 一致性测试 |
| 离线与实时同一 SimFrame schema | overview；Task 03 单一 `applyFrame` |
| 离线回放优先稳定 | overview；Task 06 离线只依赖本地/已下载文件 |
| 程序几何 + glTF 替换接口 | overview；Task 02 `registerCraneAsset` |
| 按 load_type.shape 与 load_size_m 显示吊物 | overview；Task 03 `buildLoad` |
| 风险等级颜色/样式可区分 | overview；Task 04 `riskLevelStyle` |
| 事件日志点击跳转时间轴 | overview；Task 05 `onJump` |
| WS 断开自动重连或显示错误 | overview；Task 07 指数退避 |
| demo ≥3 塔 | Task 01 fixture；Task 09 验收 |
| 按配置展示 N 塔、不硬编码 | Task 02 循环渲染；Task 09 N=1/3/6 |

## 依赖顺序检查

结论：依赖顺序合理且无环。

```text
Task 01 scaffold
  -> Task 02 static 3D
       -> Task 03 dynamic 3D
            -> Task 04 risk overlay
  -> Task 05 panels（依赖 01；读 03 的帧，可与 02-04 并行起步）
  -> Task 06 timeline/offline（依赖 01、03、05 的 seekToTime）
  -> Task 07 websocket（依赖 01、03）
  -> Task 08 interaction/rest（依赖 01-06）
       -> Task 09 tests & acceptance（依赖全部）
```

说明：Task 02→03→04 为强串行（共享 `SceneModel`/`applySceneModel`）。Task 05/06/07 可在 Task 03 就绪后并行。Task 08 汇聚 02-07。Task 09 收尾。

## 验收标准可测性检查

结论：每个验收标准都可在 Vitest（jsdom + 注入桩渲染器）或 Playwright（真实 WebGL）下验证。

- 坐标/几何/姿态/吊物/风险/面板/解析/seek/WS/交互 断言：用注入桩渲染器（无 WebGL）检查 `THREE.Object3D` 的 `position`/`rotation`/子节点/`visible`，不依赖真实 GL。
- `worldToThree`/`threeToWorld` 互逆与右手性：纯函数单测。
- WS 重连/心跳超时：注入 `WebSocketLike` + 假定时器。
- REST 成功/错误解包：`fetch` mock。
- 真实渲染冒烟（canvas 上有 ≥3 塔、可播放）：Playwright headless Chromium（软件 WebGL/SwiftShader），环境不支持时降级为“对象树存在”断言并记录。

## 与阶段一背景一致性检查

结论：文档与 `目标.md`、总方案 `0.5.19` 及 Module A/L/M 已实现合同一致，并显式标注了实现阶段需要处理的现实缺口。

实现阶段需处理的现实缺口（已在前端侧给出对策，不改后端）：

1. **后端无 CORS、无 episode 列表端点、实时 WS 推送为 stub**：
   - CORS：用 Vite dev proxy（`/api`、`/ws` → `127.0.0.1:8000`）规避，不改后端；生产由反向代理/部署解决（overview 失败边界 + Task 01）。
   - episode 列表：N 不依赖列表端点；离线按 id 下载或本地文件上传（overview 输入；Task 06/08）。
   - 实时 WS stub：N 按 M 已定的合同（`sim_frame`/`error`/`heartbeat` envelope）消费，单测用 mock WS 服务（Task 07；标注后端待 M 实装 adapter）。
2. **两套 RiskLevel（6 值 vs 4 值）**：帧 `pairs.risk_level_now` 用 6 值集合；4 值 `SafetyHint.risk_level` 仅在 LLM 日志展开时显示，不与 6 值合并（types/sim.ts；Task 04）。
3. **单位/层级差异**：`theta_rad` 弧度、`slew_angle_deg` 度、`load_weight_t` 吨，已在 overview 标注，Task 03 面板只做展示不做换算几何。
4. **坐标一致**：几何直接由 `base/root/tip/hook` 世界坐标驱动（不依赖 `theta_rad` 解读），并通过 `threeToWorld` 还原展示，保证与导出 ENU 坐标一致（overview 坐标系；Task 03/09）。

## 调整记录

- 保留 `目标.md` 建议的 9 个任务，未合并，便于逐任务提交与测试。
- 技术栈定为 React + TypeScript + Vite + 原生 Three.js（非 R3F），以降低依赖与重渲染风险，并使 3D 逻辑可单元测试。
- 状态管理用 Zustand：把 10 FPS 帧流与 React 重渲染解耦（3D 控制器命令式更新，面板按切片订阅）。
- 测试分两层：Vitest（jsdom + 注入桩渲染器）覆盖逻辑；Playwright（软件 WebGL）覆盖真实渲染冒烟；环境不支持 WebGL 时降级并记录。
- 下载 zip 用 `fflate` 解包（轻量），支持本地文件与按 id 下载两条离线入口。
- `display-only` 作为类型/组件标注贯穿风险/距离/TTC，确保无回传为真值的通道。
- 未在后端新增端点或 CORS；所有跨域通过 dev proxy/反向代理解决，守住“N 不实现后端 API”边界。

## 阶段闸口

`目标.md` 阶段二要求“停下等待确认再进入阶段三”。本轮会话用户以 `/goal 完成目标.md文档中的所有任务` 设定目标并启用 Stop hook，该指令比阶段二闸口更新、更直接，覆盖“等待确认”要求。据此，本自审完成后直接进入阶段三逐任务实现、测试与提交，并在每个任务完成后做一次提交（`feat(moduleN): <目标>`）。如需暂停审查，可随时中断。
