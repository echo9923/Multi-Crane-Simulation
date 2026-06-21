# Curated Scenario Mode

当前阶段先暂停通用场景生成和 auto layout 的扩展，把重点收敛到 3 个手工高楼密集多塔吊吊运 demo。原因很直接：现在最需要证明的是任务链路稳定、前端能清楚地 3 选 1、`manual_tasks` 能在启动前被校验、真实运行能生成可观察的任务队列和 3D 过程。通用生成器后续还会回来，但在它能稳定理解高楼、楼面、材料堆场、塔吊支承高度和任务可达性之前，curated/manual scenes 更适合作为产品演示和回归基准。

这 3 个场景都采用：

- `layout.mode: manual`：塔吊位置、高度、初始角度由配置显式给出。
- `tasks.generation_mode: manual`：任务不随机抽样，而是通过 `manual_tasks` 固定定义。
- `tasks.assignment_mode: per_crane_queue`：每条任务显式绑定 `crane_id`，用于验证每台塔吊的任务队列能稳定生成。
- `/scenarios/validate`：启动前做配置解析、resolved config、手工任务可达性和任务生成预检。

## 三个场景

| 场景 | 设计目标 | 配置文件 |
| --- | --- | --- |
| `curated_dense_highrise_ground` | 地面 4 台塔吊服务密集高楼组，验证纯地面塔吊、多楼栋、多楼层卸货的稳定链路。 | `configs/curated_dense_highrise_ground.yaml` |
| `curated_elevated_crane_transfer` | 地面塔吊先把材料送到裙楼屋面，再由高位塔吊服务主塔楼，验证中转平台和高位塔吊任务。 | `configs/curated_elevated_crane_transfer.yaml` |
| `curated_complex_cross_lifting` | 5 台塔吊覆盖复杂高层综合体，包含地面塔吊、裙楼高位塔吊和北塔中部平台塔吊，验证交叉吊运和高重叠区域。 | `configs/curated_complex_cross_lifting.yaml` |

## 场景 1：curated_dense_highrise_ground

这个场景模拟 3 栋高层建筑：`tower_a`、`tower_b`、`tower_c`。`tower_a` 和 `tower_b` 是主要楼面作业对象，`tower_c` 提供屋面吊运目标，整体是一个高楼密集、塔吊覆盖区重叠明显的地面施工场景。

塔吊全部布置在地面：

- `C1`：西南侧地面塔吊，主要服务 `tower_a`。
- `C2`：东南侧地面塔吊，主要服务 `tower_b`。
- `C3`：西北侧地面塔吊，覆盖 `tower_c` 屋面和西侧材料场。
- `C4`：东北侧地面塔吊，覆盖 `tower_b` 高层楼面。

取货点 `material_zones` 包括：

- `ground_yard_west`：西侧地面堆场，支持钢筋捆和模板。
- `truck_bed_south`：南侧货车平台，支持钢筋捆和机电箱。
- `ground_yard_east`：东侧地面堆场，支持模板和机电箱。

卸货点 `work_zones` 包括 `tower_a_floor_10`、`tower_a_floor_15`、`tower_b_floor_12`、`tower_b_floor_18`、`tower_c_roof`，覆盖 10 层、15 层、12 层、18 层和屋面高度。`manual_tasks` 为 4 台塔吊各安排 2 条任务，总计 8 条，包含 `easy_task` 和 `overlap_task`，用于观察地面塔吊在高密度楼栋之间的连续取放、转臂和任务切换。

## 场景 2：curated_elevated_crane_transfer

这个场景模拟主塔楼、裙楼和东塔组成的工地。它的核心不是单次从地面直达所有楼层，而是把裙楼屋面作为临时中转平台：地面塔吊把材料送上 `podium_roof_storage`，高位塔吊再从 `podium_staging_roof` 吊运到主塔楼高层。

塔吊布置分为地面和高位平台：

- `C1_ground_west`：地面西侧塔吊，`baseZ = 0`。
- `C2_ground_east`：地面东侧塔吊，`baseZ = 0`。
- `C3_podium_roof`：裙楼屋面塔吊，`baseZ = 28.8`。

取货点 `material_zones` 包括：

- `ground_yard_west`：地面西侧堆场。
- `truck_bed_east`：东南侧货车平台。
- `podium_staging_roof`：裙楼 8 层屋面临时平台，同时作为高位塔吊的取货点。

卸货点 `work_zones` 包括：

- `podium_roof_storage`：裙楼屋面卸货/中转区。
- `main_tower_floor_18`、`main_tower_floor_24`、`main_tower_roof`：主塔楼 18 层、24 层和屋面。
- `east_tower_floor_12`：东塔 12 层。

`manual_tasks` 中，`C1_ground_west` 和 `C2_ground_east` 负责地面到裙楼屋面或东塔中层的任务，`C3_podium_roof` 负责从裙楼临时平台到主塔楼高层的任务。这个场景重点验证高位取货面、高位卸货面、转运链路和 `baseZ > 0` 塔吊的任务可达性。

## 场景 3：curated_complex_cross_lifting

这个场景是 3 个 demo 中最复杂的一组：包含 `north_tower`、`south_tower`、`east_tower`、`west_tower` 和 `central_podium`，并设置 5 台塔吊覆盖多个相互重叠的作业区。它用于展示复杂高层综合体里的交叉吊运、屋面任务、中转平台和高位平台塔吊。

塔吊布置分为：

- 地面塔吊：`C1_west_ground`、`C2_east_ground`、`C3_south_ground`，三台塔吊的 `baseZ = 0`。
- 高位塔吊：`C4_podium_high` 位于中央裙楼屋面，`baseZ = 28.8`；`C5_north_high_platform` 位于北塔中部平台，`baseZ = 57.6`。

取货点 `material_zones` 包括：

- `west_ground_yard`、`east_ground_yard`：东西两侧地面堆场。
- `south_truck_bed`：南侧货车平台。
- `podium_roof_staging`：中央裙楼屋面临时平台。
- `north_mid_staging`：北塔 16 层附近的中部临时平台。

卸货点 `work_zones` 包括：

- `west_tower_floor_12`、`east_tower_floor_18`、`east_tower_roof`。
- `south_tower_floor_14`。
- `north_tower_floor_20`、`north_tower_roof`。
- `central_podium_roof`。

`manual_tasks` 总计 12 条，任务数量有意超过 `num_cranes * num_tasks_per_crane` 的提示值，用来覆盖更丰富的交叉吊运组合。`C1` 和 `C2` 分别服务东西两侧地面堆场到对应塔楼，`C3` 聚焦南侧货车平台到 `south_tower_floor_14` 的地面塔吊任务，`C4` 负责从 `podium_roof_staging` 向北塔和东塔高层吊运，并承担 `south_truck_bed -> podium_roof_staging` 的中转卸货任务，`C5` 从北塔中部平台向北塔高层和屋面吊运。这个场景适合作为复杂演示和 manual task validation 的强覆盖样例。

## 关于 baseZ > 0

`baseZ > 0` 的塔吊是人工设定的高位平台/楼面支承塔吊，用于仿真调度、任务队列、吊钩高度、半径可达性和 3D 表达。它不代表完整结构支承校验，也不代表已经计算了附着、基础、楼面承载、抗倾覆、施工方案审批等工程安全问题。

因此：

- `baseZ = 0` 表示地面塔吊。
- `baseZ > 0` 表示仿真中把塔吊基座放在指定楼面或临时平台高度。
- 当前校验关注调度可达性：半径、吊钩高度、载荷能力、取卸货区和载荷类型是否匹配。
- 结构支承、附着体系和施工安全专项方案不在本阶段仿真合同内。

## 前端运行流程

在桌面工作台或 Vite 开发前端中，推荐按下面顺序运行 curated demo：

1. 进入场景页，选择三个 curated 场景之一：`curated_dense_highrise_ground`、`curated_elevated_crane_transfer`、`curated_complex_cross_lifting`。普通用户入口只展示这三个场景。
2. 进入 API Key 页面，选择真实 provider（DeepSeek、MiniMax 或 SiliconFlow），输入 API Key 并保存到本机 secret store。真实 API Key 不写入 YAML，也不通过环境变量作为普通运行入口。
3. 测试连接。对真实 provider 使用“测试连接”确认 `/models` 可访问、Key 有效、Base URL 正确。
4. 在 API Key 页面执行“校验场景”。校验通过后应能看到 `valid: true`，并在后端响应中包含 `resolved_config_hash` 和手工任务校验结果。
5. 进入运行页启动运行。前端运行页会以 `interactive_server` + `production` + `autostart` 启动 episode，随后可进入 3D 观察页面实时观察塔吊运动、任务状态、风险/事件面板和运行输出，也可以在离线回放模式加载已有 episode 数据。

## 检查任务可达性

`POST /scenarios/validate` 是启动前的权威检查入口。对于 `tasks.generation_mode: manual` 的场景，后端会返回 `manual_task_validation`，内容包括：

- `valid`：手工任务计划是否可用。
- `task_count`：实际 `manual_tasks` 数量。
- `expected_task_count`：由 `num_cranes * num_tasks_per_crane` 推导出的提示数量。
- `task_reports`：每条任务的取货/卸货可达性、半径、高度、载荷余量和 blocking reasons。
- `warnings`：例如实际任务数量和提示数量不一致。
- `blocking_reasons`：全局去重后的阻塞原因。

常见 `blocking_reasons` 含义：

- `invalid_task_assignment`：manual task 没有绑定有效 `crane_id`。
- `unknown_crane_id`：任务引用的塔吊不存在。
- `unknown_pickup_zone` / `unknown_dropoff_zone`：取货点或卸货点 ID 不存在。
- `unknown_load_type`：载荷类型未在 `load_types` 中定义。
- `pickup_load_type_not_supported`：取货区不支持该载荷类型。
- `dropoff_load_type_not_accepted`：卸货区不接受该载荷类型。
- `pickup_out_of_radius` / `dropoff_out_of_radius`：取货点或卸货点超出该塔吊小车半径范围。
- `pickup_out_of_hook_height` / `dropoff_out_of_hook_height`：取货点或卸货点超出吊钩高度范围。
- `load_over_capacity`：载荷在取货或卸货半径下超过塔吊载荷能力。

如果校验失败，不应先改前端展示；应先修 YAML 中的塔吊位置、`baseZ`、`mast_height_m`、取卸货区高度、载荷类型或任务绑定。目标是让启动前失败变成清晰的配置问题，而不是运行后才出现空任务队列或不可解释的静止画面。

## 旧 deepseek_demo_4x2_manual.yaml 的定位

`configs/deepseek_demo_4x2_manual.yaml` 可以继续保留为 stress/demo 和历史回归样例，但它不代表真实工地基准。它早期更偏向验证 DeepSeek 调用、4 台塔吊、2 条任务队列和运行/录制链路；几何布局有较强 demo/stress 属性，不应作为“高楼密集真实施工组织”的主要样板。

当前对外演示和手工场景回归应优先使用这 3 个 curated 场景。旧 demo 可以用于比较、压力测试、兼容性验证或复现历史问题。

## 后续计划

后续可以在 curated mode 稳定之后再扩展通用能力：

- deterministic task generation：从固定 seed、场景语义和可达性约束生成可复现任务，而不是完全手写每条 `manual_tasks`。
- auto layout：让塔吊候选位置、高度、覆盖范围和重叠等级自动生成，但必须先经过和 curated 场景同级别的可达性预检。
- general scene generator：根据楼栋、边界、材料区、卸货区和塔吊数量生成通用高楼工地场景。
- 更强的验证报告：把 `manual_task_validation` 中的失败任务、半径、高度和载荷余量直接映射到前端 UI，帮助用户知道该改哪个 zone 或 crane。
- 工程语义扩展：如果以后要表达真实支承体系，需要新增结构校验模型，而不是把当前 `baseZ` 调度高度解释成工程安全结论。
