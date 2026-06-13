# Task 01：API Schema 与统一错误合同

## 任务目标

定义 Module M 的 REST/WebSocket/CLI 共享 API schema、统一响应包裹、错误码、分页与过滤参数，为后续 route、service 和测试提供唯一合同。

## 范围：做什么 / 不做什么

做：

- 新增 `backend/app/api/schemas.py`。
- 定义 `ApiResponse`、`ApiError`、`ApiErrorResponse`。
- 定义分页、排序、时间范围、episode 状态过滤参数。
- 定义 scenario validate、episode start/control/state/download、dataset list/summary 的请求与响应模型。
- 约定 HTTP 状态码到 `ApiError.code` 的映射。
- 约定 WebSocket error payload 与 REST `ApiError` 共用字段。
- 约定 CLI JSON 输出复用 episode response / summary response。

不做：

- 不实现 FastAPI route。
- 不启动 episode。
- 不读取 run 目录。
- 不实现 WebSocket broadcast。
- 不实现 dataset builder。

## 接口与数据结构（签名级别）

```python
API_SCHEMA_VERSION = "1.0"

class ApiBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, validate_default=True)
```

```python
class ApiError(ApiBaseModel):
    schema_version: str = API_SCHEMA_VERSION
    code: str
    message: str
    details: dict[str, Any] = {}
```

```python
class ApiResponse(ApiBaseModel):
    code: Literal[0] = 0
    data: Any
    message: str = "ok"
```

```python
class ApiErrorResponse(ApiBaseModel):
    code: str
    data: None = None
    message: str
    details: dict[str, Any] = {}
```

建议错误码：

```text
M_E_CONFIG_INVALID
M_E_EPISODE_NOT_FOUND
M_E_INVALID_EPISODE_STATE
M_E_EPISODE_START_FAILED
M_E_RUNNER_FAILED
M_E_SUMMARY_NOT_FOUND
M_E_DOWNLOAD_FAILED
M_E_DATASET_NOT_FOUND
M_E_DATASET_NOT_IMPLEMENTED
M_E_WEBSOCKET_CLOSED
M_E_INTERNAL
```

请求/响应模型：

```python
class PaginationParams(ApiBaseModel):
    limit: int = Field(default=50, ge=1, le=500)
    offset: int = Field(default=0, ge=0)
```

```python
class ScenarioValidateRequest(ApiBaseModel):
    config_path: str | None = None
    scenario: dict[str, Any] | None = None
    experiment: dict[str, Any] | None = None
    dataset: dict[str, Any] | None = None
    overrides: dict[str, Any] = Field(default_factory=dict)
```

```python
class ScenarioValidateResult(ApiBaseModel):
    valid: bool
    resolved_config_hash: str | None = None
    warnings: list[dict[str, Any]] = Field(default_factory=list)
    errors: list[ApiError] = Field(default_factory=list)
```

```python
class EpisodeStartRequest(ApiBaseModel):
    config_path: str | None = None
    scenario: dict[str, Any] | None = None
    experiment: dict[str, Any] | None = None
    dataset: dict[str, Any] | None = None
    overrides: dict[str, Any] = Field(default_factory=dict)
    run_mode: Literal["offline_batch", "offline_replay", "interactive_server"] | None = None
    episode_id: str | None = None
    autostart: bool = True
```

```python
class EpisodeStartResponse(ApiBaseModel):
    episode_id: str
    run_id: str | None = None
    run_dir: str | None = None
    status: str
    resolved_config_hash: str | None = None
    websocket_url: str | None = None
```

```python
class EpisodeControlResponse(ApiBaseModel):
    episode_id: str
    previous_status: str
    status: str
    accepted: bool
    reason: str | None = None
```

```python
class EpisodeStateResponse(ApiBaseModel):
    episode_id: str
    status: str
    frame_index: int = Field(ge=0)
    time_s: float = Field(ge=0)
    run_dir: str | None = None
    last_frame: SimFrame | None = None
    terminal_reason: str | None = None
    metrics: dict[str, Any] = Field(default_factory=dict)
```

```python
class EpisodeDownloadRequest(ApiBaseModel):
    include_logs: bool = True
    include_data: bool = True
    include_visual: bool = True
```

```python
class DatasetListItem(ApiBaseModel):
    dataset_id: str
    path: str
    created_at: str | None = None
    num_episodes: int | None = Field(default=None, ge=0)
    summary_available: bool = False
```

class DatasetListResponse(ApiBaseModel):
    items: list[DatasetListItem]
    total: int = Field(ge=0)
    limit: int = Field(ge=1)
    offset: int = Field(ge=0)
```

class DatasetSummaryResponse(ApiBaseModel):
    dataset_id: str
    summary: dict[str, Any]
```
```

## 前置依赖

- Module A 的 config schema、loader、resolver 和 config error 映射。
- Module J 的 `EpisodeStatus`、`FrameStepResult`、`EpisodeResult`。
- Module L 的 `SimFrame`、`EpisodeSummary`。
- Module O 的 dataset summary 合同；若 O 尚未实现，先使用 `dict[str, Any]` 包裹已存在的 `dataset_summary.json`。

## 验收标准（具体、可测试）

- 所有 API schema 使用 `extra="forbid"`。
- `ApiResponse(code=0, data={}, message="ok")` 可序列化为统一成功结构。
- `ApiErrorResponse` 包含错误码、错误信息、可选 details，且 `data is None`。
- `EpisodeStartRequest` 至少支持 `config_path` 和 inline config 两种入口。
- `EpisodeStateResponse.last_frame` 使用 L 的 `SimFrame` 类型。
- `PaginationParams(limit=0)` 校验失败，`limit=501` 校验失败。
- 所有错误码以 `M_E_` 前缀开头。
- schema 中不出现完整 `api_key`、`authorization`、`token`、`provider_secret` 字段。

## 测试要点（正常 + 边界 + 异常）

- 正常：构造成功响应、错误响应、episode start/state、dataset list。
- 正常：`EpisodeStateResponse` 携带一个最小合法 `SimFrame`。
- 边界：`limit=1`、`limit=500`、`offset=0` 合法。
- 边界：`last_frame=None` 合法，用于 episode 刚启动但尚无帧。
- 异常：extra 字段失败。
- 异常：非法 run_mode 失败。
- 防泄漏：静态扫描 `backend/app/api/schemas.py` 不定义 secret 字段。

## 依赖关系

Task 01 是所有 Module M 后续任务的前置依赖。Task 02-08 均读取本任务的响应和错误合同。
