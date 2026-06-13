# 回归测试命令手册

## 目的

本文档给出当前模型的常用测试命令。日常开发建议先跑相关模块的目标测试，再在提交前跑模块 acceptance，合入前跑全量测试。

## 全量测试

```bash
.venv/bin/pytest backend/app/tests -v
```

最近一次完整结果：

```text
895 passed, 1 warning in 5.86s
```

## A-M 跨模块验收

用于确认配置、调度、记录和 API 层的主链路仍然闭合：

```bash
.venv/bin/pytest backend/app/tests/test_moduleA_acceptance.py \
                 backend/app/tests/test_moduleJ_acceptance.py \
                 backend/app/tests/test_moduleL_acceptance.py \
                 backend/app/tests/test_moduleM_acceptance.py -v
```

最近一次结果：

```text
35 passed, 1 warning
```

## Module M API/CLI/WebSocket 回归

```bash
.venv/bin/pytest backend/app/tests/test_moduleM_api_schema.py \
                 backend/app/tests/test_moduleM_health_config.py \
                 backend/app/tests/test_moduleM_episode_lifecycle.py \
                 backend/app/tests/test_moduleM_episode_query.py \
                 backend/app/tests/test_moduleM_dataset_api.py \
                 backend/app/tests/test_moduleM_websocket.py \
                 backend/app/tests/test_moduleM_cli.py \
                 backend/app/tests/test_moduleM_acceptance.py -v
```

最近一次结果：

```text
58 passed, 1 warning
```

## Module L Recorder 回归

```bash
.venv/bin/pytest backend/app/tests/test_recorder.py \
                 backend/app/tests/test_moduleL_acceptance.py -v
```

关注点：

- Parquet/JSONL 写入。
- `visual/frames.jsonl` 和 `episode_manifest.json`。
- `EpisodeSummary` 聚合。
- J -> L 真实 recorder 集成。
- 写失败时不留下权威输出文件。

## Module J Scheduler 回归

```bash
.venv/bin/pytest backend/app/tests/test_scheduler.py \
                 backend/app/tests/test_moduleJ_acceptance.py -v
```

关注点：

- `WorldSnapshot` 冻结。
- command store 原子替换和过期。
- decision clock 边界。
- frame loop 调用顺序。
- offline replay mismatch。
- terminal 状态映射。

## API smoke

FastAPI app 可直接由测试客户端验证：

```bash
.venv/bin/pytest backend/app/tests/test_moduleM_health_config.py::test_openapi_documents_health_and_scenario_validate_routes -v
```

CLI 默认本地 runner smoke：

```bash
.venv/bin/python scripts/run_episode.py \
  --config backend/app/tests/fixtures/configs/demo_valid.yaml \
  --override experiment.output.run_root=/tmp/multi-crane-runs \
  --output-json
```

预期：

- 退出码为 `0`。
- stdout 是 JSON。
- `run_dir` 指向实际 episode 目录。
- `metadata/episode_summary.json` 存在。
- `visual/frames.jsonl` 存在，且每行符合 `SimFrame` schema。

## 依赖检查

当前 Python 3.13 环境需要 `pyarrow>=18.1,<19`：

```bash
.venv/bin/python -m pip show pyarrow
```

若当前网络访问默认 PyPI 很慢，可使用镜像安装：

```bash
.venv/bin/python -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple 'pyarrow==18.1.0'
```

## 失败排查顺序

1. Collection 阶段失败：先检查缺失依赖、Python 版本和 `pyproject.toml`。
2. Schema 测试失败：优先确认字段新增是否同步到 schema、导出、API 文档和测试 fixture。
3. Hash/deterministic 测试失败：检查随机种子、排序、默认值和非稳定时间字段。
4. Recorder 测试失败：检查 pyarrow、临时文件写入、flush/finalize 和 summary 聚合。
5. API 测试失败：检查统一响应结构、状态码、错误码和 app state 注入。
6. WebSocket 测试失败：检查 `SimFrame` schema、offline labels、客户端断开处理和广播 manager。
