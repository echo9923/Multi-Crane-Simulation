import * as THREE from "three";
import type { BuildingConfig, ZoneConfig } from "@/types/config";

type FootprintPoint = [number, number] | [number, number, number];

const FLOOR_COLOR = 0x9aa6b2;

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
): THREE.Object3D | null {
  const shape = footprintShape(footprint);
  if (!shape) return null;
  const geo = new THREE.ShapeGeometry(shape);
  const mat = new THREE.MeshBasicMaterial({
    color,
    transparent: true,
    opacity: 0.16,
    side: THREE.DoubleSide,
    depthWrite: false,
  });
  const mesh = new THREE.Mesh(geo, mat);
  mesh.name = name;
  mesh.rotation.x = -Math.PI / 2;
  mesh.position.set(0, surfaceZ, 0);
  return mesh;
}

export function buildBuildingFloors(buildings: BuildingConfig[] = []): THREE.Group {
  const group = new THREE.Group();
  group.name = "floors";
  for (const building of buildings) {
    for (let level = 1; level <= building.floors; level += 1) {
      const surfaceZ = building.base_z_m + level * building.floor_height_m;
      const plate = makeFloorPlate(
        `floor:${building.building_id}:level_${level}`,
        building.footprint as FootprintPoint[],
        surfaceZ,
      );
      if (plate) group.add(plate);
    }
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
  }
  return group;
}
