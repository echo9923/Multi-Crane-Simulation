# Module M Coverage Summary

## 覆盖范围

- API schema：统一成功/错误响应、分页、episode/dataset 请求响应模型、extra 字段拒绝和 secret 字段静态扫描。
- Health/config：`GET /health`、`GET /openapi.json`、`POST /scenarios/validate` 的有效配置、inline 配置、歧义输入、缺失路径和 secret redaction。
- Episode lifecycle：`start`、`pause`、`resume`、`stop`，重复 episode、缺失 episode、terminal state 和 runner factory 失败。
- Episode query/download：运行态 state、summary 文件读取、frames fallback、zip 下载和 `include_logs=false`。
- Dataset API：空 root、分页、summary 文件读取、dataset missing、未配置 root、路径穿越。
- WebSocket：缺失 episode error、已有 episode connect、multi-client `SimFrame` 广播、10 frame 基础速率、heartbeat、无客户端 no-op、offline label 拒绝和重复 schema 静态检查。
- CLI：三个脚本 `--help`、`run_episode` fake factory JSON 输出、`run_episode.py` 默认本地 runner 子进程运行并写出 `episode_summary.json`/`visual/frames.jsonl`、缺失 config、replay 缺失文件、batch not implemented、`--max-episodes` 边界和不依赖 FastAPI app。
- Acceptance：OpenAPI 全路径、API -> runner -> state/summary/download、WebSocket schema、多次 state 请求不推进 runner、统一错误结构。

## 未覆盖或有意降级

- 完整生产级 `EpisodeRunner` dependency assembly：当前 Module M 默认 runner 可在本地 CLI 中装配真实 J `EpisodeRunner` 和轻量 deterministic 依赖完成短 episode，并写出 `SimFrame`/summary；真实任务生成、外部 LLM、安全/风险全链路和 pyarrow Parquet recorder 仍由对应模块继续完善。
- Module O dataset builder：当前 O 尚未实现，M 只提供只读 filesystem fallback 和 `M_E_DATASET_NOT_IMPLEMENTED`。
- 真实前端 N：本阶段只验证 API/WebSocket payload，不渲染前端。
- 外部 LLM provider：测试使用 mock/fake runner，不调用真实 provider。

## 验证命令

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
