// Task-route descriptors: for each crane that has an active task with known
// pickup and dropoff zones, a pickup→dropoff segment colored by the crane.
// Pure — no Three.js here; the controller turns routes into arrow objects.

import type { SimFrame } from "@/types/sim";
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
  for (const c of frame.cranes) {
    if (c.task_id == null) continue;
    if (!c.pickup_zone_id || !c.dropoff_zone_id) continue;
    const from = zoneCenter.get(c.pickup_zone_id);
    const to = zoneCenter.get(c.dropoff_zone_id);
    if (!from || !to) continue;
    routes.push({
      craneId: c.crane_id,
      taskId: String(c.task_id),
      from,
      to,
      color: craneColor.get(c.crane_id) ?? 0x2563eb,
    });
  }
  return routes;
}
