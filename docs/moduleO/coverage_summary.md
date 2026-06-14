# Module O Coverage Summary

## 已覆盖

- Schema：`DatasetSummary`、manifest、split manifest、quality report、split assignment、window index、build result、batch result；覆盖 extra、NaN/Inf、非法 split、非法窗口、secret-like 字段拒绝。
- Catalog：空 root、合法 Module L run 目录、坏 JSON、缺 summary 目录跳过、dataset summary 读取、dataset id 路径穿越、secret-like summary 拒绝。
- Batch generation：fake runner 批量生成、稳定 episode id/seed、`--max-episodes` 截断、episode 失败继续/中断、generation report 无完整 secret。
- Quality gate：必需文件、time monotonic、按 `episode.frame_count` 检查中间缺帧、NaN/Inf、geometry/mechanical 基础检查、online/offline 隔离、future/offline key 大小写绕过、replay/events JSONL、quarantine report。
- Split planner：train/val/test、failed quality 排除、unseen layout、unseen num cranes、high risk holdout、重复 episode 泄漏检测、split manifest。
- Window index：窗口边界、episode/split 对齐、不跨 episode、不跨 split、positive window 识别、negative/positive sampling、too-short episode。
- Builder：`index_only` dataset 目录、manifest、summary、quality summary、split manifest、episodes/windows/files Parquet、splits JSONL、quarantine report、target actual gap、`fail_on_quality_error=True` 失败快路径。
- CLI/API：`scripts/batch_generate.py --help`、`scripts/build_dataset.py --help`、`build_dataset_from_config(..., output_json=True)`、非正 `--max-episodes` 输入错误、M `/datasets` 和 `/datasets/{dataset_id}/summary` 读取 O 输出。
- 阶段四端到端：`run_dir -> build_dataset -> dataset_summary -> windows.parquet -> M dataset API`，同时覆盖 source missing 错误路径。

## 验证命令

```bash
.venv/bin/python -m pytest backend/app/tests/test_dataset_schema.py \
       backend/app/tests/test_dataset_catalog.py \
       backend/app/tests/test_dataset_batch_runner.py \
       backend/app/tests/test_dataset_quality.py \
       backend/app/tests/test_dataset_quality_edges_extra.py \
       backend/app/tests/test_dataset_splits.py \
       backend/app/tests/test_dataset_window_index.py \
       backend/app/tests/test_dataset_builder.py \
       backend/app/tests/test_dataset_builder_options_extra.py \
       backend/app/tests/test_dataset_artifact_contract_extra.py \
       backend/app/tests/test_moduleO_cli_api.py \
       backend/app/tests/test_moduleO_cli_edges_extra.py \
       backend/app/tests/test_moduleO_acceptance.py -q
```

```bash
.venv/bin/python -m pytest backend/app/tests/test_moduleA_acceptance.py \
       backend/app/tests/test_moduleK_acceptance.py \
       backend/app/tests/test_moduleL_acceptance.py \
       backend/app/tests/test_moduleM_dataset_api.py \
       backend/app/tests/test_moduleM_acceptance.py -q
```

## 未覆盖及原因

- 真实 100 episode 长仿真：本地验收使用 fake runner 和 tiny fixture，长跑应放到实验脚本或 CI 慢任务。
- PyTorch Dataset / STGNN tensor 生成：归 Module P；Module O 只输出 `windows.parquet` 和 source file paths。
- 真实外部 LLM provider：归 Module G 和实验环境；Module O 通过已有 run 目录和 fake runner 验证批量编排。
- `copy`、`symlink`、`hardlink` 搬运策略：当前生产路径实现并验证 `index_only`，其余 copy modes 保留在 schema 和 manifest，后续需要真实搬运时补专项测试。
