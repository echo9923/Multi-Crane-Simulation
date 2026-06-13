// CSS color + label helpers for risk levels (UI side). Mirrors the 3D
// RISK_STYLE palette so panels and the scene read consistently.

import type { RiskLevel } from "@/types/sim";

export const RISK_CSS: Record<RiskLevel, string> = {
  safe: "#6b7280",
  low: "#34d399",
  medium: "#fbbf24",
  high: "#fb923c",
  near_miss: "#ef4444",
  collision: "#b91c1c",
};

export const RISK_LABEL: Record<RiskLevel, string> = {
  safe: "安全",
  low: "低",
  medium: "中",
  high: "高",
  near_miss: "临界",
  collision: "碰撞",
};

export function riskColorCss(level: RiskLevel | null | undefined): string {
  return level ? RISK_CSS[level] : "#6b7280";
}

export function riskLabel(level: RiskLevel | null | undefined): string {
  return level ? RISK_LABEL[level] : "未知";
}

export function hexCss(n: number): string {
  return `#${n.toString(16).padStart(6, "0")}`;
}
