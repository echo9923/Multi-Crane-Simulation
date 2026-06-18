import * as THREE from "three";
import type { BuildingConfig, ZoneConfig } from "@/types/config";
import { makeTextSprite } from "./labels";

type FootprintPoint = [number, number] | [number, number, number];

const FLOOR_COLOR = 0x9aa6b2;
const FLOOR_COLOR_ALT = 0xb0bac6; // alternate tint so adjacent slabs read apart
const OUTLINE_COLOR = 0x475569;
const FLOOR_LABEL_COLOR = "#334155";

// Billboarded floor-number label at a footprint corner. Returns null in
// headless/jsdom environments (no 2D canvas backend); callers skip it.
function makeFloorLabel(
  text: string,
  anchor: FootprintPoint,
  z: number,
): THREE.Sprite | null {
  const sprite = makeTextSprite(text, {
    color: FLOOR_LABEL_COLOR,
    background: "rgba(255,255,255,0.82)",
    worldHeight: 2.6,
  });
  if (!sprite) return null;
  // ENU (x east, y north, z up) → Three (x, z, -y).
  sprite.position.set(anchor[0], z + 1.4, -anchor[1]);
  sprite.name = `floorlabel:${text}`;
  return sprite;
}

function footprintShape(points: FootprintPoint[]): THREE.Shape | null {
  if (points.length < 3) return null;
  const shape = new THREE.Shape();
  points.forEach((point, index) => {
    if (index === 0) shape.moveTo(point[0], point[1]);
    else shape.lineTo(point[0], point[1]);
  });
  shape.closePath();
  return shape;
}

function makeFloorPlate(
  name: string,
  footprint: FootprintPoint[],
  surfaceZ: number,
  color = FLOOR_COLOR,
): THREE.Group | null {
  const shape = footprintShape(footprint);
  if (!shape) return null;
  const group = new THREE.Group();
  group.name = name;
  group.position.set(0, surfaceZ, 0);
  const geo = new THREE.ShapeGeometry(shape);
  const mat = new THREE.MeshBasicMaterial({
    color,
    transparent: true,
    opacity: 0.22,
    side: THREE.DoubleSide,
    depthWrite: false,
  });
  const mesh = new THREE.Mesh(geo, mat);
  mesh.name = `${name}:plate`;
  mesh.rotation.x = -Math.PI / 2;
  group.add(mesh);

  const outlinePoints: number[] = [];
  for (let index = 0; index < footprint.length; index += 1) {
    const current = footprint[index];
    const next = footprint[(index + 1) % footprint.length];
    outlinePoints.push(current[0], 0.03, -current[1]);
    outlinePoints.push(next[0], 0.03, -next[1]);
  }
  const outlineGeo = new THREE.BufferGeometry();
  outlineGeo.setAttribute(
    "position",
    new THREE.BufferAttribute(new Float32Array(outlinePoints), 3),
  );
  const outline = new THREE.LineSegments(
    outlineGeo,
    new THREE.LineBasicMaterial({ color: OUTLINE_COLOR, transparent: true, opacity: 0.72 }),
  );
  outline.name = `${name}:outline`;
  group.add(outline);
  return group;
}

function makeBuildingEnvelope(
  buildingId: string,
  footprint: FootprintPoint[],
  baseZ: number,
  topZ: number,
): THREE.LineSegments | null {
  if (footprint.length < 3) return null;
  const points: number[] = [];
  for (let index = 0; index < footprint.length; index += 1) {
    const current = footprint[index];
    const next = footprint[(index + 1) % footprint.length];
    points.push(current[0], baseZ, -current[1]);
    points.push(current[0], topZ, -current[1]);
    points.push(current[0], topZ, -current[1]);
    points.push(next[0], topZ, -next[1]);
  }
  const geo = new THREE.BufferGeometry();
  geo.setAttribute("position", new THREE.BufferAttribute(new Float32Array(points), 3));
  const envelope = new THREE.LineSegments(
    geo,
    new THREE.LineBasicMaterial({ color: OUTLINE_COLOR, transparent: true, opacity: 0.55 }),
  );
  envelope.name = `building:${buildingId}:envelope`;
  return envelope;
}

export function buildBuildingFloors(buildings: BuildingConfig[] = []): THREE.Group {
  const group = new THREE.Group();
  group.name = "floors";
  for (const building of buildings) {
    const footprint = building.footprint as FootprintPoint[];
    for (let level = 1; level <= building.floors; level += 1) {
      const surfaceZ = building.base_z_m + level * building.floor_height_m;
      const tint = level % 2 === 0 ? FLOOR_COLOR_ALT : FLOOR_COLOR;
      const plate = makeFloorPlate(
        `floor:${building.building_id}:level_${level}`,
        footprint,
        surfaceZ,
        tint,
      );
      if (plate) group.add(plate);
      const text = level === building.floors ? "屋面" : `${level}层`;
      const label = makeFloorLabel(text, footprint[0], surfaceZ);
      if (label) group.add(label);
    }
    const envelope = makeBuildingEnvelope(
      building.building_id,
      footprint,
      building.base_z_m,
      building.base_z_m + building.floors * building.floor_height_m,
    );
    if (envelope) group.add(envelope);
  }
  return group;
}

export function buildInferredZoneFloors(zones: ZoneConfig[] = []): THREE.Group {
  const group = new THREE.Group();
  group.name = "floors";
  const seen = new Set<string>();
  for (const zone of zones) {
    if (typeof zone.surface_z_m !== "number" || !Number.isFinite(zone.surface_z_m)) {
      continue;
    }
    const floorId = zone.floor_id ?? zone.zone_id;
    const key = `${zone.building_id ?? "site"}:${floorId}:${zone.surface_z_m}`;
    if (seen.has(key)) continue;
    seen.add(key);

    let footprint: FootprintPoint[] | null = null;
    if (zone.points && zone.points.length >= 3) {
      footprint = zone.points as FootprintPoint[];
    } else if (zone.center && zone.size) {
      const [cx, cy] = zone.center;
      const [sx, sy] = zone.size;
      footprint = [
        [cx - sx / 2, cy - sy / 2],
        [cx + sx / 2, cy - sy / 2],
        [cx + sx / 2, cy + sy / 2],
        [cx - sx / 2, cy + sy / 2],
      ];
    }
    if (!footprint) continue;
    const plate = makeFloorPlate(
      `floor:${zone.building_id ?? "site"}:${floorId}`,
      footprint,
      zone.surface_z_m,
      zone.zone_role === "roof" ? 0xb9c2cc : FLOOR_COLOR,
    );
    if (plate) group.add(plate);
    const label = makeFloorLabel(
      zone.zone_role === "roof" ? "屋面" : String(floorId),
      footprint[0],
      zone.surface_z_m,
    );
    if (label) group.add(label);
  }
  return group;
}
