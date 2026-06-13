import { describe, it, expect } from "vitest";
import { zipSync, strToU8 } from "fflate";
import {
  parseFramesJsonl,
  loadEpisodeFromFiles,
  loadEpisodeFromZip,
} from "@/api/loader";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const framesText = readFileSync(join(here, "fixtures", "frames.jsonl"), "utf8");
const manifestText = readFileSync(join(here, "fixtures", "episode_manifest.json"), "utf8");
const commandsText = readFileSync(join(here, "fixtures", "logs", "commands.jsonl"), "utf8");

describe("parseFramesJsonl robustness", () => {
  it("skips blank and malformed lines, keeps valid ones", () => {
    const text = `${framesText.split("\n")[0]}\n\n{not json}\n{"type":"sim_frame"}\n`;
    const r = parseFramesJsonl(text);
    expect(r.frames.length).toBe(2);
    expect(r.skipped).toBe(1);
  });

  it("handles an empty input", () => {
    const r = parseFramesJsonl("");
    expect(r.frames).toEqual([]);
    expect(r.skipped).toBe(0);
  });
});

describe("loadEpisodeFromFiles", () => {
  it("parses frames + manifest + commands", () => {
    const loaded = loadEpisodeFromFiles(framesText, manifestText, commandsText);
    expect(loaded.frames.length).toBe(30);
    expect(loaded.manifest?.episode_id).toBe("E-DEMO0001");
    expect(loaded.manifest?.coordinate_system).toBe("ENU");
    expect(loaded.commandLog.length).toBeGreaterThan(0);
    expect(loaded.skipped).toBe(0);
  });

  it("works without manifest or commands (manifest null)", () => {
    const loaded = loadEpisodeFromFiles(framesText);
    expect(loaded.frames.length).toBe(30);
    expect(loaded.manifest).toBeNull();
    expect(loaded.commandLog).toEqual([]);
  });
});

describe("loadEpisodeFromZip", () => {
  function makeZip(entries: Record<string, string>): Uint8Array {
    return zipSync(
      Object.fromEntries(Object.entries(entries).map(([k, v]) => [k, strToU8(v)])),
    );
  }

  it("reads visual/frames.jsonl + manifest + summary + commands from a zip", async () => {
    const summary = JSON.stringify({
      schema_version: "1.0",
      episode_id: "E-DEMO0001",
      scenario_id: "demo",
      episode_status: "completed",
      duration_s: 14.5,
      num_cranes: 3,
      num_tasks_total: 2,
      num_tasks_completed: 1,
      num_tasks_failed: 0,
      task_completion_rate: 0.5,
      near_miss_count: 0,
      collision_count: 0,
      high_risk_duration_s: 0,
      num_llm_calls: 12,
      risk_frame_ratio_by_level: {},
    });
    const blob = makeZip({
      "visual/frames.jsonl": framesText,
      "visual/episode_manifest.json": manifestText,
      "metadata/episode_summary.json": summary,
      "logs/commands.jsonl": commandsText,
      "config/resolved_config.yaml": "# not parsed",
    });
    const loaded = await loadEpisodeFromZip(blob);
    expect(loaded.frames.length).toBe(30);
    expect(loaded.manifest?.episode_id).toBe("E-DEMO0001");
    expect(loaded.summary?.episode_id).toBe("E-DEMO0001");
    expect(loaded.commandLog.length).toBeGreaterThan(0);
  });

  it("returns empty frames (and no throw) when visual/ is missing", async () => {
    const blob = makeZip({ "metadata/episode_summary.json": "{}" });
    const loaded = await loadEpisodeFromZip(blob);
    expect(loaded.frames).toEqual([]);
    expect(loaded.manifest).toBeNull();
  });

  it("still returns frames when manifest is missing", async () => {
    const blob = makeZip({ "visual/frames.jsonl": framesText });
    const loaded = await loadEpisodeFromZip(blob);
    expect(loaded.frames.length).toBe(30);
    expect(loaded.manifest).toBeNull();
  });
});
