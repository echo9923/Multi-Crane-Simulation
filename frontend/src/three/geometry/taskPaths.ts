// Task-route descriptors: for each crane that has an active task with known
// pickup and dropoff zones, a pickup→dropoff segment colored by the crane.
// Pure — no Three.js here; the controller turns routes into arrow objects.

import type { SimFrame, SimFrameCrane } from "@/types/sim";
import type { Vec3 } from "@/coord";

export interface TaskRoute {
  craneId: string;
  taskId: string;
  /** Pickup zone world center (ENU). */
  from: Vec3;
  /** Dropoff zone world center (ENU). */
  to: Vec3;
  color: number;
}

/** A stable key so the controller can skip rebuilding an unchanged arrow. */
export function routeKey(r: TaskRoute): string {
  return `${r.taskId}|${r.from.join(",")}|${r.to.join(",")}|${r.color}`;
}

export function buildTaskRoutes(
  frame: SimFrame,
  zoneCenter: Map<string, Vec3>,
  craneColor: Map<string, number>,
): TaskRoute[] {
  const routes: TaskRoute[] = [];
  const activeTasks = activeTasksByCrane(frame);
  for (const c of frame.cranes) {
    if (c.task_id == null && c.task_stage === "idle") continue;
    const task = activeTasks.get(c.crane_id);
    const taskId = task?.task_id ?? task?.id ?? c.task_id;
    if (taskId == null) continue;
    const pickupZoneId = stringValue(task?.pickup_zone_id ?? pointRecord(task?.pickup)?.zone_id ?? c.pickup_zone_id);
    const dropoffZoneId = stringValue(task?.dropoff_zone_id ?? pointRecord(task?.dropoff)?.zone_id ?? c.dropoff_zone_id);
    const from = pointVec(task?.pickup) ?? (pickupZoneId ? zoneCenter.get(pickupZoneId) : undefined);
    const to = pointVec(task?.dropoff) ?? (dropoffZoneId ? zoneCenter.get(dropoffZoneId) : undefined);
    if (!from || !to) continue;
    routes.push({
      craneId: c.crane_id,
      taskId: String(taskId),
      from,
      to,
      color: craneColor.get(c.crane_id) ?? 0x2563eb,
    });
  }
  return routes;
}

type LooseRecord = Record<string, unknown>;

function activeTasksByCrane(frame: SimFrame): Map<string, LooseRecord> {
  const result = new Map<string, LooseRecord>();
  const cranes = new Map(frame.cranes.map((crane) => [crane.crane_id, crane]));
  for (const queue of frame.tasks) {
    if (!isRecord(queue)) continue;
    const craneId = stringValue(queue.crane_id);
    const crane = craneId ? cranes.get(craneId) : undefined;
    const nestedTasks = Array.isArray(queue.tasks) ? queue.tasks.filter(isRecord) : [];
    if (nestedTasks.length === 0) {
      if (craneId && (queue.task_id != null || queue.id != null)) result.set(craneId, queue);
      continue;
    }
    const activeTaskId = stringValue(queue.active_task_id);
    const active =
      nestedTasks.find((task) => stringValue(task.task_id ?? task.id) === activeTaskId) ??
      nestedTasks.find((task) => stringValue(task.task_id ?? task.id) === crane?.task_id) ??
      nestedTasks.find((task) => task.status === "active");
    if (!active) continue;
    const taskCraneId = stringValue(active.crane_id) ?? craneId;
    if (taskCraneId) result.set(taskCraneId, active);
  }
  for (const crane of frame.cranes) {
    if (!result.has(crane.crane_id) && crane.task_id != null) {
      result.set(crane.crane_id, taskFromCrane(crane));
    }
  }
  for (const craneId of Array.from(result.keys())) {
    if (!cranes.has(craneId)) result.delete(craneId);
  }
  return result;
}

function taskFromCrane(crane: SimFrameCrane): LooseRecord {
  return {
    task_id: crane.task_id,
    crane_id: crane.crane_id,
    pickup_zone_id: crane.pickup_zone_id,
    dropoff_zone_id: crane.dropoff_zone_id,
  };
}

function isRecord(value: unknown): value is LooseRecord {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function pointRecord(value: unknown): LooseRecord | null {
  return isRecord(value) ? value : null;
}

function stringValue(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 ? value : null;
}

function pointVec(value: unknown): Vec3 | null {
  const point = pointRecord(value);
  if (!point) return null;
  const x = numberValue(point.x);
  const y = numberValue(point.y);
  const z =
    numberValue(point.hook_target_z_m) ??
    numberValue(point.z) ??
    numberValue(point.surface_z_m);
  return x == null || y == null || z == null ? null : [x, y, z];
}

function numberValue(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}
