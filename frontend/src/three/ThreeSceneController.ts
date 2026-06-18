// Owns the Three.js Scene / Camera / Renderer and the named object tree.
//
// The renderer is created through an injectable factory so unit tests can pass a
// stub and exercise the full scene graph (THREE.Scene / Mesh / Object3D work
// without a WebGL context — only renderer.render() needs GL). Production passes
// no factory and gets a real WebGLRenderer bound to the canvas.

import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import type { ResolvedConfig, CraneConfig, BoundaryConfig } from "@/types/config";
import type { EpisodeManifest, ZoneManifest, SimFrame, SimFrameWeather } from "@/types/sim";
import { worldToThree, type Vec3 } from "@/coord";
import { buildCrane, DEFAULT_CRANE_PALETTE, type CraneParts } from "./geometry/crane";
import { buildZone, type ZoneKind } from "./geometry/zones";
import { buildBuildingFloors, buildInferredZoneFloors } from "./geometry/floors";
import { buildBoundary } from "./geometry/site";
import { buildLoad, loadHangOffsetY } from "./geometry/load";
import { deriveDynamic } from "./model/dynamicState";
import { buildRiskOverlay, riskLevelStyle, pairKey } from "./geometry/risk";
import { buildTaskRoutes, routeKey, type TaskRoute } from "./geometry/taskPaths";
import type { RiskOverlay } from "./model/SceneModel";

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
  r.setClearColor(0xeaeef4, 1);
  return r as unknown as RendererLike;
}

/** World-frame (ENU) center of a zone, preferring its surface height. */
function zoneWorldCenter(z: ZoneManifest): Vec3 | null {
  if (z.type === "box" && z.center && z.size) {
    const [cx, cy, cz] = z.center as Vec3;
    const zc =
      typeof z.surface_z_m === "number" && Number.isFinite(z.surface_z_m) ? z.surface_z_m : cz;
    return [cx, cy, zc];
  }
  if (z.type === "polygon" && z.points && z.points.length >= 3) {
    let sx = 0;
    let sy = 0;
    for (const p of z.points) {
      sx += p[0];
      sy += p[1];
    }
    const n = z.points.length;
    let zc = 0;
    if (typeof z.surface_z_m === "number" && Number.isFinite(z.surface_z_m)) zc = z.surface_z_m;
    else if (z.z_range_m && z.z_range_m.length === 2) zc = (z.z_range_m[0] + z.z_range_m[1]) / 2;
    return [sx / n, sy / n, zc];
  }
  return null;
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

  // Dynamic-update state.
  private readonly trailHistory = new Map<string, Vec3[]>();
  private readonly trailLines = new Map<string, THREE.Line>();
  private readonly loadKeys = new Map<string, string>();
  private windArrow: THREE.Group | null = null;
  private config: ResolvedConfig | null = null;
  private readonly trailMaxLen = 48;

  // Risk-overlay state.
  private readonly riskLines = new Map<string, THREE.Line>();
  // Glow tubes for high/near_miss/collision (WebGL ignores line width, so a
  // translucent cylinder is what actually reads as a thick, hot link).
  private readonly riskGlows = new Map<string, THREE.Mesh>();
  private showRisk = true;
  private showZones = true;

  // Task-route overlay state (pickup→dropoff arrows).
  private readonly taskRoutes = new Map<string, THREE.Object3D>();
  private readonly taskRouteKeys = new Map<string, string>();
  private readonly zoneCenters = new Map<string, Vec3>();
  private readonly craneColors = new Map<string, number>();
  private showPaths = true;

  private readonly animate: boolean;
  private pulseRaf = 0;
  private controls: OrbitControls | null = null;
  private readonly raycaster = new THREE.Raycaster();

  constructor(opts: { canvas: HTMLCanvasElement; createRenderer?: RendererFactory; animate?: boolean; controls?: boolean }) {
    this.canvas = opts.canvas;
    this.animate = opts.animate ?? true;
    const factory = opts.createRenderer ?? defaultRenderer;
    this.renderer = factory(this.canvas);
    this.camera = new THREE.PerspectiveCamera(50, 1, 0.5, 5000);
    this.scene.add(this.root);
    this.scene.add(new THREE.HemisphereLight(0xffffff, 0xc8ccd4, 1.0));
    const dir = new THREE.DirectionalLight(0xffffff, 0.7);
    dir.position.set(120, 200, 80);
    this.scene.add(dir);
    this.scene.background = new THREE.Color(0xeaeef4);

    if (opts.controls) {
      this.controls = new OrbitControls(this.camera, this.canvas);
      this.controls.addEventListener("change", () => this.render());
    }
  }

  /** (Re)build the static scene from a resolved config and/or manifest. */
  buildStatic(config: ResolvedConfig | null, manifest: EpisodeManifest | null = null): ControllerStats {
    this.disposeDynamic();
    this.stopPulseLoop();
    this.cranes.clear();
    this.config = config;
    this.trailHistory.clear();
    this.trailLines.clear();
    this.loadKeys.clear();
    this.riskLines.clear();
    this.riskGlows.clear();
    this.taskRoutes.clear();
    this.taskRouteKeys.clear();
    this.zoneCenters.clear();
    this.craneColors.clear();
    this.showRisk = true;
    this.showZones = true;
    this.showPaths = true;
    this.windArrow = null;
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

    const zonesGroup = new THREE.Group();
    zonesGroup.name = "zones";
    this.root.add(zonesGroup);

    const allZonesForFloors: ZoneManifest[] = [
      ...zonesOf("material"),
      ...zonesOf("work"),
      ...zonesOf("forbidden"),
    ];
    const buildings =
      (site?.buildings as unknown[]) ??
      ((manifest?.site?.buildings as unknown[]) || []);
    const floorGroup = buildings.length > 0
      ? buildBuildingFloors(buildings as Parameters<typeof buildBuildingFloors>[0])
      : buildInferredZoneFloors(allZonesForFloors as Parameters<typeof buildInferredZoneFloors>[0]);
    if (floorGroup.children.length > 0) {
      this.root.add(floorGroup);
    }

    let zoneCount = 0;
    (["material", "work", "forbidden"] as ZoneKind[]).forEach((kind) => {
      for (const z of zonesOf(kind)) {
        if (z.type && z.type !== "box" && z.type !== "polygon") {
          unknownZoneTypes += 1;
        }
        const center = zoneWorldCenter(z);
        if (center && typeof z.zone_id === "string") this.zoneCenters.set(z.zone_id, center);
        const obj = buildZone(z as unknown as Parameters<typeof buildZone>[0], kind);
        zonesGroup.add(obj);
        zoneCount += 1;
      }
    });

    // Overlap zones (computed in the manifest; SiteConfig does not carry them).
    for (const z of (manifest?.overlap_zones ?? []) as unknown as ZoneManifest[]) {
      if (!z || !z.type) continue;
      if (z.type !== "box" && z.type !== "polygon") unknownZoneTypes += 1;
      const center = zoneWorldCenter(z);
      if (center && typeof z.zone_id === "string") this.zoneCenters.set(z.zone_id, center);
      zonesGroup.add(buildZone(z as unknown as Parameters<typeof buildZone>[0], "overlap"));
      zoneCount += 1;
    }
    zonesGroup.visible = this.showZones;

    // Cranes: prefer resolved_cranes; fall back to manifest cranes. An empty
    // resolved_cranes array (truthy but length 0) also falls back.
    const cfgCranes = config?.layout?.resolved_cranes;
    const cranes: CraneConfig[] =
      cfgCranes && cfgCranes.length
        ? cfgCranes
        : ((manifest?.cranes as unknown) as CraneConfig[]) ?? [];

    cranes.forEach((c, i) => {
      const paletteColor = (c as CraneConfig & { _color?: number })._color;
      const color = paletteColor ?? DEFAULT_CRANE_PALETTE[i % DEFAULT_CRANE_PALETTE.length];
      const parts = buildCrane(c, { color });
      this.cranes.set(c.crane_id, parts);
      this.craneColors.set(c.crane_id, color);
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

  /** True once buildStatic has placed at least one crane in the scene. */
  hasStatic(): boolean {
    return this.cranes.size > 0;
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

  /**
   * Apply one SimFrame to the scene. This is the single update entry used by
   * BOTH offline replay and realtime WebSocket — they share one SimFrame schema
   * and one render path.
   */
  applyFrame(frame: SimFrame): void {
    if (this.disposed) return;
    const states = deriveDynamic(frame, this.config);
    for (const id of this.cranes.keys()) {
      const dyn = states.get(id);
      const parts = this.cranes.get(id)!;
      if (!dyn) {
        // Crane is in the static scene but missing from this frame: keep the
        // last pose, hide the load, do not advance the trail.
        if (parts.loadSlot.children.length) {
          parts.loadSlot.remove(...parts.loadSlot.children);
          this.loadKeys.set(id, "none");
        }
        continue;
      }
      this.setCranePose(id, {
        thetaRad: dyn.thetaRad,
        trolleyR: dyn.trolleyR,
        hookHWorld: dyn.hookHWorld,
        rootZWorld: dyn.rootZWorld,
      });
      this.updateLoad(id, dyn.loadAttached, dyn.loadShape, dyn.loadSize);
      this.pushTrail(id, dyn.tip);
    }
    this.updateWind(frame.weather);

    // Risk overlay anchored on each crane's hook world position.
    const anchors = new Map<string, Vec3>();
    states.forEach((d) => anchors.set(d.craneId, d.hook));
    this.applyRisk(buildRiskOverlay(frame, anchors));

    // Task-route arrows (pickup → dropoff) per crane with an active task.
    this.applyTaskRoutes(frame);

    this.render();
  }

  /** Apply (or clear) the risk overlay. Lines are keyed by sorted pair id. */
  applyRisk(overlay: RiskOverlay | null): void {
    if (this.disposed) return;
    const present = new Set<string>();
    if (overlay) {
      for (const link of overlay.links) {
        const key = pairKey(link.craneI, link.craneJ);
        present.add(key);
        const style = riskLevelStyle(link.level);
        let line = this.riskLines.get(key);
        if (!line) {
          const geo = new THREE.BufferGeometry();
          geo.setAttribute("position", new THREE.BufferAttribute(new Float32Array(6), 3));
          const mat = new THREE.LineBasicMaterial({
            color: style.color,
            transparent: true,
            opacity: style.opacity,
            linewidth: style.lineWidth,
          });
          line = new THREE.Line(geo, mat);
          line.name = `risk:${key}`;
          line.frustumCulled = false;
          this.root.add(line);
          this.riskLines.set(key, line);
        }
        const a = worldToThree(link.a);
        const b = worldToThree(link.b);
        const arr = line.geometry.attributes.position.array as Float32Array;
        arr[0] = a[0]; arr[1] = a[1]; arr[2] = a[2];
        arr[3] = b[0]; arr[4] = b[1]; arr[5] = b[2];
        line.geometry.attributes.position.needsUpdate = true;
        line.geometry.computeBoundingSphere();
        const mat = line.material as THREE.LineBasicMaterial;
        mat.color.setHex(style.color);
        mat.opacity = style.opacity;
        mat.linewidth = style.lineWidth;
        line.visible = this.showRisk;
        line.userData.pulse = style.pulse;
        line.userData.baseOpacity = style.opacity;
        line.userData.level = link.level;
        line.userData.lineWidth = style.lineWidth;
        this.updateRiskGlow(key, link.level, style.color, a, b);
      }
    }
    // Drop lines + glows whose pair is no longer present this frame.
    for (const [key, line] of this.riskLines) {
      if (!present.has(key)) {
        this.root.remove(line);
        line.geometry.dispose();
        (line.material as THREE.Material).dispose();
        this.riskLines.delete(key);
      }
    }
    for (const [key, glow] of this.riskGlows) {
      if (!present.has(key)) this.removeRiskGlow(key, glow);
    }
    this.maybePulse();
  }

  /** Thick translucent tube for hot links (high+); removed for calmer levels. */
  private updateRiskGlow(
    key: string,
    level: import("@/types/sim").RiskLevel,
    color: number,
    a: Vec3,
    b: Vec3,
  ): void {
    const radius =
      level === "collision" ? 1.2 : level === "near_miss" ? 0.9 : level === "high" ? 0.6 : 0;
    let glow = this.riskGlows.get(key);
    if (radius === 0) {
      if (glow) this.removeRiskGlow(key, glow);
      return;
    }
    if (!glow) {
      const geo = new THREE.CylinderGeometry(1, 1, 1, 10);
      const mat = new THREE.MeshBasicMaterial({
        color,
        transparent: true,
        opacity: 0.3,
        depthWrite: false,
      });
      glow = new THREE.Mesh(geo, mat);
      glow.name = `risk:${key}:glow`;
      glow.frustumCulled = false;
      this.root.add(glow);
      this.riskGlows.set(key, glow);
    }
    const va = new THREE.Vector3(a[0], a[1], a[2]);
    const vb = new THREE.Vector3(b[0], b[1], b[2]);
    const dir = vb.clone().sub(va);
    const len = Math.max(0.001, dir.length());
    glow.position.copy(va.clone().add(vb).multiplyScalar(0.5));
    glow.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), dir.normalize());
    glow.scale.set(radius, len, radius);
    (glow.material as THREE.MeshBasicMaterial).color.setHex(color);
    glow.visible = this.showRisk;
  }

  private removeRiskGlow(key: string, glow: THREE.Mesh): void {
    this.root.remove(glow);
    glow.geometry.dispose();
    (glow.material as THREE.Material).dispose();
    this.riskGlows.delete(key);
  }

  setShowRisk(visible: boolean): void {
    this.showRisk = visible;
    for (const line of this.riskLines.values()) line.visible = visible;
    for (const glow of this.riskGlows.values()) glow.visible = visible;
    this.maybePulse();
    this.render();
  }

  setShowZones(visible: boolean): void {
    this.showZones = visible;
    const g = this.getObjectByName("zones");
    if (g) g.visible = visible;
    this.render();
  }

  /**
   * Draw/refresh the pickup→dropoff arrow for every crane that has an active
   * task with both zones known. Arrows are keyed by crane and rebuilt only when
   * the route (task / endpoints / color) changes.
   */
  applyTaskRoutes(frame: SimFrame): void {
    if (this.disposed) return;
    const routes = buildTaskRoutes(frame, this.zoneCenters, this.craneColors);
    const present = new Set<string>();
    for (const r of routes) {
      present.add(r.craneId);
      const key = routeKey(r);
      if (this.taskRouteKeys.get(r.craneId) === key) continue; // unchanged
      const existing = this.taskRoutes.get(r.craneId);
      if (existing) {
        this.root.remove(existing);
        this.disposeObject(existing);
      }
      const arrow = this.buildRouteArrow(r);
      arrow.name = `taskpath:${r.craneId}`;
      arrow.visible = this.showPaths;
      this.root.add(arrow);
      this.taskRoutes.set(r.craneId, arrow);
      this.taskRouteKeys.set(r.craneId, key);
    }
    for (const [craneId, obj] of this.taskRoutes) {
      if (!present.has(craneId)) {
        this.root.remove(obj);
        this.disposeObject(obj);
        this.taskRoutes.delete(craneId);
        this.taskRouteKeys.delete(craneId);
      }
    }
  }

  setShowPaths(visible: boolean): void {
    this.showPaths = visible;
    for (const obj of this.taskRoutes.values()) obj.visible = visible;
    this.render();
  }

  private buildRouteArrow(r: TaskRoute): THREE.ArrowHelper {
    const from = new THREE.Vector3(...worldToThree(r.from));
    const to = new THREE.Vector3(...worldToThree(r.to));
    const delta = to.clone().sub(from);
    const len = Math.max(0.5, delta.length());
    const dir = delta.lengthSq() > 0 ? delta.normalize() : new THREE.Vector3(0, 1, 0);
    const head = Math.min(6, len * 0.18);
    const arrow = new THREE.ArrowHelper(dir, from, len, r.color, head, head * 0.6);
    const lineMat = arrow.line.material as THREE.LineBasicMaterial;
    lineMat.transparent = true;
    lineMat.opacity = 0.9;
    return arrow;
  }

  private disposeObject(obj: THREE.Object3D): void {
    obj.traverse((o) => {
      const node = o as THREE.Mesh;
      node.geometry?.dispose?.();
      const mat = node.material as THREE.Material | THREE.Material[] | undefined;
      if (Array.isArray(mat)) mat.forEach((m) => m.dispose());
      else mat?.dispose?.();
    });
  }

  /**
   * Pick the crane under a normalized-device-coordinate pointer. Returns the
   * crane_id whose group (or descendant) is hit first, or null for empty space.
   */
  pickCrane(ndc: { x: number; y: number }): string | null {
    this.raycaster.setFromCamera(new THREE.Vector2(ndc.x, ndc.y), this.camera);
    const hits = this.raycaster.intersectObjects(this.root.children, true);
    for (const hit of hits) {
      let obj: THREE.Object3D | null = hit.object;
      while (obj) {
        if (obj.name && this.cranes.has(obj.name)) return obj.name;
        obj = obj.parent;
      }
    }
    return null;
  }

  /** Point the camera at a crane's base; pass null to release follow. */
  followCrane(craneId: string | null): void {
    if (!craneId) {
      this.render();
      return;
    }
    const parts = this.cranes.get(craneId);
    if (!parts) return;
    const target = parts.group.position;
    this.camera.position.set(target.x + 60, target.y + 50, target.z + 60);
    this.camera.lookAt(target);
    if (this.controls) {
      this.controls.target.copy(target);
      this.controls.update();
    }
    this.render();
  }

  private maybePulse(): void {
    if (this.disposed) return;
    const hasPulse =
      this.showRisk &&
      this.animate &&
      Array.from(this.riskLines.values()).some((l) => l.userData.pulse && l.visible);
    if (hasPulse) this.ensurePulseLoop();
    else this.stopPulseLoop();
  }

  private ensurePulseLoop(): void {
    if (this.pulseRaf || typeof requestAnimationFrame !== "function") return;
    const tick = () => {
      if (this.disposed) {
        this.pulseRaf = 0;
        return;
      }
      const t = performance.now() / 1000;
      let any = false;
      for (const line of this.riskLines.values()) {
        if (line.userData.pulse && line.visible) {
          any = true;
          const base = (line.userData.baseOpacity as number) ?? 0.9;
          (line.material as THREE.LineBasicMaterial).opacity = base * (0.4 + 0.6 * (0.5 + 0.5 * Math.sin(t * 4)));
        }
      }
      this.render();
      this.pulseRaf = any ? requestAnimationFrame(tick) : 0;
    };
    this.pulseRaf = requestAnimationFrame(tick);
  }

  private stopPulseLoop(): void {
    if (this.pulseRaf && typeof cancelAnimationFrame === "function") {
      cancelAnimationFrame(this.pulseRaf);
    }
    this.pulseRaf = 0;
  }

  private updateLoad(
    craneId: string,
    attached: boolean,
    shape: import("@/types/sim").LoadShape | null,
    size: Vec3 | null,
  ): void {
    const parts = this.cranes.get(craneId);
    if (!parts) return;
    const key = attached ? `${shape ?? "box"}|${size ? size.join(",") : ""}` : "none";
    if (this.loadKeys.get(craneId) === key) return;
    this.loadKeys.set(craneId, key);
    while (parts.loadSlot.children.length) {
      parts.loadSlot.remove(parts.loadSlot.children[0]);
    }
    if (attached) {
      const mesh = buildLoad(shape, size);
      mesh.position.y = loadHangOffsetY(size);
      parts.loadSlot.add(mesh);
    }
  }

  private ensureTrailLine(craneId: string, color: number): THREE.Line {
    let line = this.trailLines.get(craneId);
    if (line) return line;
    const geo = new THREE.BufferGeometry();
    geo.setAttribute("position", new THREE.BufferAttribute(new Float32Array(0), 3));
    const mat = new THREE.LineBasicMaterial({ color, transparent: true, opacity: 0.45 });
    line = new THREE.Line(geo, mat);
    line.name = `${craneId}:trail`;
    line.frustumCulled = false;
    this.root.add(line);
    this.trailLines.set(craneId, line);
    return line;
  }

  private pushTrail(craneId: string, tipWorld: Vec3): void {
    let hist = this.trailHistory.get(craneId);
    if (!hist) {
      hist = [];
      this.trailHistory.set(craneId, hist);
    }
    hist.push(tipWorld);
    if (hist.length > this.trailMaxLen) hist.shift();
    const parts = this.cranes.get(craneId);
    const color = parts ? (parts.jib.material as THREE.MeshStandardMaterial).color.getHex() : 0x88aacc;
    const line = this.ensureTrailLine(craneId, color);
    const pts = hist.map((p) => new THREE.Vector3(...worldToThree(p)));
    line.geometry.setFromPoints(pts);
  }

  private ensureWindArrow(): THREE.Group {
    if (this.windArrow) return this.windArrow;
    const g = new THREE.Group();
    g.name = "windArrow";
    const mat = new THREE.MeshBasicMaterial({ color: 0x0284c7 });
    const shaft = new THREE.Mesh(new THREE.CylinderGeometry(0.4, 0.4, 6, 8), mat);
    shaft.rotation.z = -Math.PI / 2; // point along +X by default
    shaft.position.x = 1;
    g.add(shaft);
    const head = new THREE.Mesh(new THREE.ConeGeometry(1.1, 2.4, 12), mat);
    head.rotation.z = -Math.PI / 2;
    head.position.x = 1 + 6 / 2 + 1.2;
    g.add(head);
    g.visible = false;
    this.root.add(g);
    this.windArrow = g;
    return g;
  }

  private updateWind(weather: SimFrameWeather): void {
    const arrow = this.ensureWindArrow();
    if (weather.wind_direction_deg == null || !Number.isFinite(weather.wind_direction_deg)) {
      arrow.visible = false;
      return;
    }
    arrow.visible = true;
    // world wind direction (ENU, deg from +X CCW) -> rotation.y (same mapping as jib)
    arrow.rotation.y = (weather.wind_direction_deg * Math.PI) / 180;
    // Park the arrow high above the scene origin so it stays visible.
    arrow.position.set(0, 120, 0);
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
    this.stopPulseLoop();
    this.disposeDynamic();
    this.renderer.dispose();
  }
}
