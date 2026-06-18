import { describe, it, expect, beforeEach } from "vitest";
import { useStore, seekIndexByTime } from "@/state/store";
import type { SimFrame } from "@/types/sim";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const framesText = readFileSync(join(here, "fixtures", "frames.jsonl"), "utf8");
const frames: SimFrame[] = framesText
  .split("\n")
  .filter((l) => l.trim().length > 0)
  .map((l) => JSON.parse(l));

function freshStore() {
  useStore.getState().reset();
  return useStore.getState();
}

describe("store loadEpisode / setFrame", () => {
  beforeEach(() => useStore.getState().reset());

  it("loads frames and points latestFrame at the first frame", () => {
    const st = useStore.getState();
    st.loadEpisode(frames, null);
    const s = useStore.getState();
    expect(s.frames.length).toBe(frames.length);
    expect(s.currentIndex).toBe(0);
    expect(s.latestFrame).not.toBeNull();
    expect(s.latestFrame!.episode_id).toBe(frames[0].episode_id);
  });

  it("setFrame clamps within range and updates latestFrame", () => {
    const st = useStore.getState();
    st.loadEpisode(frames, null);
    useStore.getState().setFrame(5);
    expect(useStore.getState().currentIndex).toBe(5);
    expect(useStore.getState().latestFrame!.frame).toBe(frames[5].frame);
    useStore.getState().setFrame(99999);
    expect(useStore.getState().currentIndex).toBe(frames.length - 1);
    useStore.getState().setFrame(-10);
    expect(useStore.getState().currentIndex).toBe(0);
  });

  it("loadEpisode with empty frames leaves latestFrame null and warns", () => {
    useStore.getState().loadEpisode([], null);
    const s = useStore.getState();
    expect(s.latestFrame).toBeNull();
    expect(s.notices.some((n) => n.text.includes("无可用帧"))).toBe(true);
  });

  it("pushRealtimeFrame sets latestFrame and episode id (live path)", () => {
    const f = frames[0];
    useStore.getState().pushRealtimeFrame(f);
    const s = useStore.getState();
    expect(s.latestFrame).toBe(f);
    expect(s.episodeId).toBe(f.episode_id);
    expect(s.frames).toEqual([f]);
    expect(s.currentIndex).toBe(0);
  });

  it("pushRealtimeFrame ignores duplicate or older frames in the live buffer", () => {
    const first = frames[2];
    const older = frames[1];
    useStore.getState().pushRealtimeFrame(first);
    useStore.getState().pushRealtimeFrame(older);
    const s = useStore.getState();
    expect(s.frames).toEqual([first]);
    expect(s.latestFrame).toBe(older);
    expect(s.currentIndex).toBe(0);
  });

  it("startLiveEpisode clears stale replay state before live frames arrive", () => {
    useStore.getState().loadEpisode(frames, {
      schema_version: "1.0",
      episode_id: "E-replay",
      scenario_id: "scenario-replay",
      episode_status: "completed",
      frame_count: frames.length,
      dt: 0.1,
      coordinate_system: "ENU",
      cranes: [],
      site: {},
      material_zones: [],
      work_zones: [],
      forbidden_zones: [],
      overlap_zones: [],
      offline_labels_available: false,
    });

    useStore.getState().startLiveEpisode("E-live");
    const s = useStore.getState();

    expect(s.mode).toBe("live");
    expect(s.episodeId).toBe("E-live");
    expect(s.config).toBeNull();
    expect(s.manifest).toBeNull();
    expect(s.summary).toBeNull();
    expect(s.commandLog).toEqual([]);
    expect(s.frames).toEqual([]);
    expect(s.latestFrame).toBeNull();
    expect(s.currentIndex).toBe(0);
  });

  it("pushRealtimeFrame resets the live buffer when the episode id changes", () => {
    const first = { ...frames[0], episode_id: "E-live-1", frame: 3 };
    const nextEpisode = { ...frames[1], episode_id: "E-live-2", frame: 0 };

    useStore.getState().startLiveEpisode("E-live-1");
    useStore.getState().pushRealtimeFrame(first);
    useStore.getState().pushRealtimeFrame(nextEpisode);
    const s = useStore.getState();

    expect(s.episodeId).toBe("E-live-2");
    expect(s.frames).toEqual([nextEpisode]);
    expect(s.latestFrame).toBe(nextEpisode);
    expect(s.currentIndex).toBe(0);
  });
});

describe("seekIndexByTime binary search", () => {
  it("finds the closest frame at or before the target time", () => {
    expect(seekIndexByTime(frames, 0)).toBe(0);
    const last = frames.length - 1;
    expect(seekIndexByTime(frames, frames[last].time_s)).toBe(last);
    expect(seekIndexByTime(frames, frames[last].time_s + 100)).toBe(last);
  });

  it("clamps before-first to 0", () => {
    expect(seekIndexByTime(frames, -5)).toBe(0);
  });

  it("returns 0 for an empty frame list", () => {
    expect(seekIndexByTime([], 10)).toBe(0);
  });
});

describe("ui and connection slices", () => {
  beforeEach(() => useStore.getState().reset());

  it("setUI toggles showRisk and selection", () => {
    useStore.getState().setUI({ showRisk: false, selectedCraneId: "C2" });
    const s = useStore.getState();
    expect(s.ui.showRisk).toBe(false);
    expect(s.ui.selectedCraneId).toBe("C2");
  });

  it("setConnection patches connection state", () => {
    useStore.getState().setConnection({ status: "open", attempts: 3 });
    expect(useStore.getState().connection.status).toBe("open");
    expect(useStore.getState().connection.attempts).toBe(3);
  });
});
