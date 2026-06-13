// Task status from the current frame's tasks list. Fields are loose (the frame
// carries tasks as Record<string, unknown>); we render common keys defensively.

import { useStore } from "@/state/store";

function str(v: unknown): string {
  return v == null ? "—" : String(v);
}

export function TaskStatusPanel() {
  const frame = useStore((s) => s.latestFrame);
  const tasks = frame?.tasks ?? [];

  return (
    <section className="panel" data-testid="task-status">
      <h3>任务状态（{tasks.length}）</h3>
      <div className="panel-body">
        {tasks.length === 0 ? (
          <span className="muted">本帧无任务</span>
        ) : (
          <table className="grid">
            <thead>
              <tr>
                <th>ID</th>
                <th>类型</th>
                <th>阶段</th>
                <th>优先级</th>
                <th>截止s</th>
              </tr>
            </thead>
            <tbody>
              {tasks.map((t, i) => (
                <tr key={str(t.task_id ?? t.id ?? i)}>
                  <td>{str(t.task_id ?? t.id)}</td>
                  <td>{str(t.type)}</td>
                  <td>{str(t.stage ?? t.status)}</td>
                  <td>{str(t.priority)}</td>
                  <td>{str(t.deadline_s)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </section>
  );
}
