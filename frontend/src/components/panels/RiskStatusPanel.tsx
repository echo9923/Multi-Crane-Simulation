// Per-pair risk table. Distances/clearances are display-only: they come
// straight from the backend SimFrame.pairs and must never be treated as
// training ground truth.

import { useStore } from "@/state/store";
import { riskColorCss, riskLabel } from "@/ui/risk";
import type { RiskLevel } from "@/types/sim";

export function RiskStatusPanel() {
  const frame = useStore((s) => s.latestFrame);
  const pairs = frame?.pairs ?? [];

  return (
    <section className="panel" data-testid="risk-status">
      <h3>
        风险状态（{pairs.length}）
        <span className="display-only" title="前端展示用，非训练真值">
          display-only
        </span>
      </h3>
      <div className="panel-body">
        {pairs.length === 0 ? (
          <span className="muted">无塔对风险（单塔或无数据）</span>
        ) : (
          <table className="grid">
            <thead>
              <tr>
                <th>塔对</th>
                <th>距离m</th>
                <th>余量m</th>
                <th>等级</th>
              </tr>
            </thead>
            <tbody>
              {pairs.map((p) => {
                const level = p.risk_level_now as RiskLevel | null;
                return (
                  <tr key={`${p.crane_i}-${p.crane_j}`}>
                    <td>
                      {p.crane_i}↔{p.crane_j}
                    </td>
                    <td>{p.distance_min_raw_now_m?.toFixed(1) ?? "—"}</td>
                    <td>{p.clearance_min_now_m?.toFixed(1) ?? "—"}</td>
                    <td>
                      <span className="lvl" style={{ background: riskColorCss(level) }}>
                        {riskLabel(level)}
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </section>
  );
}
