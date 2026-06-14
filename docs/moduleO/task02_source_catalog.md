# Task 02：Episode Source Catalog

## 任务目标

实现数据集 source catalog，发现并读取已有 run/episode 目录，把 Module L 的 episode 文件转换为 `DatasetEpisodeRecord` 和 `DatasetFileRecord`，供质量门禁、split、summary 和 M 的 dataset 查询复用。

## 范围：做什么 / 不做什么

做：

- 新增 `backend/app/data/catalog.py`。
- 从一个或多个 source root 扫描 episode run 目录。
- 读取 `metadata/episode_summary.json`、`visual/episode_manifest.json`、`config/resolved_config.yaml`。
- 检查训练必需文件是否存在：`data/trajectories.parquet`、`data/pair_risks.parquet`、`data/graph_edges.parquet`、`data/tasks.parquet`、`data/weather.parquet`。
- 记录 logs/replay/visual 文件是否可用。
- 生成稳定 `layout_hash`、`source_files`、`scenario_class`、`operator_profile_distribution`、risk 分布等索引字段。
- 支持 dataset root 下已构建 dataset 的 `metadata/dataset_summary.json` 读取，给 M 的只读查询提供可复用方法。

不做：

- 不判断 episode 是否合格进入训练集；质量门禁属于 Task 04。
- 不运行 episode。
- 不生成 split。
- 不写 dataset 输出目录。
- 不修改 Module M 路由主体；M 可继续读 summary 文件，也可在实现阶段复用 catalog。

## 接口与数据结构（签名级别）

```python
class DatasetCatalog:
    def __init__(self, *, dataset_root: Path | None = None) -> None: ...

    def discover_episodes(
        self,
        roots: Sequence[Path],
        *,
        max_episodes: int | None = None,
    ) -> list[DatasetEpisodeRecord]: ...

    def read_episode(
        self,
        run_dir: Path,
    ) -> DatasetEpisodeRecord: ...

    def read_dataset_summary(
        self,
        dataset_id: str,
    ) -> DatasetSummary: ...

    def list_datasets(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[DatasetSummary], int]: ...
```

必需文件判定建议：

```python
REQUIRED_TRAINING_FILES = {
    "episode_summary": "metadata/episode_summary.json",
    "episode_manifest": "visual/episode_manifest.json",
    "trajectories": "data/trajectories.parquet",
    "pair_risks": "data/pair_risks.parquet",
    "graph_edges": "data/graph_edges.parquet",
    "tasks": "data/tasks.parquet",
    "weather": "data/weather.parquet",
}
```

`scenario_class` 读取优先级：

1. `episode_summary.scenario_class`
2. `episode_manifest.scenario_class`
3. `resolved_config.scenario.scenario_class`
4. 从 `scenario_id` 或 task type 推断为总方案类别之一
5. `unknown` 并生成 warning

## 前置依赖

- Task 01 的 schema。
- Module L 的 run 目录和 summary/manifest 合同。
- PyYAML 或现有 YAML loader，用于读取 `resolved_config.yaml`。

## 验收标准（具体、可测试）

- 空 root 返回空 episode 列表，不抛 500。
- 单个合法 run 目录可被读取为 `DatasetEpisodeRecord`。
- 缺失 `episode_summary.json` 的目录不进入成功列表，并返回可诊断错误或 warning。
- `max_episodes=1` 时只返回 1 条稳定排序记录。
- `layout_hash` 对同一 resolved layout 稳定。
- `read_dataset_summary(dataset_id)` 可读取 `metadata/dataset_summary.json`。
- 路径穿越型 dataset_id 被拒绝。
- 不把 `api_key` 等 secret-like 字段写入 `DatasetEpisodeRecord`。

## 测试要点（正常 + 边界 + 异常）

正常：

- tmp_path 构造一个完整 L run 目录，catalog 读取成功。
- tmp_path 构造两个 run，按 episode_id 或 run_dir 稳定排序。
- tmp_path 构造一个 dataset summary，catalog 读取成功。

边界：

- 空 source root。
- `scenario_id=None`。
- manifest 缺失但 summary 存在时，episode record 标记 manifest missing，后续质量门禁决定 quarantine。

异常：

- source root 不存在。
- JSON 格式错误。
- dataset_id 包含 `/` 或 `..`。
- summary 中含 secret-like 字段。

## 依赖关系

依赖 Task 01。Task 04、Task 05、Task 07、Task 08、Task 09 依赖本任务。
