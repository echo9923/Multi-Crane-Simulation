import { describe, it, expect, beforeEach } from "vitest";
import { PlaybackController, createStoreAdapter, type PlaybackAdapter } from "@/playback";
import { useStore } from "@/state/store";
import { parseFramesJsonl, parseManifest } from "@/api/loader";
import type { SimFrame } from "@/types/sim";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const frames = parseFramesJsonl(readFileSync(join(here, "fixtures", "frames.jsonl"), "utf8")).frames;
const manifest = parseManifest(readFileSync(join(here, "fixtures", "episode_manifest.json"), "utf8"))!;

function fakeAdapter(frames: SimFrame[]): PlaybackAdapter & { index: number; playing: boolean; speed: number } {
  const state = { index: 0, playing: false, speed: 1 };
  return {
    get index() {
      return state.index;
    },
    get playing() {
      return state.playing;
    },
    get speed() {
      return state.speed;
    },
    set speed(v: number) {
      state.speed = v;
    },
    getFrames: () => frames,
    getCurrentIndex: () => state.index,
    getPlaying: () => state.playing,
    getSpeed: () => state.speed,
    setFrame: (i) => {
      state.index = i;
    },
    setPlaying: (b) => {
      state.playing = b;
    },
  } as PlaybackAdapter & { index: number; playing: boolean; speed: number };
}

describe("PlaybackController (deterministic tick)", () => {
  it("advances the frame index according to speed x elapsed time", () => {
    const a = fakeAdapter(frames);
    const pc = new PlaybackController(a);
    pc.play();
    expect(a.playing).toBe(true);
    // dt=0.5s, speed=1 -> playhead 0.5 -> frame index 1 (frames are 0.5s apart)
    pc.tick(0.5);
    expect(a.index).toBe(1);
    pc.tick(0.5);
    expect(a.index).toBe(2);
    // speed=2 -> advances 1.0s of episode per 0.5s real
    a.speed = 2;
    pc.tick(0.5);
    expect(a.index).toBe(4);
  });

  it("stops at the last frame and clears playing", () => {
    const a = fakeAdapter(frames);
    const pc = new PlaybackController(a);
    pc.play();
    // Jump playhead near the end then overshoot.
    pc.playhead = frames[frames.length - 1].time_s - 0.1;
    const more = pc.tick(1);
    expect(more).toBe(false);
    expect(a.index).toBe(frames.length - 1);
    expect(a.playing).toBe(false);
  });

  it("tick is a no-op when paused", () => {
    const a = fakeAdapter(frames);
    const pc = new PlaybackController(a);
    expect(pc.tick(5)).toBe(false);
    expect(a.index).toBe(0);
  });

  it("play is a no-op with no frames", () => {
    const a = fakeAdapter([]);
    const pc = new PlaybackController(a);
    pc.play();
    expect(a.playing).toBe(false);
  });
});

describe("createStoreAdapter integration", () => {
  beforeEach(() => useStore.getState().reset());

  it("drives the real store", () => {
    useStore.getState().loadEpisode(frames, manifest);
    const pc = new PlaybackController(createStoreAdapter());
    pc.play();
    expect(useStore.getState().playback.playing).toBe(true);
    pc.tick(1.0);
    expect(useStore.getState().currentIndex).toBe(2);
    pc.pause();
    expect(useStore.getState().playback.playing).toBe(false);
  });
});
