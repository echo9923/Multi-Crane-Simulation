// Left controls: display toggles + crane list (click to select; follow comes in
// Task 08). Selected crane drives panel highlighting and the 3D pick state.

import { useStore } from "@/state/store";
import { LoadEpisode } from "@/components/LoadEpisode";

export function LeftControls() {
  const ui = useStore((s) => s.ui);
  const setUI = useStore((s) => s.setUI);
  const cranes = useStore((s) => s.latestFrame?.cranes ?? s.manifest?.cranes ?? []);

  return (
    <div>
      <LoadEpisode />
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
        </div>
      </section>

      <section className="panel" data-testid="crane-list">
        <h3>塔吊</h3>
        <div className="panel-body">
          {cranes.length === 0 ? (
            <span className="muted">无</span>
          ) : (
            cranes.map((c) => {
              const id = (c as { crane_id?: string }).crane_id ?? "?";
              const selected = ui.selectedCraneId === id;
              return (
                <div
                  key={id}
                  className={`crane-list-item ${selected ? "row-selected" : ""}`}
                  onClick={() => setUI({ selectedCraneId: id })}
                >
                  <span className="swatch" style={{ background: "#4cc2ff" }} />
                  {id}
                </div>
              );
            })
          )}
        </div>
      </section>
    </div>
  );
}
