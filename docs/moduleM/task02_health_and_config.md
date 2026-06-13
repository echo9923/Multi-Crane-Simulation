# Task 02：Health 与配置校验 API

## 任务目标

实现 FastAPI app 基础结构、`GET /health` 和 `POST /scenarios/validate`，提供可自动生成 OpenAPI 文档的最小 API 面。

## 范围：做什么 / 不做什么

做：

- 新增 `backend/app/main.py`，创建 FastAPI app。
- 新增 `backend/app/api/routes_health.py`。
- 新增 `backend/app/api/errors.py`，注册统一异常 handler。
- 实现 `GET /health`，返回服务状态、schema version、可用模块摘要。
- 实现 `POST /scenarios/validate`，调用 A 的配置 loader/resolver/schema 校验。
- 将 A 的配置错误映射为 `M_E_CONFIG_INVALID`。
- 验证 OpenAPI/Swagger 可用。

不做：

- 不启动 episode。
- 不实现后台 runner registry。
- 不读取 L 的 run 数据。
- 不实现 WebSocket。
- 不生成或修改配置文件。

## 接口与数据结构（签名级别）

```python
def create_app() -> FastAPI: ...
```

```python
@router.get("/health")
def health() -> ApiResponse:
    ...
```

返回 `data` 建议结构：

```json
{
  "status": "ok",
  "api_schema_version": "1.0",
  "modules": {
    "api": "available",
    "config": "available",
    "scheduler": "available",
    "recorder": "available"
  }
}
```

```python
@router.post("/scenarios/validate")
def validate_scenario(request: ScenarioValidateRequest) -> ApiResponse:
    ...
```

配置入口规则：

- `config_path` 非空时，按 A 的 demo config loader 读取并解析。
- `scenario` inline 非空时，与可选 `experiment`、`dataset` 一起调用 A 的 resolver。
- `config_path` 与 inline config 同时出现时，第一版应拒绝并返回 `M_E_CONFIG_INVALID`，避免来源歧义。
- `overrides` 只传给 A 的 loader/resolver，不在 M 中手写字段覆盖逻辑。

## 前置依赖

- Task 01 的 API schema 和错误合同。
- A 的 `load_demo_config()`、`resolve_config()`、`ConfigError` 或等价错误映射能力。
- `pyproject.toml` 需要加入 FastAPI 运行依赖；若测试使用 `TestClient`，需保证对应依赖可用。

## 验收标准（具体、可测试）

- `GET /health` 返回 HTTP 200。
- `GET /health` 响应体符合统一结构，`code == 0`、`message == "ok"`。
- FastAPI 自动文档存在：`GET /openapi.json` 返回 HTTP 200 且包含 `/health` 和 `/scenarios/validate`。
- `POST /scenarios/validate` 对有效 demo config 返回 `valid=true` 和 `resolved_config_hash`。
- inline scenario/experiment/dataset 有效时返回 `valid=true`。
- `config_path` 与 inline config 同时出现时返回 HTTP 422 或 400，错误码为 `M_E_CONFIG_INVALID`。
- 无效配置返回统一错误结构，details 中包含 config kind、字段路径或 A 的原始诊断摘要。
- 错误响应中不包含完整 API key。

## 测试要点（正常 + 边界 + 异常）

- 正常：`TestClient(app).get("/health")`。
- 正常：`TestClient(app).get("/openapi.json")`。
- 正常：用 `backend/app/tests/fixtures/configs/demo_valid.yaml` 校验成功。
- 正常：用单独 scenario/experiment/dataset dict 校验成功。
- 边界：`dataset=None` 时只校验 scenario + experiment 成功。
- 异常：不存在的 `config_path` 返回统一错误。
- 异常：非法 YAML 或 schema 字段返回统一错误。
- 防泄漏：传入 inline `api_key` 后，响应 JSON 不包含完整 secret 值。

## 依赖关系

Task 02 依赖 Task 01。Task 03-06 依赖本任务创建的 FastAPI app、router 注册方式和异常 handler。
