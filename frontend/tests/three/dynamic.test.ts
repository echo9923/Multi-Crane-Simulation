import { describe, it, expect } from "vitest";
import * as THREE from "three";
import { buildLoad, loadHangOffsetY } from "@/three/geometry/load";
import { deriveDynamic } from "@/three/model/dynamicState";
import { buildSceneModel } from "@/three/model/SceneModel";
import { parseFramesJsonl } from "@/api/loader";
import { worldToThree, threeToWorld } from "@/coord";
import type { ResolvedConfig } from "@/types/config";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const framesText = readFileSync(join(here, "..", "fixtures", "frames.jsonl"), "utf8");
const frames = parseFramesJsonl(framesText).frames;
const config: ResolvedConfig = {
  schema_version: "1.0",
  resolved_config_hash: "h",
  scenario: {
    site: {
      coordinate_system: "ENU",
      boundary: { x_min: -30, x_max: 140, y_min: -30, y_max: 140, z_min: 0, z_max: 80 },
      forbidden_zones: [], material_zones: [], work_zones: [],
    },
    load_types: {
      rebar_bundle: { display_name: "rebar", weight_range_t: [1, 3], size_m: [6, 1, 1], shape: "box_long" },
      concrete_bucket: { display_name: "concrete", weight_range_t: [2, 4], size_m: [1.5, 1.5, 2], shape: "cylinder" },
    },
  },
  layout: { resolved_cranes: [] },
};

describe("buildLoad geometry by shape", () => {
  it("renders box shapes as boxes with the right world dimensions", () => {
    const m = buildLoad("box_long", [6, 1, 1]);
    const g = m.geometry as THREE.BoxGeometry;
    // three x=east(6), y=up(1), z=north(1)
    expect(g.parameters.width).toBeCloseTo(6, 6);
    expect(g.parameters.height).toBeCloseTo(1, 6);
    expect(g.parameters.depth).toBeCloseTo(1, 6);
  });

  it("renders a cylinder shape as a vertical cylinder", () => {
    const m = buildLoad("cylinder", [1.5, 1.5, 2]);
    const g = m.geometry as THREE.CylinderGeometry;
    expect(g.parameters.height).toBeCloseTo(2, 6);
    expect(g.parameters.radiusTop).toBeCloseTo(0.75, 6);
  });

  it("falls back to a box for unknown shapes", () => {
    const m = buildLoad(null, [3, 2, 1]);
    expect(m.geometry).toBeInstanceOf(THREE.BoxGeometry);
  });

  it("clamps a zero size to a minimum", () => {
    const m = buildLoad("beam", [8, 0, 0]);
    const g = m.geometry as THREE.BoxGeometry;
    expect(g.parameters.height).toBeGreaterThan(0);
    expect(g.parameters.depth).toBeGreaterThan(0);
  });

  it("loadHangOffsetY places the load below the hook block", () => {
    expect(loadHangOffsetY([6, 1, 1])).toBeCloseTo(-0.5, 6);
  });
});

describe("deriveDynamic", () => {
  it("reads pose from base/root/tip/hook and resolves load shape via config", () => {
    const frame = frames[2]; // C1 has load attached from frame 2
    const dyn = deriveDynamic(frame, config);
    const c1 = frame.cranes.find((c) => c.crane_id === "C1")!;
    const d = dyn.get("C1")!;
    expect(d.thetaRad).toBeCloseTo(c1.theta_rad, 6);
    expect(d.trolleyR).toBeCloseTo(c1.trolley_r_m, 6);
    expect(d.hookHWorld).toBeCloseTo(c1.hook_h_m, 6);
    expect(d.rootZWorld).toBe(c1.root[2]);
    expect(d.loadAttached).toBe(true);
    expect(d.loadShape).toBe("box_long");
    expect(d.loadSize).toEqual([6, 1, 1]);
  });

  it("marks loads as detached with null shape/size when load_attached=false", () => {
    const frame = frames[0];
    const dyn = deriveDynamic(frame, config);
    const c2 = dyn.get("C2")!;
    expect(c2.loadAttached).toBe(false);
    expect(c2.loadShape).toBeNull();
    expect(c2.loadSize).toBeNull();
  });
});

describe("buildSceneModel", () => {
  it("produces dynamic cranes + wind, risk left null in Task 03", () => {
    const model = buildSceneModel(frames[0], config);
    expect(model.cranes.length).toBe(3);
    expect(model.wind).not.toBeNull();
    expect(model.wind!.dirDeg).toBe(45);
    expect(model.risk).toBeNull();
  });
});

describe("coordinate round-trip through the dynamic path", () => {
  it("hook world -> three (via controller pose) -> world equals the frame hook (ENU)", () => {
    // Sanity: the mapping used by the controller preserves the frame's ENU hook.
    const frame = frames[5];
    for (const c of frame.cranes) {
      const t = worldToThree(c.hook);
      const back = threeToWorld(t);
      expect(back[0]).toBeCloseTo(c.hook[0], 6);
      expect(back[1]).toBeCloseTo(c.hook[1], 6);
      expect(back[2]).toBeCloseTo(c.hook[2], 6);
    }
  });
});
