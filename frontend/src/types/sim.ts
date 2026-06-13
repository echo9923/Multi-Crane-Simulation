// Mirror of backend/app/schemas/recorder.py SimFrame family (RECORDER_SCHEMA_VERSION "1.0").
// Field names MUST stay 1:1 with the Pydantic models (which enforce extra="forbid").
// Any field that is Optional on the backend is `| null` here.

import type { Vec3 } from "@/coord";

export type RiskLevel =
  | "safe"
  | "low"
  | "medium"
  | "high"
  | "near_miss"
  | "collision";

// load_type.shape is a free-form string on the backend; these four are the
// canonical values used in shipped fixtures. Render code dispatches on this and
// falls back to a bounding box for anything unknown.
export type LoadShape = "box_long" | "flat_box" | "cylinder" | "beam";

export type TaskStage =
  | "idle"
  | "move_to_pickup"
  | "align_pickup"
  | "lower_for_attach"
  | "attach_pending"
  | "lift_load"
  | "move_to_dropoff"
  | "align_dropoff"
  | "lower_for_release"
  | "release_pending"
  | "recovery_release"
  | (string & {}); // the backend stage is a plain string; stay open but hint the enum

export type OperatorProfile =
  | "normal"
  | "conservative"
  | "aggressive"
  | "novice"
  | "fatigued"
  | null;

export interface SimFrameCrane {
  schema_version: string;
  crane_id: string;
  base: Vec3;
  root: Vec3;
  tip: Vec3;
  hook: Vec3;
  theta_rad: number;
  trolley_r_m: number;
  hook_h_m: number;
  load_attached: boolean;
  load_type: string | null;
  load_size_m: Vec3 | null;
  task_id: string | null;
  task_stage: TaskStage;
  pickup_zone_id: string | null;
  dropoff_zone_id: string | null;
  operator_profile: OperatorProfile;
  current_command: Record<string, unknown> | null;
}

export interface SimFramePair {
  schema_version: string;
  crane_i: string;
  crane_j: string;
  distance_min_raw_now_m: number | null;
  clearance_min_now_m: number | null;
  risk_level_now: RiskLevel | null;
}

export interface SimFrameWeather {
  schema_version: string;
  wind_speed_m_s: number;
  wind_gust_m_s: number | null;
  wind_direction_deg: number | null;
  visibility: string; // "good" | "medium" | "poor"
  rain_level: string | null;
  fog_level: string | null;
}

export interface OfflineFrameLabels {
  schema_version: string;
  pair_labels: Record<string, unknown>[];
}

export interface SimFrame {
  type: "sim_frame";
  schema_version: string;
  episode_id: string;
  scenario_id: string | null;
  frame: number;
  time_s: number;
  episode_status: string;
  cranes: SimFrameCrane[];
  pairs: SimFramePair[];
  tasks: Record<string, unknown>[];
  weather: SimFrameWeather;
  events: Record<string, unknown>[];
  offline_labels: OfflineFrameLabels | null; // ALWAYS null on the realtime websocket
}

// Subset of EpisodeManifest (recorder.py) consumed by the frontend.
export interface EpisodeManifestCrane extends Record<string, unknown> {
  crane_id?: string;
}

export interface ZoneManifest extends Record<string, unknown> {
  zone_id?: string;
  type?: string;
  center?: Vec3 | null;
  size?: Vec3 | null;
  points?: Vec3[] | null;
  z_range_m?: [number, number] | null;
  load_types?: string[] | null;
  accepted_load_types?: string[] | null;
}

export interface EpisodeManifest {
  schema_version: string;
  episode_id: string;
  scenario_id: string | null;
  episode_status: string;
  frame_count: number;
  dt: number;
  coordinate_system: string; // "ENU"
  cranes: EpisodeManifestCrane[];
  site: Record<string, unknown>;
  material_zones: ZoneManifest[];
  work_zones: ZoneManifest[];
  forbidden_zones: ZoneManifest[];
  overlap_zones: Record<string, unknown>[];
  offline_labels_available: boolean;
}

// Minimal subset of EpisodeSummary (recorder.py) used by panels.
export interface EpisodeSummary {
  schema_version: string;
  episode_id: string;
  scenario_id: string | null;
  episode_status: string;
  duration_s: number;
  num_cranes: number;
  num_tasks_total: number;
  num_tasks_completed: number;
  num_tasks_failed: number;
  task_completion_rate: number;
  near_miss_count: number;
  collision_count: number;
  min_clearance_over_episode: number | null;
  high_risk_duration_s: number;
  num_llm_calls: number;
  risk_frame_ratio_by_level: Record<string, number>;
  [key: string]: unknown;
}
