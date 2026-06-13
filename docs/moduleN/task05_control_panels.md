# Task 05：状态面板与日志

## 任务目标

实现右侧状态面板：塔吊状态、任务状态、风险状态、LLM 指令日志（可展开 observation/messages/raw_response/parsed_command/executed_command/validation_errors）、事件日志（点击跳转时间轴并高亮相关塔吊）。所有面板从 store 的当前帧/manifest/离线日志派生。

## 范围：做什么 / 不做什么

做：

- 实现 `components/CraneStatusPanel`：每台塔吊的 `theta_rad`/`trolley_r_m`/`hook_h_m`/`task_stage`/`operator_profile`/`load_type`。
- 实现 `components/TaskStatusPanel`：从 `frame.tasks` 展示任务 id/阶段/优先级/截止。
- 实现 `components/RiskStatusPanel`：从 `frame.pairs` 展示塔对距离/余量/级别（`display-only`）。
- 实现 `components/LLMCommandLog`：解析离线 `logs/commands.jsonl`（及实时帧 `current_command`），按塔吊分组，可展开六个子段。
- 实现 `components/EventLog`：从 `frame.events`（及离线 `logs/events.jsonl`）展示事件，点击 → 调 store 跳转到最近 `time_s`，并 `ui.selectedCraneId` 高亮相关塔吊。
- 面板订阅 store 切片，节流更新（避免每帧重渲染）。

不做：

- 不渲染 3D（Task 02-04）。
- 不实现时间轴拖拽逻辑（Task 06 提供动作，面板只调用）。
- 不调用 LLM/不构造 observation（仅展示已落盘/已推送内容）。
- 不把面板距离/风险作为真值。

## 接口与数据结构（签名级别）

```typescript
// components/LLMCommandLog.tsx
interface CommandRow { time_s: number; crane_id: string; observation?: unknown;
  messages?: {role:string;content:string}[]; raw_response?: unknown;
  parsed_command?: unknown; executed_command?: unknown; validation_errors?: unknown[]; }
function CommandLog(props: { rows: CommandRow[]; }): JSX.Element; // 行可展开
```

```typescript
// components/EventLog.tsx
interface EventRow { event_id: string; event_type: string; time_s: number;
  crane_ids: string[]; risk_level?: RiskLevel; details?: unknown; }
function EventLog(props: { rows: EventRow[]; onJump(time_s: number, craneIds: string[]): void }): JSX.Element;
```

```typescript
// store 动作（Task 01 已有骨架，本任务补充）
seekToTime(time_s: number): void;     // 离线：定位到最近帧 index
```

## 前置依赖

- Task 01（store、types、工程基建）。
- Task 03 的 `SimFrame` 帧可用（面板读取 `latestFrame`/`frames[currentIndex]`）。
- 离线 `logs/*.jsonl` 解析（`api/loader.ts`，可由 Task 06 一并实现；本任务定义数据形状）。

## 验收标准（具体、可测试）

- 给定一帧含 3 塔的 `SimFrame`，`CraneStatusPanel` 渲染 3 行，字段值与帧一致。
- `LLMCommandLog` 对每个 `CommandRow` 渲染可折叠的六段；展开后展示对应字段（缺失段显示“无”）。
- `EventLog` 点击某事件 → 调用 `onJump(time_s, craneIds)`；store `currentIndex` 更新为 `time_s` 最近帧；`ui.selectedCraneId` 被设为相关塔吊。
- `RiskStatusPanel` 距离/余量显示 `display-only` 标记。
- 面板在帧不变时不重复渲染（selector 稳定）。
- 空数据（无 tasks/events/commands）时显示占位提示，不崩。

## 测试要点（正常 + 边界 + 异常）

- 正常：塔吊/任务/风险面板字段正确渲染。
- 正常：LLM 日志六段展开/折叠；各段缺失时降级显示。
- 正常：事件点击跳转 + 高亮调用正确参数。
- 边界：空 tasks/events/commands。
- 边界：单塔吊、6 塔吊面板均可滚动渲染。
- 异常：命令行缺字段（如 `validation_errors` 缺失）不崩。
- 防泄漏：LLM 日志展开不展示完整 api_key（后端已脱敏，前端额外做 `mask` 兜底显示）。

## 依赖关系

依赖 Task 01、Task 03（帧数据）。Task 06（时间轴）提供 `seekToTime` 实现与离线日志加载；Task 08（交互）联动 `selectedCraneId` 高亮。
