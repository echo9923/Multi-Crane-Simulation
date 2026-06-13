// Zone geometry for material_zones / work_zones / forbidden_zones. Supports the
// two backend shapes: "box" (axis-aligned, center+size) and "polygon" (2D XY
// footprint extruded over z_range_m). Unknown types yield an empty group.

import * as THREE from "three";
import type { ZoneConfig } from "@/types/config";
import { worldToThree } from "@/coord";

export type ZoneKind = "material" | "work" | "forbidden" | "overlap";

export const ZONE_COLOR: Record<ZoneKind, number> = {
  material: 0x3a7bd5,
  work: 0x2fbf71,
  forbidden: 0xe5524a,
  overlap: 0x8b5cf6,
};

function verticalExtent(
  centerZ: number | undefined,
  sizeZ: number | undefined,
  zRange: [number, number] | null | undefined,
): [number, number] {
  if (zRange && zRange.length === 2) return [zRange[0], zRange[1]];
  const cz = centerZ ?? 0;
  const sz = sizeZ ?? 1;
  return [cz - sz / 2, cz + sz / 2];
}

function makeOutline(mesh: THREE.Mesh, color: number): THREE.LineSegments {
  const edges = new THREE.LineSegments(
    new THREE.EdgesGeometry(mesh.geometry),
    new THREE.LineBasicMaterial({ color, transparent: true, opacity: 0.8 }),
  );
  edges.position.copy(mesh.position);
  edges.rotation.copy(mesh.rotation);
  return edges;
}

export function buildZone(zone: ZoneConfig, kind: ZoneKind): THREE.Object3D {
  const group = new THREE.Group();
  group.name = `zone:${kind}:${zone.zone_id}`;
  const color = ZONE_COLOR[kind];
  const mat = new THREE.MeshBasicMaterial({
    color,
    transparent: true,
    opacity: 0.22,
    depthWrite: false,
    side: THREE.DoubleSide,
  });

  if (zone.type === "box") {
    const center = zone.center;
    const size = zone.size;
    if (!center || !size) return group;
    const [cx, cy, cz] = center;
    const [dx, dy, dz] = size;
    const [zmin, zmax] = verticalExtent(cz, dz, zone.z_range_m ?? null);
    const height = Math.max(0.05, zmax - zmin);
    // Three box dims: x=east(dx), y=up(height), z=north(dy).
    const geo = new THREE.BoxGeometry(dx, height, dy);
    const mesh = new THREE.Mesh(geo, mat);
    const midZ = (zmin + zmax) / 2;
    mesh.position.set(...worldToThree([cx, cy, midZ]));
    group.add(mesh);
    group.add(makeOutline(mesh, color));
    return group;
  }

  if (zone.type === "polygon") {
    const raw = zone.points ?? [];
    const pts = raw.map((p) => [p[0], p[1]] as [number, number]);
    if (pts.length < 3) return group;
    const [zmin, zmax] = zone.z_range_m ? [zone.z_range_m[0], zone.z_range_m[1]] : [0, 0.5];
    const depth = Math.max(0.05, zmax - zmin);
    const shape = new THREE.Shape();
    pts.forEach((p, i) => (i === 0 ? shape.moveTo(p[0], p[1]) : shape.lineTo(p[0], p[1])));
    shape.closePath();
    const geo = new THREE.ExtrudeGeometry(shape, { depth, bevelEnabled: false, steps: 1 });
    const mesh = new THREE.Mesh(geo, mat);
    // Lay the extruded footprint flat: rotation.x = -PI/2 maps the shape's XY
    // (east,north) onto the Three X-(−Z) ground plane and the extrusion +Z onto +Y.
    mesh.rotation.x = -Math.PI / 2;
    mesh.position.set(0, zmin, 0);
    group.add(mesh);
    group.add(makeOutline(mesh, color));
    return group;
  }

  // Unsupported shape: empty group (caller may warn).
  return group;
}
