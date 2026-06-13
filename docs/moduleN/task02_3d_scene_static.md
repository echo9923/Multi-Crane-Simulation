# Task 02：静态 3D 场景

## 任务目标

根据 `ResolvedConfig`（及 `EpisodeManifest`）渲染静态 3D 场景：地面/工地边界、各 zones、塔吊程序几何模型（塔身/起重臂/平衡臂/小车/吊钩）、作业半径圆，并预留 glTF/GLB 替换接口。本任务只渲染静态结构，不响应 `SimFrame` 动态姿态（Task 03）。

## 范围：做什么 / 不做什么

做：

- 实现 `three/ThreeSceneController`：初始化 Scene/Camera/Renderer/灯光/地面网格，渲染器工厂可注入（便于无 WebGL 单测）。
- 实现 `three/geometry/crane.ts`：塔吊程序几何工厂（按 `CraneConfig` 的 `base/root/mast_height/jib_length/counter_jib_length/trolley_r_max` 摆放）。
- 实现 `three/geometry/zones.ts`：`material_zones` / `work_zones` / `forbidden_zones` 的 `box` 与 `polygon` 渲染，颜色按类型区分，半透明。
- 实现 `three/geometry/site.ts`：工地边界（AABB 线框）与地面网格。
- 实现作业半径圆（base 处水平圆，半径 `trolley_r_max_m`）。
- 设计 glTF 替换接口：几何工厂按 `registerModel(craneId|modelId, Object3D|loader)` 注入外部资产，未注册时回落程序几何。
- 所有几何用 Task 01 的 `worldToThree` 映射坐标。

不做：

- 不响应 `SimFrame` 动态姿态（Task 03）。
- 不渲染吊物形状（Task 03）。
- 不渲染风险连线/重叠区高亮（Task 04）。
- 不实现交互（选中/跟随，Task 08）。
- 不绑定真实 WebGL 上下文做断言（用注入渲染器做逻辑单测）。

## 接口与数据结构（签名级别）

```typescript
// three/ThreeSceneController.ts
interface RendererFactory { (canvas: HTMLCanvasElement): THREE.WebGLRenderer }
class ThreeSceneController {
  constructor(opts: { canvas: HTMLCanvasElement; createRenderer?: RendererFactory });
  buildStatic(config: ResolvedConfig, manifest?: EpisodeManifest | null): void;
  applySceneModel(model: SceneModel): void;   // Task 03+ 使用
  resize(w: number, h: number): void;
  dispose(): void;
  // 暴露场景对象树用于单测断言（不暴露渲染细节）
  getObjectByName(name: string): THREE.Object3D | undefined;
}
```

```typescript
// three/geometry/crane.ts
interface CraneParts { group: THREE.Group; jib: THREE.Object3D; trolley: THREE.Object3D;
                      hook: THREE.Object3D; loadSlot: THREE.Object3D; }
function buildCrane(cfg: CraneConfig, palette: { color: number }): CraneParts;
function registerCraneAsset(key: string, asset: THREE.Object3D | GLTFLoaderLike): void; // glTF 替换
```

```typescript
// three/geometry/zones.ts
function buildZone(zone: ZoneConfig, kind: "material"|"work"|"forbidden"): THREE.Object3D;
// box: center+size 轴对齐体；polygon: points 水平足迹挤出 z_range_m
```

## 前置依赖

- Task 01（coord、types、store、工程基建）。
- `ResolvedConfig` / `CraneConfig` / `ZoneConfig` / `BoundaryConfig` 类型（types/config.ts）。

## 验收标准（具体、可测试）

- 给定含 ≥3 台塔吊的 `ResolvedConfig`，`buildStatic` 后场景树中出现每台塔吊的 `THREE.Group`（按 `crane_id` 命名），数量等于配置塔吊数。
- 塔吊塔身位置 = `worldToThree(base)`；塔顶（root）= `worldToThree(root)`；几何高度匹配 `mast_height_m`。
- 起重臂长度方向覆盖 `jib_length_m`，平衡臂覆盖 `counter_jib_length_m`（世界尺度，米）。
- 作业半径圆半径 = `trolley_r_max_m`，位于 base 水平面。
- `box` zone 用 `center`+`size` 摆放，`polygon` zone 用 `points` 足迹 + `z_range_m` 高度，半透明且颜色按 kind 区分。
- 工地边界为 AABB 线框，范围匹配 `boundary.{x,y,z}_{min,max}`。
- glTF 替换：`registerCraneAsset` 注入后对应塔吊使用注入资产；未注入回落程序几何。
- 上述断言均可在**注入桩渲染器（无 WebGL）**下完成：通过检查 `THREE.Object3D` 的 `position`/`scale`/子节点数量验证。

## 测试要点（正常 + 边界 + 异常）

- 正常：3 台塔吊 + 3 种 zone + 边界渲染，对象树结构正确，坐标经 `worldToThree`。
- 正常：glTF 注入替换生效，回落路径生效。
- 边界：单塔吊、塔吊数量等于 N（不硬编码，循环渲染）。
- 边界：`polygon` zone `z_range_m` 缺失时退化为薄板（不崩）。
- 边界：`trolley_r_max_m` 缺失时半径圆用 `jib_length_m`。
- 异常：非法 zone `type`（非 box/polygon）跳过并计数警告，不抛错。
- 防泄漏：场景不包含任何密钥/凭证（纯几何）。

## 依赖关系

依赖 Task 01。Task 03（动态更新）在 `ThreeSceneController.applySceneModel` 与塔吊部件句柄基础上扩展。
