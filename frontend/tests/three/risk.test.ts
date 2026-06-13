import { describe, it, expect, beforeEach } from "vitest";
import * as THREE from "three";
import { buildRiskOverlay, riskLevelStyle, RISK_STYLE, pairKey } from "@/three/geometry/risk";
import { ThreeSceneController, type RendererLike, type RendererFactory } from "@/three/ThreeSceneController";
import { ZONE_COLOR } from "@/three/geometry/zones";
import type { SimFrame, RiskLevel } from "@/types/sim";
import type { EpisodeManifest } from "@/types/sim";
import { parseFramesJsonl, parseManifest } from "@/api/loader";
import { worldToThree } from "@/coord";
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

function stubFactory(): RendererFactory {
  return () => ({
    domElement: document.createElement("canvas"),
    setSize() {}, setPixelRatio() {}, setClearColor() {}, render() {}, dispose() {},
  } as RendererLike);
}

function makeController(animate = false) {
  return new ThreeSceneController({
    canvas: document.createElement("canvas"),
    createRenderer: stubFactory(),
    animate,
  });
}

describe("riskLevelStyle", () => {
  it("has a distinct color/style per level", () => {
    const levels: RiskLevel[] = ["safe", "low", "medium", "high", "near_miss", "collision"];
    const colors = new Set(levels.map((l) => riskLevelStyle(l).color));
    expect(colors.size).toBe(6);
    expect(riskLevelStyle("near_miss").pulse).toBe(true);
    expect(riskLevelStyle("collision").pulse).toBe(true);
    expect(riskLevelStyle("high").pulse).toBe(false);
  });
});

describe("buildRiskOverlay", () => {
  it("creates one link per pair, anchored on hooks", () => {
    const frame = frames[0];
    const anchors = new Map<string, [number, number, number]>();
    for (const c of frame.cranes) anchors.set(c.crane_id, c.hook);
    const overlay = buildRiskOverlay(frame, anchors);
    expect(overlay.links.length).toBe(frame.pairs.length);
    const first = overlay.links[0];
    expect(anchors.has(first.craneI)).toBe(true);
    expect(anchors.has(first.craneJ)).toBe(true);
    expect(first.a).toEqual(anchors.get(first.craneI));
  });

  it("flags collision/near_miss pairs", () => {
    const frame = frames[0];
    const anchors = new Map<string, [number, number, number]>();
    for (const c of frame.cranes) anchors.set(c.crane_id, c.hook);
    const overlay = buildRiskOverlay(frame, anchors);
    for (const link of overlay.links) {
      const isCritical = link.level === "collision" || link.level === "near_miss";
      const inList = overlay.collisionPairIds.some(
        ([a, b]) => pairKey(a, b) === pairKey(link.craneI, link.craneJ),
      );
      expect(inList).toBe(isCritical);
    }
  });

  it("skips pairs that reference an unknown crane", () => {
    const frame = frames[0];
    const anchors = new Map<string, [number, number, number]>([
      [frame.cranes[0].crane_id, frame.cranes[0].hook],
    ]);
    const overlay = buildRiskOverlay(frame, anchors);
    expect(overlay.links.length).toBe(0); // no pair has both endpoints present
  });

  it("renders a null risk_level_now as the weak safe style", () => {
    const frame: SimFrame = {
      ...frames[0],
      pairs: [
        { schema_version: "1.0", crane_i: "C1", crane_j: "C2", distance_min_raw_now_m: 9, clearance_min_now_m: 9, risk_level_now: null },
      ],
    };
    const anchors = new Map<string, [number, number, number]>([
      ["C1", [0, 0, 0]], ["C2", [9, 0, 0]],
    ]);
    const overlay = buildRiskOverlay(frame, anchors);
    expect(overlay.links[0].level).toBe("safe");
    expect(overlay.links[0].clearanceNow).toBe(9);
  });
});

describe("ThreeSceneController risk layer", () => {
  beforeEach(() => clearCraneAssets());

  it("creates one risk line per pair, colored by level, toggleable", () => {
    const ctrl = makeController();
    ctrl.buildStatic(null, manifest);
    ctrl.applyFrame(frames[0]);
    expect(frames[0].pairs.length).toBeGreaterThan(0);
    for (const p of frames[0].pairs) {
      const line = ctrl.getObjectByName(`risk:${pairKey(p.crane_i, p.crane_j)}`) as THREE.Line;
      expect(line).toBeTruthy();
      const expectedColor = RISK_STYLE[p.risk_level_now ?? "safe"].color;
      expect((line.material as THREE.LineBasicMaterial).color.getHex()).toBe(expectedColor);
      expect(line.visible).toBe(true);
    }
    ctrl.setShowRisk(false);
    for (const p of frames[0].pairs) {
      const line = ctrl.getObjectByName(`risk:${pairKey(p.crane_i, p.crane_j)}`) as THREE.Line;
      expect(line.visible).toBe(false);
    }
    ctrl.setShowRisk(true);
    ctrl.dispose();
  });

  it("removes risk lines for pairs that disappear between frames", () => {
    const ctrl = makeController();
    ctrl.buildStatic(null, manifest);
    ctrl.applyFrame(frames[0]);
    expect(frames[0].pairs.length).toBe(3);
    const noPairs: SimFrame = { ...frames[1], pairs: [] };
    ctrl.applyFrame(noPairs);
    for (const p of frames[0].pairs) {
      expect(ctrl.getObjectByName(`risk:${pairKey(p.crane_i, p.crane_j)}`)).toBeFalsy();
    }
    ctrl.dispose();
  });

  it("renders overlap zones from the manifest (purple)", () => {
    const m: EpisodeManifest = {
      ...manifest,
      overlap_zones: [
        { zone_id: "ov1", type: "box", center: [50, 20, 15], size: [20, 20, 6], z_range_m: [12, 18] },
      ],
    };
    const ctrl = makeController();
    ctrl.buildStatic(null, m);
    const obj = ctrl.getObjectByName("zone:overlap:ov1") as THREE.Group;
    expect(obj).toBeTruthy();
    expect(((obj.children[0] as THREE.Mesh).material as THREE.MeshBasicMaterial).color.getHex()).toBe(ZONE_COLOR.overlap);
    ctrl.dispose();
  });

  it("does not crash on an empty pairs list (single crane)", () => {
    const ctrl = makeController();
    ctrl.buildStatic(null, { ...manifest, cranes: [manifest.cranes[0]] });
    const single: SimFrame = { ...frames[0], cranes: [frames[0].cranes[0]], pairs: [] };
    expect(() => ctrl.applyFrame(single)).not.toThrow();
    ctrl.dispose();
  });
});
