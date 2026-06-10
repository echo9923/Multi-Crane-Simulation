# Task 06：模块 B 测试与验收

## 任务目标

为模块 B 建立可执行的测试清单和验收标准，确保型号库、载重曲线、manual layout、`CraneConfig` resolution、auto layout 和 reachability precheck 满足 v0.4 合同。

权威来源：`群塔LLM仿真系统开发方案_v0.4_完整版.md` 中 `0.8.3`、`0.8.13`、`0.8.14`、`模块 B`、`12 M0/M1` 和 `15.2/15.3`。

## 任务范围

本任务定义：

- 单元测试。
- 合同测试。
- deterministic 测试。
- startup error 测试。
- 文档验收。
- 模块 B M0/M1 退出条件。

本任务不要求实现：

- 模块 C 物理积分测试。
- 模块 I controller 测试。
- 模块 D task state machine 测试。
- 模块 H/K 风险距离测试。
- 模块 L recorder 文件写入测试。
- 前端 visual smoke。

## 建议测试文件

```text
backend/app/tests/test_crane_model.py
backend/app/tests/test_manual_layout.py
backend/app/tests/test_crane_config_resolution.py
backend/app/tests/test_auto_layout.py
backend/app/tests/test_layout_reachability.py
backend/app/tests/test_layout_errors.py
```

建议 fixtures：

```text
backend/app/tests/fixtures/configs/
  scenario_manual_valid.yaml
  scenario_manual_base_out_of_boundary.yaml
  scenario_manual_base_inside_forbidden.yaml
  scenario_manual_duplicate_crane_id.yaml
  scenario_manual_unknown_model.yaml
  scenario_auto_low_overlap.yaml
  scenario_auto_high_overlap.yaml
  scenario_auto_impossible.yaml
```

## M0 必测场景

型号库测试：

- 内置 `generic_flat_top_55m` 可加载。
- YAML 同名型号覆盖内置型号。
- YAML 新型号可新增。
- YAML 重复 `model_id` 失败。
- 型号库合并或 `CraneModelSpec` 语义错误映射为 `LAY_E_003`，不复用 `LAY_E_002`。
- deg/s 和 deg/s² 转换为 rad 单位。
- `capacity_at_radius_t` 同时受 load chart 和 rated moment 限制。
- `is_load_allowed` 与 `capacity_at_radius_t` 一致。

manual layout 测试：

- valid manual layout 通过。
- `len(cranes) != layout.num_cranes` 失败。
- 重复 `crane_id` 失败。
- 未知 `model_id` 失败。
- base 越界失败。
- base 落入 box forbidden zone 失败。
- mast height 超出型号范围失败。
- 两台塔吊 base 距离过近失败。
- `slew.mode=limited` 且没有角度限制时失败。
- 不硬编码 ID，任意合法 `crane_id` 可通过。

`CraneConfig` resolution 测试：

- valid manual layout 生成 `resolved.layout.resolved_cranes`。
- `root = base + mast_height`。
- `hook_h_min_world_m` 和 `hook_h_max_world_m` 符合 cable length 定义。
- `theta_init_deg` 正确转 rad。
- pair diagnostics 数量等于 `N*(N-1)/2`。
- `resolved.layout.layout_diagnostics` 包含 pair diagnostics、warnings 和 `quality_score`。
- `resolved.layout.model_library_snapshot` 存在，或 `resolved_cranes[*].model` 内嵌完整机械参数。
- 修改 crane base 或 mast height 会改变 `resolved_config_hash`。
- 修改最终 `CraneConfig[]` 或布局诊断中的关键布局结果会改变 `resolved_config_hash`。
- resolved output 不包含完整 LLM API key。

错误测试：

- manual layout 几何失败映射为 `LAY_E_002`。
- `LAY_E_002` error object 包含 `schema_version`、`error_code`、`category=startup_error`、`message`、`field_path`、`hint`、`details.reason`。
- `LAY_E_003` error object 包含 `schema_version`、`error_code`、`category=startup_error`、`message`、`field_path`、`hint`、`details.reason` 和 `details.model_id`。
- 布局错误阻止 episode 启动，不能继续创建 `CraneState`。

## M1 必测场景

auto layout 测试：

- 同一 seed + 配置生成同一布局。
- 不同 seed 通常生成不同布局。
- 输出数量等于 `layout.num_cranes`。
- auto layout 复用 Task 03 的 `CraneConfig` factory，不重复实现 root/hook/angle/model snapshot 计算。
- 所有 base 位于 boundary 内。
- 所有 base 不落入 forbidden zone。
- 所有 pair 满足最小塔身距离。
- low/medium/high overlap 有可测差异。
- `height_strategy=mixed` 为默认并可生成混合高度关系。
- `coverage_target=balanced/wide_coverage/dense_overlap` 影响 quality 子分数。
- impossible site 在 `max_sampling_attempts` 内失败并返回 `LAY_E_001`。
- `LAY_E_001` details 包含 `failure_counts_by_reason` 和 seed。

reachability precheck 测试：

- material zone 可达时通过。
- work zone 可达时通过。
- zone 超出所有作业半径时报告不可达。
- load type 最大重量超过半径能力时报告不可承载。
- 不存在的 load type 引用有明确 warning/blocking reason。
- manual layout 调用 precheck 时只产生 warning/report，不生成 `TASK_E_001` 或 `TASK_E_002`。
- precheck 不生成 `Task` 对象和 task runtime 字段。

## 推荐命令

M0 完成后运行：

```bash
pytest backend/app/tests/test_crane_model.py -v
pytest backend/app/tests/test_manual_layout.py -v
pytest backend/app/tests/test_crane_config_resolution.py -v
pytest backend/app/tests/test_layout_errors.py -v
pytest backend/app/tests/test_resolved_config.py -v
```

M1 完成后追加：

```bash
pytest backend/app/tests/test_auto_layout.py -v
pytest backend/app/tests/test_layout_reachability.py -v
```

完整回归：

```bash
pytest backend/app/tests -v
```

## 文档验收命令

文档创建完成后运行：

```bash
find docs/moduleB -maxdepth 1 -name "*.md" -print | sort
```

期望看到：

```text
docs/moduleB/README.md
docs/moduleB/task01_crane_model_spec.md
docs/moduleB/task02_manual_layout_validation.md
docs/moduleB/task03_crane_config_resolution.md
docs/moduleB/task04_auto_layout_generator.md
docs/moduleB/task05_task_reachability_precheck.md
docs/moduleB/task06_tests_and_acceptance.md
```

检查无未完成标记：

```bash
python3 - <<'PY'
from pathlib import Path

patterns = [
    "TB" + "D",
    "TO" + "DO",
    "implement " + "later",
    "fill in " + "details",
    "<un" + "finished",
]
for path in sorted(Path("docs/moduleB").glob("*.md")):
    text = path.read_text(encoding="utf-8")
    for lineno, line in enumerate(text.splitlines(), start=1):
        if any(pattern in line for pattern in patterns):
            print(f"{path}:{lineno}:{line}")
PY
```

期望无输出。

检查关键合同字段：

```bash
rg -n "CraneModelSpec|CraneConfig|capacity_at_radius|LAY_E_001|LAY_E_002|LAY_E_003|resolved_cranes|layout_diagnostics|model_library_snapshot|hook_h_min_world_m|hook_h_max_world_m|overlap_ratio|quality_score" docs/moduleB
```

期望能在对应任务文档中检索到关键合同。

## M0 验收标准

- 能从内置库和 YAML 生成 `CraneModelSpec`。
- `capacity_at_radius_t` 同时实现 chart capacity 和 rated moment 限制。
- `layout.mode=manual` 能输出合法 `CraneConfig[]`。
- manual crane 越界、落入禁区、型号未知、高度非法、塔身过近会 startup failure。
- `resolved.layout.resolved_cranes` 可落盘、可 hash、可供模块 C 使用。
- `resolved.layout.layout_diagnostics` 可落盘、可 hash，并包含 pair diagnostics。
- 最终型号库快照可通过 `resolved.layout.model_library_snapshot` 或 `resolved_cranes[*].model` 复现。
- 不硬编码塔吊数量或 crane ID。
- 不生成 `CraneState`，不做物理积分。
- 所有 M0 测试通过。

## M1 验收标准

- `layout.mode=auto` 能生成合法 `CraneConfig[]`。
- low/medium/high overlap 目标有可测试差异。
- `height_strategy=mixed` 为默认，并能生成符合 mixed 语义的高度关系。
- `coverage_target` 影响质量评分。
- auto layout 失败返回 `LAY_E_001`，诊断信息能定位主要失败约束。
- reachability precheck 能发现明显不可达或天然超载布局。
- 所有 M0 + M1 测试通过。

## 模块 B 退出条件

模块 B M0 可进入模块 C/I/L 的条件：

- Task 01 至 Task 03 的实现测试全部通过。
- `resolved.layout.resolved_cranes` 示例输出包含 N 台塔吊。
- `resolved.layout.layout_diagnostics` 示例输出包含 pair diagnostics。
- 示例 manual 配置至少覆盖 1 台塔吊 M0 smoke，以及 3 台塔吊多塔静态配置。
- layout 错误 `LAY_E_002` 有测试覆盖。
- 型号错误 `LAY_E_003` 有测试覆盖。
- 实现没有调用 physics、controller、task、LLM、risk 或 recorder 运行时逻辑。

模块 B M1 可进入模块 D/H 的条件：

- Task 04 和 Task 05 的实现测试全部通过。
- layout 错误 `LAY_E_001` 有测试覆盖。
- auto layout demo 至少覆盖 3 台塔吊。
- diagnostics 包含 overlap、height、coverage、quality 和 failure counts。
- reachability precheck 能为 task generator 提供明确可达/不可达报告。
