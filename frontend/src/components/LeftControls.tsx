// Left controls: display toggles + crane list (click to select; follow comes in
// Task 08). Selected crane drives panel highlighting and the 3D pick state.

import { useStore } from "@/state/store";
import { LoadEpisode } from "@/components/LoadEpisode";
import { DownloadBar } from "@/components/DownloadBar";
import { craneColorCss } from "@/ui/colors";

export function LeftControls() {
  const ui = useStore((s) => s.ui);
  const setUI = useStore((s) => s.setUI);
  const cranes = useStore((s) => s.latestFrame?.cranes ?? s.manifest?.cranes ?? []);

  return (
    <div>
      <LoadEpisode />
      <DownloadBar />
      <section className="panel" data-testid="display-toggles">
        <h3>显示</h3>
        <div className="panel-body">
          <label className="toggle">
            <input
              type="checkbox"
              checked={ui.showRisk}
              onChange={(e) => setUI({ showRisk: e.target.checked })}
            />
            风险层
          </label>
          <label className="toggle">
            <input
              type="checkbox"
              checked={ui.showZones}
              onChange={(e) => setUI({ showZones: e.target.checked })}
            />
            区域
          </label>
          <label className="toggle">
            <input
              type="checkbox"
              checked={ui.showPaths}
              onChange={(e) => setUI({ showPaths: e.target.checked })}
            />
            任务路径
          </label>
        </div>
      </section>

      <section className="panel" data-testid="crane-list">
        <h3>塔吊</h3>
        <div className="panel-body">
          {cranes.length === 0 ? (
            <span className="muted">无</span>
          ) : (
            cranes.map((c, i) => {
              const id = (c as { crane_id?: string }).crane_id ?? "?";
              const selected = ui.selectedCraneId === id;
              const following = ui.followCraneId === id;
              return (
                <div
                  key={id}
                  className={`crane-list-item ${selected ? "row-selected" : ""}`}
                  onClick={() => setUI({ selectedCraneId: id })}
                >
                  <span className="swatch" style={{ background: craneColorCss(i) }} />
                  {id}
                  {following && <span className="chip" style={{ marginLeft: "auto" }}>跟随</span>}
                </div>
              );
            })
          )}
          {ui.selectedCraneId && (
            <button
              data-testid="follow-toggle"
              style={{ marginTop: 8, width: "100%" }}
              onClick={() =>
                setUI({
                  followCraneId: ui.followCraneId === ui.selectedCraneId ? null : ui.selectedCraneId,
                })
              }
            >
              {ui.followCraneId === ui.selectedCraneId ? "取消跟随" : `跟随 ${ui.selectedCraneId}`}
            </button>
          )}
        </div>
      </section>
    </div>
  );
}
