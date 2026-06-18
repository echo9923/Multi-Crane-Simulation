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
  safe: { color: 0x64748b, opacity: 0.42, lineWidth: 1, pulse: false },
  low: { color: 0x059669, opacity: 0.68, lineWidth: 1.4, pulse: false },
  medium: { color: 0xf59e0b, opacity: 0.82, lineWidth: 2, pulse: false },
  high: { color: 0xea580c, opacity: 0.92, lineWidth: 2.6, pulse: false },
  near_miss: { color: 0xdc2626, opacity: 1.0, lineWidth: 3.2, pulse: true },
  collision: { color: 0x991b1b, opacity: 1.0, lineWidth: 3.8, pulse: true },
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
