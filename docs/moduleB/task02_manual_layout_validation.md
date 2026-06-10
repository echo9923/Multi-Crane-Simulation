# Task 02：Manual Layout 校验

## 任务目标

实现 `layout.mode=manual` 的手写塔吊布局校验，把模块 A 只做形状校验的 `ManualCraneLayoutInput` 进一步判断为可启动或 startup failure。

模块 A 已明确不判断 manual crane 越界、落入 forbidden zone 或几何不可行；这些责任从本任务开始由模块 B 承担。

权威来源：`群塔LLM仿真系统开发方案_v0.4_完整版.md` 中 `0.5.3`、`0.5.13`、`0.7.2`、`0.8.3` 和 `模块 B.3`。

## 任务范围

本任务实现：

- manual crane 数量校验。
- `crane_id` 唯一性校验。
- `model_id` 存在性校验。
- base 坐标位于 site boundary 内。
- base 不落入 forbidden zone。
- mast height 在对应 `CraneModelSpec.mast_height_range_m` 内。
- 塔身之间最小距离校验。
- theta 初始角转换和基础合法性校验。
- `slew.mode` 与型号/配置兼容性校验。
- manual 布局失败映射为 `LAY_E_002`。

本任务不实现：

- 自动布局采样。
- 作业半径 overlap 目标优化。
- 任务点生成。
- 任务可达性/天然超载最终判断。
- 运行时 forbidden zone 进入检测。

## 建议代码位置

```text
backend/app/sim/layout.py
backend/app/tests/test_manual_layout.py
```

如果布局诊断对象较多，可拆出：

```text
backend/app/schemas/layout.py
```

## 输入与输出

输入：

- `ScenarioConfig.site.boundary`
- `ScenarioConfig.site.forbidden_zones`
- `ScenarioConfig.layout`
- `ScenarioConfig.cranes`
- `dict[str, CraneModelSpec]`

输出：

- 通过校验的 manual crane 输入，供 Task 03 实例化 `CraneConfig`。
- manual layout diagnostic。

失败输出：

- `LAY_E_002` startup error。
- `field_path` 指向具体字段，例如 `cranes[0].base`、`cranes[1].model_id`。
- `details.reason` 使用稳定英文值，例如：

```text
duplicate_crane_id
manual_count_mismatch
unknown_model_id
base_out_of_boundary
base_inside_forbidden_zone
mast_height_out_of_model_range
root_distance_too_small
invalid_slew_mode
limited_slew_missing_theta_limit
```

## 校验规则

### 数量

- `layout.mode=manual` 时 `cranes` 必须存在，模块 A 已做基础校验。
- `len(cranes)` 必须等于 `layout.num_cranes`。
- 如果后续决定 manual 模式以 `cranes` 列表长度为准，必须同步修改模块 A 和本文档；当前建议保持二者一致，避免 resolved config 中 N 台数量含糊。

### ID

- `crane_id` 必须唯一。
- `crane_id` 不要求固定为 C1/C2/C3，但推荐测试覆盖任意 ID，如 `TC_A`。
- 模块 B 不负责 operator assignment 的 ID 映射；只保证输出 ID 稳定。

### base 与 boundary

- base 是 `[x, y, z]`。
- `x_min <= x <= x_max`。
- `y_min <= y <= y_max`。
- `z_min <= z <= z_max`。
- 建议 base_z 在 M0 要求等于或高于 boundary.z_min；不在 M0 做地形高度模型。

### forbidden zone

M0 至少支持 `type="box"` 的 forbidden zone base 点检测：

```text
abs(base_x - center_x) <= size_x / 2
abs(base_y - center_y) <= size_y / 2
z_range or box z 覆盖 base_z
```

M0 可暂不支持 polygon point-in-polygon，但必须明确处理：

- 如果 forbidden zone 是 polygon 且实现了 point-in-polygon，则正常校验。
- 如果暂未实现 polygon，测试和错误信息不得假装支持；可以先只对 box 校验，并在 diagnostics 中记录 `unsupported_zone_shape_for_base_check` warning。

M1 auto layout 前应补齐 polygon。

### 塔身最小距离

需要定义最小塔身距离常量或配置入口。M0 建议：

```text
min_base_distance_m = 8.0
```

规则：

- 任意两台塔吊 base 的水平距离必须 `>= min_base_distance_m`。
- 失败字段可指向 `cranes`，details 里包含 `crane_id_a`、`crane_id_b`、`distance_m`、`min_base_distance_m`。

### 高度

- `mast_height_m` 必须落在 `CraneModelSpec.mast_height_range_m`。
- `root_z = base_z + mast_height_m`。
- `root_z` 不得超过 site boundary `z_max`，除非后续明确允许塔臂根部高于工地区域边界；当前建议不允许。

### 回转

- 输入 `theta_init_deg` 转为 `theta_init_rad`。
- continuous 模式允许任意角度输入，内部可保留转换后的 rad。
- limited 模式需要 `theta_limit_deg` 才能完整校验；当前 `SlewConfigInput` 只有 `mode`，M0 不支持 limited 的角度范围校验。若 manual 中出现 `limited`，建议先返回 `LAY_E_002`，reason=`limited_slew_missing_theta_limit`，直到 schema 扩展。

## 拥有对象

本任务拥有：

- manual layout validator。
- manual layout startup diagnostics。
- `LAY_E_002` 的 manual 布局失败判定。

本任务不拥有：

- `ManualCraneLayoutInput` schema，归模块 A。
- `CraneConfig` 最终实例化，归 Task 03。
- 任务可达性，归 Task 05/模块 D。

## 测试要求

建议测试文件：

```text
backend/app/tests/test_manual_layout.py
```

必测场景：

- valid manual layout 通过。
- `layout.num_cranes=2` 但 `cranes` 只有 1 台时报 `manual_count_mismatch`。
- 重复 `crane_id` 报 `duplicate_crane_id`。
- 未知 `model_id` 报 `unknown_model_id`。
- base x/y/z 越界报 `base_out_of_boundary`。
- base 落入 box forbidden zone 报 `base_inside_forbidden_zone`。
- `mast_height_m` 低于型号范围报 `mast_height_out_of_model_range`。
- `mast_height_m` 高于型号范围报 `mast_height_out_of_model_range`。
- 两台 base 距离小于 `min_base_distance_m` 报 `root_distance_too_small`。
- `slew.mode=continuous` 通过。
- `slew.mode=limited` 且没有角度限制时报 `limited_slew_missing_theta_limit`。
- 任意合法 `crane_id`，例如 `TC_A`，可以通过。

推荐命令：

```bash
pytest backend/app/tests/test_manual_layout.py -v
```

## 验收标准

- manual layout 不再允许几何明显非法的配置启动 episode。
- 所有失败都能映射到稳定 `LAY_E_002` startup error。
- 错误对象能指出具体 crane 和失败约束。
- 校验只读取配置和型号参数，不创建 `CraneState`。
- 不硬编码 3 台塔吊或固定 crane ID。
