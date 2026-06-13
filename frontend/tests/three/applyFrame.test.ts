import { describe, it, expect, beforeEach } from "vitest";
import * as THREE from "three";
import { ThreeSceneController, type RendererLike, type RendererFactory } from "@/three/ThreeSceneController";
import type { ResolvedConfig } from "@/types/config";
import type { EpisodeManifest, SimFrame } from "@/types/sim";
import { parseFramesJsonl, parseManifest } from "@/api/loader";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { clearCraneAssets } from "@/three/geometry/crane";

const here = dirname(fileURLToPath(import.meta.url));
const manifest = parseManifest(
  readFileSync(join(here, "..", "fixtures", "episode_manifest.json"), "utf8"),
) as EpisodeManifest;
const frames = parseFramesJsonl(
  readFileSync(join(here, "..", "fixtures", "frames.jsonl"), "utf8"),
).frames;

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

function stubFactory(): RendererFactory {
  return () => ({
    domElement: document.createElement("canvas"),
    setSize() {}, setPixelRatio() {}, setClearColor() {}, render() {}, dispose() {},
  } as RendererLike);
}

function makeController() {
  return new ThreeSceneController({
    canvas: document.createElement("canvas"),
    createRenderer: stubFactory(),
  });
}

describe("ThreeSceneController.applyFrame (dynamic updates)", () => {
  beforeEach(() => clearCraneAssets());

  it("moves the jib / trolley / hook between two frames", () => {
    const ctrl = makeController();
    ctrl.buildStatic(config, manifest);
    ctrl.applyFrame(frames[0]);
    const before = ctrl.getCraneParts("C1")!;
    const beforeTheta = before.jibAssembly.rotation.y;
    const beforeTrolley = before.trolley.position.x;
    ctrl.applyFrame(frames[8]);
    const after = ctrl.getCraneParts("C1")!;
    expect(after.jibAssembly.rotation.y).not.toBeCloseTo(beforeTheta, 3);
    expect(after.trolley.position.x).not.toBeCloseTo(beforeTrolley, 3);
    // hook world height maps to local Y = hookHWorld - rootZWorld
    const f = frames[8].cranes.find((c) => c.crane_id === "C1")!;
    expect(after.hook.position.y).toBeCloseTo(f.hook_h_m - f.root[2], 6);
    ctrl.dispose();
  });

  it("shows a load when load_attached and hides it otherwise", () => {
    const ctrl = makeController();
    ctrl.buildStatic(config, manifest);
    // frame 0: C1 load_attached=false
    ctrl.applyFrame(frames[0]);
    expect(ctrl.getCraneParts("C1")!.loadSlot.children.length).toBe(0);
    // frame 2: C1 load_attached=true (rebar_bundle -> box)
    ctrl.applyFrame(frames[2]);
    const slot = ctrl.getCraneParts("C1")!.loadSlot;
    expect(slot.children.length).toBe(1);
    const load = slot.children[0] as THREE.Mesh;
    expect(load.geometry).toBeInstanceOf(THREE.BoxGeometry);
    ctrl.dispose();
  });

  it("builds a trail line that grows then caps at the max length", () => {
    const ctrl = makeController();
    ctrl.buildStatic(config, manifest);
    for (let i = 0; i < 60; i++) ctrl.applyFrame(frames[i % frames.length]);
    const trail = ctrl.getObjectByName("C1:trail") as THREE.Line | undefined;
    expect(trail).toBeTruthy();
    const count = trail!.geometry.attributes.position.count;
    expect(count).toBeLessThanOrEqual(48 * 3);
    expect(count).toBeGreaterThanOrEqual(3);
    ctrl.dispose();
  });

  it("shows the wind arrow rotated to the frame wind direction", () => {
    const ctrl = makeController();
    ctrl.buildStatic(config, manifest);
    ctrl.applyFrame(frames[0]);
    const arrow = ctrl.getObjectByName("windArrow") as THREE.Group;
    expect(arrow).toBeTruthy();
    expect(arrow.visible).toBe(true);
    expect(arrow.rotation.y).toBeCloseTo((45 * Math.PI) / 180, 4);
    ctrl.dispose();
  });

  it("keeps the last pose for a crane missing from a frame (no crash)", () => {
    const ctrl = makeController();
    ctrl.buildStatic(config, manifest);
    ctrl.applyFrame(frames[0]);
    const beforeHookY = ctrl.getCraneParts("C2")!.hook.position.y;
    const partial: SimFrame = {
      ...frames[1],
      cranes: frames[1].cranes.filter((c) => c.crane_id !== "C2"),
    };
    expect(() => ctrl.applyFrame(partial)).not.toThrow();
    expect(ctrl.getCraneParts("C2")!.hook.position.y).toBe(beforeHookY);
    ctrl.dispose();
  });
});
