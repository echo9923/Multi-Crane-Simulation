// SceneModel: the pure-data description the controller renders each frame.
// Risk overlay is populated by Task 04; Task 03 leaves it null.

import type { SimFrame } from "@/types/sim";
import type { ResolvedConfig } from "@/types/config";
import type { Vec3 } from "@/coord";
import { DynamicCraneState, deriveDynamic } from "./dynamicState";

export interface RiskLink {
  craneI: string;
  craneJ: string;
  level: import("@/types/sim").RiskLevel;
  clearanceNow: number | null;
  a: Vec3;
  b: Vec3;
}

export interface RiskOverlay {
  links: RiskLink[];
  collisionPairIds: [string, string][];
}

export interface SceneModel {
  cranes: DynamicCraneState[];
  wind: { dirDeg: number | null; speed: number } | null;
  risk: RiskOverlay | null;
}

export function buildSceneModel(
  frame: SimFrame,
  config: ResolvedConfig | null,
  riskOverlay: RiskOverlay | null = null,
): SceneModel {
  const dyn = deriveDynamic(frame, config);
  return {
    cranes: Array.from(dyn.values()),
    wind: {
      dirDeg: frame.weather.wind_direction_deg,
      speed: frame.weather.wind_speed_m_s,
    },
    risk: riskOverlay,
  };
}
