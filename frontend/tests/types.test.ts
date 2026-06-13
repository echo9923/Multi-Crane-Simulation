import { describe, it, expect } from "vitest";
import type { SimFrame, SimFrameCrane, SimFramePair, SimFrameWeather } from "@/types/sim";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));

// Canonical key sets, verbatim from backend/app/schemas/recorder.py.
// If the backend adds/removes a field, this test must be updated on purpose.
const SIMFRAME_KEYS = [
  "type",
  "schema_version",
  "episode_id",
  "scenario_id",
  "frame",
  "time_s",
  "episode_status",
  "cranes",
  "pairs",
  "tasks",
  "weather",
  "events",
  "offline_labels",
];

const CRANE_KEYS = [
  "schema_version",
  "crane_id",
  "base",
  "root",
  "tip",
  "hook",
  "theta_rad",
  "trolley_r_m",
  "hook_h_m",
  "load_attached",
  "load_type",
  "load_size_m",
  "task_id",
  "task_stage",
  "pickup_zone_id",
  "dropoff_zone_id",
  "operator_profile",
  "current_command",
];

const PAIR_KEYS = [
  "schema_version",
  "crane_i",
  "crane_j",
  "distance_min_raw_now_m",
  "clearance_min_now_m",
  "risk_level_now",
];

const WEATHER_KEYS = [
  "schema_version",
  "wind_speed_m_s",
  "wind_gust_m_s",
  "wind_direction_deg",
  "visibility",
  "rain_level",
  "fog_level",
];

describe("SimFrame contract parity with backend recorder.py", () => {
  it("demo frames carry exactly the SimFrame key set", () => {
    const framesText = readFileSync(join(here, "fixtures", "frames.jsonl"), "utf8");
    const frame = JSON.parse(framesText.split("\n").filter(Boolean)[0]) as SimFrame;
    expect(Object.keys(frame).sort()).toEqual([...SIMFRAME_KEYS].sort());
    expect(frame.cranes.length).toBeGreaterThanOrEqual(3);
    expect(Object.keys(frame.cranes[0]).sort()).toEqual([...CRANE_KEYS].sort());
    expect(Object.keys(frame.pairs[0]).sort()).toEqual([...PAIR_KEYS].sort());
    expect(Object.keys(frame.weather).sort()).toEqual([...WEATHER_KEYS].sort());
  });

  it("every crane carries the full crane key set", () => {
    const framesText = readFileSync(join(here, "fixtures", "frames.jsonl"), "utf8");
    for (const line of framesText.split("\n").filter(Boolean)) {
      const frame = JSON.parse(line) as SimFrame;
      for (const c of frame.cranes) {
        expect(Object.keys(c).sort()).toEqual([...CRANE_KEYS].sort());
      }
      for (const p of frame.pairs) {
        expect(Object.keys(p).sort()).toEqual([...PAIR_KEYS].sort());
      }
    }
  });

  it("fixture is a valid multi-crane episode (>=3 cranes, C(n,2) pairs)", () => {
    const framesText = readFileSync(join(here, "fixtures", "frames.jsonl"), "utf8");
    const frame = JSON.parse(framesText.split("\n").filter(Boolean)[0]) as SimFrame;
    const n = frame.cranes.length;
    expect(n).toBeGreaterThanOrEqual(3);
    const expectedPairs = (n * (n - 1)) / 2;
    expect(frame.pairs.length).toBe(expectedPairs);
  });
});
