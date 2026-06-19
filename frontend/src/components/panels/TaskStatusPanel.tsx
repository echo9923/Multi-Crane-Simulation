// Task status from frame task payloads, with compatibility fallback for older
// visual frames that only carry crane-level task fields. Zone ids are enriched
// with floor info from the manifest/config so a dropoff reads "roof_dropoff（屋面）".

import { useMemo } from "react";
import { useStore } from "@/state/store";
import type { SimFrame, SimFrameCrane } from "@/types/sim";

type LooseRecord = Record<string, unknown>;

interface TaskRow {
  key: string;
  id: unknown;
  craneId: unknown;
  type: unknown;
  loadType: unknown;
  stage: unknown;
  priority: unknown;
  deadlineS: unknown;
  pickupZoneId: unknown;
  dropoffZoneId: unknown;
  pickupFloorId: unknown;
  dropoffFloorId: unknown;
  pickupSurfaceZ: unknown;
  dropoffSurfaceZ: unknown;
  pickupHookTargetZ: unknown;
  dropoffHookTargetZ: unknown;
}

// Backend task_stage values → readable Chinese. The raw value is also rendered
// (faint) so it stays greppable and panel tests keep matching it.
const STAGE_LABEL: Record<string, string> = {
  idle: "空闲",
  move_to_pickup: "去取货",
  align_pickup: "取货对位",
  lower_for_attach: "下放挂钩",
  attach_pending: "挂钩中",
  lift_load: "起吊",
  move_to_dropoff: "去卸货",
  align_dropoff: "卸货对位",
  lower_for_release: "下放卸货",
  release_pending: "释放中",
  recovery_release: "应急释放",
};

interface ZoneInfo {
  floorId?: unknown;
  levelIndex?: unknown;
  zoneRole?: unknown;
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
  const pickup = isRecord(task.pickup) ? task.pickup : {};
  const dropoff = isRecord(task.dropoff) ? task.dropoff : {};
  return {
    key: str(id ?? `${craneId ?? "task"}-${stage ?? index}`),
    id,
    craneId,
    type: task.type ?? task.task_type ?? task.load_type,
    loadType: task.load_type ?? dropoff.load_type ?? pickup.load_type,
    stage,
    priority: task.priority,
    deadlineS: task.deadline_s,
    pickupZoneId: task.pickup_zone_id ?? pickup.zone_id,
    dropoffZoneId: task.dropoff_zone_id ?? dropoff.zone_id,
    pickupFloorId: pickup.floor_id ?? task.pickup_floor_id,
    dropoffFloorId: dropoff.floor_id ?? task.dropoff_floor_id,
    pickupSurfaceZ: pickup.surface_z_m ?? task.pickup_surface_z_m,
    dropoffSurfaceZ: dropoff.surface_z_m ?? task.dropoff_surface_z_m,
    pickupHookTargetZ: pickup.hook_target_z_m ?? task.pickup_hook_target_z_m,
    dropoffHookTargetZ: dropoff.hook_target_z_m ?? task.dropoff_hook_target_z_m,
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
    if (isEmptyQueueShell(task)) continue;
    rows.push(rowFromTask(task, task.crane_id, index));
  }
  return dedupeRows(rows);
}

function isEmptyQueueShell(task: LooseRecord): boolean {
  return (
    Array.isArray(task.tasks) &&
    task.tasks.length === 0 &&
    task.task_id == null &&
    task.id == null &&
    task.stage == null &&
    task.task_stage == null &&
    task.status == null
  );
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
        loadType: crane.load_type,
        stage: crane.task_stage,
        priority: null,
        deadlineS: null,
        pickupZoneId: crane.pickup_zone_id,
        dropoffZoneId: crane.dropoff_zone_id,
        pickupFloorId: null,
        dropoffFloorId: null,
        pickupSurfaceZ: null,
        dropoffSurfaceZ: null,
        pickupHookTargetZ: null,
        dropoffHookTargetZ: null,
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

function stageCell(stage: unknown) {
  if (stage == null) return <>—</>;
  const raw = String(stage);
  const label = STAGE_LABEL[raw];
  if (!label) return <>{raw}</>;
  return (
    <>
      {label} <span className="faint">{raw}</span>
    </>
  );
}

export function TaskStatusPanel() {
  const frame = useStore((s) => s.latestFrame);
  const manifest = useStore((s) => s.manifest);
  const config = useStore((s) => s.config);
  const tasks = taskRowsForFrame(frame);

  // zone_id → floor/role info, merged from config site and/or manifest lists.
  const zoneIndex = useMemo(() => {
    const index = new Map<string, ZoneInfo>();
    const add = (zones: LooseRecord[] | undefined) => {
      for (const z of zones ?? []) {
        const id = z.zone_id;
        if (typeof id !== "string") continue;
        index.set(id, {
          floorId: z.floor_id,
          levelIndex: z.level_index,
          zoneRole: z.zone_role,
        });
      }
    };
    const site = (config?.scenario?.site ?? null) as LooseRecord | null;
    if (site) {
      add(recordArray(site.material_zones));
      add(recordArray(site.work_zones));
      add(recordArray(site.forbidden_zones));
    }
    const frameSite = frame?.site as LooseRecord | undefined;
    if (frameSite) {
      add(recordArray(frameSite.material_zones));
      add(recordArray(frameSite.work_zones));
      add(recordArray(frameSite.forbidden_zones));
      add(recordArray(frameSite.overlap_zones));
    }
    if (manifest) {
      add(recordArray(manifest.material_zones));
      add(recordArray(manifest.work_zones));
      add(recordArray(manifest.forbidden_zones));
      add(recordArray(manifest.overlap_zones));
      const mSite = manifest.site as LooseRecord | undefined;
      if (mSite) {
        add(recordArray(mSite.material_zones));
        add(recordArray(mSite.work_zones));
        add(recordArray(mSite.forbidden_zones));
      }
    }
    return index;
  }, [config, frame, manifest]);

  const zoneCell = (zoneId: unknown) => {
    if (zoneId == null) return "—";
    const id = String(zoneId);
    const info = zoneIndex.get(id);
    if (!info) return id;
    if (info.zoneRole === "roof") return `${id}（屋面）`;
    if (info.levelIndex != null) return `${id}（${info.levelIndex}层）`;
    if (info.floorId != null) return `${id}（${info.floorId}）`;
    return id;
  };

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
                <th>载荷</th>
                <th>阶段</th>
                <th>取货区</th>
                <th>卸货区</th>
                <th>取货面</th>
                <th>卸货面</th>
                <th>吊钩目标</th>
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
                  <td>{str(t.loadType)}</td>
                  <td>{stageCell(t.stage)}</td>
                  <td>{zoneCell(t.pickupZoneId)}</td>
                  <td>{zoneCell(t.dropoffZoneId)}</td>
                  <td>{str(t.pickupFloorId)} / {str(t.pickupSurfaceZ)}</td>
                  <td>{str(t.dropoffFloorId)} / {str(t.dropoffSurfaceZ)}</td>
                  <td>{str(t.pickupHookTargetZ)} → {str(t.dropoffHookTargetZ)}</td>
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
