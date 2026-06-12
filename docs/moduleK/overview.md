# Module K Overview：离线风险标签边界

## 职责

Module K 在 episode 完成后，基于完整真实轨迹为每一帧、每一对塔吊生成训练用风险标签。它读取 `trajectories.parquet` 或等价内存轨迹、`CraneConfig[]` 和 `RiskConfig`，复用几何距离计算能力，计算当前精确距离、未来窗口最小 clearance、TTC、风险等级和碰撞标签，产出 `OfflineRiskLabel`。

Module K 是训练标签的权威来源。它只服务数据集生成、图转换、统计分析和 recorder 落盘，不参与在线决策，也不能向 LLM observation、prompt 或在线风险链路写入任何真实未来信息。

## 在线 / 离线隔离

在线模块 H 的 `OnlineRisk` 只能使用当前状态、当前命令和短时外推，`RiskPairResult.used_future_truth` 必须为 `False`。Module K 与之相反：它必须在 episode 结束后读取完整真实轨迹，计算真实未来窗口标签，并在离线标签对象中标记 `used_future_truth=True`。

隔离规则：

- `OfflineRiskLabel`、`OfflinePairRiskRecord`、`min_clearance_future_*`、`ttc_*`、`collision_label_*`、`offline_ttc` 和同义字段不得进入 `WorldSnapshot`、`Observation`、prompt、operator decision、online risk 或 safety intervention。
- K 不调用 LLM provider，不构造 observation，不修改 prompt，不修改 online risk。
- K 不影响已完成 episode 的状态、任务、命令、控制目标或轨迹。标签生成失败只能映射为 dataset build error/warning。
- K 可以读取 H 的 `OnlineRisk` 记录用于 offline vs online 差异分析，但生成 ground truth 标签不依赖 H 的预测结果。

## 输入

Module K 读取以下输入：

- `episode_id`：标签所属 episode。
- `scenario_id | None`：可选场景标识，用于聚合统计。
- 完整 episode 轨迹：来自 `trajectories.parquet` 或内存中的逐帧 `CraneState[]`，必须包含每帧每台塔吊的 `frame_index`、`time_s`、`crane_id`、`root_position`、`tip_position`、`hook_position`、可选 `load_position` 和运动状态。
- `CraneConfig[]`：模块 B 解析的静态塔吊配置，用于校验 crane_id、几何参数和后续扩展。
- `RiskConfig`：模块 A 解析的风险配置，包括 `geometry_envelope`、`thresholds_m`、`ttc_threshold_level`、`wind_safe_distance_factor`，并需扩展 `future_windows_s` 支持 `5/10/15` 秒等可配置窗口。
- `OnlineRisk[] | None`：可选在线风险记录，仅用于对比分析和报告，不参与离线标签真值计算。

轨迹输入的最低内存形态建议为：

```python
class OfflineTrajectoryFrame(RiskBaseModel):
    episode_id: str
    frame: int
    time_s: float
    crane_states: list[CraneState]
```

也可以先用 `dict`/DataFrame 行转换为同等 `CraneState` 结构；转换失败应抛出明确的 K 专属错误。

## 输出

Module K 输出以下对象，定义在 `backend/app/schemas/risk.py`：

- `OfflineRiskLabel`：单条标签记录，即某个 episode、某个 frame、某对塔吊的完整离线风险标签。
- `OfflinePairRiskRecord`：单个 crane pair 的时序标签集合，便于 L/O/P 按 pair 消费。
- `OfflineRiskReport`：标签统计与质量报告，包括正负样本比例、risk level 分布、按 episode/scenario/crane_pair 聚合统计和 warning。

`OfflineRiskLabel` 的权威字段必须覆盖总方案 K.2：

```text
episode_id
frame
time_s
crane_i
crane_j
distance_min_raw_now_m
clearance_min_now_m
distance_jib_jib_raw_now_m
clearance_jib_jib_now_m
distance_jib_i_hook_j_raw_now_m
clearance_jib_i_hook_j_now_m
distance_jib_j_hook_i_raw_now_m
clearance_jib_j_hook_i_now_m
distance_hook_hook_raw_now_m
clearance_hook_hook_now_m
min_clearance_future_5s_m
min_clearance_future_10s_m
ttc_5s_s
ttc_10s_s
risk_level_5s
risk_level_10s
collision_label_5s
collision_label_10s
```

为了满足 `future_windows_s` 可配置和 15s 验收，schema 还应包含通用窗口 map，例如：

```text
future_window_labels: dict[str, OfflineFutureWindowLabel]
```

其中 key 使用规范格式 `5s`、`10s`、`15s`。显式 `*_5s`、`*_10s` 字段用于兼容 K.2 和 Parquet 固定列；`future_window_labels` 用于扩展窗口。

## 对外接口

建议的阶段性运行接口：

```python
class OfflineLabelGenerator:
    @classmethod
    def from_config(cls, config: object) -> "OfflineLabelGenerator":
        ...

    def generate(
        self,
        *,
        episode_id: str,
        trajectory_frames: Sequence[OfflineTrajectoryFrame],
        crane_configs: Sequence[CraneConfig],
        risk_config: RiskConfig,
        scenario_id: str | None = None,
        online_risks: Sequence[OnlineRisk] | None = None,
    ) -> list[OfflineRiskLabel]:
        ...

    def generate_many(
        self,
        *,
        episodes: Sequence[OfflineEpisodeInput],
    ) -> list[OfflinePairRiskRecord]:
        ...
```

底层函数建议：

```python
def compute_pair_geometry_distances(
    *,
    state_i: CraneState,
    state_j: CraneState,
    risk_config: RiskConfig,
) -> OfflinePairGeometryDistance:
    ...

def compute_future_window_label(
    *,
    current_index: int,
    pair_series: Sequence[OfflinePairGeometryDistanceAtTime],
    window_s: float,
    risk_config: RiskConfig,
) -> OfflineFutureWindowLabel:
    ...

def build_offline_risk_report(
    *,
    labels: Sequence[OfflineRiskLabel],
    positive_collision_ratio_warning_threshold: float = 0.01,
) -> OfflineRiskReport:
    ...
```

接口名称可在实现阶段根据代码风格微调，但对象边界必须保持：K 产出结构化对象，L 负责落盘，O/P 负责训练数据消费。

## 对内依赖

- A：读取 `ResolvedConfig` 和 `RiskConfig`，尤其是 geometry envelope、thresholds、TTC 配置和 future windows。
- B：读取 `CraneConfig`，校验 crane_id 与轨迹一致，并为几何计算提供静态参数。
- C：读取 `CraneState` 轨迹真值，不推进物理状态。
- H：可读取 `OnlineRisk` 用于报告对比，不把 H 的短时预测当作 label 真值。
- L：K 不写文件；L 消费 K 的对象写入 `pair_risks.parquet`。
- O：消费 `OfflineRiskLabel` 作为训练标签。
- P：消费 `OfflineRiskLabel` 作为 STGNN 边标签/节点特征来源。

## 拥有对象

Module K 拥有：

- `OFFLINE_LABEL_SCHEMA_VERSION`
- `OfflineRiskLabel`
- `OfflineFutureWindowLabel`
- `OfflinePairGeometryDistance`
- `OfflinePairRiskRecord`
- `OfflineRiskReport`
- `OfflineRiskAggregate`
- `OfflineLabelError`
- `OFFLINE_LABEL_*` 错误码
- `backend/app/sim/offline_label.py` 中的几何距离、未来窗口标签、完整生成器和统计报告函数。

Module K 不拥有：

- `CraneState`、`CraneConfig`、`RiskConfig` 的基础定义。
- `OnlineRisk`、`RiskPairResult` 和在线风险算法。
- `WorldSnapshot`、`Observation`、prompt、LLM provider、scheduler 主循环。
- Parquet/JSONL 写入器、dataset split、STGNN 图转换。

## 非目标

Module K 不做以下事情：

- 不在 episode 运行期间计算标签。
- 不阻塞或影响仿真主循环。
- 不修改 `CraneState`、`Task.status`、`ControlTarget`、`ExecutedCommand` 或已完成 episode 数据。
- 不调用 LLM provider，不读取 prompt，不构造 observation。
- 不做在线风险评估、安全干预或碰撞终止。
- 不冻结 `WorldSnapshot`。
- 不直接写 `pair_risks.parquet`、`trajectories.parquet`、JSONL 或 dataset 文件。
- 不切分训练/验证/测试集，不构造 STGNN 图窗口。
- 不依赖任何模型预测。

## 风险等级语义

Module K 使用与 H 一致的风险等级枚举：

| 等级 | 离线标签语义 |
| --- | --- |
| `safe` | 未来窗口内最小 clearance 大于 low 阈值，未进入有效安全距离。 |
| `low` | 未来窗口最小 clearance 小于等于 low 阈值，但高于 medium。 |
| `medium` | 未来窗口最小 clearance 小于等于 medium 阈值，但高于 high。 |
| `high` | 未来窗口最小 clearance 小于等于 high 阈值，或 TTC 进入有效安全距离。 |
| `near_miss` | 未来窗口最小 clearance 小于等于 near_miss 阈值但仍大于 0。 |
| `collision` | 当前或未来窗口内 `clearance <= 0`，等价 collision label 为 1。 |

`collision_label_{window}` 的规则必须简单明确：只要该窗口内任一采样帧的最小 clearance `<= 0`，即为 `1`；否则为 `0`。

## 失败边界

| 失败 | 默认处理 | 输出 |
| --- | --- | --- |
| 轨迹为空 | dataset build error | `OFFLINE_LABEL_E_EMPTY_TRAJECTORY` |
| frame 缺失或同一 episode 时间不单调 | dataset build error | `OFFLINE_LABEL_E_MISSING_FRAME` |
| 某帧 crane_id 与 `CraneConfig[]` 不匹配 | dataset build error | `OFFLINE_LABEL_E_CRANE_ID_MISMATCH` |
| 重复 crane_id 或重复 frame/crane 行 | dataset build error | `OFFLINE_LABEL_E_DUPLICATE_TRAJECTORY_ROW` |
| 配置窗口非法 | dataset build error | `OFFLINE_LABEL_E_INVALID_WINDOW` |
| 几何字段缺失或非法数值 | dataset build error | `OFFLINE_LABEL_E_INVALID_GEOMETRY` |
| 生成标签但正样本比例过低 | dataset build warning | `OFFLINE_LABEL_W_LOW_POSITIVE_RATIO` |

失败不得修改已完成 episode 的轨迹、命令或任务状态。

## 权威来源

若本文档与根目录 `目标.md` 或总方案冲突，以 `目标.md` 中 Module K 背景、K.1-K.5、0.7.2、0.7.3、0.7.5 和本轮硬性约束为准，并同步修订本文档。
