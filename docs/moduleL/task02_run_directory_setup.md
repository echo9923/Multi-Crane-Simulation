# Task 02：Run Directory Setup

## 任务目标

实现 Module L 的 run 目录初始化能力，按固定结构创建目录、复制 resolved config，并写入 episode metadata 骨架。

## 范围：做什么 / 不做什么

做：

- 新增 `backend/app/sim/recorder.py` 中的目录初始化 helper。
- 定义 `RunDirectoryLayout` 或等价内部对象，集中管理 `config/`、`metadata/`、`logs/`、`data/`、`replay/`、`visual/` 路径。
- 实现 `init_run_directory(config, episode_id=None, scenario_id=None) -> RunDirectoryLayout`。
- 创建 L.1 规定的六个子目录。
- 将 `ResolvedConfig` 写为 `config/resolved_config.yaml`，并保留 `resolved_config_hash`、provider 脱敏信息和 runtime/output 配置。
- 若原始 scenario/experiment/dataset payload 可从 `ResolvedConfig` 取得，则写入 `config/scenario.yaml`、`config/experiment.yaml`、`config/dataset.yaml`。
- 写入 `metadata/episode_metadata.json` 骨架。
- 预留 `metadata/dataset_summary.json` 路径，但不生成全量 dataset summary。
- 将目录创建失败映射为 `DataExportError`。

不做：

- 不创建 Parquet 或 JSONL 数据文件。
- 不打开长期 writer。
- 不计算 `EpisodeSummary`。
- 不改动 A 的 run workspace 逻辑。
- 不把 API key、token、authorization 等秘密写入任何 metadata。

## 接口与数据结构（签名级别）

```python
class DataExportError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        error_code: str,
        category: Literal["data_export_error"] = "data_export_error",
        episode_id: str | None = None,
        frame: int | None = None,
        file_path: str | None = None,
        field_path: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None: ...
```

```python
@dataclass(frozen=True)
class RunDirectoryLayout:
    run_root: Path
    config_dir: Path
    metadata_dir: Path
    logs_dir: Path
    data_dir: Path
    replay_dir: Path
    visual_dir: Path
    resolved_config_path: Path
    episode_metadata_path: Path
    episode_summary_path: Path
    dataset_summary_path: Path
    episode_manifest_path: Path
    frames_jsonl_path: Path
    trajectories_path: Path
    pair_risks_path: Path
    graph_edges_path: Path
    tasks_path: Path
    weather_path: Path
    observations_path: Path
    decisions_path: Path
    commands_path: Path
    interventions_path: Path
    events_path: Path
```

```python
def init_run_directory(
    *,
    config: ResolvedConfig | Mapping[str, Any] | object,
    episode_id: str,
    scenario_id: str | None = None,
    run_root_override: Path | None = None,
) -> RunDirectoryLayout: ...
```

`episode_metadata.json` 初始骨架：

```json
{
  "schema_version": "1.0",
  "episode_id": "E001",
  "scenario_id": "S001",
  "episode_status": "running",
  "resolved_config_hash": "...",
  "created_at": "ISO-8601",
  "updated_at": "ISO-8601",
  "files": {
    "trajectories": "data/trajectories.parquet",
    "pair_risks": "data/pair_risks.parquet",
    "graph_edges": "data/graph_edges.parquet",
    "tasks": "data/tasks.parquet",
    "weather": "data/weather.parquet",
    "frames": "visual/frames.jsonl",
    "episode_manifest": "visual/episode_manifest.json",
    "commands": "logs/commands.jsonl",
    "events": "logs/events.jsonl"
  },
  "warnings": []
}
```

目录命名：

- 默认从 `ResolvedConfig.output.run_root` 取 run 根目录。
- 若配置里已有 experiment/run id，则用它作为 `{exp_id}`。
- 若暂时只有 `episode_id`，MVP 可使用 `runs/{episode_id}`，但 metadata 中必须记录该决定，后续 A/M 可替换为正式 exp id。

## 前置依赖

- Task 01 的 `EpisodeManifest`、`DataExportWarning`、schema version 常量。
- `backend/app/schemas/resolved_config.py` 中的 `ResolvedConfig`。
- `PyYAML` 已在 `pyproject.toml` 中存在。
- `backend/app/core/path_utils.py` 和 `backend/app/core/run_workspace.py` 可复用时优先复用，避免重复路径规范。

## 验收标准（具体、可测试）

- 调用 `init_run_directory()` 后创建六个子目录。
- `config/resolved_config.yaml` 存在，能用 `yaml.safe_load()` 读取。
- `metadata/episode_metadata.json` 存在，包含 `schema_version`、`episode_id`、`scenario_id`、`episode_status="running"`、`files`。
- metadata 不包含完整 API key、token、authorization、secret 字段。
- 重复调用同一个 run 目录是幂等的；已有目录不报错。
- 对不可写目录调用时抛出 `DataExportError`，并包含 `file_path`。
- 不创建半截 `trajectories.parquet`、`frames.jsonl` 等数据文件。

## 测试要点（正常 + 边界 + 异常）

- 正常：用 `tmp_path` 和最小 `ResolvedConfig` 初始化目录。
- 正常：`dataset=None` 时不写 `dataset.yaml`，metadata 合法。
- 边界：`scenario_id=None` 时 metadata 使用 `null`。
- 边界：重复初始化同一路径不覆盖已有 metadata 的必要字段，或以明确策略更新 `updated_at`。
- 异常：run root 指向普通文件时失败。
- 异常：配置 payload 中出现 secret-like 字段时，落盘前脱敏或拒绝。
- 静态检查：`backend/app/sim/recorder.py` 不导入 LLM provider，不读取环境 API key。

## 依赖关系

Task 02 依赖 Task 01。Task 03、04、05、06、07 都依赖 Task 02 提供路径布局。
