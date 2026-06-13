// Reproducible generator for the offline demo episode used by tests and the
// default dev view. Computes internally-consistent SimFrame geometry (root/tip/
// trolley/hook derived from base/mast/theta/jib/trolley_r/hook_h) so the 3D
// scene and the recorded coordinates cannot drift.
//
//   node scripts/gen-demo-frames.mjs
//
// Writes tests/fixtures/frames.jsonl and tests/fixtures/episode_manifest.json.

import { writeFileSync, mkdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const fixturesDir = join(here, "..", "tests", "fixtures");
mkdirSync(fixturesDir, { recursive: true });

const SCHEMA = "1.0";
const EPISODE_ID = "E-DEMO0001";
const SCENARIO_ID = "demo_scenario";
const DT = 0.5;
const NUM_FRAMES = 30;

/** @typedef {[number,number,number]} Vec3 */

/**
 * @param {number} theta rad, measured from +X (East) CCW in the ENU plane
 * @returns {Vec3} unit vector [cos, sin, 0]
 */
function dir2(theta) {
  return [Math.cos(theta), Math.sin(theta), 0];
}

function add(a, s, b) {
  return [a[0] + s * b[0], a[1] + s * b[1], a[2] + s * b[2]];
}

const cranes = [
  {
    crane_id: "C1",
    model_id: "TC7032",
    base: [0, 0, 0],
    mast: 40,
    jib: 55,
    counter_jib: 18,
    trolley_min: 3,
    trolley_max: 55,
    cable_min: 5,
    cable_max: 38,
    theta0: 0,
    color: 0x4cc2ff,
    operator_profile: "normal",
    task_stage: "lift_load",
    load_type: "rebar_bundle",
    load_size: [6, 1, 1],
    pickup: "rebar_yard",
    dropoff: "floorA",
  },
  {
    crane_id: "C2",
    model_id: "TC6015",
    base: [78, 4, 0],
    mast: 46,
    jib: 50,
    counter_jib: 16,
    trolley_min: 3,
    trolley_max: 50,
    cable_min: 5,
    cable_max: 40,
    theta0: Math.PI,
    color: 0xffb454,
    operator_profile: "conservative",
    task_stage: "idle",
    load_type: null,
    load_size: null,
    pickup: null,
    dropoff: null,
  },
  {
    crane_id: "C3",
    model_id: "TC5518",
    base: [36, 62, 0],
    mast: 42,
    jib: 50,
    counter_jib: 16,
    trolley_min: 3,
    trolley_max: 50,
    cable_min: 5,
    cable_max: 36,
    theta0: -Math.PI / 2,
    color: 0x9b8cff,
    operator_profile: "aggressive",
    task_stage: "move_to_dropoff",
    load_type: "concrete_bucket",
    load_size: [1.5, 1.5, 2],
    pickup: "concrete_yard",
    dropoff: "floorB",
  },
];

// Per-frame animation params per crane (functions of frame index f).
function dynamics(c, f) {
  switch (c.crane_id) {
    case "C1":
      return {
        theta: c.theta0 + f * 0.02,
        trolley_r: Math.min(c.trolley_max, 30 + f * 0.5),
        hook_h: 12 + Math.sin(f * 0.3) * 2,
        load_attached: f >= 2,
      };
    case "C2":
      return {
        theta: c.theta0 - f * 0.015,
        trolley_r: Math.max(c.trolley_min, 28 - f * 0.3),
        hook_h: 14 + Math.cos(f * 0.25) * 2,
        load_attached: false,
      };
    case "C3":
      return {
        theta: c.theta0 + f * 0.01,
        trolley_r: 26,
        hook_h: 10 + Math.sin(f * 0.2) * 1.5,
        load_attached: true,
      };
    default:
      return { theta: c.theta0, trolley_r: 25, hook_h: 10, load_attached: false };
  }
}

function riskLevelForClearance(clr) {
  if (clr < 0) return "collision";
  if (clr < 2) return "near_miss";
  if (clr < 5) return "high";
  if (clr < 10) return "medium";
  if (clr < 20) return "low";
  return "safe";
}

function dist3(a, b) {
  const dx = a[0] - b[0];
  const dy = a[1] - b[1];
  const dz = a[2] - b[2];
  return Math.sqrt(dx * dx + dy * dy + dz * dz);
}

function buildFrame(f) {
  const time_s = +(f * DT).toFixed(3);
  const craneStates = cranes.map((c) => {
    const dyn = dynamics(c, f);
    const root = [c.base[0], c.base[1], c.base[2] + c.mast];
    const d = dir2(dyn.theta);
    const tip = add(root, c.jib, d);
    const trolleyWorld = add(root, dyn.trolley_r, d);
    const hook = [trolleyWorld[0], trolleyWorld[1], dyn.hook_h];
    return {
      crane: c,
      dyn,
      root,
      tip,
      trolleyWorld,
      hook,
      theta: dyn.theta,
    };
  });

  const cranePayload = craneStates.map((s) => ({
    schema_version: SCHEMA,
    crane_id: s.crane.crane_id,
    base: s.crane.base,
    root: s.root,
    tip: s.tip,
    hook: s.hook,
    theta_rad: +s.theta.toFixed(6),
    trolley_r_m: +s.dyn.trolley_r.toFixed(3),
    hook_h_m: +s.dyn.hook_h.toFixed(3),
    load_attached: s.dyn.load_attached,
    load_type: s.dyn.load_attached ? s.crane.load_type : null,
    load_size_m: s.dyn.load_attached ? s.crane.load_size : null,
    task_id: s.crane.crane_id === "C2" ? null : `T-${s.crane.crane_id}`,
    task_stage: s.crane.task_stage,
    pickup_zone_id: s.crane.pickup,
    dropoff_zone_id: s.crane.dropoff,
    operator_profile: s.crane.operator_profile,
    current_command:
      s.crane.crane_id === "C2"
        ? null
        : {
            left_joystick: {
              slew: { direction: s.theta > s.crane.theta0 ? "right" : "left", gear: 2 },
              trolley: { direction: "out", gear: 1 },
            },
            right_joystick: { hoist: { direction: "neutral", gear: 0 } },
            deadman_pressed: true,
            emergency_stop: false,
          },
  }));

  // Pairs: every combination C(n,2).
  const pairs = [];
  for (let i = 0; i < craneStates.length; i++) {
    for (let j = i + 1; j < craneStates.length; j++) {
      const a = craneStates[i];
      const b = craneStates[j];
      const d = dist3(a.hook, b.hook);
      const clearance = +(d - 1.5).toFixed(3);
      pairs.push({
        schema_version: SCHEMA,
        crane_i: a.crane.crane_id,
        crane_j: b.crane.crane_id,
        distance_min_raw_now_m: +d.toFixed(3),
        clearance_min_now_m: clearance,
        risk_level_now: riskLevelForClearance(clearance),
      });
    }
  }

  const events = [];
  if (f === 0) {
    events.push({
      event_id: "EVT-001",
      event_type: "task_assigned",
      episode_id: EPISODE_ID,
      scenario_id: SCENARIO_ID,
      frame: f,
      time_s,
      crane_ids: ["C1", "C3"],
      risk_level: "safe",
      distance_min_raw_now_m: null,
      clearance_min_now_m: null,
      details: { note: "demo event" },
    });
  }
  const highPair = pairs.find((p) => p.risk_level_now === "high" || p.risk_level_now === "near_miss");
  if (highPair && f % 5 === 0 && f > 0) {
    events.push({
      event_id: `EVT-RISK-${f}`,
      event_type: "risk_high",
      episode_id: EPISODE_ID,
      scenario_id: SCENARIO_ID,
      frame: f,
      time_s,
      crane_ids: [highPair.crane_i, highPair.crane_j],
      risk_level: highPair.risk_level_now,
      distance_min_raw_now_m: highPair.distance_min_raw_now_m,
      clearance_min_now_m: highPair.clearance_min_now_m,
      details: {},
    });
  }

  return {
    type: "sim_frame",
    schema_version: SCHEMA,
    episode_id: EPISODE_ID,
    scenario_id: SCENARIO_ID,
    frame: f,
    time_s,
    episode_status: "running",
    cranes: cranePayload,
    pairs,
    tasks: [],
    weather: {
      schema_version: SCHEMA,
      wind_speed_m_s: +(6 + f * 0.1).toFixed(2),
      wind_gust_m_s: +(8.5 + f * 0.1).toFixed(2),
      wind_direction_deg: 45,
      visibility: "good",
      rain_level: "none",
      fog_level: "none",
    },
    events,
    offline_labels: null,
  };
}

function thetaInitRadDeg(theta0) {
  const deg = ((theta0 * 180) / Math.PI + 360) % 360;
  return {
    theta_init_rad: +theta0.toFixed(6),
    theta_init_deg: +deg.toFixed(3),
    theta_sin: +Math.sin(theta0).toFixed(6),
    theta_cos: +Math.cos(theta0).toFixed(6),
  };
}

function buildManifest() {
  const craneConfigs = cranes.map((c) => ({
    crane_id: c.crane_id,
    model_id: c.model_id,
    base: c.base,
    root: [c.base[0], c.base[1], c.base[2] + c.mast],
    mast_height_m: c.mast,
    jib_length_m: c.jib,
    counter_jib_length_m: c.counter_jib,
    trolley_r_min_m: c.trolley_min,
    trolley_r_max_m: c.trolley_max,
    hook_h_min_world_m: Math.max(0, c.base[2] + c.mast - c.cable_max),
    hook_h_max_world_m: c.base[2] + c.mast - c.cable_min,
    cable_length_min_m: c.cable_min,
    cable_length_max_m: c.cable_max,
    ...thetaInitRadDeg(c.theta0),
    slew_mode: "continuous",
    theta_limit_rad: null,
    source: "manual",
    _color: c.color,
  }));

  return {
    schema_version: SCHEMA,
    episode_id: EPISODE_ID,
    scenario_id: SCENARIO_ID,
    episode_status: "running",
    frame_count: NUM_FRAMES,
    dt: DT,
    coordinate_system: "ENU",
    cranes: craneConfigs,
    site: {
      coordinate_system: "ENU",
      boundary: { x_min: -30, x_max: 140, y_min: -30, y_max: 140, z_min: 0, z_max: 80 },
      forbidden_zone_policy: { mode: "hard", record_violation: true },
    },
    material_zones: [
      {
        zone_id: "rebar_yard",
        type: "polygon",
        points: [
          [-20, -20, 0],
          [-4, -20, 0],
          [-4, -4, 0],
          [-20, -4, 0],
        ],
        z_range_m: [0, 2],
        load_types: ["rebar_bundle", "steel_beam"],
      },
      {
        zone_id: "concrete_yard",
        type: "box",
        center: [8, 72, 1],
        size: [20, 20, 2],
        z_range_m: [0, 2],
        load_types: ["concrete_bucket"],
      },
    ],
    work_zones: [
      {
        zone_id: "floorA",
        type: "box",
        center: [40, 20, 15],
        size: [30, 30, 6],
        z_range_m: [12, 18],
        accepted_load_types: ["rebar_bundle", "formwork"],
      },
      {
        zone_id: "floorB",
        type: "box",
        center: [64, 40, 20],
        size: [26, 26, 8],
        z_range_m: [16, 24],
        accepted_load_types: ["concrete_bucket"],
      },
    ],
    forbidden_zones: [
      {
        zone_id: "power_corridor",
        type: "polygon",
        points: [
          [30, 30, 0],
          [70, 30, 0],
          [70, 34, 0],
          [30, 34, 0],
        ],
        z_range_m: [0, 30],
      },
    ],
    overlap_zones: [],
    offline_labels_available: false,
  };
}

const frames = [];
for (let f = 0; f < NUM_FRAMES; f++) frames.push(buildFrame(f));

const framesText = frames.map((fr) => JSON.stringify(fr)).join("\n") + "\n";
writeFileSync(join(fixturesDir, "frames.jsonl"), framesText, "utf8");
writeFileSync(
  join(fixturesDir, "episode_manifest.json"),
  JSON.stringify(buildManifest(), null, 2) + "\n",
  "utf8",
);

console.log(`wrote ${frames.length} frames + manifest to ${fixturesDir}`);
