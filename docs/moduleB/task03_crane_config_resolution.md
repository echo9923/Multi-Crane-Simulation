# Task 03：CraneConfig 统一实例化与 Resolved Layout 对接

## 任务目标

把通过 Task 01/Task 02 校验的 manual 布局输入，或 Task 04 采样出的 auto 布局候选，转换为最终可仿真的 `CraneConfig[]`，并写入 `ResolvedConfig.layout.resolved_cranes`。

本任务是模块 B 的统一出口。M0 至少接通 manual 来源；M1 的 auto layout 也必须复用本任务的 `CraneConfig` 实例化逻辑。模块 C 初始化 `CraneState` 时，应只读取 `CraneConfig`，不再回头解释 YAML 输入。

权威来源：`群塔LLM仿真系统开发方案_v0.4_完整版.md` 中 `0.5.2`、`0.5.3`、`0.5.13`、`0.7.2`、`模块 B` 和 `15.2`。

## 任务范围

本任务实现：

- `CraneConfig` schema。
- manual/auto 共用的 `CraneConfig` factory，例如 `create_crane_config(...)` 或 `build_crane_configs(...)`。
- 从 manual layout 输入实例化 `CraneConfig[]`。
- 为 Task 04 提供 auto layout 候选转 `CraneConfig[]` 的统一入口。
- 计算 `root_position`、`hook_h_min_world_m`、`hook_h_max_world_m`。
- 计算初始 `theta_init_rad`、`theta_sin`、`theta_cos`。
- 写入 `resolved.layout.resolved_cranes`。
- 生成 pair-level layout diagnostics。
- 写入 `resolved.layout.layout_diagnostics`。
- 写入 `resolved.layout.model_library_snapshot` 或在 `resolved_cranes` 中内嵌足够完整的型号参数快照。
- 确保 resolved config hash 因最终 `CraneConfig[]` 变化而变化。

本任务不实现：

- `CraneState` 运行时字段，如 `theta_dot_rad_s`、`trolley_v_m_s`、`load_attached`。
- 物理 step。
- controller。
- trajectories/visual frames 导出。
- auto layout 采样。

## 建议代码位置

```text
backend/app/schemas/crane.py
backend/app/sim/layout.py
backend/app/core/config_resolver.py
backend/app/tests/test_crane_config_resolution.py
```

如果不新增 `schemas/crane.py`，也可以把 schema 放在 `backend/app/sim/layout.py`，但后续模块会共同依赖 `CraneConfig`，建议独立文件。

## 数据结构

`CraneConfig` 至少包含：

```text
schema_version: str
crane_id: str
model_id: str
model: CraneModelSpec or model payload
base: [float, float, float]
root: [float, float, float]
mast_height_m: float
jib_length_m: float
counter_jib_length_m: float
trolley_r_min_m: float
trolley_r_max_m: float
hook_h_min_world_m: float
hook_h_max_world_m: float
cable_length_min_m: float
cable_length_max_m: float
theta_init_rad: float
theta_init_deg: float
slew_mode: "continuous" | "limited"
theta_limit_rad: optional [float, float]
source: "manual" | "auto"
```

说明：

- `model` 可以内嵌完整 `CraneModelSpec`，也可以只保存 `model_id` 并在同一 resolved layout 中保存型号库快照。M0 推荐内嵌必要机械参数，保证 run artifact 可复现。
- `hook_h_min_world_m = max(site.boundary.z_min, root_z - cable_length_max_m)`。
- `hook_h_max_world_m = root_z - cable_length_min_m`。
- `hook_h_max_world_m` 不得超过 `root_z`。
- `trolley_r_max_m` 必须不超过 `jib_length_m`。
- M0 若 `slew_mode="limited"` 且输入 schema 不含 `theta_limit_deg`，必须由 Task 02 拦截；Task 03 不接受没有 `theta_limit_rad` 的 limited `CraneConfig`。

## LayoutDiagnostics

pair-level diagnostic 至少包含：

```text
crane_id_a
crane_id_b
root_distance_m
base_distance_m
height_delta_m
work_radius_overlap_area_m2
work_radius_union_area_m2
overlap_ratio
```

layout-level diagnostic 至少包含：

```text
mode
num_cranes
quality_score
pair_diagnostics
warnings
```

M0 manual 模式可使用简单 `quality_score`：

```text
quality_score = clamp(1.0 - average_overlap_penalty - height_conflict_penalty, 0.0, 1.0)
```

如果暂不实现完整 score，必须仍输出结构化 diagnostics，并把 `quality_score` 设为可解释默认值，例如 `null` 或 `1.0`。推荐使用 `null`，避免误导。

## ResolvedConfig 对接

当前 `backend/app/schemas/resolved_config.py` 已有：

```text
ResolvedLayoutConfig.mode
ResolvedLayoutConfig.auto_params
ResolvedLayoutConfig.manual_cranes
ResolvedLayoutConfig.resolved_cranes
ResolvedLayoutConfig.layout_diagnostics
ResolvedLayoutConfig.model_library_snapshot
```

其中 `layout_diagnostics` 和 `model_library_snapshot` 需要由本任务新增到 `backend/app/schemas/resolved_config.py`。`layout_diagnostics` 必须是可 JSON 序列化结构，并参与 `resolved_config_hash`。`model_library_snapshot` 可选；如果每个 `resolved_cranes[*].model` 已内嵌完整 `CraneModelSpec`，可以省略，但必须保证 run artifact 不依赖运行时内置库变化才能复现。

Task 03 应修改模块 A 的 `_resolve_layout` 对接方式，但保持边界清晰：

- 模块 A 仍负责基础 `ResolvedConfig` 构造。
- 模块 B 提供 pure function，例如 `resolve_layout_config(scenario_config, seeds.layout)`。
- `config_resolver.resolve_config()` 调用模块 B 函数生成 `ResolvedLayoutConfig`。
- `layout.mode=manual` 时 `manual_cranes` 保留原始 manual 输入摘要，`resolved_cranes` 保存最终 `CraneConfig[]`。
- `layout.mode=auto` 在 M0 可继续不生成 `resolved_cranes`，但如果 M0 runner 只支持 manual，应在启动前给出清楚错误或使用 manual fixture。
- `layout.mode=auto` 在 M1 必须调用 Task 04 生成候选布局，并复用本任务 factory 写入 `resolved_cranes` 和 `layout_diagnostics`。

## 输入与输出

输入：

- `ScenarioConfig`
- `dict[str, CraneModelSpec]`
- manual layout validation result
- `seeds.layout`

输出：

- `CraneConfig[]`
- `LayoutDiagnostics`
- `model_library_snapshot` 或内嵌在 `CraneConfig.model` 的型号参数快照
- 更新后的 `ResolvedLayoutConfig`

失败输出：

- `LAY_E_002` manual layout 无法实例化。
- `CFG_E_003` 仅用于 hash 不可计算，不应用来表达布局失败。

## 测试要求

建议测试文件：

```text
backend/app/tests/test_crane_config_resolution.py
```

必测场景：

- valid manual scenario 生成 `resolved.layout.resolved_cranes`。
- `resolved_cranes` 数量等于 `layout.num_cranes`。
- `CraneConfig.root == [base_x, base_y, base_z + mast_height_m]`。
- `theta_init_deg=90` 时 `theta_init_rad` 约等于 `pi/2`。
- `theta_sin/theta_cos` 如保存，则与 `theta_init_rad` 一致。
- `hook_h_min_world_m = root_z - cable_length_max_m`，且不低于 `site.boundary.z_min`。
- `hook_h_max_world_m = root_z - cable_length_min_m`。
- `hook_h_max_world_m <= root_z`。
- `CraneConfig` 内包含载重/速度/行程必要机械参数。
- pair diagnostics 对 N 台塔吊生成 `N*(N-1)/2` 条。
- `resolved.layout.layout_diagnostics` 包含 pair diagnostics、warnings 和 `quality_score`。
- `resolved.layout.model_library_snapshot` 存在，或 `resolved_cranes[*].model` 内嵌完整机械参数。
- resolved config hash 会随 crane base 改变而改变。
- resolved config hash 会随 `mast_height_m` 改变而改变。
- resolved config hash 会随最终 `CraneConfig[]` 或布局诊断中的关键布局结果改变而改变。
- resolved config 中不包含 LLM API key。

推荐命令：

```bash
pytest backend/app/tests/test_crane_config_resolution.py -v
pytest backend/app/tests/test_resolved_config.py -v
```

## 验收标准

- 模块 C 可以仅凭 `CraneConfig[]` 初始化塔吊静态几何。
- `CraneConfig` 不包含任务状态、速度、载荷状态等运行时字段。
- `ResolvedConfig.layout.resolved_cranes` 是稳定、可落盘、可 hash 的 JSON 结构。
- 修改任一关键塔吊静态参数会改变 `resolved_config_hash`。
- 所有角度单位和高度语义与总方案一致。
