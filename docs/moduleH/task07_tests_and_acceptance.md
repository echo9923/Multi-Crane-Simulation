# Task 07：模块 H 测试清单与验收标准

## 任务目标

定义模块 H 的 schema、机械安全、禁区策略、在线风险评估、风险干预、碰撞终止、信息泄漏防护和 G->H->I 链路验收测试，确保安全总闸门可独立验证并与相邻模块合同兼容。

## 范围：做什么 / 不做什么

做：

- 新增并维护 `backend/app/tests/test_safety_risk_schema.py`。
- 新增并维护 `backend/app/tests/test_safety_mechanical.py`。
- 新增并维护 `backend/app/tests/test_forbidden_zone_policy.py`。
- 新增并维护 `backend/app/tests/test_risk_online.py`。
- 新增并维护 `backend/app/tests/test_safety_intervention.py`。
- 新增并维护 `backend/app/tests/test_collision.py`。
- 新增并维护 `backend/app/tests/test_moduleH_acceptance.py`。
- 回归模块 A/B/C/E/F/G 的相邻合同测试。
- 覆盖正常路径、边界路径、异常路径、信息泄漏防护和多塔集成路径。

不做：

- 不要求真实 LLM provider。
- 不要求完整 recorder 写 Parquet/JSONL。
- 不要求模块 K 已实现离线标签。
- 不要求真实物理仿真长 episode。

## 接口与数据结构（签名级别）

本任务不新增生产接口，只定义并维护测试入口：

```python
def test_executed_command_preserves_raw_command_and_forbids_extra() -> None: ...
def test_online_risk_pair_schema_rejects_future_truth_and_invalid_level() -> None: ...
def test_deadman_release_neutralizes_all_motion_axes() -> None: ...
def test_emergency_stop_neutralizes_all_motion_axes() -> None: ...
def test_trolley_limits_clamp_out_and_in_commands() -> None: ...
def test_hoist_limits_clamp_up_and_down_commands() -> None: ...
def test_moment_limit_prevents_overload_motion() -> None: ...
def test_task_only_forbidden_zone_records_without_modifying_command() -> None: ...
def test_hard_forbidden_zone_blocks_entering_motion() -> None: ...
def test_online_risk_computes_pair_count_for_all_cranes() -> None: ...
def test_online_risk_uses_wind_extra_clearance() -> None: ...
def test_online_risk_short_horizon_detects_closing_pair_without_future_truth() -> None: ...
def test_s0_s1_record_risk_without_risk_intervention() -> None: ...
def test_s2_limits_speed_on_high_risk() -> None: ...
def test_s3_forces_stop_on_near_miss() -> None: ...
def test_collision_event_marks_failed_collision() -> None: ...
def test_module_h_boundaries_remain_static() -> None: ...
def test_g_to_h_to_i_command_contract_smoke() -> None: ...
```

## 前置依赖

- Task 01 schema。
- Task 02 mechanical safety。
- Task 03 forbidden zone policy。
- Task 04 online risk evaluator。
- Task 05 intervention pipeline。
- Task 06 collision detection。
- 模块 G 的 `ParsedCommand`。
- 模块 I 的 `ControlTarget` schema 或转换入口，若 I 尚未实现，则 smoke test 只验证 `ExecutedCommand` 具备 I 所需字段。

## 验收标准（具体、可测试）

- `目标.md` 中列出的 Module H 单项测试、完整验收测试和邻近模块回归测试必须通过。
- 本文档额外列出的 `test_safety_risk_schema.py` 和 `test_forbidden_zone_policy.py` 是为了让 Task 01 和 Task 03 可独立交付；它们不替代 `目标.md` 的硬性测试命令。
- schema、机械安全、禁区策略、在线风险、风险干预、碰撞检测、信息泄漏防护和 G->H->I smoke path 都必须有可执行 pytest 覆盖。
- 若模块 I 尚未实现，G->H->I smoke path 可降级为 H 输出字段合同验证，并在测试名或断言注释中说明等待 I 接入；模块 I 完成后必须升级为真实 `ExecutedCommand -> ControlTarget` 测试。
- 默认测试不得依赖真实 LLM 网络调用、真实 recorder 写文件或离线标签生成器。
- 每个实现任务在提交前运行对应单项测试，并在最终阶段运行完整验收和邻近模块回归测试。

## 推荐测试命令

schema 测试：

```bash
pytest backend/app/tests/test_safety_risk_schema.py -v
```

目标文档中的机械安全层测试：

机械安全层测试：

```bash
pytest backend/app/tests/test_safety_mechanical.py -v
```

禁区策略测试：

```bash
pytest backend/app/tests/test_forbidden_zone_policy.py -v
```

目标文档中的在线风险评估测试：

在线风险评估测试：

```bash
pytest backend/app/tests/test_risk_online.py -v
```

目标文档中的干预管线测试：

干预管线测试：

```bash
pytest backend/app/tests/test_safety_intervention.py -v
```

目标文档中的碰撞检测测试：

碰撞检测测试：

```bash
pytest backend/app/tests/test_collision.py -v
```

扩展后的模块 H 完整验收：

```bash
pytest backend/app/tests/test_safety_risk_schema.py \
       backend/app/tests/test_safety_mechanical.py \
       backend/app/tests/test_forbidden_zone_policy.py \
       backend/app/tests/test_risk_online.py \
       backend/app/tests/test_safety_intervention.py \
       backend/app/tests/test_collision.py \
       backend/app/tests/test_moduleH_acceptance.py -v
```

`目标.md` 中的模块 H 完整验收基线也必须保留：

```bash
pytest backend/app/tests/test_safety_mechanical.py \
       backend/app/tests/test_risk_online.py \
       backend/app/tests/test_safety_intervention.py \
       backend/app/tests/test_collision.py \
       backend/app/tests/test_moduleH_acceptance.py -v
```

回归邻近模块：

```bash
pytest backend/app/tests/test_config_schema.py \
       backend/app/tests/test_crane_model.py \
       backend/app/tests/test_crane_state.py \
       backend/app/tests/test_weather_wind_contract.py \
       backend/app/tests/test_observation.py -v
```

扩展邻近回归建议：

```bash
pytest backend/app/tests/test_config_schema.py \
       backend/app/tests/test_crane_model.py \
       backend/app/tests/test_crane_state.py \
       backend/app/tests/test_weather_wind_contract.py \
       backend/app/tests/test_observation.py \
       backend/app/tests/test_command_schema.py -v
```

## schema 验收

- `ExecutedCommand`、`OnlineRisk`、`RiskPairResult`、`MechanicalLimitResult`、`ForbiddenZoneResult`、`InterventionRecord`、`CollisionEvent` 全部拒绝 extra 字段。
- 所有 H schema 拒绝 NaN/Inf。
- `ExecutedCommand` 保留完整 `raw_command`。
- `OnlineRisk` 可以表达每帧每对塔吊风险结果。
- `CollisionEvent` 固定输出 `failed_collision`。
- `OnlineRiskHint` 合同可与模块 F 的 `build_safety_hint()` 衔接。

## 机械安全验收

- 基础机械安全始终生效，不受 S0-S3 影响。
- deadman release 与 emergency stop 都会 neutralize 所有运动轴。
- 小车、起升、回转速度/加速度限制都可被单测触发。
- 力矩超限和载重曲线超限都会硬限制危险动作。
- 机械限位会记录原因，但不会伪装成 S2/S3 风险干预。

## 禁区策略验收

- `task_only` 模式记录 violation，不修改命令。
- `hard` 模式阻止进入禁区的动作。
- box 与 polygon 禁区均有测试覆盖。
- z_range 生效。
- `record_violation=False` 时不落 event，但仍返回 result。

## 在线风险验收

- 风险距离单元测试覆盖 jib-jib、jib-hook、hook-hook 和 load 相关组合。
- 线段交叉和点线距离用例覆盖。
- `d_min_online_m`、`d_hat_min_m`、`ttc_hat_s` 可解释且非负。
- 风速冗余会影响 `d_safe_effective_m`。
- 风险等级映射覆盖 safe/low/medium/high/near_miss/collision。
- 不使用真实未来轨迹、offline label 或 future TTC。
- 每帧每对塔吊风险标签可导出。

## 干预验收

- S0/S1 不因风险修改命令，但记录 risk。
- S2 在 high 或更高风险时限速。
- S3 在 high/near_miss 或更高风险时强制减速/停车。
- `intervention_applied` 只在 S2/S3 实际修改命令时记录。
- raw vs executed 差异可被序列化和回放检查。
- R0/R1 只影响 F observation 暴露，不影响 H risk 计算。

## 碰撞验收

- 碰撞发生时记录 collision event。
- H 返回 `episode_status="failed_collision"`。
- J/I 集成测试确认碰撞后不会继续生成新的控制目标或轨迹。
- 碰撞 event 包含对象类型、塔吊对、时间、距离和原因。

## 信息泄漏与越权验收

H 的 online risk 和 safety hint 输入不得包含：

```text
future_min_distance
offline_ttc
offline_label
future_ttc
planned_future_position
neighbor_future_task
```

静态 import/name 扫描应确认 H 的实现不导入或调用：

```text
backend.app.sim.operator_decision
backend.app.sim.llm_provider
recorder writer
offline label generator
```

允许 H 导入 `CraneState`、`CraneConfig`、`WeatherState`、`ParsedCommand`、`OnlineRiskHint`、风险/配置 schema 和基础几何 helper。

## 集成验收

- 构造 3 台塔吊的同一 snapshot 状态、配置、天气和 `ParsedCommand`。
- 先通过 H 产出 `ExecutedCommand` 与 `OnlineRisk`。
- 对无风险塔吊，executed command 与 raw command 保持一致。
- 对 high risk pair，S2 限速、S3 停车。
- 对 R1 observation 构建，模块 F 能消费 H 的 hint 输入；对 R0 observation 构建，不暴露 `safety_hint`。
- 若模块 I 已实现转换入口，验证 `ExecutedCommand -> ControlTarget` smoke path；若未实现，仅验证 H 输出字段满足 I 合同并在测试中标注待 I 完成。

## 最终退出条件

- Module H 七个测试文件全部通过。
- 目标文档列出的完整验收命令通过，或对尚未实现的相邻模块给出明确跳过原因。
- 邻近模块 A/B/C/E/F/G 回归测试通过。
- 默认测试不依赖网络、不依赖真实 LLM、不写持久化 recorder 输出。
- 每个实现任务按依赖顺序独立提交，提交信息格式为 `feat(moduleH): <任务目标>`。

## 测试要点（正常 + 边界 + 异常）

- 正常：合法命令、无风险、多塔 pair 风险、S2/S3 干预、碰撞终止。
- 边界：单塔、两塔距离正好等于阈值、gear=0/5、载重等于容量、风速为 0、无禁区。
- 异常：缺失 state/config/command、snapshot mismatch、非法 geometry、重复 crane_id、dt/horizon/sample_dt 非法。
- 防泄漏：schema、序列化 payload 和静态 import 均不暴露未来真值或越权依赖。
