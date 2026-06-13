# Module M 阶段二自审

## 审查范围

本次自审覆盖以下阶段一产物：

- `docs/moduleM/overview.md`
- `docs/moduleM/task01_api_schema.md`
- `docs/moduleM/task02_health_and_config.md`
- `docs/moduleM/task03_episode_lifecycle.md`
- `docs/moduleM/task04_episode_query.md`
- `docs/moduleM/task05_dataset_api.md`
- `docs/moduleM/task06_websocket.md`
- `docs/moduleM/task07_cli_scripts.md`
- `docs/moduleM/task08_tests_and_acceptance.md`

本阶段只产出文档，没有写 `backend/app/`、`scripts/` 实现代码、测试代码或运行时配置。

## 任务重叠检查

结论：任务之间有衔接，但职责边界清楚，没有重复实现同一能力。

- Task 01 只定义 API schema、响应包裹、错误码和参数模型。
- Task 02 只建立 FastAPI app、健康检查、配置校验和异常 handler。
- Task 03 只管理 episode 生命周期和 API 侧 registry，不做 state/summary/download 查询。
- Task 04 只读取运行态和 L 的 run 目录结果，不启动或控制 episode。
- Task 05 只做 dataset 元数据只读查询，不构建 dataset。
- Task 06 只做 WebSocket 连接管理和 `SimFrame` 推送，不定义第二套 frame schema。
- Task 07 只做 CLI 入口，复用 runner factory，不依赖 Web 服务。
- Task 08 只定义测试和验收，不新增生产接口。

## 任务遗漏检查

结论：`目标.md` 列出的 Module M 能力已覆盖。

- `docs/moduleM/overview.md` 已重述职责、API 列表、WebSocket 协议、输入/输出、接口、依赖和非目标。
- REST API schema、错误响应结构、分页与过滤参数：Task 01。
- `GET /health`、`POST /scenarios/validate`：Task 02。
- `POST /episodes/start`、`/pause`、`/resume`、`/stop`：Task 03。
- `GET /episodes/{episode_id}/state`、`/summary`、`/download`：Task 04。
- `GET /datasets`、`GET /datasets/{dataset_id}/summary`：Task 05。
- `WS /ws/episodes/{episode_id}` 和至少 10 FPS 的 `SimFrame` 推送：Task 06。
- `run_episode.py`、`replay_episode.py`、`batch_generate.py`：Task 07。
- API/WebSocket/CLI/错误处理/端到端集成测试：Task 08。
- API 自动文档：Task 02 和 Task 08。
- 本地单机运行、无前端批量生成数据：Task 07。
- WebSocket 与 `visual/frames.jsonl` 使用同一 `SimFrame` schema：overview、Task 06、Task 08 均列为硬性验收。
- 错误响应结构统一：overview、Task 01、Task 02、Task 08。
- M 不实现仿真核心、不记录落盘、不生成 dataset、不渲染前端：overview 和各任务 non-goals 已标注。

## 依赖顺序检查

结论：依赖顺序合理且无环。

```text
Task 01 api schema
  -> Task 02 health and config
  -> Task 03 episode lifecycle
  -> Task 04 episode query
  -> Task 06 websocket
  -> Task 08 tests and acceptance

Task 01 api schema
  -> Task 02 health and config
  -> Task 05 dataset api
  -> Task 08 tests and acceptance

Task 03 episode lifecycle
  -> Task 07 cli scripts
  -> Task 08 tests and acceptance
```

说明：

- Task 03 需要 Task 02 的 app/error handler；Task 04 需要 Task 03 的 registry。
- Task 05 只依赖 Task 01/02，可与 Task 03/04 大体并行实现。
- Task 06 依赖 Task 03 的 episode registry 和 L 的 `SimFrame`，但不依赖 Task 04/05。
- Task 07 依赖 Task 03 提取出的共享 runner factory，但不依赖 FastAPI app 的运行。
- Task 08 依赖所有前置任务。

## 验收标准可测性检查

结论：每个验收标准都可以通过 pytest、FastAPI TestClient、WebSocket TestClient、subprocess、tmp_path 文件夹 fixture、Pydantic schema 校验或静态扫描验证。

- schema 验收可通过 Pydantic `model_validate()`、extra 字段和 JSON dump 验证。
- OpenAPI 验收可通过 `GET /openapi.json` 验证路径集合。
- 配置校验可复用 `backend/app/tests/fixtures/configs/demo_valid.yaml` 和已有 Module A fixtures。
- episode lifecycle 可用 fake runner factory 验证 API registry 与状态流转，避免依赖完整外部 LLM。
- summary/download 可用 tmp_path 构造 Module L run 目录，写入 `episode_summary.json`、`frames.jsonl` 和 manifest。
- dataset API 可用 tmp_path 构造 dataset root，并用缺失 O service 验证 not implemented 路径。
- WebSocket 可用 TestClient websocket 和真实 `SimFrame` fixture 验证 schema、offline label 隔离和多客户端广播。
- CLI 可用 subprocess 调 `--help` 和 monkeypatch/fake runner 的脚本入口函数验证退出码。
- 防泄漏可静态扫描 API schema、error handler、websocket payload 构造和测试响应 JSON。

## 与阶段一背景一致性检查

结论：文档与 `目标.md`、总方案 M.1-M.5、推荐代码目录以及当前 A/J/L 代码合同一致，并显式标注了实现阶段需要补齐的依赖。

- 当前 `EpisodeRunner` 已提供 `run_episode()`、`run_one_frame()`、`stop()`；Task 03 只通过 runner/service 使用这些入口。
- 当前 J 已有 `websocket.broadcast_sim_frame_if_enabled(...)` hook；Task 06 设计 adapter 对接该 hook。
- 当前 L 已有 `SimFrame`、`EpisodeSummary`、run 目录结构和 `visual/frames.jsonl`；Task 04/06 直接复用这些合同。
- 当前项目尚无 FastAPI 依赖；Task 02 明确阶段三需补齐 FastAPI/TestClient 运行依赖。
- 当前 O 尚未实现；Task 05 明确 dataset API 的文件系统只读降级或 `M_E_DATASET_NOT_IMPLEMENTED` 行为，不伪造 dataset 构建。
- CLI 不绑定 FastAPI app，满足“第一版必须支持命令行脚本运行，不能把仿真核心绑定在 Web 服务中”。
- 统一错误结构使用 `code/data/message/details`，满足 `目标.md` 的 API 响应约束。

## 调整记录

- 保留 `目标.md` 建议的 8 个任务，没有合并为更粗粒度任务，便于逐任务提交和测试。
- 将 API schema 单独作为 Task 01，避免各 route 自行定义响应结构。
- 将 health/config 单独作为 Task 02，先建立 app、OpenAPI 和异常 handler。
- 将 episode 控制与 episode 查询拆开：控制写 registry，查询读 registry/run 文件。
- 将 dataset API 设计为只读查询，并明确 O 未实现时的错误路径。
- 将 WebSocket 明确绑定 L 的 `SimFrame`，禁止第二套实时 frame schema。
- 将 CLI 设计为复用 runner factory，避免 Web 服务成为仿真核心依赖。
- 在验收中加入 secret 防泄漏、路径穿越和慢 WebSocket 客户端边界。

## 阶段闸口

阶段一和阶段二的规划文档已经写完。根据 `目标.md` 的硬性要求，现在应停下等待确认；收到确认后再进入阶段三逐任务实现、测试和提交。
