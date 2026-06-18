// HTML overlays drawn on top of the 3D canvas: a "not live" banner plus risk and
// zone color legends. Purely informational (pointer-events: none) so they never
// intercept orbit/zoom/pick on the canvas underneath.

import { useStore } from "@/state/store";
import { RISK_CSS, RISK_LABEL } from "@/ui/risk";
import type { RiskLevel } from "@/types/sim";

const RISK_ORDER: RiskLevel[] = ["safe", "low", "medium", "high", "near_miss", "collision"];

// Mirror of three/geometry/zones.ts ZONE_COLOR, kept as CSS hex so the legend
// does not pull the Three.js geometry module into the UI bundle.
const ZONE_LEGEND: { key: string; color: string; label: string }[] = [
  { key: "material", color: "#3a7bd5", label: "物料区" },
  { key: "work", color: "#2fbf71", label: "作业/卸料区" },
  { key: "forbidden", color: "#e5524a", label: "禁入区" },
  { key: "overlap", color: "#8b5cf6", label: "重叠区" },
];

function bannerText(
  mode: string,
  status: string,
  episodeId: string | null,
): string | null {
  if (mode === "live" && status === "open") return null; // truly live
  const suffix = episodeId ? `（${episodeId}）` : "";
  if (mode === "replay") return `离线回放数据 · 非实时运行${suffix}`;
  if (status === "connecting" || status === "reconnecting") return "连接中 · 暂非实时";
  if (status === "error") return "连接异常 · 非实时运行";
  if (mode === "live") return `等待实时帧 · 暂未连接${suffix}`;
  return "未连接 · 非实时运行";
}

export function SceneOverlays() {
  const mode = useStore((s) => s.mode);
  const connection = useStore((s) => s.connection);
  const episodeId = useStore((s) => s.episodeId);
  const showRisk = useStore((s) => s.ui.showRisk);
  const showZones = useStore((s) => s.ui.showZones);

  const banner = bannerText(mode, connection.status, episodeId);

  return (
    <div className="scene-overlay" data-testid="scene-overlays" aria-hidden>
      {banner && (
        <div className="scene-banner" data-testid="scene-not-live-banner">
          <span className="scene-banner-dot" />
          {banner}
        </div>
      )}

      <div className="scene-legends">
        {showZones && (
          <div className="scene-legend" data-testid="zone-legend">
            <h4>区域</h4>
            {ZONE_LEGEND.map((z) => (
              <div className="scene-legend-row" key={z.key}>
                <span className="scene-legend-box" style={{ background: z.color }} />
                {z.label}
              </div>
            ))}
          </div>
        )}

        {showRisk && (
          <div className="scene-legend" data-testid="risk-legend">
            <h4>风险等级</h4>
            {RISK_ORDER.map((level) => (
              <div className="scene-legend-row" key={level}>
                <span className="scene-legend-swatch" style={{ background: RISK_CSS[level] }} />
                {RISK_LABEL[level]}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
