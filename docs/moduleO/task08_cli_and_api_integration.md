# Task 08：CLI 与 Dataset API 对接

## 任务目标

补齐 Module O 的命令行入口，并让 Module M 的 dataset API 能读取 O 生成的数据集目录和 summary。CLI 是 O 的主要交互入口；API 仍保持只读查询，不在请求中构建 dataset。

## 范围：做什么 / 不做什么

做：

- 新增 `scripts/build_dataset.py`。
- 扩展 `backend/app/api/cli.py`：
  - `batch_generate_from_config()` 调用 Task 03。
  - 新增 `build_dataset_from_config()` 调用 Task 07。
  - 新增 `main_build_dataset()`。
- 保持 `scripts/batch_generate.py --config ... --max-episodes ...` 可用。
- 新增 CLI 参数：
  - `--source-root`
  - `--output-root`
  - `--copy-mode`
  - `--max-episodes`
  - `--output-json`
- 让 `GET /datasets` 和 `GET /datasets/{dataset_id}/summary` 能读取 O 的 `metadata/dataset_summary.json`；如果 M 当前文件系统 fallback 已满足，只补必要测试和 dataset root 配置说明。

不做：

- 不在 FastAPI route 中执行 dataset build。
- 不让前端直接调用 O builder。
- 不新增训练 API。
- 不要求 batch_generate 必须一次生成 100 个 episode 才能通过本地单元测试；100 episode 作为阶段四可配置验收目标，用 fake/快速 runner 做 smoke。

## 接口与数据结构（签名级别）

CLI：

```bash
python scripts/batch_generate.py \
  --config configs/dataset.yaml \
  --max-episodes 2 \
  --output-json

python scripts/build_dataset.py \
  --config configs/dataset.yaml \
  --source-root runs \
  --output-root runs/datasets \
  --copy-mode index_only \
  --output-json
```

Python：

```python
def build_dataset_from_config(
    config_path: Path,
    *,
    source_roots: list[Path],
    output_root: Path,
    copy_mode: str = "index_only",
    max_episodes: int | None = None,
    output_json: bool = False,
) -> CliResult: ...
```

成功 JSON 最低字段：

```json
{
  "dataset_id": "tower_crane_llm_dataset_v1",
  "dataset_dir": "runs/datasets/tower_crane_llm_dataset_v1",
  "summary_path": "runs/datasets/tower_crane_llm_dataset_v1/metadata/dataset_summary.json",
  "num_episodes": 100,
  "num_quarantined": 3,
  "window_index_path": "runs/datasets/tower_crane_llm_dataset_v1/index/windows.parquet"
}
```

## 前置依赖

- Task 03 batch generation。
- Task 07 dataset builder。
- Module M 已有 routes_datasets filesystem fallback。

## 验收标准（具体、可测试）

- `python scripts/build_dataset.py --help` 退出 0。
- valid dataset config + fixture source root 构建成功，CLI 返回 0。
- `--output-json` 输出可解析 JSON。
- invalid dataset config 返回 `EXIT_INPUT_ERROR`。
- split leakage 或写入失败返回 `EXIT_DATASET_FAILED`。
- `scripts/batch_generate.py` 不再返回固定 not implemented；可用 fake runner 测试成功路径。
- M 的 `/datasets` 能列出 O 构建出的 dataset。
- M 的 `/datasets/{dataset_id}/summary` 能返回 O 写出的 summary。

## 测试要点（正常 + 边界 + 异常）

正常：

- subprocess 或 main 函数调用 `--help`。
- fake source root 构建 tiny dataset。
- FastAPI TestClient 读取 tiny dataset summary。

边界：

- `--max-episodes=1`。
- `--copy-mode=index_only`。
- output_root 已存在。

异常：

- config path 不存在。
- source root 不存在。
- output root 不可写。
- dataset summary 缺失时 M 返回 `M_E_DATASET_NOT_FOUND`。

## 依赖关系

依赖 Task 03 和 Task 07。Task 09 依赖本任务。
