// Owns the Three.js Scene / Camera / Renderer and the named object tree.
//
// The renderer is created through an injectable factory so unit tests can pass a
// stub and exercise the full scene graph (THREE.Scene / Mesh / Object3D work
// without a WebGL context — only renderer.render() needs GL). Production passes
// no factory and gets a real WebGLRenderer bound to the canvas.

import * as THREE from "three";
import type { ResolvedConfig, CraneConfig, BoundaryConfig } from "@/types/config";
import type { EpisodeManifest, ZoneManifest } from "@/types/sim";
import { worldToThree } from "@/coord";
import { buildCrane, DEFAULT_CRANE_PALETTE, type CraneParts } from "./geometry/crane";
import { buildZone, type ZoneKind } from "./geometry/zones";
import { buildBoundary } from "./geometry/site";

export interface RendererLike {
  domElement: HTMLCanvasElement | HTMLElement;
  setSize(w: number, h: number): void;
  setPixelRatio(r: number): void;
  setClearColor(color: THREE.ColorRepresentation, alpha?: number): void;
  render(scene: THREE.Scene, camera: THREE.Camera): void;
  dispose(): void;
}

export type RendererFactory = (canvas: HTMLCanvasElement) => RendererLike;

export interface CranePose {
  thetaRad: number;
  trolleyR: number;
  hookHWorld: number;
  rootZWorld: number;
}

function defaultRenderer(canvas: HTMLCanvasElement): RendererLike {
  const r = new THREE.WebGLRenderer({ canvas, antialias: true });
  r.setClearColor(0x0a0c10, 1);
  return r as unknown as RendererLike;
}

export interface ControllerStats {
  cranes: number;
  zones: number;
  unknownZoneTypes: number;
}

export class ThreeSceneController {
  readonly scene = new THREE.Scene();
  readonly camera: THREE.PerspectiveCamera;
  private renderer: RendererLike;
  private readonly canvas: HTMLCanvasElement;
  private readonly root = new THREE.Group();
  private readonly cranes = new Map<string, CraneParts>();
  private disposed = false;
  lastStats: ControllerStats = { cranes: 0, zones: 0, unknownZoneTypes: 0 };

  constructor(opts: { canvas: HTMLCanvasElement; createRenderer?: RendererFactory }) {
    this.canvas = opts.canvas;
    const factory = opts.createRenderer ?? defaultRenderer;
    this.renderer = factory(this.canvas);
    this.camera = new THREE.PerspectiveCamera(50, 1, 0.5, 5000);
    this.scene.add(this.root);
    this.scene.add(new THREE.HemisphereLight(0xffffff, 0x202028, 1.0));
    const dir = new THREE.DirectionalLight(0xffffff, 0.8);
    dir.position.set(120, 200, 80);
    this.scene.add(dir);
    this.scene.background = new THREE.Color(0x0a0c10);
  }

  /** (Re)build the static scene from a resolved config and/or manifest. */
  buildStatic(config: ResolvedConfig | null, manifest: EpisodeManifest | null = null): ControllerStats {
    this.disposeDynamic();
    this.cranes.clear();
    let unknownZoneTypes = 0;

    const site = config?.scenario?.site ?? null;
    const boundary = (site?.boundary ?? manifest?.site?.boundary ?? null) as BoundaryConfig | null;
    if (boundary) {
      this.root.add(buildBoundary(boundary));
    }

    // Zones: prefer config, fall back to manifest lists.
    const zonesOf = (kind: ZoneKind): ZoneManifest[] => {
      if (site) {
        return site[`${kind}_zones` as "material_zones"] as unknown as ZoneManifest[];
      }
      const key = `${kind}_zones`;
      return ((manifest?.[key as "material_zones"] as unknown) as ZoneManifest[]) ?? [];
    };

    let zoneCount = 0;
    (["material", "work", "forbidden"] as ZoneKind[]).forEach((kind) => {
      for (const z of zonesOf(kind)) {
        if (z.type && z.type !== "box" && z.type !== "polygon") {
          unknownZoneTypes += 1;
        }
        const obj = buildZone(z as unknown as Parameters<typeof buildZone>[0], kind);
        this.root.add(obj);
        zoneCount += 1;
      }
    });

    // Cranes: prefer resolved_cranes; fall back to manifest cranes.
    const cranes: CraneConfig[] = config?.layout?.resolved_cranes
      ? config.layout.resolved_cranes
      : ((manifest?.cranes as unknown) as CraneConfig[]) ?? [];

    cranes.forEach((c, i) => {
      const paletteColor = (c as CraneConfig & { _color?: number })._color;
      const color = paletteColor ?? DEFAULT_CRANE_PALETTE[i % DEFAULT_CRANE_PALETTE.length];
      const parts = buildCrane(c, { color });
      this.cranes.set(c.crane_id, parts);
      this.root.add(parts.group);
    });

    this.frameCamera(boundary);
    this.lastStats = { cranes: cranes.length, zones: zoneCount, unknownZoneTypes };
    this.render();
    return this.lastStats;
  }

  getCraneIds(): string[] {
    return Array.from(this.cranes.keys());
  }

  getCraneParts(id: string): CraneParts | undefined {
    return this.cranes.get(id);
  }

  /** Update a single crane's dynamic pose (Task 03 drives this per frame). */
  setCranePose(craneId: string, pose: CranePose): void {
    const p = this.cranes.get(craneId);
    if (!p || p.fromAsset) return;
    p.jibAssembly.rotation.y = pose.thetaRad;
    p.trolley.position.x = pose.trolleyR;
    const hookLocalY = pose.hookHWorld - pose.rootZWorld;
    p.hook.position.set(pose.trolleyR, hookLocalY, 0);
    // Rescale the cable to span trolley (y=0) to hook.
    const cableLen = Math.max(0.05, Math.abs(hookLocalY));
    const baseHeight = (p.cable.geometry as THREE.CylinderGeometry).parameters.height || 1;
    p.cable.scale.set(1, cableLen / Math.max(0.05, baseHeight), 1);
    p.cable.position.set(pose.trolleyR, hookLocalY / 2, 0);
  }

  getObjectByName(name: string): THREE.Object3D | undefined {
    return this.root.getObjectByName(name) ?? this.scene.getObjectByName(name);
  }

  /** Frame the camera on the whole site, or a default pose if no boundary. */
  frameCamera(boundary: BoundaryConfig | null): void {
    if (!boundary) {
      this.camera.position.set(140, 130, 160);
      this.camera.lookAt(0, 30, 0);
      return;
    }
    const cx = (boundary.x_min + boundary.x_max) / 2;
    const cy = (boundary.y_min + boundary.y_max) / 2;
    const cz = (boundary.z_min + boundary.z_max) / 2;
    const span = Math.max(
      boundary.x_max - boundary.x_min,
      boundary.y_max - boundary.y_min,
      boundary.z_max - boundary.z_min,
      10,
    );
    const target = worldToThree([cx, cy, cz]);
    this.camera.position.set(target[0] + span * 0.9, span * 0.9, target[2] + span * 0.9);
    this.camera.lookAt(target[0], target[1], target[2]);
  }

  resize(width: number, height: number): void {
    if (width <= 0 || height <= 0) return;
    this.camera.aspect = width / height;
    this.camera.updateProjectionMatrix();
    this.renderer.setSize(width, height);
  }

  render(): void {
    if (this.disposed) return;
    this.renderer.render(this.scene, this.camera);
  }

  private disposeDynamic(): void {
    this.root.traverse((obj) => {
      const mesh = obj as THREE.Mesh;
      if (mesh.geometry) mesh.geometry.dispose?.();
      const mat = mesh.material as THREE.Material | THREE.Material[] | undefined;
      if (Array.isArray(mat)) mat.forEach((m) => m.dispose());
      else mat?.dispose?.();
    });
    while (this.root.children.length) {
      this.root.remove(this.root.children[0]);
    }
  }

  dispose(): void {
    if (this.disposed) return;
    this.disposed = true;
    this.disposeDynamic();
    this.renderer.dispose();
  }
}
