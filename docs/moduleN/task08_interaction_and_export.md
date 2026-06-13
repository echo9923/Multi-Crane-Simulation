# Task 08：交互与导出

## 任务目标

实现交互能力与对外操作入口：切换跟随某台塔吊、点击塔吊查看状态、点击塔对查看距离与 TTC（`display-only`）、场景配置上传/选择入口（只触发后端 `validate`）、数据导出按钮（触发后端 `download`）。同时实现 `api/rest.ts` 统一 REST 客户端。

## 范围：做什么 / 不做什么

做：

- 实现 `api/rest.ts`：`getEpisodeState`/`getEpisodeSummary`/`downloadEpisode`/`listDatasets`/`validateScenario`，统一解包 `ApiResponse{code:0,data}` 并把 `ApiErrorResponse` 映射为前端错误。
- 实现交互（基于 Task 03/04 的场景对象 raycaster）：
  - 点击塔吊 → 选中并展开其状态（联动 `ui.selectedCraneId`）。
  - 跟随某塔吊 → 相机平滑跟随该塔吊 base。
  - 点击风险连线/塔对 → 弹出距离/余量/TTC（`display-only`；TTC 仅在离线帧含 `offline_labels` 时展示，否则只显示 `pairs` 的 `clearance_min_now_m`）。
- 实现 `/config` 页：配置上传（文件或 JSON）→ `POST /scenarios/validate` → 展示 `valid`/`warnings`/`errors`；权威校验在后端，前端只展示。
- 实现“导出/下载”按钮 → `GET /episodes/{id}/download` → 浏览器保存 zip（或转交 Task 06 离线加载）。
- 实现“按 id 加载”输入框（replay/live 模式）。

不做：

- 不做距离/TTC 计算（仅展示后端已有字段，标 `display-only`）。
- 不在前端做配置权威校验（只转发 validate 结果）。
- 不修改后端端点。
- 不实现 LLM/物理（仅交互层）。

## 接口与数据结构（签名级别）

```typescript
// api/rest.ts
async function get<T>(path: string): Promise<T>;                 // 解 ApiResponse
async function post<T>(path: string, body: unknown): Promise<T>;
async function downloadBlob(path: string): Promise<Blob>;
function validateScenario(req: ScenarioValidateRequest): Promise<ScenarioValidateResult>;
function downloadEpisode(id: string, opts?: {include_logs?:boolean;include_data?:boolean;include_visual?:boolean}): Promise<Blob>;
function getEpisodeState(id: string): Promise<EpisodeStateResponse>;
function getEpisodeSummary(id: string): Promise<EpisodeSummary>;
```

```typescript
// 交互
function pickCrane(controller: ThreeSceneController, ndc: {x:number;y:number}): string | null;
function followCrane(controller: ThreeSceneController, craneId: string | null): void;
```

## 前置依赖

- Task 01（store、`ui` 切片、router）。
- Task 02-04（场景对象、风险连线，用于 raycast）。
- Task 05（状态面板联动选中）。
- Task 06（下载 zip → 离线加载）。

## 验收标准（具体、可测试）

- `api/rest.ts`：成功响应解包 `data`；错误响应（`code` 为 `M_E_*`）抛出含 `code`/`message`/`details` 的前端错误。
- 点击塔吊 → `ui.selectedCraneId` 更新且面板高亮该塔吊。
- 跟随塔吊 → 相机目标移至该塔吊 base（`threeToWorld` 还原坐标用于日志）。
- 点击塔对 → 展示 `clearance_min_now_m`/`risk_level_now`（`display-only`）；离线帧有 `offline_labels` 时额外展示对应 TTC/collision（仍 `display-only`）。
- 配置上传 → 调 `validateScenario`，UI 展示 `valid`/`warnings`/`errors`；不通过时不进入运行。
- 导出按钮 → 触发 `downloadEpisode` 并保存 zip（mock fetch 可断言请求路径与参数）。
- 所有展示的距离/风险/TTC 均带 `display-only` 标记。

## 测试要点（正常 + 边界 + 异常）

- 正常：REST 解包成功/错误两条路径。
- 正常：选中/跟随/点击塔对交互回调正确。
- 正常：validate 上传成功（valid=true）与失败（valid=false + errors）。
- 边界：点击空白处不选中。
- 边界：离线帧无 `offline_labels` → 塔对详情只显示 clearance，不显示 TTC。
- 异常：`downloadEpisode` 返回 `M_E_DOWNLOAD_FAILED` → 前端抛出错误码，UI 提示。
- 异常：`validateScenario` 网络/422 → 前端错误映射。
- 防泄漏：上传配置不含明文 api_key（前端做字段遮蔽后再发，或仅发 `config_path`）。

## 依赖关系

依赖 Task 01-06。Task 09 在交互链路端到端测试中验证；本任务为 Task 06 下载入口提供 REST 客户端。
