// Task status from frame task payloads, with compatibility fallback for older
// visual frames that only carry crane-level task fields.

import { useStore } from "@/state/store";
import type { SimFrame, SimFrameCrane } from "@/types/sim";

type LooseRecord = Record<string, unknown>;

interface TaskRow {
  key: string;
  id: unknown;
  craneId: unknown;
  type: unknown;
  stage: unknown;
  priority: unknown;
  deadlineS: unknown;
}

function str(v: unknown): string {
  return v == null ? "—" : String(v);
}

function isRecord(value: unknown): value is LooseRecord {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function recordArray(value: unknown): LooseRecord[] {
  return Array.isArray(value) ? value.filter(isRecord) : [];
}

function rowFromTask(task: LooseRecord, fallbackCraneId: unknown, index: number): TaskRow {
  const id = task.task_id ?? task.id;
  const craneId = task.crane_id ?? fallbackCraneId;
  const stage = task.stage ?? task.task_stage ?? task.status;
  return {
    key: str(id ?? `${craneId ?? "task"}-${stage ?? index}`),
    id,
    craneId,
    type: task.type ?? task.task_type ?? task.load_type,
    stage,
    priority: task.priority,
    deadlineS: task.deadline_s,
  };
}

function explicitTaskRows(tasks: LooseRecord[]): TaskRow[] {
  const rows: TaskRow[] = [];
  for (const [index, task] of tasks.entries()) {
    const nestedTasks = recordArray(task.tasks);
    if (nestedTasks.length > 0) {
      nestedTasks.forEach((nestedTask, nestedIndex) => {
        rows.push(rowFromTask(nestedTask, task.crane_id, nestedIndex));
      });
      continue;
    }
    rows.push(rowFromTask(task, task.crane_id, index));
  }
  return dedupeRows(rows);
}

function fallbackRowsFromCranes(cranes: SimFrameCrane[]): TaskRow[] {
  return dedupeRows(
    cranes
      .filter((crane) => crane.task_id != null || crane.task_stage !== "idle")
      .map((crane) => ({
        key: str(crane.task_id ?? `${crane.crane_id}-${crane.task_stage}`),
        id: crane.task_id,
        craneId: crane.crane_id,
        type: crane.load_type,
        stage: crane.task_stage,
        priority: null,
        deadlineS: null,
      })),
  );
}

function dedupeRows(rows: TaskRow[]): TaskRow[] {
  const seen = new Set<string>();
  const unique: TaskRow[] = [];
  for (const row of rows) {
    const key = str(row.id ?? `${row.craneId}-${row.stage}`);
    if (seen.has(key)) continue;
    seen.add(key);
    unique.push({ ...row, key });
  }
  return unique;
}

function taskRowsForFrame(frame: SimFrame | null): TaskRow[] {
  if (!frame) return [];
  const rows = explicitTaskRows(frame.tasks);
  return rows.length > 0 ? rows : fallbackRowsFromCranes(frame.cranes);
}

export function TaskStatusPanel() {
  const frame = useStore((s) => s.latestFrame);
  const tasks = taskRowsForFrame(frame);

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
                <th>塔吊</th>
                <th>类型</th>
                <th>阶段</th>
                <th>优先级</th>
                <th>截止s</th>
              </tr>
            </thead>
            <tbody>
              {tasks.map((t, i) => (
                <tr key={t.key || String(i)}>
                  <td>{str(t.id)}</td>
                  <td>{str(t.craneId)}</td>
                  <td>{str(t.type)}</td>
                  <td>{str(t.stage)}</td>
                  <td>{str(t.priority)}</td>
                  <td>{str(t.deadlineS)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </section>
  );
}
