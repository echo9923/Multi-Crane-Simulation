# Task 04：Auto Layout 生成器

## 任务目标

实现 `layout.mode=auto` 的正式自动布局生成器。它不能只是随机撒点，而必须执行候选生成、约束过滤、重叠分析、高度策略、coverage 目标和质量评分。

本任务属于模块 B 的 M1 交付，不阻塞 M0 的 manual layout + 运动学骨架，但必须与 Task 01-03 的对象保持同一套出口：最终仍通过 Task 03 的 `CraneConfig` factory 输出 `CraneConfig[]` 和 `LayoutDiagnostics`。

权威来源：`群塔LLM仿真系统开发方案_v0.4_完整版.md` 中 `0.5.3`、`模块 B.2`、`12 M1`、`15.3` 和 `15.8 ISSUE-005`。

## 任务范围

本任务实现：

- deterministic random generator，使用 `seeds.layout`。
- N 台塔吊候选 base 采样。
- site boundary 过滤。
- forbidden zone 过滤。
- 塔身最小距离过滤。
- 型号和 mast height 采样。
- `height_strategy=staggered/same_level/mixed`。
- 作业半径 overlap ratio 计算。
- `overlap_level=low/medium/high` 目标。
- `coverage_target=balanced/wide_coverage/dense_overlap` 目标。
- quality score。
- `max_sampling_attempts` 失败诊断。
- 调用 Task 03 的统一实例化入口输出 auto layout `CraneConfig[]`。

本任务不实现：

- 具体任务点生成。
- 任务队列状态机。
- risk distance 运行时计算。
- controller 或 physics。
- dataset 采样策略。

## 建议代码位置

```text
backend/app/sim/auto_layout.py
backend/app/sim/layout_geometry.py
backend/app/tests/test_auto_layout.py
```

几何工具可放在 `layout_geometry.py`，后续模块 H/K 的风险几何不要反向依赖 auto layout 业务逻辑。

## Auto Layout 流程

必须按以下流程实现：

```text
1. 初始化 rng = Random(seeds.layout)
2. 合并 CraneModelSpec 型号库
3. 循环 attempts in 1..max_sampling_attempts:
   3.1 采样 N 台候选 crane model
   3.2 采样 base_x/base_y/base_z
   3.3 校验 boundary
   3.4 校验 forbidden_zones
   3.5 校验 min_base_distance_m
   3.6 根据 height_strategy 采样 mast_height_m
   3.7 调用 Task 03 factory 实例化候选 CraneConfig[]
   3.8 计算 pair overlap diagnostics
   3.9 计算 coverage diagnostics
   3.10 执行任务可达性预检查 hook
   3.11 计算 quality_score
   3.12 如果满足目标，返回 best layout
4. 若失败，返回 LAY_E_001 startup error
```

## 重叠目标

建议初始阈值：

```text
low:
  average_pair_overlap_ratio: 0.05 - 0.20
medium:
  average_pair_overlap_ratio: 0.15 - 0.45
high:
  average_pair_overlap_ratio: 0.35 - 0.75
```

说明：

- overlap ratio 固定采用二维作业圆 `intersection_area / min(area_i, area_j)`，因为它更直接表达较小塔吊作业范围被重叠覆盖的程度。
- diagnostics 可额外输出 `intersection_area / union_area`，但 low/medium/high 阈值和测试只使用 `intersection_area / min(area_i, area_j)`。
- 阈值可以后续根据实际 demo 调整，但必须同步修改文档和测试。

## 高度策略

```text
staggered:
  重叠塔吊高度差尽量 >= min_height_delta_m，推荐 6m。

same_level:
  允许高度接近，高度差可低至 0-3m，但仍须满足型号范围和边界。

mixed:
  默认。部分重叠 pair 满足 staggered，部分 pair 允许接近。
```

`same_level` 不表示违反机械安全；只是允许相近高度，为后续 stress task 创造交互背景。

## Coverage 目标

```text
balanced:
  覆盖和重叠平衡。

wide_coverage:
  更偏向覆盖较大 site / work zone 面积，惩罚过度集中。

dense_overlap:
  更偏向集中布局和高 overlap，但仍不得违反禁区、边界、塔身间距和高度限制。
```

M1 初版可用可解释启发式质量分：

```text
quality_score =
  overlap_target_score * 0.40
  + coverage_target_score * 0.30
  + height_strategy_score * 0.20
  + boundary_margin_score * 0.10
```

每个子分数都应进入 diagnostics，便于调参。

## 失败诊断

`LAY_E_001` details 至少包含：

```text
max_sampling_attempts
attempts
last_failure_reason
failure_counts_by_reason
layout_params
seed
```

`failure_counts_by_reason` 使用稳定英文 key：

```text
base_out_of_boundary
base_inside_forbidden_zone
root_distance_too_small
mast_height_out_of_model_range
overlap_target_not_met
coverage_target_not_met
height_strategy_not_met
task_reachability_precheck_failed
```

## 输入与输出

输入：

- `ScenarioConfig.site`
- `ScenarioConfig.layout`
- `dict[str, CraneModelSpec]`
- `seeds.layout`
- Task 05 的 reachability precheck hook

输出：

- `CraneConfig[]`
- `LayoutDiagnostics`
- auto layout sampling diagnostics
- 更新后的 `resolved.layout.layout_diagnostics`

失败输出：

- `LAY_E_001` startup error。

## 测试要求

建议测试文件：

```text
backend/app/tests/test_auto_layout.py
```

必测场景：

- 同一 seed + 同一配置生成完全相同的 `CraneConfig[]`。
- 不同 seed 通常生成不同布局。
- auto layout 输出数量等于 `layout.num_cranes`。
- auto layout 复用 Task 03 的 `CraneConfig` factory，不重复实现 root/hook/angle/model snapshot 计算。
- 所有 base 位于 boundary 内。
- 所有 base 不落入 forbidden zone。
- 所有 pair 距离满足 `min_base_distance_m`。
- low overlap 的平均 overlap 小于 high overlap。
- `height_strategy=staggered` 时重叠 pair 高度差满足阈值。
- `height_strategy=mixed` 时既允许错层也允许部分接近。
- `coverage_target=wide_coverage` 的 coverage score 高于 dense overlap 同配置倾向。
- `max_sampling_attempts=1` 且 impossible site 时返回 `LAY_E_001`。
- `LAY_E_001` details 包含 `failure_counts_by_reason`。
- 不硬编码 3 台塔吊，测试至少覆盖 `num_cranes=2` 和 `num_cranes=6`。

推荐命令：

```bash
pytest backend/app/tests/test_auto_layout.py -v
```

## 验收标准

- `layout.mode=auto` 不再只是配置形状，而能生成可启动 `CraneConfig[]`。
- 同一 seed 下结果可复现。
- low/medium/high overlap 有可测试差异。
- auto layout 失败信息足够定位是哪类约束导致失败。
- 输出仍走 Task 03 的 `CraneConfig[]`、`LayoutDiagnostics` 和 resolved layout 字段，后续模块不需要关心布局来自 manual 还是 auto。
