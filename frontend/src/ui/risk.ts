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

// Soft pill backgrounds + same-family deep text, tuned for the light theme so
// risk badges read clearly on white panels (vs. saturated fills on dark).
export const RISK_SOFT: Record<RiskLevel, string> = {
  safe: "#f1f5f9",
  low: "#d1fae5",
  medium: "#fef3c7",
  high: "#ffedd5",
  near_miss: "#fee2e2",
  collision: "#fecaca",
};

export const RISK_TEXT: Record<RiskLevel, string> = {
  safe: "#475569",
  low: "#065f46",
  medium: "#92400e",
  high: "#9a3412",
  near_miss: "#991b1b",
  collision: "#7f1d1d",
};

export function riskColorCss(level: RiskLevel | null | undefined): string {
  return level ? RISK_CSS[level] : "#6b7280";
}

export function riskSoftCss(level: RiskLevel | null | undefined): string {
  return level ? RISK_SOFT[level] : RISK_SOFT.safe;
}

export function riskTextCss(level: RiskLevel | null | undefined): string {
  return level ? RISK_TEXT[level] : RISK_TEXT.safe;
}

export function riskLabel(level: RiskLevel | null | undefined): string {
  return level ? RISK_LABEL[level] : "未知";
}

export function hexCss(n: number): string {
  return `#${n.toString(16).padStart(6, "0")}`;
}
