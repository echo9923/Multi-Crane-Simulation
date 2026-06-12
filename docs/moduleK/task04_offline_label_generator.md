# Task 04：Offline Label Generator

## 任务目标

实现完整离线标签生成器，按 episode 遍历所有帧和所有塔吊对，产出符合 K.2 字段要求的 `OfflineRiskLabel` 列表，并支持批量 episode 处理。

## 范围：做什么 / 不做什么

做：

- 在 `backend/app/sim/offline_label.py` 中实现 `OfflineLabelGenerator`。
- 定义内存输入对象 `OfflineTrajectoryFrame` 和 `OfflineEpisodeInput`，或使用等价 typed dict/Pydantic schema。
- 校验 episode 轨迹完整性：非空、frame 连续、time 单调、每帧 crane_id 与 `CraneConfig[]` 完全匹配。
- 遍历每一帧、每一对塔吊，调用 Task 02 计算当前几何距离。
- 为每个 pair 构造完整时序，再调用 Task 03 计算每个当前帧的所有未来窗口标签。
- 组装 `OfflineRiskLabel`，填充 K.2 的显式 5s/10s 字段和通用 `future_window_labels`。
- 支持 `generate_many()` 批量处理多个 episode，并输出 `OfflinePairRiskRecord` 或 labels 列表。
- 对错误输入抛出 `OfflineLabelError`，错误分类为 dataset build error。

不做：

- 不读取真实文件路径，不打开 Parquet；L 或调用方负责把文件读成轨迹输入。
- 不写 `pair_risks.parquet`。
- 不构造 dataset window，不切分 train/val/test。
- 不调用 LLM、scheduler、controller、safety pipeline。
- 不修改 episode 原始轨迹。

## 接口与数据结构（签名级别）

建议输入 schema：

```python
class OfflineTrajectoryFrame(RiskBaseModel):
    schema_version: str = OFFLINE_LABEL_SCHEMA_VERSION
    episode_id: str
    frame: int = Field(ge=0)
    time_s: float = Field(ge=0)
    crane_states: list[CraneState]
```

```python
class OfflineEpisodeInput(RiskBaseModel):
    schema_version: str = OFFLINE_LABEL_SCHEMA_VERSION
    episode_id: str
    scenario_id: str | None = None
    trajectory_frames: list[OfflineTrajectoryFrame]
    crane_configs: list[CraneConfig]
    risk_config: RiskConfig
    online_risks: list[OnlineRisk] = Field(default_factory=list)
```

生成器：

```python
class OfflineLabelGenerator:
    def __init__(self, *, future_windows_s: Sequence[float] | None = None) -> None:
        ...

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

    def generate_pair_records(
        self,
        *,
        episode_id: str,
        trajectory_frames: Sequence[OfflineTrajectoryFrame],
        crane_configs: Sequence[CraneConfig],
        risk_config: RiskConfig,
        scenario_id: str | None = None,
    ) -> list[OfflinePairRiskRecord]:
        ...

    def generate_many(
        self,
        *,
        episodes: Sequence[OfflineEpisodeInput],
    ) -> list[OfflinePairRiskRecord]:
        ...
```

`from_config()` 提取顺序：

```text
if config has .risk.future_windows_s:
    use config.risk.future_windows_s
elif config has .future_windows_s:
    use config.future_windows_s
else:
    use None and defer to each risk_config.future_windows_s
```

完整生成流程：

```text
1. validate trajectory frames and crane config ids
2. sorted crane ids -> all unordered pairs
3. for every frame:
     for every pair:
       compute_pair_geometry_distances()
       append OfflinePairGeometryDistanceAtTime to pair series
4. for every pair series:
     for every frame index:
       compute_future_window_labels()
       build OfflineRiskLabel
5. return labels sorted by (episode_id, frame, crane_i, crane_j)
```

## 前置依赖

- Task 01 的 `OfflineRiskLabel`、`OfflinePairRiskRecord`、错误码和 `RiskConfig.future_windows_s`。
- Task 02 的 `compute_pair_geometry_distances()`。
- Task 03 的 `compute_future_window_labels()`。
- `CraneState`、`CraneConfig`、`RiskConfig`。
- `itertools.combinations` 用于稳定 pair 遍历。

## 验收标准（具体、可测试）

- 两台塔吊、3 帧轨迹生成 3 条 label。
- 三台塔吊、4 帧轨迹生成 `4 * 3 = 12` 条 label。
- labels 排序稳定：先 frame，再 `crane_i`，再 `crane_j`。
- 每条 label 的 `pair_id` 稳定为排序后的 `C1-C2`。
- 每条 label 的 `used_future_truth=True`。
- 每条 label 同时包含显式 5s/10s 字段和 `future_window_labels`。
- 当 `risk_config.future_windows_s` 包含 15s 时，`future_window_labels["15s"]` 存在。
- `min_clearance_future_5s_m` 与 `future_window_labels["5s"].min_clearance_future_m` 一致。
- 轨迹为空抛出 `OFFLINE_LABEL_E_EMPTY_TRAJECTORY`。
- 缺失 frame 或 frame 不连续抛出 `OFFLINE_LABEL_E_MISSING_FRAME`。
- time_s 非单调抛出 `OFFLINE_LABEL_E_MISSING_FRAME`。
- 某帧缺失某台塔吊或出现未知 crane_id 抛出 `OFFLINE_LABEL_E_CRANE_ID_MISMATCH`。
- 同一帧重复 crane_id 抛出 `OFFLINE_LABEL_E_DUPLICATE_TRAJECTORY_ROW`。
- `generate_many()` 不混淆不同 episode 的 labels。
- 可选 `online_risks` 不影响 label 数值；只保留给 Task 05 报告对比扩展。

## 测试要点（正常 + 边界 + 异常）

- 正常：两塔距离逐步减少，验证每帧未来窗口最小值。
- 正常：多塔三对同时生成，验证数量和 pair 排序。
- 正常：`future_windows_s=[5, 10, 15]` 时输出三个窗口。
- 边界：只有一帧轨迹时，未来窗口只包含当前帧。
- 边界：只有一台塔吊时，labels 为空但不报错；报告阶段 sample_count 为 0。
- 异常：空 trajectory。
- 异常：frame 0 后直接 frame 2。
- 异常：某帧 `C1/C3`，配置为 `C1/C2`。
- 异常：同一帧两个 `C1`。
- 防泄漏：生成器模块不得导入 `backend.app.sim.prompt_builder`、operator orchestrator 或 observation builder。

## 依赖关系

依赖 Task 01-03。Task 05 消费本任务生成的 labels；Task 06 将本任务作为主要端到端验收对象。
