# Task 07：模块 F 测试清单与验收标准

## 任务目标

定义模块 F 的单元测试、合同测试、集成测试和最终验收标准，确保 observation 是局部、可复现、可校验且不泄漏未来真值。

## 范围：做什么 / 不做什么

做：

- 新增并维护 `backend/app/tests/test_observation.py`。
- 新增并维护 `backend/app/tests/test_observation_visibility.py`。
- 新增并维护 `backend/app/tests/test_moduleF_acceptance.py`。
- 回归模块 D/E 的相邻合同测试。
- 在测试中覆盖正常路径、边界路径、异常路径、静态边界和信息泄漏防护。

不做：

- 不要求真实模块 G provider。
- 不要求真实模块 H risk engine。
- 不要求模块 L 写 Parquet/JSONL。

## 接口与数据结构（签名级别）

本任务不新增生产接口，只定义并维护测试入口：

```python
def test_observation_schema_accepts_llm_consumable_payload() -> None: ...
def test_observation_schema_forbids_extra_fields_recursively() -> None: ...
def test_observation_schema_forbids_extra_memory_decision_fields() -> None: ...
def test_visible_neighbors_are_filtered_by_weather_radius_and_summarized() -> None: ...
def test_distance_noise_and_hook_hide_are_deterministic_and_do_not_mutate_state() -> None: ...
def test_build_observation_assembles_complete_llm_json_without_leaks() -> None: ...
def test_observation_memory_sanitizes_forbidden_history_keys() -> None: ...
def test_module_f_boundaries_remain_static() -> None: ...
```

## 前置依赖

- Task 01 的 `Observation` 及子 schema。
- Task 02 的 `build_self_state_summary()`。
- Task 03 的 `build_task_summary()`。
- Task 04 的 `build_visible_neighbors()`。
- Task 05 的 `build_safety_hint()`。
- Task 06 的 `ObservationWorldSnapshot`、`build_observation()`、`build_observations_for_snapshot()`。

## 推荐测试命令

schema 测试：

```bash
pytest backend/app/tests/test_observation.py -v
```

可见度筛选测试：

```bash
pytest backend/app/tests/test_observation_visibility.py -v
```

模块 F 完整验收：

```bash
pytest backend/app/tests/test_observation.py \
       backend/app/tests/test_observation_visibility.py \
       backend/app/tests/test_moduleF_acceptance.py -v
```

回归邻近模块：

```bash
pytest backend/app/tests/test_weather_visibility_contract.py \
       backend/app/tests/test_task_queue_scheduler.py \
       backend/app/tests/test_moduleD_acceptance.py \
       backend/app/tests/test_moduleE_acceptance.py -v
```

## schema 验收

- `Observation` 及所有子 schema 拒绝 extra 字段。
- 所有 float 字段拒绝 NaN/Inf。
- `schema_version` 存在并等于 `"1.0"`。
- `Observation.model_dump(mode="json")` 可被 JSON 序列化。
- 禁用字段名不在 schema 字段集合中。

## builder 验收

- self state builder 正确摘要自身状态，且不输出完整几何真值。
- task builder 正确消费 active/idle 上下文，idle 不泄漏下一任务。
- neighbor builder 正确执行 radius/noise/hide/rounding。
- safety hint builder 正确区分 R0/R1。
- assembly builder 输出完整 observation 并可重放一致。

## 信息泄漏验收

完整 observation JSON 中不得出现：

```text
planned_start_s
future_min_distance
offline_ttc
offline_label
future_ttc
source_failed_task_id
neighbor_task_id
pickup_zone_id for neighbor
dropoff_zone_id for neighbor
```

允许自己的 `deadline_s` 和自己的 pickup/dropoff 相对摘要，但不允许邻塔目标坐标或队列信息。

## 集成验收

- 构造 3 台塔吊 demo snapshot。
- 其中一台 active task、一台 visible neighbor、一台被 visibility radius 过滤。
- medium/poor visibility 下观察距离含 deterministic noise 并按 precision 圆整。
- `hide_hook_prob=1` 时邻塔 hook 精细字段隐藏。
- `R0` 无 safety hint；`R1` 有 online risk hint。
- 同一 snapshot 构造两次输出一致。
- 修改 `noise_seed` 后 visibility 输出可改变，但物理 state 不变。

## 最终退出条件

- 模块 F 三个测试文件全部通过。
- D/E 邻近回归命令通过。
- 全仓库 `pytest` 通过。
- 至少一次检查序列化 observation，确认不含 forbidden keys。
- 每个实现任务按顺序有独立提交，提交信息格式为 `feat(moduleF): <任务目标>`。

## 测试要点（正常 + 边界 + 异常）

- 正常：schema 构造、self/task/weather/safety/memory 汇总、批量 observation。
- 边界：idle task、无 current command、无 online risk、`R0`、`hide_hook_prob=0/1`、空 memory。
- 异常：extra 字段、NaN/Inf、缺 state/config/context、重复 crane id、缺 neighbor state。
- 防泄漏：schema 字段、序列化 neighbor、完整 observation、memory history 和静态 import/name 扫描均不暴露 forbidden keys。
