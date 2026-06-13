// Cross-task acceptance tests. These exercise the full chains end-to-end at the
// unit level (real store + real controller with a stub renderer; fake WS):
//   - offline replay: frames.jsonl -> parse -> load -> applyFrame -> seek
//   - realtime: WS sim_frame -> pushRealtimeFrame -> applyFrame; disconnect/reconnect
//   - coordinate consistency: hook world <-> three mapping round-trips exactly,
//     and the controller-placed hook world position equals the frame's ENU hook
//   - multi-crane: N=1/3/6 render without hardcoding

import { describe, it, expect, beforeEach } from "vitest";
import * as THREE from "three";
import { useStore } from "@/state/store";
import { ThreeSceneController, type RendererLike, type RendererFactory } from "@/three/ThreeSceneController";
import { EpisodeWebSocketClient, type WebSocketLike, type SocketFactory, type ScheduleFn } from "@/api/ws";
import { parseFramesJsonl, parseManifest, parseCommandLog } from "@/api/loader";
import { manifestFromFrame } from "@/three/model/liveManifest";
import { worldToThree, threeToWorld } from "@/coord";
import type { EpisodeManifest, SimFrame } from "@/types/sim";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const framesText = readFileSync(join(here, "fixtures", "frames.jsonl"), "utf8");
const manifest = parseManifest(readFileSync(join(here, "fixtures", "episode_manifest.json"), "utf8")) as EpisodeManifest;
const frames = parseFramesJsonl(framesText).frames;
const commands = parseCommandLog(readFileSync(join(here, "fixtures", "logs", "commands.jsonl"), "utf8")).rows;

function stubFactory(): RendererFactory {
  return () => ({
    domElement: document.createElement("canvas"),
    setSize() {}, setPixelRatio() {}, setClearColor() {}, render() {}, dispose() {},
  } as RendererLike);
}
function makeController() {
  return new ThreeSceneController({
    canvas: document.createElement("canvas"),
    createRenderer: stubFactory(),
    animate: false,
  });
}

// ---- fakes for the WS chain (compact copies) ----
class FakeSocket implements WebSocketLike {
  readyState = 0;
  onopen: (() => void) | null = null;
  onmessage: ((e: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: ((e: unknown) => void) | null = null;
  constructor(readonly url: string) {}
  close(): void {
    this.readyState = 3;
    this.onclose?.();
  }
  fireOpen(): void {
    this.readyState = 1;
    this.onopen?.();
  }
  fireMessage(data: unknown): void {
    this.onmessage?.({ data: typeof data === "string" ? data : JSON.stringify(data) });
  }
  fireClose(): void {
    this.readyState = 3;
    this.onclose?.();
  }
}
function fakeWs() {
  const sockets: FakeSocket[] = [];
  const factory: SocketFactory = (url) => {
    const s = new FakeSocket(url);
    sockets.push(s);
    return s;
  };
  let t = 1000;
  const jobs: { fn: () => void; at: number; cancelled: boolean }[] = [];
  const schedule: ScheduleFn = (fn, ms) => {
    const j = { fn, at: t + ms, cancelled: false };
    jobs.push(j);
    return () => {
      j.cancelled = true;
    };
  };
  const clock = {
    now: () => t,
    schedule,
    advance(ms: number) {
      t += ms;
      for (const j of [...jobs]) if (!j.cancelled && j.at <= t) {
        j.cancelled = true;
        j.fn();
      }
    },
  };
  return { sockets, factory, clock };
}

describe("acceptance: offline replay chain", () => {
  beforeEach(() => useStore.getState().reset());

  it("parses frames.jsonl, loads, applies frames, and seeks", () => {
    const { frames: fr, skipped } = parseFramesJsonl(framesText);
    expect(skipped).toBe(0);
    expect(fr.length).toBeGreaterThan(0);
    useStore.getState().loadEpisode(fr, manifest, null, null, commands);

    const ctrl = makeController();
    ctrl.buildStatic(useStore.getState().config, useStore.getState().manifest);

    for (let i = 0; i < 5; i++) {
      useStore.getState().setFrame(i);
      ctrl.applyFrame(useStore.getState().latestFrame!);
    }
    const c1 = ctrl.getCraneParts("C1")!;
    const f1 = fr[4].cranes.find((c) => c.crane_id === "C1")!;
    expect(c1.jibAssembly.rotation.y).toBeCloseTo(f1.theta_rad, 5);

    const lastIdx = useStore.getState().seekToTime(fr[fr.length - 1].time_s);
    expect(lastIdx).toBe(fr.length - 1);
    expect(useStore.getState().currentIndex).toBe(fr.length - 1);
    ctrl.dispose();
  });
});

describe("acceptance: realtime WS -> store -> controller", () => {
  beforeEach(() => useStore.getState().reset());

  it("delivered sim_frame flows into the store and renders; disconnect reconnects", () => {
    const { sockets, factory, clock } = fakeWs();
    const client = new EpisodeWebSocketClient({
      episodeId: "E1",
      baseUrl: "/ws",
      socketFactory: factory,
      now: clock.now,
      schedule: clock.schedule,
      onFrame: (f) => useStore.getState().pushRealtimeFrame(f),
      onStatus: () => {},
    });
    client.connect();
    sockets[0].fireOpen();
    sockets[0].fireMessage({ type: "sim_frame", data: frames[3] });
    const live = useStore.getState().latestFrame;
    expect(live).not.toBeNull();
    expect(live!.frame).toBe(frames[3].frame);

    const ctrl = makeController();
    ctrl.buildStatic(null, manifestFromFrame(live!));
    ctrl.applyFrame(live!);
    expect(ctrl.hasStatic()).toBe(true);
    expect(ctrl.getCraneIds().length).toBe(frames[3].cranes.length);

    // disconnect -> exponential-backoff reconnect opens a second socket
    sockets[0].fireClose();
    clock.advance(500);
    expect(sockets.length).toBe(2);

    client.stop();
    ctrl.dispose();
  });
});

describe("acceptance: coordinate consistency", () => {
  it("hook world -> three -> world round-trips exactly (ENU)", () => {
    for (const f of frames.slice(0, 8)) {
      for (const c of f.cranes) {
        const back = threeToWorld(worldToThree(c.hook));
        expect(back[0]).toBeCloseTo(c.hook[0], 9);
        expect(back[1]).toBeCloseTo(c.hook[1], 9);
        expect(back[2]).toBeCloseTo(c.hook[2], 9);
      }
    }
  });

  it("the controller-placed hook world position equals the frame's ENU hook", () => {
    const ctrl = makeController();
    ctrl.buildStatic(null, manifest);
    ctrl.applyFrame(frames[6]);
    for (const c of frames[6].cranes) {
      const parts = ctrl.getCraneParts(c.crane_id)!;
      const wp = new THREE.Vector3();
      parts.hook.getWorldPosition(wp);
      const world = threeToWorld([wp.x, wp.y, wp.z]);
      // The frame stores hook from unrounded trolley/theta while trolley_r_m/
      // hook_h_m are rounded, so allow a 5mm tolerance.
      expect(world[0]).toBeCloseTo(c.hook[0], 2);
      expect(world[1]).toBeCloseTo(c.hook[1], 2);
      expect(world[2]).toBeCloseTo(c.hook[2], 2);
    }
    ctrl.dispose();
  });
});

describe("acceptance: multi-crane (no hardcoded count)", () => {
  function buildWithN(n: number) {
    const cranes = Array.from({ length: n }, (_, i) => ({
      ...(manifest.cranes[i % manifest.cranes.length] as Record<string, unknown>),
      crane_id: `CN${i}`,
      base: [i * 40, 0, 0],
      root: [i * 40, 0, 40],
    }));
    const m: EpisodeManifest = { ...manifest, cranes: cranes as EpisodeManifest["cranes"] };
    const ctrl = makeController();
    ctrl.buildStatic(null, m);
    return ctrl;
  }

  it("renders 1, 3, and 6 cranes", () => {
    for (const n of [1, 3, 6]) {
      const ctrl = buildWithN(n);
      expect(ctrl.getCraneIds().length).toBe(n);
      ctrl.dispose();
    }
  });

  it("a single crane has no risk pairs and does not crash", () => {
    const ctrl = buildWithN(1);
    const singleFrame: SimFrame = {
      ...frames[0],
      cranes: [{ ...frames[0].cranes[0], crane_id: "CN0" }],
      pairs: [],
    };
    expect(() => ctrl.applyFrame(singleFrame)).not.toThrow();
    ctrl.dispose();
  });
});
