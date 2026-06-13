# Task 01：前端工程脚手架

## 任务目标

初始化 Module N 的前端工程：Vite + React + TypeScript + Three.js，搭建目录结构、路由、基础布局、全局状态骨架、坐标映射与后端 schema 镜像类型，配置 Vite dev proxy 与测试基建，为后续任务提供唯一地基。

## 范围：做什么 / 不做什么

做：

- 创建 `frontend/` Vite + React + TS 工程，安装 `three`、`zustand`、`fflate`（zip 解包）。
- 实现 `src/coord.ts`（`worldToThree` / `threeToWorld`）。
- 实现 `src/types/sim.ts`、`types/config.ts`、`types/api.ts`，字段与后端 schema 一一对应（`extra="forbid"` 语义镜像）。
- 实现路由与基础布局骨架（顶栏 / 左控制 / 中画布占位 / 右面板 / 底时间轴占位）。
- 实现 Zustand store 骨架（`mode`/`episodeId`/`connection`/`playback`/`ui` 切片）。
- 配置 `vite.config.ts` dev proxy：`/api` → `http://127.0.0.1:8000`、`/ws` → ws 反向代理。
- 配置 Vitest（jsdom 环境）+ 基础测试工具；预留 Playwright 配置（Phase 4 启用）。
- 提供 `tests/fixtures/` 示例 `frames.jsonl`（≥3 台塔吊）与 `episode_manifest.json`。

不做：

- 不实现真实 3D 渲染（Task 02+）。
- 不实现 REST/WS 客户端逻辑（Task 06/07）。
- 不接入真实后端数据（本任务用 fixture）。
- 不实现状态面板/日志/时间轴业务（Task 05/06）。

## 接口与数据结构（签名级别）

```typescript
// src/coord.ts
export function worldToThree(p: Vec3): Vec3;   // [x,y,z] -> [x, z, -y]
export function threeToWorld(p: Vec3): Vec3;   // [X,Y,Z] -> [X, -Z, Y]
export function worldDist(a: Vec3, b: Vec3): number; // 米
```

```typescript
// src/state/store.ts
interface AppState {
  mode: "replay" | "live" | "idle";
  episodeId: string | null;
  config: ResolvedConfig | null;
  manifest: EpisodeManifest | null;
  frames: SimFrame[];            // 离线加载的全部帧（实时模式为空，逐帧入）
  currentIndex: number;
  latestFrame: SimFrame | null;  // 实时最新帧
  playback: { playing: boolean; speed: number };
  connection: { status: "idle"|"connecting"|"open"|"reconnecting"|"error"; error: string | null; attempts: number };
  ui: { selectedCraneId: string | null; followCraneId: string | null; showRisk: boolean; showZones: boolean };
  // actions（签名级别）
  loadEpisode(frames, manifest, config?): void;
  setFrame(index: number): void;
  pushRealtimeFrame(frame: SimFrame): void;
  setConnection(patch): void;
  setUI(patch): void;
}
export const useStore: UseBoundStore<StoreApi<AppState>>;
```

```typescript
// vite.config.ts（关键）
server: {
  proxy: {
    "/api": "http://127.0.0.1:8000",
    "/ws": { target: "ws://127.0.0.1:8000", ws: true },
  }
}
```

## 前置依赖

- Module A/L/M 的 schema 合同（类型镜像来源）。
- Node.js + npm（已确认 v25 / v11）。
- `tests/fixtures/` 需手写一份最小合法 `SimFrame`（≥3 台塔吊、含 pairs、weather、events），与后端 `RECORDER_SCHEMA_VERSION="1.0"` 一致。

## 验收标准（具体、可测试）

- `npm install` 成功；`npm run build` 通过类型检查与打包。
- `npm run dev` 启动后，访问根路由渲染基础布局骨架（5 个区域可见）。
- `worldToThree([1,2,3]) === [1, 3, -2]` 且 `threeToWorld` 为其逆。
- `worldToThree` 保持右手性（叉积符号不变），不镜像。
- `types/sim.ts` 的 `SimFrame` 字段名与后端 `SimFrame` 完全一致（键集合相等）。
- store 的 `loadEpisode` 能注入 fixture 帧并使 `currentIndex=0`、`latestFrame` 指向首帧。
- dev proxy 配置存在且 `/api`、`/ws` 指向 `127.0.0.1:8000`。
- Vitest 配置就绪，`npm test` 可运行并至少有一条通过的基础测试。
- `frontend/` 不引入任何会触发后端代码改动的配置。

## 测试要点（正常 + 边界 + 异常）

- 正常：`worldToThree` / `threeToWorld` 互逆；`worldDist` 与欧氏距离一致。
- 正常：store `loadEpisode`/`setFrame`/`pushRealtimeFrame` 状态转移正确。
- 边界：零向量、负坐标的映射不变换（与正坐标同一公式）。
- 边界：`loadEpisode([])` 空帧时 `latestFrame=null`、`currentIndex=0`，不抛错。
- 异常：类型层面非法字段在 TS 编译期被拒（`as` 之外不可构造）。
- 防泄漏：fixture 中不含真实 api_key / token（用占位/mock）。

## 依赖关系

Task 01 是 Module N 所有后续任务的前置依赖。Task 02-09 均复用本任务的类型、store、coord 与工程基建。
