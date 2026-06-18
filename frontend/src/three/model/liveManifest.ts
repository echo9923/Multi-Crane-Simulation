// Synthesize a minimal EpisodeManifest from a single SimFrame so the live
// (realtime) view can render a static scene before/without a downloaded
// manifest. Crane geometry is inferred from the frame's base/root/tip; the
// scene is still driven by world coords so it stays consistent with the data.

import type { SimFrame } from "@/types/sim";
import type { EpisodeManifest } from "@/types/sim";
import type { CraneConfig } from "@/types/config";

const LIVE_PALETTE = [0x2563eb, 0xd97706, 0x7c3aed, 0x0d9488, 0xdb2777, 0x4f46e5];

export function craneConfigFromFrame(
  craneId: string,
  base: [number, number, number],
  root: [number, number, number],
  tip: [number, number, number],
  index: number,
): CraneConfig {
  const mast = Math.max(1, root[2] - base[2]);
  const jib = Math.max(1, Math.hypot(tip[0] - root[0], tip[1] - root[1]));
  return {
    crane_id: craneId,
    model_id: "live",
    base,
    root,
    mast_height_m: mast,
    jib_length_m: jib,
    counter_jib_length_m: jib * 0.32,
    trolley_r_min_m: 2,
    trolley_r_max_m: jib,
    hook_h_min_world_m: base[2],
    hook_h_max_world_m: root[2],
    cable_length_min_m: 1,
    cable_length_max_m: mast,
    theta_init_rad: 0,
    theta_init_deg: 0,
    theta_sin: 0,
    theta_cos: 1,
    slew_mode: "continuous",
    theta_limit_rad: null,
    source: "manual",
    _color: LIVE_PALETTE[index % LIVE_PALETTE.length],
  } as CraneConfig & { _color: number };
}

export function manifestFromFrame(frame: SimFrame): EpisodeManifest {
  const cranes = frame.cranes.map((c, i) =>
    craneConfigFromFrame(c.crane_id, c.base, c.root, c.tip, i),
  );
  const site = frame.site ?? {};
  return {
    schema_version: frame.schema_version,
    episode_id: frame.episode_id,
    scenario_id: frame.scenario_id,
    episode_status: frame.episode_status,
    frame_count: 1,
    dt: 0.1,
    coordinate_system: "ENU",
    cranes,
    site,
    material_zones: site.material_zones ?? [],
    work_zones: site.work_zones ?? [],
    forbidden_zones: site.forbidden_zones ?? [],
    overlap_zones: site.overlap_zones ?? [],
    offline_labels_available: false,
  };
}
