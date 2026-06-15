// Risk overlay: build per-pair risk links from SimFrame.pairs anchored on the
// cranes' hook world positions, and map risk levels to render styles. Pure —
// no Three.js here beyond type imports; the controller turns links into lines.

import type { SimFrame, RiskLevel } from "@/types/sim";
import type { Vec3 } from "@/coord";
import type { RiskOverlay, RiskLink } from "@/three/model/SceneModel";

export interface RiskStyle {
  color: number;
  opacity: number;
  lineWidth: number;
  pulse: boolean;
}

export const RISK_STYLE: Record<RiskLevel, RiskStyle> = {
  safe: { color: 0x94a3b8, opacity: 0.3, lineWidth: 1, pulse: false },
  low: { color: 0x10b981, opacity: 0.55, lineWidth: 1, pulse: false },
  medium: { color: 0xfbbf24, opacity: 0.6, lineWidth: 1.5, pulse: false },
  high: { color: 0xfb923c, opacity: 0.78, lineWidth: 2, pulse: false },
  near_miss: { color: 0xef4444, opacity: 0.9, lineWidth: 2.5, pulse: true },
  collision: { color: 0xb91c1c, opacity: 1.0, lineWidth: 3, pulse: true },
};

export function riskLevelStyle(level: RiskLevel): RiskStyle {
  return RISK_STYLE[level];
}

export function pairKey(a: string, b: string): string {
  return [a, b].sort().join("-");
}

/**
 * Build the risk overlay for one frame. Pairs referencing cranes absent from
 * `anchorByCrane` are skipped (and counted) so a stray pair id never throws.
 * A null risk_level_now renders as the weak "safe" style.
 */
export function buildRiskOverlay(
  frame: SimFrame,
  anchorByCrane: Map<string, Vec3>,
): RiskOverlay {
  const links: RiskLink[] = [];
  const collisionPairIds: [string, string][] = [];
  for (const p of frame.pairs) {
    const a = anchorByCrane.get(p.crane_i);
    const b = anchorByCrane.get(p.crane_j);
    if (!a || !b) continue;
    const level: RiskLevel = p.risk_level_now ?? "safe";
    links.push({
      craneI: p.crane_i,
      craneJ: p.crane_j,
      level,
      clearanceNow: p.clearance_min_now_m,
      a,
      b,
    });
    if (level === "near_miss" || level === "collision") {
      collisionPairIds.push([p.crane_i, p.crane_j]);
    }
  }
  return { links, collisionPairIds };
}
