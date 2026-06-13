# Task 08：Module M 测试与整体验收

## 任务目标

补齐 Module M 的单元、API、WebSocket、CLI 和端到端集成测试，验证 API -> 调度器 -> recorder -> WebSocket -> 数据查询链路符合目标文档。

## 范围：做什么 / 不做什么

做：

- 新增 `backend/app/tests/test_moduleM_api_schema.py`。
- 新增 `backend/app/tests/test_moduleM_health_config.py`。
- 新增 `backend/app/tests/test_moduleM_episode_lifecycle.py`。
- 新增 `backend/app/tests/test_moduleM_episode_query.py`。
- 新增 `backend/app/tests/test_moduleM_dataset_api.py`。
- 新增 `backend/app/tests/test_moduleM_websocket.py`。
- 新增 `backend/app/tests/test_moduleM_cli.py`。
- 新增 `backend/app/tests/test_moduleM_acceptance.py`。
- 覆盖统一错误结构、OpenAPI、episode 生命周期、summary/download、dataset、WebSocket、CLI。
- 覆盖并发/边界和错误路径。

不做：

- 不要求真实前端 N 渲染。
- 不要求真实外部 LLM provider。
- 不要求 O/P 完整训练 dataset 构建，除非相应模块已经实现。
- 不做性能压测，只做 10 FPS 基础能力验证。

## 接口与数据结构（签名级别）

测试命令建议：

```bash
pytest backend/app/tests/test_moduleM_api_schema.py -v
pytest backend/app/tests/test_moduleM_health_config.py -v
pytest backend/app/tests/test_moduleM_episode_lifecycle.py -v
pytest backend/app/tests/test_moduleM_episode_query.py -v
pytest backend/app/tests/test_moduleM_dataset_api.py -v
pytest backend/app/tests/test_moduleM_websocket.py -v
pytest backend/app/tests/test_moduleM_cli.py -v
pytest backend/app/tests/test_moduleM_acceptance.py -v
```

整体回归建议：

```bash
pytest backend/app/tests/test_moduleA_acceptance.py \
       backend/app/tests/test_moduleJ_acceptance.py \
       backend/app/tests/test_moduleL_acceptance.py \
       backend/app/tests/test_moduleM_acceptance.py -v
```

## 验收标准（具体、可测试）

API schema：

- 成功响应统一为 `{"code": 0, "data": ..., "message": "ok"}`。
- 错误响应统一包含 `code`、`data=null`、`message`、`details`。
- API schema extra 字段拒绝。
- API payload 不包含完整 secret 字段。

Health/config：

- `/health` 200。
- `/openapi.json` 包含全部 REST 路径。
- `/scenarios/validate` 有效配置成功，无效配置返回统一错误。

Episode lifecycle：

- `/episodes/start` 创建 episode。
- `/pause`、`/resume`、`/stop` 按合法状态流转。
- 不存在 episode 返回 404。
- terminal episode 非法操作返回 409。

Episode query/download：

- `/state` 返回 frame/time/status。
- `/summary` 读取 L 的 `episode_summary.json`。
- `/download` 返回合法 zip，且不包含路径穿越。
- summary/download 缺失返回统一错误。

Dataset：

- `/datasets` 支持空列表、分页和已有 dataset。
- `/datasets/{dataset_id}/summary` 返回 `dataset_summary.json`。
- O 未实现或 dataset 不存在时返回明确错误。

WebSocket：

- `WS /ws/episodes/{episode_id}` 可连接已有 episode。
- 可推送 `SimFrame`，客户端接收后通过 `SimFrame.model_validate()`。
- 多客户端接收同一 frame。
- 10 FPS 基础能力通过。
- 实时 frame 不包含 `offline_labels`。

CLI：

- 三个脚本 `--help` 可用。
- `run_episode.py --output-json` 输出可解析 JSON。
- invalid config 非零退出码。
- replay mismatch 非零退出码。
- batch O 未实现时非零退出码和明确错误。

端到端：

- API start episode -> runner 推进 -> WebSocket 收到 frame -> summary 可查询 -> download 可下载。
- 多客户端 WebSocket 不阻塞 episode 推进。
- 高频 `/state` 请求不改变 episode 状态。
- episode 不存在、仿真未启动查询、下载归档失败都有统一错误。

## 测试要点（正常 + 边界 + 异常）

- 正常：使用 fake runner/fake recorder 做快速 API 测试。
- 正常：使用真实 `SimFrame` fixture 做 WebSocket schema 测试。
- 正常：tmp_path 构造 Module L run 目录做 summary/download 测试。
- 边界：空 dataset root。
- 边界：episode 刚启动尚无 frame。
- 边界：paused episode 保持 WebSocket 心跳。
- 异常：invalid config、episode not found、summary missing、dataset not found。
- 异常：monkeypatch 文件写入/zip 失败。
- 异常：WebSocket 客户端断开。
- 防泄漏：静态扫描 API response fixtures、download metadata 和 websocket payload 不含完整 API key。

## 依赖关系

Task 08 依赖 Task 01-07。它是 Module M 阶段三实现完成后的总验收任务，也是阶段四集成测试和覆盖总结的来源。
