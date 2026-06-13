# Task 06：时间轴与离线回放

## 任务目标

实现时间轴与播放控制（播放/暂停/倍速/拖拽跳转）以及离线 episode 加载（读取 `visual/frames.jsonl` + `episode_manifest.json`），并补齐 `api/loader.ts`（本地文件、下载 zip 解包、manifest/summary 解析）与 `seekToTime`。离线回放优先稳定。

## 范围：做什么 / 不做什么

做：

- 实现 `api/loader.ts`：
  - `parseFramesJsonl(text): SimFrame[]`（逐行 `JSON.parse`，跳过空行/坏行并计数）。
  - `parseManifest(json): EpisodeManifest`。
  - `parseSummary(json): EpisodeSummary`。
  - `loadEpisodeFromFiles(framesFile, manifestFile?): {frames, manifest}`。
  - `loadEpisodeFromZip(blob): {frames, manifest, summary?, config?}`（fflate 解包读 `visual/frames.jsonl`、`visual/episode_manifest.json`、`metadata/episode_summary.json`、`config/resolved_config.yaml`）。
- 实现 `components/Timeline`：刻度、当前指针、拖拽跳转（`setFrame`）、播放/暂停/倍速按钮。
- 实现离线播放循环：`requestAnimationFrame` 按倍速推进 `currentIndex`，到达末尾停止。
- 实现 `seekToTime(time_s)`：二分定位最近帧。
- 实现“加载 episode”入口：本地文件上传 与 按 id 下载（调用 Task 08 的导出/下载能力，或本任务内置 `GET /episodes/{id}/download`）。

不做：

- 不实现 WebSocket 实时（Task 07）。
- 不做物理/插值（按帧离散跳转，可在帧间线性插值显示但标记 `display-only`）。
- 不修改后端下载端点。

## 接口与数据结构（签名级别）

```typescript
// api/loader.ts
function parseFramesJsonl(text: string): { frames: SimFrame[]; skipped: number };
function parseManifest(json: string): EpisodeManifest;
function loadEpisodeFromZip(blob: Blob): Promise<{ frames: SimFrame[]; manifest: EpisodeManifest | null; summary: EpisodeSummary | null; config: ResolvedConfig | null }>;
function seekIndexByTime(frames: SimFrame[], time_s: number): number; // 二分
```

```typescript
// components/Timeline.tsx
function Timeline(props: { total: number; index: number; speed: number; playing: boolean;
  onSeek(index: number): void; onPlayPause(): void; onSpeed(s: number): void }): JSX.Element;
```

## 前置依赖

- Task 01（store、types、coord）。
- Task 03（动态更新，喂帧）。
- Task 05（事件日志 `onJump` → `seekToTime`）。
- 下载能力（Task 08 实现 REST 客户端；本任务可先用 `fetch` 直连 `/api/episodes/{id}/download`）。

## 验收标准（具体、可测试）

- `parseFramesJsonl` 正确解析多行 `SimFrame`；空行跳过；坏行跳过并返回 `skipped` 计数；不抛错。
- `loadEpisodeFromZip` 能从含 `visual/frames.jsonl` + `visual/episode_manifest.json` 的 zip 解出 frames 与 manifest。
- `seekIndexByTime` 对单调递增 `time_s` 返回最近帧 index（边界：早于首帧返回 0，晚于末帧返回末帧）。
- Timeline 拖拽 → `onSeek(index)`；播放按倍速推进 `currentIndex`；到末尾停止并 `playing=false`。
- 离线加载完成后 3D 场景从首帧开始渲染（与 Task 03 `applyFrame` 联动）。
- 空文件/无帧 → 不崩，UI 提示“无可用帧”。

## 测试要点（正常 + 边界 + 异常）

- 正常：典型 `frames.jsonl`（≥3 塔，多帧）解析 + 回放。
- 正常：zip 解包含 visual + metadata + config。
- 边界：空 `frames.jsonl`（0 帧）。
- 边界：首尾时间越界的 seek。
- 边界：倍速 0.5/1/2/4 推进正确。
- 异常：单行 JSON 损坏 → 跳过 + 计数。
- 异常：zip 缺 `visual/` → frames=[]，manifest=null，不抛错并提示。
- 异常：`episode_manifest.json` 缺失 → manifest=null，UI 提示退化。

## 依赖关系

依赖 Task 01、Task 03、Task 05。Task 07（实时）复用同一 `applyFrame`；Task 08 提供下载/导出 REST 客户端。
