import { describe, it, expect, beforeEach } from "vitest";
import * as THREE from "three";
import { ThreeSceneController, type RendererLike, type RendererFactory } from "@/three/ThreeSceneController";
import type { EpisodeManifest } from "@/types/sim";
import { parseManifest, parseFramesJsonl } from "@/api/loader";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { clearCraneAssets } from "@/three/geometry/crane";

const here = dirname(fileURLToPath(import.meta.url));
const manifest = parseManifest(readFileSync(join(here, "..", "fixtures", "episode_manifest.json"), "utf8")) as EpisodeManifest;
const frames = parseFramesJsonl(readFileSync(join(here, "..", "fixtures", "frames.jsonl"), "utf8")).frames;

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

describe("ThreeSceneController interaction", () => {
  beforeEach(() => clearCraneAssets());

  it("pickCrane returns the crane id under the pointer", () => {
    const ctrl = makeController();
    ctrl.buildStatic(null, manifest);
    ctrl.applyFrame(frames[0]);
    // Aim the camera straight at C1's tower (base at three [0,0,0]).
    const c1 = manifest.cranes.find((c) => c.crane_id === "C1")!;
    const base = c1.base as [number, number, number];
    ctrl.camera.position.set(base[0], base[2] + 20, 60);
    ctrl.camera.lookAt(base[0], base[2] + 20, 0);
    ctrl.camera.updateMatrixWorld(true);
    expect(ctrl.pickCrane({ x: 0, y: 0 })).toBe("C1");
    // An NDC pointing well off to the side misses everything.
    expect(ctrl.pickCrane({ x: 0.99, y: 0.99 })).toBe(null);
    ctrl.dispose();
  });

  it("followCrane moves the camera toward the crane base", () => {
    const ctrl = makeController();
    ctrl.buildStatic(null, manifest);
    const before = ctrl.camera.position.clone();
    ctrl.followCrane("C2");
    const after = ctrl.camera.position;
    expect(after.distanceTo(before)).toBeGreaterThan(0);
    // Camera should now be offset from C2's base (three frame).
    const c2 = manifest.cranes.find((c) => c.crane_id === "C2")!;
    const base = c2.base as [number, number, number];
    const baseThree = new THREE.Vector3(base[0], base[2], -base[1]);
    expect(after.distanceTo(baseThree)).toBeLessThan(120);
    ctrl.dispose();
  });

  it("followCrane(null) is a safe no-op", () => {
    const ctrl = makeController();
    ctrl.buildStatic(null, manifest);
    expect(() => ctrl.followCrane(null)).not.toThrow();
    ctrl.dispose();
  });

  it("followCrane on an unknown crane id is a no-op", () => {
    const ctrl = makeController();
    ctrl.buildStatic(null, manifest);
    const before = ctrl.camera.position.clone();
    ctrl.followCrane("NOPE");
    expect(ctrl.camera.position.equals(before)).toBe(true);
    ctrl.dispose();
  });
});
