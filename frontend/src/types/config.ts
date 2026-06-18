// Mirror of the Module A static config that the frontend renders.
// Sources: backend/app/schemas/crane.py (CraneConfig, CraneModelSpec) and
// backend/app/schemas/config.py (SiteConfig, BoundaryConfig, ZoneConfig,
// LoadTypeConfig). ResolvedConfig is only partially typed — we only model the
// fields the 3D scene actually consumes (resolved_cranes, site, load_types).

import type { Vec3 } from "@/coord";
import type { LoadShape } from "./sim";

export interface BoundaryConfig {
  x_min: number;
  x_max: number;
  y_min: number;
  y_max: number;
  z_min: number;
  z_max: number;
}

export interface ZoneConfig {
  zone_id: string;
  type: string; // "box" | "polygon" (backend rejects others)
  center?: Vec3 | null;
  size?: Vec3 | null;
  points?: Vec3[] | null;
  z_range_m?: [number, number] | null;
  surface_z_m?: number | null;
  floor_id?: string | null;
  building_id?: string | null;
  level_index?: number | null;
  zone_role?: string | null;
  hook_target_offset_m?: number | null;
  load_center_offset_m?: number | null;
  approach_clearance_m?: number | null;
  load_types?: string[] | null;
  accepted_load_types?: string[] | null;
}

export interface BuildingConfig {
  building_id: string;
  name: string;
  footprint: Vec3[] | [number, number][];
  floors: number;
  floor_height_m: number;
  base_z_m: number;
}

export interface LoadTypeConfig {
  display_name: string;
  weight_range_t: [number, number];
  size_m: Vec3;
  shape: string; // LoadShape values, but open string on the backend
}

export interface CraneModelSpec {
  model_id: string;
  jib_length_m: number;
  counter_jib_length_m: number;
  mast_height_range_m: [number, number];
  max_load_t: number;
  max_load_radius_m: number;
  tip_load_t: number;
  rated_moment_t_m: number;
  trolley_r_min_m: number;
  trolley_r_max_m: number;
  cable_length_min_m: number;
  cable_length_max_m: number;
  [key: string]: unknown;
}

export interface CraneConfig {
  crane_id: string;
  model_id: string;
  model?: CraneModelSpec;
  base: Vec3;
  root: Vec3;
  mast_height_m: number;
  jib_length_m: number;
  counter_jib_length_m: number;
  trolley_r_min_m: number;
  trolley_r_max_m: number;
  hook_h_min_world_m: number;
  hook_h_max_world_m: number;
  cable_length_min_m: number;
  cable_length_max_m: number;
  theta_init_rad: number;
  theta_init_deg: number;
  theta_sin: number;
  theta_cos: number;
  slew_mode: "continuous" | "limited";
  theta_limit_rad: [number, number] | null;
  source: "manual" | "auto";
  [key: string]: unknown;
}

export interface SiteConfig {
  coordinate_system: string;
  boundary: BoundaryConfig;
  buildings?: BuildingConfig[];
  forbidden_zones: ZoneConfig[];
  material_zones: ZoneConfig[];
  work_zones: ZoneConfig[];
}

// We only model the parts of ResolvedConfig the frontend needs.
export interface ResolvedConfig {
  schema_version: string;
  resolved_config_hash: string;
  scenario: {
    site: SiteConfig;
    load_types: Record<string, LoadTypeConfig>;
    crane_models?: Record<string, CraneModelSpec>;
    [key: string]: unknown;
  };
  layout: {
    resolved_cranes: CraneConfig[];
    [key: string]: unknown;
  };
  [key: string]: unknown;
}

export function craneRadius(cfg: CraneConfig): number {
  // Prefer the working radius; fall back to jib length.
  const r = cfg.trolley_r_max_m ?? cfg.jib_length_m;
  return r > 0 ? r : cfg.jib_length_m;
}

export function loadShapeOf(lt: LoadTypeConfig | undefined): LoadShape | null {
  if (!lt) return null;
  switch (lt.shape) {
    case "box_long":
    case "flat_box":
    case "cylinder":
    case "beam":
      return lt.shape;
    default:
      return null;
  }
}
