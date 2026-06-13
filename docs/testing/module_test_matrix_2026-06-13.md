# 模块测试矩阵 2026-06-13

## 说明

本文档按模块列出当前自动化测试的主要覆盖面、代表性测试文件和关键风险。它不是替代各模块 `coverage_summary.md`，而是给完整模型测试提供一个总览。

## 覆盖矩阵

| 模块 | 主要测试文件 | 覆盖重点 | 当前状态 |
|---|---|---|---|
| A | `test_config_schema.py`, `test_config_loader.py`, `test_resolved_config.py`, `test_run_workspace.py`, `test_secret_governance.py`, `test_moduleA_acceptance.py` | 配置 schema、加载/override、resolved hash、运行目录、secret redaction、错误映射 | 通过 |
| B | `test_crane_model.py`, `test_manual_layout.py`, `test_auto_layout.py`, `test_layout_reachability.py`, `test_moduleB_*_extra.py`, `test_moduleB_acceptance.py` | 型号库、manual/auto layout、布局诊断、载荷曲线、reachability | 通过 |
| C | `test_physics*.py`, `test_crane_state.py`, `test_moduleC_*_extra.py`, `test_moduleC_acceptance.py` | 初始状态、几何、步进、世界集成、有限值、纯物理边界 | 通过 |
| D | `test_task_*.py`, `test_moduleD_*_extra.py`, `test_moduleD_acceptance.py` | 任务生成、队列、状态机、失败恢复、任务事件/观测合同 | 通过 |
| E | `test_weather_*.py`, `test_moduleE_acceptance.py` | 天气配置、生成器、随机可复现、可见度、风告警、调度/记录合同 | 通过 |
| F | `test_observation.py`, `test_observation_visibility.py`, `test_moduleF_*_extra.py`, `test_moduleF_acceptance.py` | LLM observation、邻居可见性、任务上下文、安全提示、历史清洗 | 通过 |
| G | `test_prompt_builder.py`, `test_llm_provider.py`, `test_command_*.py`, `test_operator_*.py`, `test_moduleG_*_extra.py`, `test_moduleG_acceptance.py` | prompt、provider、parser、retry/fallback、operator orchestrator、secret 防泄漏 | 通过 |
| H | `test_safety_*.py`, `test_forbidden_zone_policy.py`, `test_risk_online.py`, `test_collision.py`, `test_moduleH_acceptance.py` | 机械安全、禁区、在线风险、干预、碰撞终止 | 通过 |
| I | `test_controller.py`, `test_moduleI_*_extra.py`, `test_moduleI_acceptance.py` | 档位映射、速度平滑、停止模式、batch 控制器 | 通过 |
| J | `test_scheduler.py`, `test_moduleJ_acceptance.py` | WorldSnapshot、command store、decision clock、frame loop、终止状态、replay | 通过 |
| K | `test_offline_label.py`, `test_moduleK_acceptance.py` | 离线风险标签、几何距离、未来窗口、标签报告 | 通过 |
| L | `test_recorder.py`, `test_moduleL_acceptance.py` | Recorder schema、run 目录、Parquet/JSONL、SimFrame、summary、J->L 集成 | 通过 |
| M | `test_moduleM_*.py` | FastAPI、REST、WebSocket、CLI、本地 runner、dataset fallback、下载错误 | 通过 |

## 跨模块链路

当前完整测试覆盖以下关键链路：

- A 配置解析 -> B 布局解析 -> C 初始物理状态。
- D 任务队列 -> F observation -> G command -> H safety -> I control -> C physics。
- J 调度循环 -> L recorder -> `visual/frames.jsonl` / Parquet / summary。
- M API start/query/download -> WebSocket `SimFrame` -> CLI 本地 episode 运行。
- K 离线标签 -> L 写入 offline labels，同时实时帧和 observation 禁止泄漏 offline truth。

## 当前强覆盖区域

- Schema 合同：大多数核心对象都有 `extra="forbid"`、枚举、边界和 JSON 序列化测试。
- 可复现性：layout、task、weather、resolved config hash、随机时间线均有 deterministic 测试。
- 错误路径：配置错误、layout 失败、task 不可达、LLM parser 错误、replay mismatch、recorder 写失败、API not found/download failed 均有覆盖。
- 安全边界：secret redaction、防 future truth 泄漏、实时 WebSocket 禁止 offline labels、模块 import 边界静态检查。

## 当前弱覆盖区域

- 真实外部 LLM provider 网络调用没有在默认测试中执行，当前主要覆盖 provider wrapper、mock/fallback 和错误处理。
- Module M 的默认本地 runner 是 deterministic 短 episode 装配，未跑完整生产任务生成 + 外部 LLM + 全安全/风险链路。
- 数据集生成 Module O、前端 Module N 和训练 Module P 尚未作为完整生产链路纳入本轮测试。
- 大规模性能压测没有覆盖；当前测试偏向合同、边界和小规模集成。

## 建议补充优先级

1. 在 Module O 完成后，补 `run_dir -> dataset summary -> split/window export` 的端到端验收。
2. 在 Module N 完成后，补 `visual/frames.jsonl` 与 WebSocket `SimFrame` 的真实渲染 smoke test。
3. 在接入真实 LLM key 的受控环境中，补 provider integration smoke test，并确保不进入默认 CI。
4. 对 J/L/M 增加长 episode 小基准，记录帧数、写入耗时和文件大小，作为性能退化基线。
