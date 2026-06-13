# Module M Overview：后端 API 边界

## 职责

Module M 是仿真系统的后端 API 层。它把模块 A/J/L/O 已有能力包装成稳定的 REST API、WebSocket 推送和命令行入口，让前端 N、外部脚本和本地用户可以启动仿真、查询运行状态、读取落盘结果、下载 run 目录产物，并订阅实时 `SimFrame`。

M 的核心原则是薄 API、薄运行时编排。它可以创建和管理 `EpisodeRunner` 会话、维护 API 侧 episode registry、把统一错误映射为 HTTP/WebSocket/CLI 响应，但不得把仿真核心逻辑、数据记录逻辑、数据集构建逻辑或前端渲染逻辑搬进 API 层。

## REST API

最低端点：

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

所有 JSON 响应统一包裹：

```json
{"code": 0, "data": {}, "message": "ok"}
```

错误响应统一包裹：

```json
{
  "code": "M_E_EPISODE_NOT_FOUND",
  "data": null,
  "message": "episode not found",
  "details": {"episode_id": "E001"}
}
```

HTTP 状态码只表达传输层/请求层语义；业务错误码放在 `code` 字段。成功响应使用 `code=0` 和 `message="ok"`。

## WebSocket 协议

端点：

```text
WS /ws/episodes/{episode_id}
```

服务器推送的仿真帧必须直接使用 `backend.app.schemas.recorder.SimFrame`，并与 `visual/frames.jsonl` 的每行 schema 保持一致。实时推送禁止携带 `offline_labels`；如果 recorder 或 frame builder 生成了离线扩展，WebSocket adapter 必须拒绝或剥离并记录错误。

建议第一版 WebSocket 消息类型：

```text
sim_frame     data 为 SimFrame
episode_state data 为 EpisodeStateResponse
error         data 为 ApiError
heartbeat     data 包含 server_time_s
```

`sim_frame` 推送频率最低支持 10 FPS。若仿真 dt 更小，可节流到前端需要的频率；若仿真暂停，连接保持心跳但不伪造新 frame。

## 命令行运行

第一版必须支持纯命令行运行，不能把仿真核心绑定在 Web 服务中：

```bash
python scripts/run_episode.py --config configs/demo.yaml
python scripts/replay_episode.py --run runs/exp_xxx/E001
python scripts/batch_generate.py --config configs/batch.yaml
```

CLI 与 API 共享同一底层 episode service / runner factory。CLI 不启动 FastAPI，不依赖 WebSocket，不要求前端存在。批量生成数据时应走 `offline_batch` 或 `offline_replay` 模式，并继续由 L 负责落盘。

## 输入

M 读取或调用以下对象：

- A：`ScenarioConfig`、`ExperimentConfig`、`DatasetConfig`、`ResolvedConfig`，以及 `load_demo_config()`、`load_dataset_config()`、`resolve_config()` 等配置加载与校验能力。
- J：`EpisodeRunner`、`SchedulerConfig`、`EpisodeStatus`、`FrameStepResult`、`EpisodeResult`，用于启动、单步推进、停止和查询 episode。
- L：`SimFrame`、`EpisodeSummary`、`EpisodeManifest`、run 目录结构、`metadata/episode_summary.json`、`visual/frames.jsonl`、`visual/episode_manifest.json`、`data/*.parquet`、`logs/*.jsonl`。
- O：数据集列表、`DatasetSummary` 或等价 `metadata/dataset_summary.json` 查询能力；若 O 尚未实现，M 只能读取已有文件并返回明确的 not implemented / not found 错误。

## 输出

M 输出：

- FastAPI app 和 OpenAPI/Swagger 自动文档。
- REST JSON 响应。
- WebSocket `SimFrame` 推送。
- episode registry 中的运行态摘要。
- 下载响应，例如单 episode run 目录 zip 或指定文件归档。
- CLI stdout/stderr、退出码和可选 JSON summary。

M 不直接产出训练数据或回放数据文件；这些仍由 L/O 写入。

## 对外接口

建议新增 `backend/app/api/schemas.py`，作为 M 的 API schema 源：

```python
API_SCHEMA_VERSION = "1.0"

class ApiResponse(BaseModel): ...
class ApiError(BaseModel): ...
class PaginationParams(BaseModel): ...
class ScenarioValidateRequest(BaseModel): ...
class ScenarioValidateResult(BaseModel): ...
class EpisodeStartRequest(BaseModel): ...
class EpisodeStartResponse(BaseModel): ...
class EpisodeControlResponse(BaseModel): ...
class EpisodeStateResponse(BaseModel): ...
class EpisodeDownloadRequest(BaseModel): ...
class DatasetListItem(BaseModel): ...
class DatasetListResponse(BaseModel): ...
class DatasetSummaryResponse(BaseModel): ...
```

建议新增 API/service 文件：

```text
backend/app/main.py
backend/app/api/__init__.py
backend/app/api/errors.py
backend/app/api/schemas.py
backend/app/api/episode_service.py
backend/app/api/routes_health.py
backend/app/api/routes_episodes.py
backend/app/api/routes_datasets.py
backend/app/api/websocket.py
scripts/run_episode.py
scripts/replay_episode.py
scripts/batch_generate.py
```

`EpisodeService` 建议承担 API 侧 runtime registry：

```python
class EpisodeService:
    def start_episode(self, request: EpisodeStartRequest) -> EpisodeStartResponse: ...
    def pause_episode(self, episode_id: str) -> EpisodeControlResponse: ...
    def resume_episode(self, episode_id: str) -> EpisodeControlResponse: ...
    def stop_episode(self, episode_id: str) -> EpisodeControlResponse: ...
    def get_state(self, episode_id: str) -> EpisodeStateResponse: ...
    def get_summary(self, episode_id: str) -> EpisodeSummary: ...
    def build_download(self, episode_id: str) -> Path: ...
```

暂停/恢复是 API 层状态控制：暂停时不推进 `run_one_frame()`，恢复后继续推进；它不得修改 J 的物理、任务或安全业务规则。若阶段三发现 `EpisodeRunner` 需要补一个可暂停的外部驱动，应先更新 Module M/J 文档再实现。

## 对内依赖边界

允许：

- 创建 FastAPI app、注册 router、配置 CORS 和异常 handler。
- 调用 A 的配置加载、解析和 schema 校验能力。
- 创建 `EpisodeRunner` 或调用 runner factory。
- 在 `interactive_server` 模式下维护后台任务，循环调用 `run_one_frame()`。
- 读取 L 产出的 summary、manifest、frames、logs、data 文件并返回 API 响应或下载。
- 把 J/L/A/O 的结构化异常映射为统一 `ApiError`。
- 维护 WebSocket 连接集合，把 J/L 产出的 `SimFrame` 广播给订阅客户端。

不允许：

- 在 route handler 中实现物理积分、任务状态机、安全审查、LLM 决策或风险计算。
- 在 API 层直接写 Parquet、JSONL、manifest 或 summary 的业务内容。
- WebSocket 推送与 `visual/frames.jsonl` 不一致的自定义 frame schema。
- 为 CLI、REST 和 WebSocket 分别实现三套仿真主循环。
- 把完整 API key、Authorization header、provider secret、prompt 或 raw LLM response 放入前端/API payload，除非该字段已经由 L/G 定义为可下载日志且经过明确下载路径访问。

## 非目标

Module M 不做以下事情：

- 不实现仿真核心逻辑；J 仍是 episode 主循环 owner。
- 不冻结 `WorldSnapshot`，不决定单帧生命周期顺序。
- 不构造 observation，不调用 LLM provider，不解析 LLM 输出。
- 不做安全干预、碰撞检测、离线标签或数据集切分。
- 不记录或落盘训练/回放文件；L/O 拥有文件内容。
- 不渲染前端 3D 视图；N 消费 M 的 API 与 WebSocket。
- 不强制依赖外部服务；本地单机、mock provider 和无前端批量运行必须可用。

## 失败边界

| 失败 | 默认处理 |
| --- | --- |
| 配置 schema 校验失败 | HTTP 422，`M_E_CONFIG_INVALID`，details 保留字段路径与 A 的错误信息 |
| episode 不存在 | HTTP 404，`M_E_EPISODE_NOT_FOUND` |
| episode 状态不允许操作 | HTTP 409，`M_E_INVALID_EPISODE_STATE` |
| runner 启动失败 | HTTP 500 或 422，按 A/J 错误类型映射，episode 不进入 running |
| 查询 summary 但文件不存在 | HTTP 404，`M_E_SUMMARY_NOT_FOUND` |
| 下载文件缺失或归档失败 | HTTP 404/500，`M_E_DOWNLOAD_FAILED`，不得返回半截 zip |
| WebSocket 连接不存在的 episode | accept 后发送 error 并关闭，或握手阶段拒绝 |
| WebSocket 发送速度慢 | 对慢客户端断开或丢弃旧帧，不能阻塞仿真主循环 |
| 数据集能力未实现 | HTTP 501，`M_E_DATASET_NOT_IMPLEMENTED` |

## 权威来源

若本文档与根目录 `目标.md` 或 `群塔LLM仿真系统开发方案_v0.4_完整版.md` 冲突，以总方案 M.1-M.5、推荐目录结构、Module A/J/L/O 的已实现合同以及本轮 `目标.md` 为准，并同步修订本文档。
