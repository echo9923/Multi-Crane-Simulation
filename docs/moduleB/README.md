# 模块 B：塔吊布局与型号库模块任务索引

## 为什么下一个做模块 B

模块 A 已经完成配置 schema、加载、resolve、run workspace、密钥治理和 startup error。下一个最小可运行链路是 M0 的：

```text
ResolvedConfig -> CraneModelSpec -> CraneConfig -> CraneState
```

其中 `CraneModelSpec` 和 `CraneConfig` 的权威归属在模块 B。没有模块 B，模块 C 的运动学、模块 I 的 controller、模块 L 的 trajectories/visual frames 都缺少稳定的静态塔吊参数输入。

因此下一个模块应完成模块 B 的 M0 子集，并为 M1 的 auto layout 留出清晰边界。

## 模块目标

模块 B 负责把模块 A 解析出的配置输入转换为可仿真的塔吊静态配置：

- 加载内置通用塔吊型号库。
- 合并 YAML 中的型号覆盖或新增型号。
- 生成 `CraneModelSpec`，并提供 `capacity_at_radius` / 力矩限制计算。
- 在 `layout.mode=manual` 时校验手写塔吊布局。
- 输出标准化 `CraneConfig[]` 和布局诊断信息。
- 在 `layout.mode=auto` 时提供自动布局生成器，M1 完成完整实现。

权威来源为项目根目录下的 `群塔LLM仿真系统开发方案_v0.4_完整版.md`。若本目录文档与该方案冲突，以方案中 `0.5.3`、`0.5.13`、`0.7`、`0.8`、`模块 B`、`12` 和 `15.2/15.3` 的合同约定为准，并同步修订本目录文档。

## 分阶段边界

模块 B 横跨 M0 和 M1：

- M0 必须完成：型号库、`CraneModelSpec`、载重/力矩函数、manual layout 校验、`CraneConfig[]` 输出、resolved config 对接。
- M1 必须完成：auto layout、overlap 目标、coverage 目标、任务可达性预检查、布局质量评分和采样诊断。

当前下一个开发模块建议先实现 Task 01-03 和 Task 06，作为 M0 的模块 B 交付；Task 04-05 作为同一模块的 M1 扩展任务。

## 模块边界

模块 B 的输入：

- `ScenarioConfig`
- `seeds.layout`
- `scenario.crane_models`
- `scenario.layout`
- `scenario.cranes`
- `scenario.site.boundary`
- `scenario.site.forbidden_zones`
- `scenario.tasks` 中用于 M1 auto layout 预检查的配置入口

模块 B 的输出：

- `CraneModelSpec`
- `CraneConfig`
- `CranePairLayoutDiagnostic`
- `LayoutDiagnostics`
- `resolved.layout.resolved_cranes`
- `resolved.layout.layout_diagnostics`
- `resolved.layout.model_library_snapshot` 或 `resolved_cranes[*].model` 内嵌型号快照
- `resolved.layout.auto_params` 或 `resolved.layout.manual_cranes`

模块 B 不允许做的事情：

- 不积分或更新 `CraneState`。
- 不把 joystick、LLM command 或 rule command 转成速度。
- 不生成任务点或任务队列。
- 不推进任务状态机。
- 不计算 online/offline 风险标签。
- 不写 trajectories、events、frames 或 summary。
- 不调用真实 LLM。

## 拥有对象

模块 B 拥有并写入：

- `CraneModelSpec`
- `CraneConfig`
- 型号库合并结果
- manual layout validator
- auto layout generator
- 布局诊断对象
- `LAY_*` 布局和型号错误

模块 B 只读取或接收接口，不拥有：

- `ScenarioConfig`、`ExperimentConfig`、`ResolvedConfig` 的配置 schema 定义，归模块 A。
- `CraneState`，归模块 C。
- `Task`，归模块 D。
- `ControlTarget`，归模块 I。
- `OnlineRisk` / `OfflineRiskLabel`，归模块 H/K。
- `SimFrame`、`EpisodeSummary`、导出文件，归模块 L/J。

## 任务顺序

| 顺序 | 文档 | 阶段 | 目标 |
|---|---|---|---|
| 1 | [task01_crane_model_spec](task01_crane_model_spec.md) | M0 | 定义 `CraneModelSpec`、内置型号库、YAML 覆盖和 `capacity_at_radius` |
| 2 | [task02_manual_layout_validation](task02_manual_layout_validation.md) | M0 | 校验 manual crane 是否可成为合法 `CraneConfig` |
| 3 | [task03_crane_config_resolution](task03_crane_config_resolution.md) | M0 | 提供 manual/auto 共用 `CraneConfig[]` 实例化出口、hook 高度边界和布局诊断 |
| 4 | [task04_auto_layout_generator](task04_auto_layout_generator.md) | M1 | 实现 auto layout 采样、约束过滤、重叠目标和质量评分 |
| 5 | [task05_task_reachability_precheck](task05_task_reachability_precheck.md) | M1 | 为 auto layout 与后续任务生成提供 zone 可达性和载重预检查 |
| 6 | [task06_tests_and_acceptance](task06_tests_and_acceptance.md) | M0/M1 | 定义模块 B 的单元测试、合同测试和退出条件 |

## 全局实现约束

- `CraneModelSpec` 是塔吊型号参数的唯一事实源。
- `CraneConfig` 是单台塔吊静态配置的唯一事实源，运行中不可变。
- `ScenarioConfig.crane_models` 是配置输入，不等同于最终型号库；必须先与内置库合并并校验。
- `ManualCraneLayoutInput` 是配置输入，不等同于 `CraneConfig`；manual 几何校验在模块 B 完成。
- 内部角度统一使用 rad，配置输入可使用 deg。
- 坐标系统一为 ENU：x East、y North、z Up。
- `theta=0` 指向 +x，正方向为从 +x 朝 +y 逆时针。
- `hook_h_m` 表示吊钩世界高度，不是绳长。
- `cable_length_m = root_z - hook_h_m`。
- `layout.num_cranes` 和 manual `cranes` 列表必须支持 N 台塔吊，不能硬编码 C1/C2/C3。
- 同一 seed 和同一配置必须生成确定性的 auto layout。
- manual layout 失败返回 `LAY_E_002` startup error。
- auto layout 在 `max_sampling_attempts` 内失败返回 `LAY_E_001` startup error。
- 塔吊型号库合并或 `CraneModelSpec` 语义校验失败返回 `LAY_E_003` startup error，不复用 `LAY_E_002`。

## M0 最小交付结果

完成 Task 01、Task 02、Task 03 和 Task 06 的 M0 部分后，后续模块应能：

1. 从内置库和 YAML 覆盖生成稳定 `CraneModelSpec`。
2. 对任意半径计算 `capacity_at_radius_t`。
3. 校验 manual crane 的型号、边界、禁区、塔身间距和高度范围。
4. 输出可供模块 C 初始化 `CraneState` 的 `CraneConfig[]`。
5. 把 `CraneConfig[]` 写回 resolved layout。
6. 把布局诊断和最终型号库快照写回 resolved layout，保证可落盘、可 hash、可复现。
7. 对失败场景给出稳定、可测试的 `LAY_*` startup error。

## M1 完整交付结果

完成 Task 04、Task 05 和 Task 06 的 M1 部分后，模块 B 应能：

1. 根据 `layout.mode=auto` 自动生成 N 台塔吊布局。
2. 支持 `overlap_level=low/medium/high`。
3. 支持 `height_strategy=staggered/same_level/mixed`，默认 mixed。
4. 支持 `coverage_target=balanced/wide_coverage/dense_overlap`。
5. 输出 pair overlap、root distance、height delta、quality score 和采样失败诊断。
6. 对 material/work zones 做任务可达性预检查，但不生成具体 `Task`。
