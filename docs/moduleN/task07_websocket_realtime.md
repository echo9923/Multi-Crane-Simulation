# Task 07：WebSocket 实时推送

## 任务目标

实现 WebSocket 实时推送客户端：连接 `WS /ws/episodes/{episode_id}`，接收 `sim_frame`/`error`/`heartbeat` 三类消息，解包 `sim_frame` 后驱动 3D 场景（同一 `applyFrame`），断线指数退避自动重连，并在 UI 显示连接状态与错误。WebSocket 抽象可注入，便于用 mock WS 服务单测。

## 范围：做什么 / 不做什么

做：

- 实现 `api/ws.ts`：`EpisodeWebSocketClient`，构造接收 `episodeId` 与可注入的 `socketFactory`（默认 `new WebSocket(url)`）。
- 处理消息：`sim_frame` → `pushRealtimeFrame` + `applyFrame`；`error` → 记录 `connection.error`；`heartbeat` → 刷新 `server_time_s`。
- 实现自动重连：`onclose`/`onerror` 后按指数退避重连（带上限与最大尝试），状态机 `idle→connecting→open→reconnecting→error`。
- 实现心跳超时检测：长时间无 `sim_frame`/`heartbeat` 触发重连。
- 实现 `stop()`：清理监听、不再重连。
- 顶栏显示连接状态指示器。

不做：

- 不实现后端 WS 适配器（归 M；当前后端实时推送为 stub，N 仅按合同消费）。
- 不构造/伪造 `SimFrame`（只解包后端推送）。
- 不做离线回放（Task 06）。
- 不在前端做物理/风险计算。

## 接口与数据结构（签名级别）

```typescript
// api/ws.ts
type WSMessage =
  | { type: "sim_frame"; data: SimFrame }
  | { type: "error"; data: ApiError }
  | { type: "heartbeat"; data: { server_time_s: number } };

interface SocketFactory { (url: string): WebSocketLike; }
interface WebSocketLike {
  onopen: (() => void) | null; onmessage: ((e:{data:string})=>void) | null;
  onclose: (() => void) | null; onerror: ((e:unknown)=>void) | null;
  close(): void; send?(s: string): void;
}
class EpisodeWebSocketClient {
  constructor(opts: { episodeId: string; baseUrl?: string; socketFactory?: SocketFactory;
                      onFrame:(f:SimFrame)=>void; onStatus:(s:ConnectionStatus, err?:string|null)=>void;
                      maxAttempts?: number; });
  connect(): void; stop(): void;
}
```

## 前置依赖

- Task 01（store、types、connection 状态切片）。
- Task 03（`applyFrame` 驱动 3D）。
- dev proxy `/ws` 配置（Task 01）。

## 验收标准（具体、可测试）

- 用注入的 mock `WebSocketLike`：`onmessage` 推 `{type:"sim_frame", data:<frame>}` → 触发 `onFrame(frame)`。
- 推 `{type:"error", data:<ApiError>}` → `onStatus("error", code)`，保持上一帧。
- 推 `{type:"heartbeat", ...}` → 不触发 `onFrame`，刷新 server 时间。
- `onclose` 后按指数退避重连（用可控时钟/假定时器断言重连次数与间隔递增，达上限后 `onStatus("error")`）。
- `stop()` 后不再重连。
- 心跳超时（可配置短阈值）触发重连。
- 实时帧的 `offline_labels` 恒为 `null`（类型保证；若收到非空则忽略并记 warning）。

## 测试要点（正常 + 边界 + 异常）

- 正常：sim_frame 推送驱动 `applyFrame`（与离线同路径）。
- 正常：error/heartbeat 正确分类。
- 正常：指数退避重连序列正确（假定时器）。
- 边界：连接立即 open 又 close（抖动）。
- 边界：达最大重连次数后停止。
- 边界：心跳超时短阈值触发重连。
- 异常：收到的 `sim_frame.data` 缺字段 → 跳过该帧并 `onStatus("error", ...)`，不崩。
- 异常：`offline_labels` 非空 → 忽略 + warning。

## 依赖关系

依赖 Task 01、Task 03。与 Task 06（离线）共享 `applyFrame`；Task 09 在实时链路端到端测试中验证。
