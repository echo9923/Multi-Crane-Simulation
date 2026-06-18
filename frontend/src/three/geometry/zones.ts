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
  surfaceZ: number | null | undefined,
): [number, number] {
  if (typeof surfaceZ === "number" && Number.isFinite(surfaceZ)) {
    const thickness = zRange && zRange.length === 2
      ? Math.max(0.05, zRange[1] - zRange[0])
      : Math.max(0.05, sizeZ ?? 0.4);
    return [surfaceZ, surfaceZ + thickness];
  }
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

function makeFootprintBox(dx: number, dy: number, color: number): THREE.Mesh {
  const geo = new THREE.PlaneGeometry(dx, dy);
  const mat = new THREE.MeshBasicMaterial({
    color,
    transparent: true,
    opacity: 0.28,
    depthWrite: false,
    side: THREE.DoubleSide,
  });
  const footprint = new THREE.Mesh(geo, mat);
  footprint.name = "zone-footprint";
  footprint.rotation.x = -Math.PI / 2;
  return footprint;
}

function makeHeightPost(height: number, color: number): THREE.LineSegments {
  const h = Math.max(0.05, height);
  const points = new Float32Array([
    0, 0, 0,
    0, h, 0,
  ]);
  const geo = new THREE.BufferGeometry();
  geo.setAttribute("position", new THREE.BufferAttribute(points, 3));
  const mat = new THREE.LineBasicMaterial({ color, transparent: true, opacity: 0.9 });
  const post = new THREE.LineSegments(geo, mat);
  post.name = "zone-height-post";
  return post;
}

function makeSurfaceBand(dx: number, dy: number, color: number): THREE.LineSegments {
  const x = dx / 2;
  const z = dy / 2;
  const points = new Float32Array([
    -x, 0, -z, x, 0, -z,
    x, 0, -z, x, 0, z,
    x, 0, z, -x, 0, z,
    -x, 0, z, -x, 0, -z,
  ]);
  const geo = new THREE.BufferGeometry();
  geo.setAttribute("position", new THREE.BufferAttribute(points, 3));
  const mat = new THREE.LineBasicMaterial({ color, transparent: true, opacity: 1 });
  const band = new THREE.LineSegments(geo, mat);
  band.name = "zone-surface-band";
  return band;
}

function makeFootprintPolygon(
  pts: [number, number][],
  color: number,
): THREE.Mesh {
  const shape = new THREE.Shape();
  pts.forEach((p, i) => (i === 0 ? shape.moveTo(p[0], p[1]) : shape.lineTo(p[0], p[1])));
  shape.closePath();
  const geo = new THREE.ShapeGeometry(shape);
  const mat = new THREE.MeshBasicMaterial({
    color,
    transparent: true,
    opacity: 0.28,
    depthWrite: false,
    side: THREE.DoubleSide,
  });
  const footprint = new THREE.Mesh(geo, mat);
  footprint.name = "zone-footprint";
  footprint.rotation.x = -Math.PI / 2;
  return footprint;
}

function makeSurfacePolygonBand(
  pts: [number, number][],
  color: number,
): THREE.LineSegments {
  const points: number[] = [];
  for (let index = 0; index < pts.length; index += 1) {
    const current = pts[index];
    const next = pts[(index + 1) % pts.length];
    points.push(current[0], 0, -current[1]);
    points.push(next[0], 0, -next[1]);
  }
  const geo = new THREE.BufferGeometry();
  geo.setAttribute("position", new THREE.BufferAttribute(new Float32Array(points), 3));
  const mat = new THREE.LineBasicMaterial({ color, transparent: true, opacity: 1 });
  const band = new THREE.LineSegments(geo, mat);
  band.name = "zone-surface-band";
  return band;
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
    const [zmin, zmax] = verticalExtent(cz, dz, zone.z_range_m ?? null, zone.surface_z_m);
    const height = Math.max(0.05, zmax - zmin);
    // Three box dims: x=east(dx), y=up(height), z=north(dy).
    const geo = new THREE.BoxGeometry(dx, height, dy);
    const mesh = new THREE.Mesh(geo, mat);
    mesh.name = "zone-volume";
    const midZ = (zmin + zmax) / 2;
    mesh.position.set(...worldToThree([cx, cy, midZ]));
    group.add(mesh);
    group.add(makeOutline(mesh, color));
    const footprint = makeFootprintBox(dx, dy, color);
    footprint.position.set(...worldToThree([cx, cy, 0.02]));
    group.add(footprint);
    const band = makeSurfaceBand(dx, dy, color);
    band.position.set(...worldToThree([cx, cy, zmin]));
    group.add(band);
    const post = makeHeightPost(zmax, color);
    post.position.set(...worldToThree([cx, cy, 0]));
    group.add(post);
    return group;
  }

  if (zone.type === "polygon") {
    const raw = zone.points ?? [];
    const pts = raw.map((p) => [p[0], p[1]] as [number, number]);
    if (pts.length < 3) return group;
    const [zmin, zmax] = verticalExtent(undefined, 0.5, zone.z_range_m ?? null, zone.surface_z_m);
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
    const footprint = makeFootprintPolygon(pts, color);
    footprint.position.y = 0.02;
    group.add(footprint);
    const band = makeSurfacePolygonBand(pts, color);
    band.position.y = zmin;
    group.add(band);
    const centroid = pts.reduce(
      (acc, point) => [acc[0] + point[0] / pts.length, acc[1] + point[1] / pts.length],
      [0, 0],
    );
    const post = makeHeightPost(zmax, color);
    post.position.set(centroid[0], 0, -centroid[1]);
    group.add(post);
    return group;
  }

  // Unsupported shape: empty group (caller may warn).
  return group;
}
