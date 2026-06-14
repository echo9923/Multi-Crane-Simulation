# Task 03：Batch Episode Generation

## 任务目标

让 `DatasetConfig.sources` 能批量生成 episode，并把每个 episode 的运行结果和 run 目录交给 catalog/quality 后续处理。O 只负责编排生成，不实现仿真主循环。

## 范围：做什么 / 不做什么

做：

- 新增 `backend/app/data/batch_runner.py`。
- 扩展 `backend/app/api/cli.py::batch_generate_from_config()`，由 not implemented 改为调用 batch runner。
- 复用 A 的 `load_dataset_config()`、`load_demo_config()`、`resolve_config()`。
- 复用 M/J 的 `default_runner_factory` 或可注入 runner factory。
- 对每个 source 的 `scenario_ref`、`experiment_template_ref` 和 episode index 派生稳定 episode id 与 seed。
- 支持 `--max-episodes` 截断，便于本地快速 smoke。
- 生成 `metadata/generation_report.json`，记录每个 episode 成功、失败、run_dir、退出原因和耗时。

不做：

- 不实现 physics、scheduler、LLM、safety 或 recorder。
- 不在 route handler 内写 batch 逻辑。
- 不构建 split/window index；这些属于 Task 05/06。
- 不把失败 episode 强行修复为成功。

## 接口与数据结构（签名级别）

```python
class BatchEpisodeRequest(DatasetBaseModel):
    dataset_config: DatasetConfig
    output_root: Path
    max_episodes: int | None = Field(default=None, gt=0)
    continue_on_episode_failure: bool = True


class BatchEpisodeResult(DatasetBaseModel):
    schema_version: str = DATASET_SCHEMA_VERSION
    dataset_id: str
    requested_episodes: int = Field(ge=0)
    completed_episodes: int = Field(ge=0)
    failed_episodes: int = Field(ge=0)
    run_dirs: list[Path]
    failures: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[DatasetBuildWarning] = Field(default_factory=list)


class BatchEpisodeRunner:
    def __init__(self, *, runner_factory: Callable[..., Any]) -> None: ...

    def run(
        self,
        request: BatchEpisodeRequest,
    ) -> BatchEpisodeResult: ...
```

Seed 派生规则必须稳定并写入 generation report：

```text
episode_seed = dataset_source_seed_base + source_index * 100000 + episode_index
episode_id = "{dataset_id}-{source_index:02d}-{episode_index:05d}"
```

如果现有 `DatasetConfig` 没有 source seed 字段，第一版使用 dataset/source/scenario/experiment 的 hash 派生，并在 report 中记录 `seed_derivation="hash_v1"`。

## 前置依赖

- Task 01 schema。
- Module A config loader/resolver。
- Module M/J runner factory 或当前 `backend/app/api/local_runner.py`。
- Module L recorder 能为 episode 写出 run 目录。

## 验收标准（具体、可测试）

- `scripts/batch_generate.py --config valid_dataset.yaml --max-episodes 1` 返回 0，写出 generation report。
- runner factory 可注入 fake runner，单元测试不依赖真实长仿真。
- 某个 episode 失败且 `continue_on_episode_failure=True` 时，batch 继续运行后续 episode，并在 report 记录失败。
- `--max-episodes` 小于配置总数时只运行指定数量。
- invalid dataset config 返回 `EXIT_INPUT_ERROR`。
- runner 抛异常时返回 `EXIT_DATASET_FAILED` 或 report 中失败项。
- generation report 不包含完整 secret。

## 测试要点（正常 + 边界 + 异常）

正常：

- fake runner 成功生成 2 个 episode。
- `max_episodes=1` 只生成 1 个 episode。
- 每个 episode 的 seed 和 episode id 稳定。

边界：

- source 有多个 scenario/experiment 组合。
- 第一个 source 0 个成功、第二个 source 成功。
- output_root 已存在。

异常：

- dataset config 文件不存在。
- runner factory 抛异常。
- generation report 写入失败。
- source scenario_ref 或 experiment_template_ref 不存在。

## 依赖关系

依赖 Task 01。Task 07、Task 08 和 Task 09 依赖本任务；Task 04/05/06 可以先使用已有 run fixture 并与本任务并行实现。
