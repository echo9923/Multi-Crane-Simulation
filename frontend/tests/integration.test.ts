// Phase 4 integration tests: cross-module error and edge paths the spec calls
// out explicitly — corrupted frames.jsonl, loading a nonexistent episode, a WS
// error surfacing into the store, an empty episode, and the N=6 boundary.

import { describe, it, expect, beforeEach, vi } from "vitest";
import { useStore } from "@/state/store";
import { ThreeSceneController, type RendererLike, type RendererFactory } from "@/three/ThreeSceneController";
import { EpisodeWebSocketClient, type WebSocketLike, type SocketFactory, type ScheduleFn } from "@/api/ws";
import { parseFramesJsonl, parseManifest, loadEpisodeFromZip } from "@/api/loader";
import { downloadEpisode } from "@/api/rest";
import type { EpisodeManifest, SimFrame } from "@/types/sim";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const framesText = readFileSync(join(here, "fixtures", "frames.jsonl"), "utf8");
const manifest = parseManifest(readFileSync(join(here, "fixtures", "episode_manifest.json"), "utf8")) as EpisodeManifest;
const lines = framesText.split("\n").filter(Boolean);

function stubFactory(): RendererFactory {
  return () => ({
    domElement: document.createElement("canvas"),
    setSize() {}, setPixelRatio() {}, setClearColor() {}, render() {}, dispose() {},
  } as RendererLike);
}
function makeController() {
  return new ThreeSceneController({ canvas: document.createElement("canvas"), createRenderer: stubFactory(), animate: false });
}

beforeEach(() => useStore.getState().reset());

describe("integration: corrupted frames.jsonl", () => {
  it("skips bad/blank lines, loads the good ones, and the scene still renders", () => {
    const corrupted = [lines[0], "{not json", "", "   ", lines[5], lines[10]].join("\n");
    const { frames, skipped } = parseFramesJsonl(corrupted);
    expect(frames.length).toBe(3);
    expect(skipped).toBe(1);
    useStore.getState().loadEpisode(frames, manifest);
    expect(useStore.getState().latestFrame).not.toBeNull();
    const ctrl = makeController();
    ctrl.buildStatic(null, manifest);
    expect(() => ctrl.applyFrame(useStore.getState().latestFrame!)).not.toThrow();
    ctrl.dispose();
  });
});

describe("integration: loading a nonexistent episode", () => {
  it("downloadEpisode surfaces M_E_EPISODE_NOT_FOUND on a 404", async () => {
    global.fetch = vi.fn(async () => ({
      ok: false,
      status: 404,
      json: async () => ({ code: "M_E_EPISODE_NOT_FOUND", message: "nope", details: {} }),
    }) as unknown as Response) as unknown as typeof fetch;
    await expect(downloadEpisode("E-NOPE")).rejects.toMatchObject({ code: "M_E_EPISODE_NOT_FOUND" });
  });

  it("loadEpisodeFromZip on a zip without visual/ yields no frames without throwing", async () => {
    // Build a tiny zip with only a stray file (no visual/frames.jsonl).
    const { zipSync, strToU8 } = await import("fflate");
    const zipped = zipSync({ "readme.txt": strToU8("nope") });
    const loaded = await loadEpisodeFromZip(zipped);
    expect(loaded.frames).toEqual([]);
    expect(loaded.manifest).toBeNull();
    // And loading that into the store warns instead of crashing.
    useStore.getState().loadEpisode(loaded.frames, loaded.manifest);
    expect(useStore.getState().latestFrame).toBeNull();
    expect(useStore.getState().notices.some((n) => n.text.includes("无可用帧"))).toBe(true);
  });
});

describe("integration: WS error -> store connection", () => {
  it("an error message flips the store connection to error with the code", () => {
    class FakeSocket implements WebSocketLike {
      readyState = 0;
      onopen: (() => void) | null = null;
      onmessage: ((e: { data: string }) => void) | null = null;
      onclose: (() => void) | null = null;
      onerror: ((e: unknown) => void) | null = null;
      close() {}
    }
    let t = 1000;
    const schedule: ScheduleFn = (fn, ms) => {
      const j = { fn, at: t + ms, c: false };
      return () => { j.c = true; };
    };
    const sockets: FakeSocket[] = [];
    const wrap: SocketFactory = () => {
      const s = new FakeSocket();
      sockets.push(s);
      return s;
    };
    const client = new EpisodeWebSocketClient({
      episodeId: "E1",
      baseUrl: "/ws",
      socketFactory: wrap,
      now: () => t,
      schedule,
      onFrame: (f) => useStore.getState().pushRealtimeFrame(f),
      onStatus: (status, error) => useStore.getState().setConnection({ status, error: error ?? null }),
    });
    client.connect();
    sockets[0].onopen?.();
    sockets[0].onmessage?.({
      data: JSON.stringify({
        type: "error",
        data: { schema_version: "1.0", code: "M_E_EPISODE_NOT_FOUND", message: "x", details: {} },
      }),
    });
    expect(useStore.getState().connection.status).toBe("error");
    expect(useStore.getState().connection.error).toBe("M_E_EPISODE_NOT_FOUND");
    client.stop();
  });
});

describe("integration: empty episode and N=6 boundary", () => {
  it("an empty episode loads with a warning and the scene stays empty (no crash)", () => {
    useStore.getState().loadEpisode([], null);
    expect(useStore.getState().latestFrame).toBeNull();
    const ctrl = makeController();
    expect(() => ctrl.buildStatic(null, null)).not.toThrow();
    expect(ctrl.hasStatic()).toBe(false);
    ctrl.dispose();
  });

  it("N=6 cranes render and 15 pairs visualize without hardcoding", () => {
    const cranes = Array.from({ length: 6 }, (_, i) => ({
      ...(manifest.cranes[i % 3] as Record<string, unknown>),
      crane_id: `CN${i}`,
      base: [i * 30, (i % 2) * 40, 0],
      root: [i * 30, (i % 2) * 40, 40],
    }));
    const m: EpisodeManifest = { ...manifest, cranes: cranes as EpisodeManifest["cranes"] };
    const ctrl = makeController();
    ctrl.buildStatic(null, m);
    expect(ctrl.getCraneIds().length).toBe(6);
    const frame: SimFrame = {
      ...JSON.parse(lines[0]),
      cranes: cranes.map((c, i) => ({
        ...(JSON.parse(lines[0]).cranes[i % 3] as Record<string, unknown>),
        crane_id: `CN${i}`,
        base: c.base,
        root: c.root,
      })) as SimFrame["cranes"],
      pairs: Array.from({ length: 15 }, (_, k) => ({
        schema_version: "1.0",
        crane_i: `CN${Math.floor(k / (6 - 1))}`,
        crane_j: `CN${(k % 5) + 1}`,
        distance_min_raw_now_m: 10,
        clearance_min_now_m: 5,
        risk_level_now: "medium" as const,
      })),
    };
    expect(() => ctrl.applyFrame(frame)).not.toThrow();
    ctrl.dispose();
  });
});
