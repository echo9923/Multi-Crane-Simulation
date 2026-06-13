# Task 07：命令行脚本

## 任务目标

实现 `run_episode.py`、`replay_episode.py`、`batch_generate.py` 三个命令行入口，支持无前端、无 Web 服务的本地单机仿真运行和批量数据生成。

## 范围：做什么 / 不做什么

做：

- 新增 `scripts/run_episode.py`。
- 新增 `scripts/replay_episode.py`。
- 新增 `scripts/batch_generate.py`。
- CLI 复用 API/service 的 runner factory 或共享 episode service 底层能力。
- 支持 `--config`、`--run`、`--output-json`、`--max-episodes` 等基础参数。
- 返回明确退出码。
- 输出 episode id、status、run_dir、summary path。

不做：

- 不启动 FastAPI。
- 不依赖 WebSocket。
- 不实现仿真核心。
- 不构造 dataset split 或 STGNN window；批量生成只运行 episode 并调用 O 的公开入口或预留接口。
- 不吞掉失败；失败必须有非零退出码。

## 接口与数据结构（签名级别）

```bash
python scripts/run_episode.py --config configs/demo.yaml
```

行为：

- 加载 demo/scenario/experiment 配置。
- 强制或默认使用 `offline_batch`，除非配置指定其他本地可运行模式。
- 调用共享 runner factory 执行完整 `run_episode()`。
- 打印简短文本 summary；`--output-json` 时打印机器可读 JSON。

```bash
python scripts/replay_episode.py --run runs/exp_xxx/E001
```

行为：

- 读取 run 目录下 config/metadata/replay 文件。
- 使用 J 的 `offline_replay` 模式。
- 不调用 LLM provider。
- replay mismatch 返回非零退出码。

```bash
python scripts/batch_generate.py --config configs/batch.yaml
```

行为：

- 加载 dataset/batch 配置。
- 按配置运行多个 episode，或调用 O 的 dataset builder 公开入口。
- O 未实现时，至少返回明确 `not implemented` 错误和非零退出码，不伪造成功。

建议共享函数：

```python
def run_episode_from_config(config_path: Path, *, output_json: bool = False) -> EpisodeResult: ...
def replay_episode_from_run(run_dir: Path, *, output_json: bool = False) -> EpisodeResult: ...
def batch_generate_from_config(config_path: Path, *, max_episodes: int | None = None) -> dict[str, Any]: ...
```

退出码：

```text
0 成功
1 配置或输入路径错误
2 episode 运行失败
3 replay mismatch
4 dataset/batch 能力未实现或构建失败
```

## 前置依赖

- Task 01 的输出 schema 可复用。
- Task 03 的 runner factory / EpisodeService 底层能力。
- Module A 的 config loader/resolver。
- Module J 的 `run_episode()`、`offline_batch`、`offline_replay`。
- Module L 的 recorder/run 目录落盘。
- Module O 的 batch/dataset 入口；若 O 未实现，必须明确降级失败。

## 验收标准（具体、可测试）

- `python scripts/run_episode.py --config <valid>` 能在无 Web 服务时运行。
- `--output-json` 输出可 `json.loads()`，包含 `episode_id`、`status`、`run_dir`。
- invalid config 返回非零退出码，不创建成功 registry。
- `replay_episode.py --run <run_dir>` 不调用 LLM provider。
- replay mismatch 返回退出码 3。
- `batch_generate.py --config <valid>` 在 O 可用时能运行多个 episode；O 未实现时返回退出码 4 和明确错误。
- CLI 脚本不导入 FastAPI app 作为运行前置。
- CLI 输出不包含完整 API key。

## 测试要点（正常 + 边界 + 异常）

- 正常：subprocess 调用 `run_episode.py --help` 返回 0。
- 正常：用 fake runner factory 测 `--output-json`。
- 正常：`replay_episode.py --help`、`batch_generate.py --help` 返回 0。
- 边界：`--max-episodes 0` 返回参数错误。
- 边界：run 目录缺少 replay 文件时返回清晰错误。
- 异常：不存在 config path 返回退出码 1。
- 异常：runner 抛错返回退出码 2。
- 异常：dataset builder 未实现返回退出码 4。

## 依赖关系

Task 07 依赖 Task 03 的共享 runner factory，可与 Task 04-06 大体并行，但最终 Task 08 要把 CLI 与 API 共用底层能力作为验收点。
