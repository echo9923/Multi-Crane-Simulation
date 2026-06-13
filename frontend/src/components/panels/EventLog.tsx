// Event log. Clicking an event seeks the timeline to its time and selects the
// first related crane so the 3D scene and panels jump to the relevant moment.

import { useStore } from "@/state/store";
import { collectEventsFromFrames } from "@/api/loader";
import { riskColorCss, riskLabel } from "@/ui/risk";
import type { RiskLevel } from "@/types/sim";

export function EventLog() {
  const frames = useStore((s) => s.frames);
  const currentIndex = useStore((s) => s.currentIndex);
  const events = collectEventsFromFrames(frames);
  const seekToTime = useStore((s) => s.seekToTime);
  const setUI = useStore((s) => s.setUI);

  const onJump = (timeS: number, craneIds: string[]) => {
    seekToTime(timeS);
    if (craneIds.length > 0) setUI({ selectedCraneId: craneIds[0] });
  };

  return (
    <section className="panel" data-testid="event-log">
      <h3>事件日志（{events.length}）</h3>
      <div className="panel-body">
        {events.length === 0 ? (
          <span className="muted">无事件</span>
        ) : (
          <table className="grid">
            <thead>
              <tr>
                <th>t</th>
                <th>类型</th>
                <th>塔吊</th>
                <th>等级</th>
              </tr>
            </thead>
            <tbody>
              {events.map((e, i) => {
                const level = e.risk_level as RiskLevel | undefined;
                const time = e.time_s ?? 0;
                const isCurrent = frames[currentIndex]?.time_s === time;
                return (
                  <tr
                    key={e.event_id ?? i}
                    className={`clickable ${isCurrent ? "row-selected" : ""}`}
                    onClick={() => onJump(time, e.crane_ids ?? [])}
                  >
                    <td>{time.toFixed(1)}</td>
                    <td>{e.event_type}</td>
                    <td>{(e.crane_ids ?? []).join(",")}</td>
                    <td>
                      {level ? (
                        <span className="lvl" style={{ background: riskColorCss(level) }}>
                          {riskLabel(level)}
                        </span>
                      ) : (
                        "—"
                      )}
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
