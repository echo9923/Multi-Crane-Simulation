// Per-crane status table. Reads the current frame. theta_rad shown in degrees
// (converted for display only — the scene is driven by world coords).

import { useStore } from "@/state/store";
import { hexCss } from "@/ui/risk";

export function CraneStatusPanel() {
  const frame = useStore((s) => s.latestFrame);
  const selectedId = useStore((s) => s.ui.selectedCraneId);
  const select = useStore((s) => s.setUI);
  const cranes = frame?.cranes ?? [];

  return (
    <section className="panel" data-testid="crane-status">
      <h3>塔吊状态（{cranes.length}）</h3>
      <div className="panel-body">
        {cranes.length === 0 ? (
          <span className="muted">无塔吊数据</span>
        ) : (
          <table className="grid">
            <thead>
              <tr>
                <th></th>
                <th>ID</th>
                <th>回转°</th>
                <th>小车m</th>
                <th>钩高m</th>
                <th>阶段</th>
                <th>载荷</th>
              </tr>
            </thead>
            <tbody>
              {cranes.map((c, i) => {
                const selected = c.crane_id === selectedId;
                return (
                  <tr
                    key={c.crane_id}
                    className={`clickable ${selected ? "row-selected" : ""}`}
                    onClick={() => select({ selectedCraneId: c.crane_id })}
                  >
                    <td>
                      <span
                        className="swatch"
                        style={{ background: hexCss(0x4cc2ff + ((i * 0x3333) % 0xbbbb)) }}
                      />
                    </td>
                    <td>{c.crane_id}</td>
                    <td>{((c.theta_rad * 180) / Math.PI).toFixed(1)}</td>
                    <td>{c.trolley_r_m.toFixed(1)}</td>
                    <td>{c.hook_h_m.toFixed(1)}</td>
                    <td>
                      <span className="chip">{c.task_stage}</span>
                    </td>
                    <td>{c.load_attached ? c.load_type ?? "—" : "—"}</td>
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
