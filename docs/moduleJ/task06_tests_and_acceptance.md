# Task 06：Tests and Acceptance

## 任务目标

定义 Module J 的测试清单与验收标准，覆盖 scheduler schema、snapshot freezer、command store、decision timing、完整 frame loop、replay、LLM 降级、terminal status 和跨模块回归。

## 范围：做什么 / 不做什么

做：

- 新增 `backend/app/tests/test_scheduler.py`。
- 新增 `backend/app/tests/test_moduleJ_acceptance.py`。
- 为 Task 01-05 写单元测试和验收测试。
- 使用 fake adapters 验证完整 frame loop 顺序。
- 覆盖 replay、LLM timeout、command expiry、collision、invalid state、completed/timeout。
- 跑目标文档要求的邻近模块回归测试。

不做：

- 不要求真实 DeepSeek/MiniMax 网络调用。
- 不要求真实 FastAPI/WebSocket 端到端。
- 不要求真实 Parquet writer，只需 recorder fake 验证调用合同。
- 不生成 offline risk label。
- 不把跨模块测试写成依赖外部服务的慢测试。

## 接口与数据结构（签名级别）

测试文件：

```text
backend/app/tests/test_scheduler.py
backend/app/tests/test_moduleJ_acceptance.py
```

建议测试分组：

```python
class FakeRecorder:
    calls: list[tuple[str, dict]]
    def record_initial_frame(...): ...
    def record_step(...): ...

class FakeOperator:
    calls: list[Observation]
    def decide(...): ...

class FakeReplaySource:
    def commands_for_decision(...): ...
```

`test_scheduler.py` 重点：

- schema。
- freezer。
- command store。
- decision timing。
- terminal status helper。

`test_moduleJ_acceptance.py` 重点：

- 15 步 frame loop call order。
- multi-crane same snapshot。
- simultaneous command apply。
- replay no-LLM。
- LLM timeout/failed。
- command expiry neutral_stop。
- collision/invalid state terminal。
- completed/timeout。

## 前置依赖

- Task 01-05 实现。
- A-I、K 的现有 schema 和纯函数。
- pytest。

## 验收标准（具体、可测试）

Module J schema：

- `SchedulerConfig.from_config()` 支持 dict / ResolvedConfig-like。
- `WorldSnapshot` 拒绝 extra 字段和 forbidden future/offline keys。
- `EpisodeStatus` 覆盖全部 terminal status。

WorldSnapshot：

- 同一 decision time 多塔 observation 来自同一 `snapshot_id`。
- 快照构造后输入状态变化不影响 snapshot。
- snapshot 不包含 LLM reason、raw response、offline label。

CommandStore：

- startup neutral_stop。
- 批量替换原子性。
- 到期 neutral_stop。
- replay 命令可替换当前命令且不调用 G/H。

Decision timing：

- 首帧所有塔 due。
- interval 未到不 due，到达 interval due。
- idle 也参与判断。
- rule/LLM/replay driver 共用同一 due 判定。

Frame loop：

- 每帧调用顺序符合 0.7.8。
- `record_initial_frame` 只在 `time_s=0` 调用一次。
- `record_step` 在 physics 后、terminal stop 前调用。
- 多塔命令收齐后同时应用。
- 未 due crane 使用旧命令并接受 expiry 检查。

Replay：

- `offline_replay` 不调用 LLM/operator。
- 历史 `ExecutedCommand` 按 decision key 唯一匹配。
- config hash/schema version mismatch 失败。
- safety audit mismatch 失败且不改写命令。

LLM failure：

- 单次 timeout 或 invalid output 使用 neutral_stop，episode 继续。
- 连续失败达到阈值后 `llm_failed`。
- `offline_wait` 等待期间仿真时间不推进。
- `realtime_stale` 可用上一命令，但过期后 neutral_stop。

Terminal：

- collision -> `failed_collision`，不生成碰撞后轨迹。
- NaN/Inf -> `failed_invalid_state`。
- all tasks done + min duration + cooldown -> `completed`。
- duration exceeded -> `timeout`。
- stopped by user -> `stopped_by_user`。
- recovery blocked/timeout -> 对应 recovery terminal status。

## 测试命令

调度器单元测试：

```bash
pytest backend/app/tests/test_scheduler.py -v
```

模块 J 完整验收：

```bash
pytest backend/app/tests/test_scheduler.py \
       backend/app/tests/test_moduleJ_acceptance.py -v
```

回归邻近模块：

```bash
pytest backend/app/tests/test_controller.py \
       backend/app/tests/test_safety_mechanical.py \
       backend/app/tests/test_crane_state.py \
       backend/app/tests/test_physics.py \
       backend/app/tests/test_observation.py \
       backend/app/tests/test_task_queue.py \
       backend/app/tests/test_weather.py -v
```

当前仓库中部分测试文件名与目标文档命令可能不同。实现阶段若发现文件不存在，应优先使用已存在的等价测试文件，并在覆盖总结中说明映射，例如：

```text
test_physics.py -> test_physics_step.py / test_physics_world.py
test_task_queue.py -> test_task_queue_scheduler.py
test_weather.py -> test_weather_state.py / test_weather_generation.py
```

## 测试要点（正常 + 边界 + 异常）

正常：

- two-crane offline batch with fake rule driver。
- two-crane LLM decision batch with same snapshot。
- replay batch with saved executed commands。
- all tasks done after cooldown completed。

边界：

- one crane no neighbors。
- idle-only episode until min duration。
- command expires exactly at `time_s == command.time_s + command_duration_s`。
- `duration_s` not an integer multiple of `dt_s`，最后一帧不超过合同中定义的停止规则。
- decision interval not an integer multiple of dt，due 判定仍 deterministic。

异常：

- duplicate crane ids in snapshot。
- operator returns command for wrong snapshot。
- safety returns collision candidate。
- physics returns NaN。
- replay command missing/duplicate/mismatch。
- recorder throws write failure；默认映射为 episode/run failure，具体 status 在实现阶段与 L 合同对齐。

防越界：

- 静态扫描 `backend/app/sim/scheduler.py` 不应包含 LLM provider HTTP 调用。
- 静态扫描不应在 scheduler 中实现 gear-to-velocity 表。
- 静态扫描不应在 scheduler 中计算 task attach/release 条件。
- 静态扫描不应在 scheduler 中计算 collision geometry 细节。

## 覆盖总结要求

阶段四完成后输出简短覆盖总结：

```text
已覆盖：
- schema/freezer/command store/decision timing。
- offline_batch/offline_replay/interactive single-step。
- LLM timeout、连续失败、command expiry。
- collision、invalid state、completed、timeout。
- A→B→C→D→E→F→G→H→I→J→K/L fake chain。

未覆盖及原因：
- 真实 DeepSeek/MiniMax 网络调用：依赖外部服务，不作为本地必跑。
- 真实 WebSocket 浏览器渲染：归 M/N 集成测试。
- offline label 生成：归 K/O，J 只保证 episode 后可触发。
```
