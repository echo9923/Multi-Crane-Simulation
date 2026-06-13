// Site boundary (AABB wireframe) and ground grid. Boundary is an axis-aligned
// box in ENU metres; rendered via Box3Helper in the mapped Three.js frame.

import * as THREE from "three";
import type { BoundaryConfig } from "@/types/config";
import { worldToThree } from "@/coord";

export function buildBoundary(boundary: BoundaryConfig): THREE.Object3D {
  const group = new THREE.Group();
  group.name = "site:boundary";

  const min = worldToThree([boundary.x_min, boundary.y_min, boundary.z_min]);
  const max = worldToThree([boundary.x_max, boundary.y_max, boundary.z_max]);
  const box = new THREE.Box3(new THREE.Vector3(...min), new THREE.Vector3(...max));
  const helper = new THREE.Box3Helper(box, 0x5a6473);
  helper.name = "site:boundary:box";
  group.add(helper);

  // Ground grid at z_min (world) — GridHelper lies in the XZ (Three) plane.
  const w = boundary.x_max - boundary.x_min;
  const h = boundary.y_max - boundary.y_min;
  const size = Math.max(w, h);
  if (size > 0) {
    const grid = new THREE.GridHelper(size, 24, 0x3a4150, 0x232831);
    const mx = (boundary.x_min + boundary.x_max) / 2;
    const my = (boundary.y_min + boundary.y_max) / 2;
    grid.position.set(mx, boundary.z_min, -my);
    grid.name = "site:ground";
    group.add(grid);
  }

  return group;
}
