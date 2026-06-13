# Task 03：Episode 生命周期 API

## 任务目标

实现 episode 启动、暂停、恢复和停止 API，并在 API 层维护本地单机 episode registry，调用 Module J 的 runner 而不复制仿真主循环。

## 范围：做什么 / 不做什么

做：

- 新增 `backend/app/api/episode_service.py`。
- 实现 `POST /episodes/start`。
- 实现 `POST /episodes/{episode_id}/pause`。
- 实现 `POST /episodes/{episode_id}/resume`。
- 实现 `POST /episodes/{episode_id}/stop`。
- 管理 episode runtime registry：episode id、status、runner、run_dir、last_frame、terminal reason。
- 支持 `interactive_server` 后台推进和 `offline_batch` 同步/后台运行策略。
- 把 J 的 `EpisodeStatus` 映射到 API state。

不做：

- 不实现 J 的 frame loop。
- 不实现物理、任务、LLM、安全或 recorder 业务逻辑。
- 不实现 summary/download 查询。
- 不实现 WebSocket transport。
- 不实现多进程/分布式调度。

## 接口与数据结构（签名级别）

```python
class EpisodeRuntime(ApiBaseModel):
    episode_id: str
    status: str
    run_dir: str | None = None
    frame_index: int = 0
    time_s: float = 0.0
    paused: bool = False
    terminal_reason: str | None = None
```

运行时对象中真实 `EpisodeRunner`、后台 task、锁等不可直接放入 Pydantic 对外响应，可在 service 内部 dataclass 保存：

```python
@dataclass
class EpisodeHandle:
    episode_id: str
    runner: EpisodeRunner
    run_dir: Path | None
    status: EpisodeStatus
    paused: bool = False
    last_frame: SimFrame | None = None
    terminal_reason: str | None = None
```

```python
class EpisodeService:
    def start_episode(self, request: EpisodeStartRequest) -> EpisodeStartResponse: ...
    def pause_episode(self, episode_id: str) -> EpisodeControlResponse: ...
    def resume_episode(self, episode_id: str) -> EpisodeControlResponse: ...
    def stop_episode(self, episode_id: str) -> EpisodeControlResponse: ...
    def get_handle(self, episode_id: str) -> EpisodeHandle: ...
```

Routes：

```python
@router.post("/episodes/start")
def start_episode(request: EpisodeStartRequest) -> ApiResponse: ...

@router.post("/episodes/{episode_id}/pause")
def pause_episode(episode_id: str) -> ApiResponse: ...

@router.post("/episodes/{episode_id}/resume")
def resume_episode(episode_id: str) -> ApiResponse: ...

@router.post("/episodes/{episode_id}/stop")
def stop_episode(episode_id: str) -> ApiResponse: ...
```

状态控制规则：

- `start` 创建 runner 和 registry 记录；`episode_id` 未传时生成稳定唯一 id。
- `pause` 只允许 running episode；暂停后后台循环不再调用 `run_one_frame()`。
- `resume` 只允许 paused/running 但 paused=true 的 episode。
- `stop` 调用 `EpisodeRunner.stop("api stop")`，下一次推进后状态应变为 `stopped_by_user`；如果 runner 支持立即 stop，可同步推进一次。
- completed/failed/stopped episode 再 pause/resume 返回 `M_E_INVALID_EPISODE_STATE`。

## 前置依赖

- Task 01 的 API schema。
- Task 02 的 FastAPI app 与错误 handler。
- Module A 的配置解析入口。
- Module J 的 `EpisodeRunner.from_config()`、`run_one_frame()`、`stop()`、`EpisodeStatus`。
- Module L 的 recorder factory；若真实依赖装配尚未完整，测试可用 fake dependencies，但文档必须保留真实装配入口。

## 验收标准（具体、可测试）

- `POST /episodes/start` 对有效 config 返回 `episode_id`、`status`、可选 `run_dir`。
- 启动后 registry 中能通过 `episode_id` 找到 handle。
- `pause` running episode 返回 `accepted=true`，状态摘要为 paused/running。
- paused episode 不继续推进 frame。
- `resume` 后 episode 可继续推进 frame。
- `stop` 后 runner 收到 stop 请求，最终状态为 `stopped_by_user` 或 API 标记为 stopping 后收敛到 stopped。
- 不存在 episode 的 pause/resume/stop 返回 404 与 `M_E_EPISODE_NOT_FOUND`。
- terminal episode 的 pause/resume 返回 409 与 `M_E_INVALID_EPISODE_STATE`。
- route handler 不导入或调用 C/D/E/F/G/H/I 的业务函数，只通过 service/runner factory 调用 J。

## 测试要点（正常 + 边界 + 异常）

- 正常：用 fake runner factory 启动 episode。
- 正常：pause -> resume -> stop 状态流转。
- 正常：显式传 `episode_id` 能被 registry 使用。
- 边界：重复 episode_id 返回 conflict，不能覆盖已有运行态。
- 边界：`autostart=false` 创建但不推进。
- 异常：配置无效时 start 失败且 registry 不新增 handle。
- 异常：runner 创建抛错映射为 `M_E_EPISODE_START_FAILED`。
- 静态边界：route 文件不包含 physics/task/llm/safety 业务导入。

## 依赖关系

Task 03 依赖 Task 01 和 Task 02。Task 04 查询 episode state 依赖本任务 registry；Task 06 WebSocket 依赖 registry 和 frame broadcast hook；Task 07 CLI 复用 runner factory。
