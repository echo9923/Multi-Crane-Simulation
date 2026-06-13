# Task 06：WebSocket SimFrame 推送

## 任务目标

实现 `WS /ws/episodes/{episode_id}`，让前端 N 可以订阅实时 `SimFrame`，且推送 schema 与 L 的 `visual/frames.jsonl` 完全一致。

## 范围：做什么 / 不做什么

做：

- 新增 `backend/app/api/websocket.py`。
- 实现 WebSocket 连接管理器。
- 实现 `WS /ws/episodes/{episode_id}`。
- 将 EpisodeService/runner 产出的 `SimFrame` 广播给订阅客户端。
- 至少支持 10 FPS 推送能力。
- 支持 heartbeat、error 消息和断开清理。
- 实时推送禁止 `offline_labels`。

不做：

- 不渲染前端。
- 不构造独立 frame schema。
- 不实现 replay 播放 UI 控制。
- 不阻塞 J 的 frame loop 等待慢客户端。
- 不把 offline labels 推给实时前端。

## 接口与数据结构（签名级别）

```python
class WebSocketConnectionManager:
    async def connect(self, episode_id: str, websocket: WebSocket) -> None: ...
    def disconnect(self, episode_id: str, websocket: WebSocket) -> None: ...
    async def broadcast_sim_frame(self, episode_id: str, frame: SimFrame) -> None: ...
    async def broadcast_error(self, episode_id: str, error: ApiError) -> None: ...
```

J adapter 形态：

```python
class ApiWebSocketAdapter:
    def __init__(self, manager: WebSocketConnectionManager, frame_source: FrameSource) -> None: ...

    def broadcast_sim_frame_if_enabled(
        self,
        *,
        episode_id: str,
        frame_index: int,
        time_s: float,
        states: Sequence[CraneState],
        events: Sequence[Mapping[str, Any]],
        status: EpisodeStatus | str,
    ) -> None: ...
```

如果 J 已经通过 recorder 得到 `SimFrame`，adapter 应优先使用该 frame；如果只收到 state/events 参数，必须调用 L 的 `build_sim_frame(..., for_realtime=True)` 或等价已实现构造器，不得手写第二套 schema。

WebSocket 消息包裹：

```json
{
  "type": "sim_frame",
  "data": {"type": "sim_frame", "episode_id": "E001", "frame": 1}
}
```

错误消息：

```json
{
  "type": "error",
  "data": {
    "schema_version": "1.0",
    "code": "M_E_EPISODE_NOT_FOUND",
    "message": "episode not found",
    "details": {"episode_id": "E001"}
  }
}
```

## 前置依赖

- Task 01 的 API error schema。
- Task 02 的 app/router。
- Task 03 的 episode registry。
- Module L 的 `SimFrame` 和 frame builder。
- Module J 的 `websocket.broadcast_sim_frame_if_enabled(...)` adapter hook。

## 验收标准（具体、可测试）

- 连接存在的 episode 成功。
- 连接不存在的 episode 得到统一 error 并关闭，或握手阶段拒绝。
- `broadcast_sim_frame()` 发送的 `data` 可通过 `SimFrame.model_validate()`。
- 实时 frame 中 `offline_labels is None`。
- 单个 episode 支持多个客户端同时接收同一 frame。
- 慢客户端不会阻塞其他客户端或 episode 推进。
- 10 FPS：测试中连续广播 10 帧，1 秒预算内客户端可收到至少 10 条 `sim_frame`。
- 断开连接后 manager 清理连接，不再尝试发送。

## 测试要点（正常 + 边界 + 异常）

- 正常：`TestClient.websocket_connect("/ws/episodes/E001")` 后接收一条 frame。
- 正常：两个 websocket 连接同一 episode，同时收到同一 frame。
- 正常：heartbeat 消息可发送。
- 边界：无订阅客户端时 broadcast no-op。
- 边界：episode paused 时不推新 frame，但连接保持 heartbeat。
- 异常：SimFrame 携带 offline labels 时 broadcast 拒绝或返回错误。
- 异常：发送中客户端断开，manager 清理。
- 静态边界：websocket 文件不定义 `SimFrameCrane`/`SimFramePair` 等重复 schema。

## 依赖关系

Task 06 依赖 Task 01-03 和 Module L 的 `SimFrame`。Task 08 需要覆盖 WebSocket + API + runner 的集成链路。
