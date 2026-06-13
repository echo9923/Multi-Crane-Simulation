// Derive per-crane dynamic state from a SimFrame (+ static config for load
// shape resolution). Pure function — fully unit-testable without Three.js.

import type { SimFrame, SimFrameCrane, LoadShape } from "@/types/sim";
import type { ResolvedConfig } from "@/types/config";
import { loadShapeOf } from "@/types/config";
import type { Vec3 } from "@/coord";

export interface DynamicCraneState {
  craneId: string;
  base: Vec3;
  root: Vec3;
  tip: Vec3;
  hook: Vec3;
  thetaRad: number;
  trolleyR: number;
  hookHWorld: number;
  rootZWorld: number;
  loadAttached: boolean;
  loadShape: LoadShape | null;
  loadSize: Vec3 | null;
  loadType: string | null;
  taskStage: string;
  operatorProfile: string | null;
}

export function deriveCrane(c: SimFrameCrane, config: ResolvedConfig | null): DynamicCraneState {
  const loadType = c.load_attached ? c.load_type : null;
  const loadTypeCfg = loadType ? config?.scenario?.load_types?.[loadType] : undefined;
  const loadShape: LoadShape | null = loadTypeCfg ? loadShapeOf(loadTypeCfg) : null;
  return {
    craneId: c.crane_id,
    base: c.base,
    root: c.root,
    tip: c.tip,
    hook: c.hook,
    thetaRad: c.theta_rad,
    trolleyR: c.trolley_r_m,
    hookHWorld: c.hook_h_m,
    rootZWorld: c.root[2],
    loadAttached: c.load_attached,
    loadShape,
    loadSize: c.load_attached ? c.load_size_m ?? loadTypeCfg?.size_m ?? null : null,
    loadType,
    taskStage: c.task_stage,
    operatorProfile: c.operator_profile,
  };
}

export function deriveDynamic(
  frame: SimFrame,
  config: ResolvedConfig | null,
): Map<string, DynamicCraneState> {
  const out = new Map<string, DynamicCraneState>();
  for (const c of frame.cranes) {
    out.set(c.crane_id, deriveCrane(c, config));
  }
  return out;
}
