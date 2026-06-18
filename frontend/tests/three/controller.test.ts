import { describe, it, expect, beforeEach } from "vitest";
import * as THREE from "three";
import { ThreeSceneController, type RendererLike, type RendererFactory } from "@/three/ThreeSceneController";
import type { ResolvedConfig } from "@/types/config";
import type { EpisodeManifest, SimFrame } from "@/types/sim";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { clearCraneAssets } from "@/three/geometry/crane";

const here = dirname(fileURLToPath(import.meta.url));
const manifest = JSON.parse(
  readFileSync(join(here, "..", "fixtures", "episode_manifest.json"), "utf8"),
) as EpisodeManifest;
const frames: SimFrame[] = readFileSync(join(here, "..", "fixtures", "frames.jsonl"), "utf8")
  .split("\n")
  .filter(Boolean)
  .map((l) => JSON.parse(l));

function stubRendererFactory(): RendererFactory {
  return (_canvas) => {
    const stub: RendererLike = {
      domElement: document.createElement("canvas"),
      setSize() {},
      setPixelRatio() {},
      setClearColor() {},
      render() {},
      dispose() {},
    };
    return stub;
  };
}

function makeController() {
  const canvas = document.createElement("canvas");
  return new ThreeSceneController({ canvas, createRenderer: stubRendererFactory() });
}

describe("ThreeSceneController.buildStatic", () => {
  beforeEach(() => clearCraneAssets());

  it("builds one crane group per manifest crane, positioned at worldToThree(base)", () => {
    const ctrl = makeController();
    ctrl.buildStatic(null, manifest);
    expect(ctrl.lastStats.cranes).toBe(manifest.cranes.length);
    expect(ctrl.getCraneIds().sort()).toEqual(["C1", "C2", "C3"]);
    for (const mc of manifest.cranes) {
      const craneId = mc.crane_id as string;
      const parts = ctrl.getCraneParts(craneId)!;
      const base = mc.base as [number, number, number];
      expect(parts.group.position.toArray()).toEqual([
        base[0],
        base[2],
        -base[1],
      ]);
    }
    ctrl.dispose();
  });

  it("renders zones from the manifest lists and counts unknown types", () => {
    const ctrl = makeController();
    const stats = ctrl.buildStatic(null, manifest);
    const expectedZones =
      manifest.material_zones.length + manifest.work_zones.length + manifest.forbidden_zones.length;
    expect(stats.zones).toBe(expectedZones);
    expect(stats.unknownZoneTypes).toBe(0);
    ctrl.dispose();
  });

  it("exposes named objects (boundary, cranes, zones)", () => {
    const ctrl = makeController();
    ctrl.buildStatic(null, manifest);
    expect(ctrl.getObjectByName("C1")).toBeTruthy();
    expect(ctrl.getObjectByName("zone:forbidden:power_corridor")).toBeTruthy();
    expect(ctrl.getObjectByName("site:boundary:box")).toBeTruthy();
    ctrl.dispose();
  });

  it("renders building floor plates from site buildings", () => {
    const ctrl = makeController();
    const withBuilding = {
      ...manifest,
      site: {
        ...manifest.site,
        buildings: [
          {
            building_id: "tower_a",
            name: "Tower A",
            footprint: [[0, 0], [20, 0], [20, 20], [0, 20]],
            floors: 3,
            floor_height_m: 3.6,
            base_z_m: 0,
          },
        ],
      },
    } as EpisodeManifest;

    ctrl.buildStatic(null, withBuilding);

    expect(ctrl.getObjectByName("floors")).toBeTruthy();
    expect(ctrl.getObjectByName("floor:tower_a:level_3")).toBeTruthy();
    expect(ctrl.getObjectByName("floor:tower_a:level_3")?.position.y).toBeCloseTo(10.8, 6);
    ctrl.dispose();
  });

  it("infers floor plates from zone surface heights when buildings are absent", () => {
    const ctrl = makeController();
    const withSemanticZone = {
      ...manifest,
      work_zones: [
        {
          zone_id: "floor_05_dropoff",
          type: "box",
          center: [30, 20, 18],
          size: [12, 10, 0.4],
          surface_z_m: 18,
          floor_id: "floor_05",
          building_id: "tower_a",
          zone_role: "floor_slab",
        },
      ],
    } as EpisodeManifest;

    ctrl.buildStatic(null, withSemanticZone);

    expect(ctrl.getObjectByName("floors")).toBeTruthy();
    expect(ctrl.getObjectByName("floor:tower_a:floor_05")).toBeTruthy();
    expect(ctrl.getObjectByName("floor:tower_a:floor_05")?.position.y).toBeCloseTo(18, 6);
    ctrl.dispose();
  });

  it("supports config-driven scenes (resolved_cranes + site)", () => {
    const config: ResolvedConfig = {
      schema_version: "1.0",
      resolved_config_hash: "h",
      scenario: {
        site: {
          coordinate_system: "ENU",
          boundary: { x_min: 0, x_max: 100, y_min: 0, y_max: 100, z_min: 0, z_max: 60 },
          forbidden_zones: [],
          material_zones: [
            { zone_id: "m1", type: "box", center: [10, 10, 1], size: [5, 5, 2] },
          ],
          work_zones: [],
        },
        load_types: {},
      },
      layout: {
        resolved_cranes: [
          {
            crane_id: "X1", model_id: "M", base: [5, 5, 0], root: [5, 5, 30],
            mast_height_m: 30, jib_length_m: 40, counter_jib_length_m: 12,
            trolley_r_min_m: 3, trolley_r_max_m: 40, hook_h_min_world_m: 2,
            hook_h_max_world_m: 25, cable_length_min_m: 5, cable_length_max_m: 28,
            theta_init_rad: 0, theta_init_deg: 0, theta_sin: 0, theta_cos: 1,
            slew_mode: "continuous", theta_limit_rad: null, source: "manual",
          },
        ],
      },
    };
    const ctrl = makeController();
    ctrl.buildStatic(config, null);
    expect(ctrl.lastStats.cranes).toBe(1);
    expect(ctrl.getCraneIds()).toEqual(["X1"]);
    expect(ctrl.getObjectByName("zone:material:m1")).toBeTruthy();
    ctrl.dispose();
  });

  it("does not hardcode crane count (renders N cranes for any config)", () => {
    const ctrl = makeController();
    const many = {
      ...manifest,
      cranes: Array.from({ length: 6 }, (_, i) => ({
        ...manifest.cranes[i % 3],
        crane_id: `CN${i}`,
        base: [i * 30, 0, 0],
        root: [i * 30, 0, 40],
      })),
    } as EpisodeManifest;
    ctrl.buildStatic(null, many);
    expect(ctrl.lastStats.cranes).toBe(6);
    ctrl.dispose();
  });
});

describe("ThreeSceneController.setCranePose", () => {
  beforeEach(() => clearCraneAssets());

  it("rotates the jib assembly and moves trolley + hook from a frame", () => {
    const ctrl = makeController();
    ctrl.buildStatic(null, manifest);
    const frame = frames[5];
    const crane = frame.cranes.find((c) => c.crane_id === "C1")!;
    const rootZ = crane.root[2];
    ctrl.setCranePose("C1", {
      thetaRad: crane.theta_rad,
      trolleyR: crane.trolley_r_m,
      hookHWorld: crane.hook_h_m,
      rootZWorld: rootZ,
    });
    const parts = ctrl.getCraneParts("C1")!;
    expect(parts.jibAssembly.rotation.y).toBeCloseTo(crane.theta_rad, 6);
    expect(parts.trolley.position.x).toBeCloseTo(crane.trolley_r_m, 6);
    expect(parts.hook.position.x).toBeCloseTo(crane.trolley_r_m, 6);
    expect(parts.hook.position.y).toBeCloseTo(crane.hook_h_m - rootZ, 6);
    ctrl.dispose();
  });

  it("is a no-op for an unknown crane id", () => {
    const ctrl = makeController();
    ctrl.buildStatic(null, manifest);
    expect(() => ctrl.setCranePose("NOPE", { thetaRad: 1, trolleyR: 1, hookHWorld: 1, rootZWorld: 40 })).not.toThrow();
    ctrl.dispose();
  });
});
