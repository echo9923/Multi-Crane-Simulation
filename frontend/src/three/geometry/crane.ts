// Procedural tower-crane geometry. All placement is derived from the crane
// config's world coordinates via worldToThree so the rendered scene matches the
// exported data. A glTF/GLB asset can replace the procedural body per crane_id
// or model_id via registerCraneAsset.

import * as THREE from "three";
import type { CraneConfig } from "@/types/config";
import { craneRadius } from "@/types/config";
import { worldToThree } from "@/coord";

export interface CraneParts {
  craneId: string;
  /** Root group, positioned at worldToThree(base); name = crane_id. */
  group: THREE.Group;
  /** Sits at the mast top (root) in the group's local frame; rotation.y = theta. */
  jibAssembly: THREE.Group;
  jib: THREE.Mesh;
  counterJib: THREE.Mesh;
  trolley: THREE.Mesh;
  /** Positioned in jibAssembly-local: (trolleyR, hookHWorld - rootZ, 0). */
  hook: THREE.Group;
  /** Child of hook; the load mesh (Task 03) is attached here. */
  loadSlot: THREE.Group;
  /** Horizontal working-radius circle at ground level around base. */
  radiusCircle: THREE.LineLoop;
  cable: THREE.Mesh;
  /** Whether this crane is backed by an injected glTF/GLB asset. */
  fromAsset: boolean;
}

// Saturated, mid-deep tones chosen to read clearly against the light viewport.
export const DEFAULT_CRANE_PALETTE = [
  0x2563eb, 0xd97706, 0x7c3aed, 0x0d9488, 0xdb2777, 0x4f46e5,
];

// Registry of replacement assets keyed by crane_id or model_id.
const assetRegistry = new Map<string, THREE.Object3D>();

export function registerCraneAsset(key: string, asset: THREE.Object3D): void {
  assetRegistry.set(key, asset);
}

export function clearCraneAssets(): void {
  assetRegistry.clear();
}

function assetFor(cfg: CraneConfig): THREE.Object3D | null {
  return assetRegistry.get(cfg.crane_id) ?? assetRegistry.get(cfg.model_id) ?? null;
}

function circlePoints(r: number, segments = 96): THREE.Vector3[] {
  const pts: THREE.Vector3[] = [];
  for (let i = 0; i < segments; i++) {
    const a = (i / segments) * Math.PI * 2;
    pts.push(new THREE.Vector3(Math.cos(a) * r, 0, Math.sin(a) * r));
  }
  return pts;
}

export function buildCrane(
  cfg: CraneConfig,
  opts: { color?: number } = {},
): CraneParts {
  const color = opts.color ?? DEFAULT_CRANE_PALETTE[0];
  const baseWorld = cfg.base;
  const rootWorld: [number, number, number] = [
    baseWorld[0],
    baseWorld[1],
    baseWorld[2] + cfg.mast_height_m,
  ];
  const mast = cfg.mast_height_m;
  const jibLen = cfg.jib_length_m;
  const counterLen = cfg.counter_jib_length_m;
  const radius = craneRadius(cfg);

  const group = new THREE.Group();
  group.name = cfg.crane_id;
  group.position.set(...worldToThree(baseWorld));

  const towerMat = new THREE.MeshStandardMaterial({ color: 0x9aa3b2, metalness: 0.2, roughness: 0.6 });
  const jibMat = new THREE.MeshStandardMaterial({ color, metalness: 0.2, roughness: 0.5 });
  const accentMat = new THREE.MeshStandardMaterial({ color: 0x2a313d, metalness: 0.3, roughness: 0.7 });

  const injected = assetFor(cfg);
  const fromAsset = injected !== null;

  if (injected) {
    // Use the provided asset as the whole crane body. Still expose named slots
    // so dynamic updates keep working; place them at sane defaults.
    const clone = injected.clone();
    clone.name = `${cfg.crane_id}:asset`;
    group.add(clone);

    const jibAssembly = new THREE.Group();
    jibAssembly.name = `${cfg.crane_id}:jibAssembly`;
    jibAssembly.position.set(0, mast, 0);
    group.add(jibAssembly);

    const placeholderGeo = new THREE.BoxGeometry(0.01, 0.01, 0.01);
    const jib = new THREE.Mesh(placeholderGeo, accentMat);
    const counterJib = new THREE.Mesh(placeholderGeo, accentMat);
    const trolley = new THREE.Mesh(placeholderGeo, accentMat);
    trolley.position.set(cfg.trolley_r_min_m, 0, 0);
    const hook = new THREE.Group();
    hook.position.set(cfg.trolley_r_min_m, cfg.hook_h_min_world_m - rootWorld[2], 0);
    const loadSlot = new THREE.Group();
    hook.add(loadSlot);
    [jib, counterJib, trolley, hook].forEach((o) => {
      o.visible = false;
      jibAssembly.add(o);
    });

    const circle = new THREE.LineLoop(
      new THREE.BufferGeometry().setFromPoints(circlePoints(radius)),
      new THREE.LineBasicMaterial({ color, transparent: true, opacity: 0.5 }),
    );
    group.add(circle);

    return { craneId: cfg.crane_id, group, jibAssembly, jib, counterJib, trolley, hook, loadSlot, radiusCircle: circle, cable: new THREE.Mesh(new THREE.BoxGeometry(0.001, 0.001, 0.001), accentMat), fromAsset };
  }

  // ---- procedural geometry ----

  // Tower (mast): vertical cylinder from base (y=0) up to mast height.
  const towerR = Math.max(0.5, Math.min(1.2, jibLen * 0.012));
  const tower = new THREE.Mesh(
    new THREE.CylinderGeometry(towerR * 0.7, towerR, mast, 12),
    towerMat,
  );
  tower.position.set(0, mast / 2, 0);
  group.add(tower);

  // Slewing ring / cab at the top.
  const cab = new THREE.Mesh(
    new THREE.CylinderGeometry(towerR * 1.4, towerR * 1.4, mast * 0.04, 12),
    accentMat,
  );
  cab.position.set(0, mast, 0);
  group.add(cab);

  // Jib assembly: pivots at the mast top. rotation.y = theta (radians, ENU).
  const jibAssembly = new THREE.Group();
  jibAssembly.name = `${cfg.crane_id}:jibAssembly`;
  jibAssembly.position.set(0, mast, 0);
  group.add(jibAssembly);

  const jibThickness = Math.max(0.4, jibLen * 0.02);
  const jibWidth = Math.max(0.6, jibLen * 0.03);

  const jib = new THREE.Mesh(
    new THREE.BoxGeometry(jibLen, jibThickness, jibWidth),
    jibMat,
  );
  jib.position.set(jibLen / 2, 0, 0);
  jib.name = `${cfg.crane_id}:jib`;
  jibAssembly.add(jib);

  const counterJib = new THREE.Mesh(
    new THREE.BoxGeometry(counterLen, jibThickness, jibWidth),
    accentMat,
  );
  counterJib.position.set(-counterLen / 2, 0, 0);
  counterJib.name = `${cfg.crane_id}:counterJib`;
  jibAssembly.add(counterJib);

  // Counterweight block.
  const counterweight = new THREE.Mesh(
    new THREE.BoxGeometry(counterLen * 0.35, jibThickness * 2.2, jibWidth * 0.9),
    accentMat,
  );
  counterweight.position.set(-counterLen * 0.82, -jibThickness * 0.4, 0);
  jibAssembly.add(counterweight);

  // Trolley: rides along the jib at +X offset = trolleyR.
  const trolley = new THREE.Mesh(
    new THREE.BoxGeometry(jibWidth * 1.2, jibThickness * 1.4, jibWidth * 1.2),
    accentMat,
  );
  trolley.position.set(cfg.trolley_r_min_m, -jibThickness * 0.8, 0);
  trolley.name = `${cfg.crane_id}:trolley`;
  jibAssembly.add(trolley);

  // Hook group + cable.
  const hook = new THREE.Group();
  hook.name = `${cfg.crane_id}:hook`;
  const hookLocalY = cfg.hook_h_min_world_m - rootWorld[2];
  hook.position.set(cfg.trolley_r_min_m, hookLocalY, 0);
  jibAssembly.add(hook);

  const hookBlock = new THREE.Mesh(
    new THREE.BoxGeometry(jibWidth * 0.9, jibThickness * 1.5, jibWidth * 0.9),
    accentMat,
  );
  hookBlock.position.y = 0;
  hook.add(hookBlock);

  const cableLen = Math.abs(hookLocalY);
  const cable = new THREE.Mesh(
    new THREE.CylinderGeometry(Math.max(0.03, jibThickness * 0.08), Math.max(0.03, jibThickness * 0.08), cableLen, 6),
    accentMat,
  );
  cable.position.set(cfg.trolley_r_min_m, hookLocalY / 2, 0);
  jibAssembly.add(cable);

  const loadSlot = new THREE.Group();
  loadSlot.name = `${cfg.crane_id}:loadSlot`;
  loadSlot.position.set(0, -jibThickness * 1.2, 0); // hangs just below the hook block
  hook.add(loadSlot);

  // Working-radius circle on the ground around the base.
  const circle = new THREE.LineLoop(
    new THREE.BufferGeometry().setFromPoints(circlePoints(radius)),
    new THREE.LineBasicMaterial({ color, transparent: true, opacity: 0.5 }),
  );
  circle.name = `${cfg.crane_id}:radius`;
  group.add(circle);

  return { craneId: cfg.crane_id, group, jibAssembly, jib, counterJib, trolley, hook, loadSlot, radiusCircle: circle, cable, fromAsset };
}
