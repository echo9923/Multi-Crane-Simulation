# Module H Overview：安全审查与在线风险边界

## 职责

模块 H 是仿真安全链路的总闸门。它消费模块 G 产出的 `ParsedCommand`，结合当前 `CraneState`、`CraneConfig`、`WeatherState` 和 R/S 配置，依次执行基础机械安全、禁区策略、在线风险评估、可配置多塔干预和碰撞终止判断，最终产出 `ExecutedCommand`、`OnlineRisk` 以及可被记录器消费的风险/干预/碰撞事件。

H 位于命令链路第三步：

```text
RawLLMResponse -> ParsedCommand -> ExecutedCommand -> ControlTarget -> CraneState
```

其中 `ParsedCommand` 归模块 G，`ExecutedCommand` 与 `OnlineRisk` 归模块 H，`ControlTarget` 归模块 I。H 可以修改 G 的司机意图，但只能基于安全合同修改，且必须同时保存 raw command 与 executed command 差异。

## 三层安全架构

H 的核心处理顺序如下：

```text
ParsedCommand
  -> 基础机械安全层
  -> 禁区策略层
  -> 在线风险影子评估层
  -> S0/S1/S2/S3 多塔干预层
  -> 碰撞检测与 episode 终止
  -> ExecutedCommand + OnlineRisk + events
```

基础机械安全层始终生效，不受 `SafetyMode` 影响；在线风险评估始终计算并记录，不依赖 `RiskPromptMode` 是否向观察暴露；多塔干预由 `SafetyMode` 控制；风险提示是否进入 observation 由模块 F 根据 `RiskPromptMode` 和 H 的 `OnlineRisk` 输入决定。

## 输入

H 读取以下对象：

- `ParsedCommand`：模块 G 输出的结构化高层手柄命令。
- `CraneState[]`：模块 C 当前帧物理状态，包括角度、速度、小车半径、吊钩高度、hook/load 位置和载重。
- `CraneConfig[]`：模块 B 解析后的塔吊静态参数，包括起重臂长度、行程限制、高度限制、回转模式和型号规格。
- `CraneModelSpec`：来自 `CraneConfig.model`，提供速度/加速度上限、起升/小车限制、载重曲线、力矩计算和 `is_load_allowed()`。
- `WeatherState`：模块 E 当前天气状态，H 只读取 `wind_for_safety_m_s` 计算风险安全距离冗余。
- `RiskConfig`：来自 `ScenarioConfig.risk`，包括 `geometry_envelope`、`thresholds_m`、`ttc_threshold_level` 和 `wind_safe_distance_factor`。
- `ExperimentConfig.safety_mode`：S0/S1/S2/S3，控制多塔风险干预强度。
- `ExperimentConfig.risk_prompt_mode`：R0/R1，只作为记录和下游 F 合同的一部分，H 不直接构造 observation。
- `ScenarioConfig.site.forbidden_zones` 和 `forbidden_zone_policy`：禁区策略输入。
- 调度器提供的当前 frame/decision 上下文，例如 `snapshot_id`、`time_s`、`dt_s`、episode status sink 或等价返回对象。

## 输出

H 输出以下对象，供 I/F/J/L/K 消费：

```text
ExecutedCommand
OnlineRisk
RiskPairResult[]
MechanicalLimitResult
ForbiddenZoneResult
InterventionRecord[]
CollisionEvent | None
safety/risk/intervention/collision events
episode_status candidate
```

建议的阶段性运行接口：

```python
def apply_mechanical_safety(
    *,
    command: ParsedCommand,
    state: CraneState,
    config: CraneConfig,
    dt_s: float,
) -> MechanicalLimitResult:
    ...

def evaluate_online_risk(
    *,
    crane_states: list[CraneState],
    crane_configs: list[CraneConfig],
    risk_config: RiskConfig,
    weather_state: WeatherState,
    proposed_commands: dict[str, ParsedCommand | ExecutedCommand],
    horizon_s: float = 5.0,
) -> OnlineRisk:
    ...

def apply_safety_pipeline(
    *,
    commands: list[ParsedCommand],
    crane_states: list[CraneState],
    crane_configs: list[CraneConfig],
    risk_config: RiskConfig,
    weather_state: WeatherState,
    safety_mode: SafetyMode,
    forbidden_zones: list[ZoneConfig],
    forbidden_zone_policy: ForbiddenZonePolicyConfig,
    dt_s: float,
) -> SafetyPipelineResult:
    ...
```

接口名称可在实现阶段调整，但对象边界必须保持：H 接收 G 的 `ParsedCommand`，输出 H 拥有的 `ExecutedCommand` 和 `OnlineRisk`。

## 对内依赖

- A：读取 resolved config 中的 risk、safety mode、risk prompt mode 和禁区策略配置。
- B：读取 `CraneConfig` 与 `CraneModelSpec`，不重新解析塔吊型号库。
- C：读取当前帧 `CraneState`，不推进物理状态。
- E：读取 `WeatherState.wind_for_safety_m_s`，不生成天气。
- G：读取 `ParsedCommand`，保留原始司机意图。
- F：消费 H 输出的 `OnlineRisk` 或等价 hint 输入，但 H 不构造 `Observation`。
- I：消费 H 输出的 `ExecutedCommand` 并转成 `ControlTarget`。
- J：按 frozen snapshot 调用 H，并根据 H 的 collision/failed status 终止 episode。
- K：消费 H 记录的每帧每对塔吊风险数据生成离线标签。
- L：消费 H 输出对象和事件落盘，H 本身不写 Parquet/JSONL。

## 拥有对象

模块 H 拥有并实现：

- `SAFETY_SCHEMA_VERSION`、`RISK_SCHEMA_VERSION`
- `ExecutedCommand`
- `OnlineRisk`
- `RiskPairResult`
- `RiskLevel`
- `InterventionRecord`
- `MechanicalLimitResult`
- `ForbiddenZoneResult`
- `CollisionEvent`
- `SafetyPipelineResult`
- `SAFETY_*`、`RISK_*`、`COLLISION_*` 错误码
- 基础机械安全层
- 禁区策略层
- 在线风险评估器
- S0/S1/S2/S3 干预管线
- 碰撞检测与终止候选结果

模块 H 只读取或接收接口，不拥有：

- `ParsedCommand`、`RawLLMResponse` 和 LLM retry，归模块 G。
- `Observation`、`SafetyHint` 构造，归模块 F。
- `ControlTarget` 和低层控制器，归模块 I。
- `CraneState` 状态推进与动力学，归模块 C。
- task attach/release 合法性和任务状态机，归模块 D。
- 天气生成，归模块 E。
- snapshot 冻结、episode 主循环和 replay 调度，归模块 J。
- 离线标签生成，归模块 K。
- 文件写入、Parquet/JSONL 和 manifest，归模块 L。

## 非目标

模块 H 不做以下事情：

- 不调用 LLM provider，不解析自然语言，不生成 `RawLLMResponse`。
- 不构造 `Observation`，也不决定 R0/R1 下 prompt 如何呈现风险。
- 不把 `ExecutedCommand` 转为 `ControlTarget`。
- 不推进 `CraneState` 或物理时钟。
- 不判定任务 attach/release 是否业务合法。
- 不生成或修正天气状态。
- 不冻结 `WorldSnapshot`。
- 不使用 episode 真实未来轨迹、离线标签或未来任务计划做 online risk。
- 不写 recorder 输出文件。

## 关键边界规则

- 基础机械安全层始终生效，覆盖回转速度/角加速度、小车半径、起升高度、载重曲线、力矩、deadman 和 emergency stop。
- S0/S1 不因在线风险修改命令，但机械安全、力矩限制、deadman、emergency stop 和 hard forbidden zone 仍可修改命令。
- S1 仍记录风险，且风险不会因为 R0 隐藏提示而停止计算。
- S2 在 high 或更高风险时限速，记录实际干预。
- S3 在 high/near_miss 或更高风险时强制减速或停车，记录实际干预。
- `intervention_applied` 只在 S2/S3 因风险干预实际修改命令时记录；机械限位和禁区硬阻止使用各自事件。
- `raw_command` 与 `executed_command` 都必须可序列化保存。
- `OnlineRisk` 每帧每对塔吊都应有 `RiskPairResult`，供 K 后续生成离线标签。
- 碰撞发生后记录 collision event，向 J 返回 `episode_status="failed_collision"` 候选，当前 episode 必须立即终止，不生成碰撞后的轨迹。
- 所有 H 拥有的 Pydantic schema 使用 `extra="forbid"`，数值拒绝 NaN/Inf。

## 风险等级语义

H 使用以下风险等级：

| 等级 | 语义 |
| --- | --- |
| `safe` | 当前和短时外推都满足安全距离，未出现明显闭合风险。 |
| `low` | 低于 low 阈值或 TTC 轻微接近，但仍有充足余量。 |
| `medium` | 进入 medium 阈值或 TTC 达到配置关注等级，需要记录并可提示。 |
| `high` | 进入 high 阈值或短时外推显示高风险，S2/S3 可干预。 |
| `near_miss` | 接近 near-miss 阈值但尚未碰撞，S3 应强制减速/停车。 |
| `collision` | 几何包络已相交或距离小于碰撞阈值，应终止 episode。 |

## 失败边界

| 失败 | 默认处理 | 输出 |
| --- | --- | --- |
| 机械限制命中 | clamp 或 neutralize 对应轴 | `MechanicalLimitResult`、mechanical event、`ExecutedCommand` |
| 载重/力矩超限 | 硬限制危险动作，必要时保持/回退 | `moment_limit` / `overload_prevented` event |
| 禁区进入 | `task_only` 记录；`hard` 阻止进入动作或标记失败候选 | `ForbiddenZoneResult`、forbidden zone event |
| 高风险 | S0/S1 仅记录；S2/S3 按模式干预 | `OnlineRisk`、`InterventionRecord` |
| 碰撞 | 立即返回 failed collision 候选 | `CollisionEvent`、`episode_status="failed_collision"` |
| 输入状态缺失或不一致 | 抛出 H 专属错误，交由 J 标记 episode invalid | `SAFETY_E_INVALID_STATE` 或等价错误码 |

## 权威来源

若本文档与根目录 `群塔LLM仿真系统开发方案_v0.4_完整版.md` 或 `目标.md` 冲突，以总方案 `0.7.1`、`0.7.2`、`0.7.3`、`0.7.4`、`H.2`、`H.3`、`H.4`、`H.5`、`H.6` 以及本轮 `目标.md` 为准，并同步修订本文档。
