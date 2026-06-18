import { describe, it, expect } from "vitest";
import * as THREE from "three";
import { buildCrane, registerCraneAsset, clearCraneAssets } from "@/three/geometry/crane";
import { buildZone, ZONE_COLOR } from "@/three/geometry/zones";
import { buildBoundary } from "@/three/geometry/site";
import { worldToThree } from "@/coord";
import type { CraneConfig, ZoneConfig } from "@/types/config";

function manifestCrane(over: Partial<CraneConfig> = {}): CraneConfig {
  return {
    crane_id: "C1",
    model_id: "TC7032",
    base: [0, 0, 0],
    root: [0, 0, 40],
    mast_height_m: 40,
    jib_length_m: 55,
    counter_jib_length_m: 18,
    trolley_r_min_m: 3,
    trolley_r_max_m: 55,
    hook_h_min_world_m: 2,
    hook_h_max_world_m: 35,
    cable_length_min_m: 5,
    cable_length_max_m: 38,
    theta_init_rad: 0,
    theta_init_deg: 0,
    theta_sin: 0,
    theta_cos: 1,
    slew_mode: "continuous",
    theta_limit_rad: null,
    source: "manual",
    ...over,
  };
}

describe("buildCrane procedural geometry", () => {
  it("places the group at worldToThree(base)", () => {
    const c = manifestCrane({ base: [10, 20, 0] });
    const parts = buildCrane(c);
    const pos = parts.group.position;
    expect(pos.toArray()).toEqual(worldToThree([10, 20, 0]));
  });

  it("puts the jib assembly at mast height (root)", () => {
    const c = manifestCrane({ mast_height_m: 40 });
    const parts = buildCrane(c);
    expect(parts.jibAssembly.position.y).toBe(40);
    expect(parts.jibAssembly.position.x).toBe(0);
    expect(parts.jibAssembly.position.z).toBe(0);
  });

  it("sizes the jib and counter-jib to the configured lengths", () => {
    const c = manifestCrane({ jib_length_m: 55, counter_jib_length_m: 18 });
    const parts = buildCrane(c);
    const jibGeo = parts.jib.geometry as THREE.BoxGeometry;
    const cjGeo = parts.counterJib.geometry as THREE.BoxGeometry;
    expect(jibGeo.parameters.width).toBeCloseTo(55, 6);
    expect(cjGeo.parameters.width).toBeCloseTo(18, 6);
    expect(parts.jib.position.x).toBeCloseTo(55 / 2, 6);
    expect(parts.counterJib.position.x).toBeCloseTo(-18 / 2, 6);
  });

  it("draws a working-radius circle of trolley_r_max_m", () => {
    const c = manifestCrane({ trolley_r_max_m: 55 });
    const parts = buildCrane(c);
    const geo = parts.radiusCircle.geometry;
    const r = geo.attributes.position.getX(0);
    expect(r).toBeCloseTo(55, 6);
  });

  it("falls back to jib length when trolley_r_max is missing", () => {
    const c = manifestCrane({ trolley_r_max_m: 0, jib_length_m: 50 } as Partial<CraneConfig>);
    // craneRadius uses jib when r_max <= 0
    const parts = buildCrane(c);
    const r = parts.radiusCircle.geometry.attributes.position.getX(0);
    expect(r).toBeCloseTo(50, 6);
  });
});

describe("buildCrane glTF replacement", () => {
  it("uses an injected asset when registered by crane_id", () => {
    clearCraneAssets();
    const asset = new THREE.Group();
    asset.name = "gltf-body";
    registerCraneAsset("C1", asset);
    const parts = buildCrane(manifestCrane({ crane_id: "C1" }));
    expect(parts.fromAsset).toBe(true);
    expect(parts.group.getObjectByName("C1:asset")).toBeTruthy();
    clearCraneAssets();
  });

  it("falls back to procedural geometry when nothing is registered", () => {
    clearCraneAssets();
    const parts = buildCrane(manifestCrane({ crane_id: "C9" }));
    expect(parts.fromAsset).toBe(false);
    expect(parts.jib.geometry).toBeTruthy();
  });
});

describe("buildZone", () => {
  it("builds a box zone at worldToThree(center) with correct dims", () => {
    const z: ZoneConfig = {
      zone_id: "w1",
      type: "box",
      center: [40, 20, 15],
      size: [30, 30, 6],
      z_range_m: [12, 18],
      accepted_load_types: ["rebar_bundle"],
    };
    const obj = buildZone(z, "work") as THREE.Group;
    const mesh = obj.children[0] as THREE.Mesh;
    const geo = mesh.geometry as THREE.BoxGeometry;
    // x=east(30), y=height(18-12=6), z=north(30)
    expect(geo.parameters.width).toBeCloseTo(30, 6);
    expect(geo.parameters.height).toBeCloseTo(6, 6);
    expect(geo.parameters.depth).toBeCloseTo(30, 6);
    // position at mid Z = 15
    expect(mesh.position.toArray()).toEqual(worldToThree([40, 20, 15]));
  });

  it("uses surface_z_m as the displayed platform height", () => {
    const z: ZoneConfig = {
      zone_id: "floor_05",
      type: "box",
      center: [40, 20, 0],
      size: [30, 30, 0.4],
      z_range_m: [0, 0.4],
      surface_z_m: 18,
      zone_role: "floor_slab",
    };
    const obj = buildZone(z, "work") as THREE.Group;
    const mesh = obj.children[0] as THREE.Mesh;
    const geo = mesh.geometry as THREE.BoxGeometry;

    expect(geo.parameters.height).toBeCloseTo(0.4, 6);
    expect(mesh.position.toArray()).toEqual(worldToThree([40, 20, 18.2]));
  });

  it("builds a polygon zone (extruded footprint, laid flat)", () => {
    const z: ZoneConfig = {
      zone_id: "p1",
      type: "polygon",
      points: [
        [-20, -20, 0],
        [-4, -20, 0],
        [-4, -4, 0],
        [-20, -4, 0],
      ],
      z_range_m: [0, 2],
      load_types: ["rebar_bundle"],
    };
    const obj = buildZone(z, "material") as THREE.Group;
    const mesh = obj.children[0] as THREE.Mesh;
    expect(mesh.geometry).toBeInstanceOf(THREE.ExtrudeGeometry);
    expect(mesh.rotation.x).toBeCloseTo(-Math.PI / 2, 5);
    expect(mesh.position.y).toBeCloseTo(0, 6); // floor at z_min
  });

  it("colors zones by kind", () => {
    const box: ZoneConfig = { zone_id: "b", type: "box", center: [0, 0, 1], size: [2, 2, 2] };
    const a = buildZone(box, "material") as THREE.Group;
    const b = buildZone(box, "work") as THREE.Group;
    const c = buildZone(box, "forbidden") as THREE.Group;
    expect(((a.children[0] as THREE.Mesh).material as THREE.MeshBasicMaterial).color.getHex()).toBe(ZONE_COLOR.material);
    expect(((b.children[0] as THREE.Mesh).material as THREE.MeshBasicMaterial).color.getHex()).toBe(ZONE_COLOR.work);
    expect(((c.children[0] as THREE.Mesh).material as THREE.MeshBasicMaterial).color.getHex()).toBe(ZONE_COLOR.forbidden);
  });

  it("returns an empty group for unsupported zone types", () => {
    const z = { zone_id: "x", type: "sphere" } as unknown as ZoneConfig;
    const obj = buildZone(z, "forbidden") as THREE.Group;
    expect(obj.children.length).toBe(0);
  });
});

describe("buildBoundary", () => {
  it("emits a named boundary + ground grid within extents", () => {
    const obj = buildBoundary({
      x_min: -30, x_max: 140, y_min: -30, y_max: 140, z_min: 0, z_max: 80,
    }) as THREE.Group;
    expect(obj.getObjectByName("site:boundary:box")).toBeTruthy();
    const grid = obj.getObjectByName("site:ground") as THREE.GridHelper;
    expect(grid).toBeTruthy();
    // grid centered on the site midpoint, at ground z_min (Y in three frame)
    expect(grid.position.y).toBe(0);
    expect(grid.position.x).toBeCloseTo(55, 6); // (-30+140)/2
    expect(grid.position.z).toBeCloseTo(-55, 6); // -((−30+140)/2)
  });
});
