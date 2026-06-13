# Task 04：风险可视化

## 任务目标

在 3D 场景中展示多塔风险：风险连线（塔对）、临界接近/碰撞高亮、多塔重叠作业区、风险等级颜色/样式区分，并提供风险显示开关。风险数据来自 `SimFrame.pairs`（`risk_level_now`、`clearance_min_now_m`）与 `manifest.overlap_zones`，前端只展示、不计算。

## 范围：做什么 / 不做什么

做：

- 实现 `three/geometry/risk.ts`：塔对风险连线（按 `risk_level_now` 着色/样式）、碰撞/临界接近高亮（脉冲材质）。
- 实现 `RiskOverlay` 构建函数：从 `SimFrame.pairs` + 静态塔吊坐标生成连线列表。
- 实现重叠作业区渲染：从 `manifest.overlap_zones` 绘制半透明高亮体。
- 实现 `riskLevelStyle(level)`：颜色 + 不透明度 + 线宽映射（6 级 `RiskLevel`）。
- 接入 `SceneModel.risk` 与 `applySceneModel` 的风险层；接入 `ui.showRisk` 开关（隐藏/显示风险层）。

不做：

- 不计算距离/TTC（仅展示 `pairs` 已有字段；Task 08 把字段显示为 `display-only`）。
- 不做风险判定/碰撞检测（归 H/K）。
- 不把风险作为训练真值回传（无回传通道）。
- 不实现点击塔对查看详情的 UI（Task 08）。

## 接口与数据结构（签名级别）

```typescript
// three/geometry/risk.ts
interface RiskLink { craneI: string; craneJ: string; level: RiskLevel;
                    clearanceNow: number | null; a: Vec3; b: Vec3; }
function buildRiskOverlay(frame: SimFrame, craneWorldPos: Map<string, Vec3>): RiskOverlay;
function riskLevelStyle(level: RiskLevel): { color: number; opacity: number; lineWidth: number; pulse: boolean };
interface RiskOverlay { links: RiskLink[]; collisionPairIds: [string,string][]; }
```

```typescript
// 颜色映射（默认）
safe -> 灰; low -> 绿; medium -> 黄; high -> 橙; near_miss -> 红(脉冲); collision -> 深红(脉冲)
```

## 前置依赖

- Task 01、Task 02（塔吊坐标）、Task 03（`SceneModel`/`applySceneModel`、塔吊世界位置来源）。

## 验收标准（具体、可测试）

- 给定含若干 `pairs` 的 `SimFrame`，`buildRiskOverlay` 生成连线数 = `pairs.length`，每条连线端点 = 对应两台塔吊的 `hook`（或 root）世界坐标经 `worldToThree`。
- 连线颜色/样式由 `risk_level_now` 决定：6 级各有不同颜色；`near_miss`/`collision` 启用脉冲。
- `risk_level_now=null` 的 pair 渲染为弱化（灰、低不透明度）或不连线（可配置），不抛错。
- `ui.showRisk=false` 时风险层整体 `visible=false`；`true` 时可见。
- 重叠区（`manifest.overlap_zones`）渲染为半透明体，数量匹配。
- 风险层为 `display-only`：组件/类型标注，不存在写入回传路径。

## 测试要点（正常 + 边界 + 异常）

- 正常：3 塔存在 3 对风险连线，颜色按级别正确。
- 正常：`showRisk` 开关切换可见性。
- 边界：某 pair `risk_level_now=null` → 弱化处理。
- 边界：无 pairs（空数组）→ 无连线，不报错。
- 边界：单塔吊 → 无 pairs、无连线。
- 异常：pair 引用的 `crane_id` 在场景中不存在 → 跳过该连线并计数。
- 防泄漏：无回传/写入接口（纯展示）。

## 依赖关系

依赖 Task 01-03。Task 08（交互）消费风险连线做点击查看距离/TTC（`display-only`）。
