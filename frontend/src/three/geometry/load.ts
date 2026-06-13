// Simplified load/cargo geometry. Dispatches on load_type.shape and uses
// load_size_m ([east, north, up] metres). Unknown shapes fall back to a
// bounding box so the load is still visible.

import * as THREE from "three";
import type { LoadShape } from "@/types/sim";
import type { Vec3 } from "@/coord";

function clampMin(v: number, min: number): number {
  return Number.isFinite(v) && v > min ? v : min;
}

export function buildLoad(shape: LoadShape | null, size: Vec3 | null): THREE.Mesh {
  const s: Vec3 = size && size.length === 3 ? size : [1, 1, 1];
  let geo: THREE.BufferGeometry;
  if (shape === "cylinder") {
    const r = clampMin(Math.min(s[0], s[1]) / 2, 0.1);
    geo = new THREE.CylinderGeometry(r, r, clampMin(s[2], 0.1), 16);
  } else {
    // box_long, flat_box, beam, and unknown fallback -> box.
    // Three dims: x=east(s0), y=up(s2), z=north(s1).
    geo = new THREE.BoxGeometry(clampMin(s[0], 0.1), clampMin(s[2], 0.1), clampMin(s[1], 0.1));
  }
  const mat = new THREE.MeshStandardMaterial({
    color: 0xc89b3c,
    metalness: 0.15,
    roughness: 0.75,
  });
  return new THREE.Mesh(geo, mat);
}

// Offset so the load hangs below the hook block (top flush at the slot origin).
export function loadHangOffsetY(size: Vec3 | null): number {
  const s: Vec3 = size && size.length === 3 ? size : [1, 1, 1];
  return -clampMin(s[2], 0.1) / 2;
}
