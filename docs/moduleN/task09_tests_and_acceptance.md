# Task 09：测试清单与验收

## 任务目标

定义 Module N 的测试清单与验收标准：3D 渲染测试、离线回放测试、WebSocket 实时推送测试、交互测试、多塔吊展示测试、坐标一致性测试；补齐验收用例与运行命令，并产出覆盖总结。本任务汇总并补充跨任务验收，确认通用约束全部满足。

## 范围：做什么 / 不做什么

做：

- 汇总 Task 01-08 的单测，补齐以下跨任务/验收用例：
  - 3D 渲染（注入桩渲染器，断言对象树坐标/姿态/吊物/风险）。
  - 离线回放完整链路（加载 frames.jsonl → 解析 → applyFrame → 播放/seek）。
  - WebSocket 实时链路（mock WS → sim_frame → applyFrame → 断线重连）。
  - 交互链路（选中/跟随/点击塔对/validate/下载）。
  - 多塔吊（N=1/3/6）。
  - 坐标一致性（`worldToThree`↔`threeToWorld` 互逆；展示坐标等于导出 ENU 坐标）。
- 配置 Playwright（headless Chromium，software WebGL）e2e：加载 fixture 离线 episode → 断言 canvas 渲染、播放、坐标显示。
- 提供 `npm test`（vitest）与 `npm run e2e`（playwright）运行命令。
- 产出 `coverage_summary.md`。

不做：

- 不新增生产功能（仅测试与验收）。
- 不接入真实后端运行态（e2e 用本地 fixture/静态服务）。
- 不做性能压测（标注为后续）。

## 接口与数据结构（签名级别）

```text
frontend/tests/
  unit/...                      # Task 01-08 单测
  acceptance/
    offline_replay.test.ts      # 离线完整链路
    realtime_ws.test.ts         # mock WS 实时链路
    interaction.test.ts         # 交互链路
    multi_crane.test.ts         # N=1/3/6
    coord_consistency.test.ts   # 坐标一致
  e2e/
    replay.spec.ts              # Playwright 真实渲染冒烟
```

## 前置依赖

- Task 01-08 全部完成。

## 验收标准（具体、可测试）

- `npm test` 全绿，覆盖：
  - 坐标映射互逆 + 右手性。
  - 静态场景塔吊数 = 配置数；zones/边界几何正确。
  - 动态姿态/吊物/尾迹/风向随帧正确。
  - 风险连线 6 级样式 + 开关。
  - 面板字段、LLM 日志六段、事件跳转。
  - 离线解析（含坏行）/seek/播放。
  - WS 三类消息 + 指数退避重连 + 心跳超时。
  - 交互选中/跟随/塔对详情 `display-only`、validate、下载错误映射。
- 离线回放链路：fixture → frames → applyFrame → seek 后 3D 对象状态正确。
- 实时链路：mock WS 推帧 → 与离线同路径更新；断线后重连。
- 多塔吊：N=1（无 pairs）、N=3、N=6 均正确渲染且不硬编码。
- 坐标一致：任意塔吊 `hook` 经展示路径还原后等于帧 `hook`（ENU）。
- 通用约束逐条满足：display-only、配置只 validate、坐标一致、同 SimFrame schema、离线优先稳定、自动重连、≥3 塔覆盖、按配置 N 塔、glTF 接口预留。
- `npm run e2e`（如环境支持 WebGL）：canvas 渲染 ≥3 塔、播放可推进、坐标显示为 ENU。

## 测试要点（正常 + 边界 + 异常）

- 正常：上述各链路 happy path。
- 边界：空 episode、单塔、N=6。
- 边界：坏行 frames.jsonl、缺 manifest。
- 异常：WS 断开/错误、下载失败、validate 失败、未知 load shape、非法 zone type。
- 防泄漏：fixture/mock 不含真实密钥。

## 依赖关系

依赖 Task 01-08。本任务为 Module N 阶段三收尾，并为阶段四集成测试提供基线。
