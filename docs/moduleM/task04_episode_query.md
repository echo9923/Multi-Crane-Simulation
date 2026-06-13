# Task 04：Episode 查询、Summary 与下载 API

## 任务目标

实现 episode 运行态查询、summary 查询和 run 数据下载 API，让前端和脚本能读取 Module J/L 产出的状态与落盘结果。

## 范围：做什么 / 不做什么

做：

- 实现 `GET /episodes/{episode_id}/state`。
- 实现 `GET /episodes/{episode_id}/summary`。
- 实现 `GET /episodes/{episode_id}/download`。
- 从 Task 03 registry 读取运行中 episode 状态。
- 从 L 的 `metadata/episode_summary.json` 读取完成后的 summary。
- 从 L 的 `visual/frames.jsonl` 可选读取最后一帧，用于无 registry 的历史 run 查询。
- 将 run 目录安全打包为 zip 或返回文件响应。
- 防止路径穿越，只允许下载该 episode 对应 run 目录内产物。

不做：

- 不计算 summary。
- 不修改 run 目录。
- 不读取 Parquet 内容做统计。
- 不实现 dataset 查询。
- 不实现 WebSocket。

## 接口与数据结构（签名级别）

```python
@router.get("/episodes/{episode_id}/state")
def get_episode_state(episode_id: str) -> ApiResponse: ...
```

返回 `EpisodeStateResponse`：

- 运行中 episode：从 registry handle 获取 `status`、`frame_index`、`time_s`、`last_frame`。
- 已完成但不在 registry：若能定位 run 目录，则从 manifest/summary/frames 读取状态。
- 不存在：返回 `M_E_EPISODE_NOT_FOUND`。

```python
@router.get("/episodes/{episode_id}/summary")
def get_episode_summary(episode_id: str) -> ApiResponse: ...
```

返回 L 的 `EpisodeSummary.model_dump(mode="json")` 或等价 dict。

```python
@router.get("/episodes/{episode_id}/download")
def download_episode(
    episode_id: str,
    include_logs: bool = True,
    include_data: bool = True,
    include_visual: bool = True,
) -> FileResponse | StreamingResponse:
    ...
```

下载内容规则：

```text
config/      默认包含
metadata/    默认包含
logs/        include_logs 控制
data/        include_data 控制
visual/      include_visual 控制
replay/      默认包含
```

必须排除：

```text
__pycache__/
.DS_Store
*.tmp
*.partial
```

## 前置依赖

- Task 01 的 API schema。
- Task 02 的 app/error handler。
- Task 03 的 episode registry。
- Module L 的 run 目录结构、`EpisodeSummary`、`SimFrame`、`EpisodeManifest`。

## 验收标准（具体、可测试）

- 运行中 episode 的 `GET /state` 返回 registry 中的 frame/time/status。
- `last_frame` 若存在，必须能通过 L 的 `SimFrame.model_validate()`。
- 不存在 episode 的 `GET /state` 返回 404 与 `M_E_EPISODE_NOT_FOUND`。
- 已完成 episode 的 `GET /summary` 从 `metadata/episode_summary.json` 读取并返回统一结构。
- summary 文件缺失返回 404 与 `M_E_SUMMARY_NOT_FOUND`。
- `GET /download` 返回 zip，包含被选择的目录，且 zip 内相对路径不以 `/` 或 `..` 开头。
- 下载归档失败不返回半截 zip，返回 `M_E_DOWNLOAD_FAILED`。
- 查询和下载响应不包含完整 API key。

## 测试要点（正常 + 边界 + 异常）

- 正常：fake registry handle 查询 state。
- 正常：tmp_path 构造 L run 目录，写入合法 `episode_summary.json` 后查询 summary。
- 正常：tmp_path 构造 `visual/frames.jsonl`，读取最后一帧作为 state fallback。
- 正常：download zip 包含 `metadata/episode_summary.json` 和 `visual/episode_manifest.json`。
- 边界：`include_logs=false` 时 zip 不包含 `logs/`。
- 边界：frames 文件为空时 `last_frame=None`，state 仍返回可用 status。
- 异常：summary JSON 非法时返回统一错误。
- 异常：episode_id 包含路径穿越字符时返回 404 或 422，不访问 run root 之外文件。
- 异常：monkeypatch zip 写入失败，验证不留下半截归档。

## 依赖关系

Task 04 依赖 Task 01-03。Task 08 的端到端测试需要覆盖 start -> state -> summary/download 链路。
