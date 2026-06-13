# Task 03：动态 3D 更新

## 任务目标

根据 `SimFrame` 实时/离线更新 3D 场景：塔吊姿态（塔身/起重臂方向/小车位置/吊钩高度）、吊物显示（按 `load_type.shape` 与 `load_size_m`）、塔臂轨迹尾迹、风向箭头。所有动态几何直接由 `SimFrame` 的 `base/root/tip/hook` 世界坐标驱动，保证与导出数据坐标一致。

## 范围：做什么 / 不做什么

做：

- 实现 `three/model/dynamicState.ts`：从 `SimFrame` + 静态配置派生每台塔吊的 `DynamicCraneState`（臂方向、小车位置、钩位置、吊物）。
- 实现 `three/model/SceneModel.ts`：合并静态布局与动态状态，产出 `applySceneModel` 输入。
- 实现 `ThreeSceneController.applySceneModel`：把 `SceneModel` 应用到对象树（位移/旋转/可见性）。
- 实现吊物几何：`box_long|flat_box|cylinder|beam` 四种 shape × `load_size_m` 程序几何；`load_attached=false` 时隐藏。
- 实现塔臂轨迹尾迹（按 `crane_id` 缓存最近 N 个 `tip`，渲染为渐隐线）。
- 实现风向箭头（按 `weather.wind_direction_deg` 摆放方向）。
- 实现单元化更新：同一 `applyFrame(frame)` 路径同时服务离线与实时。

不做：

- 不渲染风险连线/碰撞高亮（Task 04）。
- 不做距离/TTC 计算（仅 Task 08 展示 `pairs` 已有字段，标 `display-only`）。
- 不实现 UI 面板（Task 05）。
- 不修改静态场景结构（Task 02 产物）。

## 接口与数据结构（签名级别）

```typescript
// three/model/dynamicState.ts
interface DynamicCraneState {
  craneId: string;
  base: Vec3; root: Vec3; tip: Vec3; hook: Vec3;
  jibDirRad: number;            // 由 root->tip 推得（display-only）
  trolleyWorld: Vec3;           // 由 trolley_r_m 沿臂推得
  loadAttached: boolean;
  loadShape: LoadShape | null;
  loadSize: Vec3 | null;
  taskStage: string;
}
function deriveDynamic(frame: SimFrame, config: ResolvedConfig | null): Map<string, DynamicCraneState>;
```

```typescript
// three/model/SceneModel.ts
interface SceneModel {
  cranes: { id: string; parts: CraneParts; dynamic: DynamicCraneState }[];
  trails: { craneId: string; points: Vec3[] }[]; // 世界坐标
  wind: { dirDeg: number | null; speed: number } | null;
  risk: RiskOverlay | null;        // Task 04 填充，本任务置 null
}
function buildSceneModel(staticBuilt: StaticIndex, frame: SimFrame, ctx: { config, trails }): SceneModel;
```

```typescript
// 吊物几何
function buildLoad(shape: LoadShape, size: Vec3): THREE.Object3D;
// box_long/flat_box: BoxGeometry; cylinder: CylinderGeometry; beam: 细长 BoxGeometry
```

## 前置依赖

- Task 01（coord、types、store）。
- Task 02（`ThreeSceneController`、塔吊部件句柄、`applySceneModel` 接口）。

## 验收标准（具体、可测试）

- 喂入两个不同 `SimFrame`（同一塔吊 `tip`/`hook` 不同），`applySceneModel` 后塔吊臂朝向与钩位置随之改变；断言 `jib` 朝向 = `worldToThree` 下 `root→tip` 方向。
- 吊钩世界坐标（`threeToWorld` 还原）等于帧 `hook` 字段（容差 1e-6），验证坐标一致。
- `load_attached=true` 且 `load_type` 在 `load_types` 目录中时，吊物按 `shape` 渲染且尺寸 = `load_size_m`；`load_attached=false` 时吊物节点 `visible=false`。
- `shape` 为四种之一时几何类型正确；未知 `shape` 回落为包围盒（BoxGeometry）并计数。
- 塔臂尾迹在连续喂帧后增长到上限 N 后不再增长（FIFO）。
- 风向箭头角度 = `wind_direction_deg`（缺省时隐藏）。
- 离线帧与“构造等价的实时帧”经同一 `applyFrame` 产生相同场景对象状态。

## 测试要点（正常 + 边界 + 异常）

- 正常：3 台塔吊的姿态/吊物/尾迹随帧更新；坐标经 `worldToThree` 后再 `threeToWorld` 还原一致。
- 正常：四种 shape 吊物几何正确。
- 边界：`load_size_m=null` 但 `load_attached=true` → 用 `load_types` 目录默认 `size_m` 或最小盒。
- 边界：`trolley_r_m` 超出 `[trolley_r_min,trolley_r_max]` 仍渲染（不夹紧几何，仅面板提示）。
- 边界：`wind_direction_deg=null` 时箭头隐藏。
- 异常：帧缺少某台塔吊（配置有但帧无）→ 该塔吊保持上一帧姿态或空闲态，不抛错。
- 异常：未知 `shape` 字符串 → 包围盒回落 + 计数。

## 依赖关系

依赖 Task 01、Task 02。Task 04（风险）扩展 `SceneModel.risk` 与 `applySceneModel` 的风险层。
