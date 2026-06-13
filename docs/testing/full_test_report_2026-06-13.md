# 全量测试报告 2026-06-13

## 测试对象

本轮测试覆盖当前仓库已经实现到 Module A-M 的仿真后端模型与接口栈：

- Module A：配置 schema、配置加载、resolved config、运行目录、密钥治理和配置错误。
- Module B：塔吊型号库、manual/auto layout、resolved crane config 和 reachability precheck。
- Module C：物理状态、几何、积分、世界步进和纯度边界。
- Module D：任务 schema、任务生成、队列调度、状态机、失败与恢复。
- Module E：天气状态、配置解析、天气生成、可见度、风风险合同和调度/记录合同。
- Module F：LLM observation schema、可见性过滤、任务上下文、安全提示和批量观测装配。
- Module G：prompt、provider、command parser、retry/fallback、operator orchestrator。
- Module H：安全风险 schema、机械安全、禁区策略、在线风险和安全干预。
- Module I：控制器 schema、档位速度映射、平滑过渡、停止模式和 batch orchestrator。
- Module J：调度器 schema、WorldSnapshot、command store、decision clock 和 frame loop。
- Module K：离线标签 schema、几何距离、未来窗口标签和标签报告。
- Module L：Recorder schema、run directory、Parquet/JSONL/SimFrame/summary 和 J->L 集成。
- Module M：FastAPI REST、WebSocket、CLI、本地 runner、dataset 查询和端到端 API 验收。

## 环境

- 当前日期：2026-06-13
- Python：3.13.13
- 测试框架：pytest 8.4.2
- 关键依赖：
  - fastapi `>=0.115,<1`
  - pydantic `>=2.13,<3`
  - pyarrow `>=18.1,<19`
  - PyYAML `>=6.0,<7`
  - httpx `>=0.27,<1`

`pyarrow` 已在当前 `.venv` 中安装为 `18.1.0`。该版本用于支持 Python 3.13 wheel，避免旧的 `pyarrow<18` 约束触发源码构建。

## 执行命令

```bash
.venv/bin/pytest backend/app/tests -v
```

## 执行结果

```text
895 passed, 1 warning in 5.86s
```

唯一 warning：

```text
StarletteDeprecationWarning: Using httpx with starlette.testclient is deprecated; install httpx2 instead.
```

该 warning 来自 `fastapi.testclient` / Starlette 与 httpx 的兼容提示，不影响当前测试结果。后续若升级 FastAPI/Starlette/httpx，应单独安排依赖兼容性回归。

## 重点通过项

- 全部模块级 acceptance 测试通过。
- 全部 schema 严格性测试通过，包括 extra 字段拒绝、NaN/Inf 处理、稳定枚举和 JSON 序列化。
- A -> B -> D/E -> F/G/H/I -> J -> L -> M 的核心合同链路可测试闭合。
- Module M 的 REST、WebSocket、CLI、本地 runner 和下载错误路径均通过自动化测试。
- Module L 的真实 recorder 与 J 的 `EpisodeRunner` 集成测试通过，证明真实 Parquet/JSONL/SimFrame/summary 写入链路可用。
- 安全边界测试通过，包括密钥不落盘、offline label 不进入实时帧/observation、模块边界 import 静态检查。

## 运行后工作区状态

本轮测试没有要求修改业务代码。运行测试后应只允许出现用户已有的工作区改动；本轮未将 `目标.md` 纳入任何提交或修改流程。

## 结论

当前模型在本地单机环境下完成了一次完整自动化测试。测试结果表明当前 A-M 模块的配置解析、布局、任务、天气、观测、LLM 命令、安全、控制、调度、离线标签、记录导出和 API/CLI 层均处于可回归状态。
