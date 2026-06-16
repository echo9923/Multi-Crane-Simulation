import { beforeEach, describe, it, expect } from "vitest";
import { EpisodeWebSocketClient, type WebSocketLike, type SocketFactory, type ScheduleFn } from "@/api/ws";
import type { SimFrame } from "@/types/sim";
import { parseFramesJsonl } from "@/api/loader";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const frames = parseFramesJsonl(readFileSync(join(here, "fixtures", "frames.jsonl"), "utf8")).frames;

beforeEach(() => {
  window.history.replaceState(null, "", "/");
  delete window.__MULTI_CRANE_DESKTOP__;
});

// ---- fakes ----

class FakeSocket implements WebSocketLike {
  readyState = 0;
  onopen: (() => void) | null = null;
  onmessage: ((e: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: ((e: unknown) => void) | null = null;
  closed = false;
  readonly url: string;
  constructor(url: string) {
    this.url = url;
  }
  close(): void {
    this.closed = true;
    this.readyState = 3;
    // A real browser fires onclose after close(); mirror that so the client's
    // reconnect path is exercised (stop() nulls onclose first, so it stays inert).
    this.onclose?.();
  }
  fireOpen(): void {
    this.readyState = 1;
    this.onopen?.();
  }
  fireMessage(data: unknown): void {
    const text = typeof data === "string" ? data : JSON.stringify(data);
    this.onmessage?.({ data: text });
  }
  fireRaw(text: string): void {
    this.onmessage?.({ data: text });
  }
  fireClose(): void {
    this.readyState = 3;
    this.onclose?.();
  }
  fireError(e: unknown): void {
    this.onerror?.(e);
  }
}

function fakeFactory() {
  const sockets: FakeSocket[] = [];
  const factory: SocketFactory = (url) => {
    const s = new FakeSocket(url);
    sockets.push(s);
    return s;
  };
  return { factory, sockets };
}

function fakeClock() {
  let t = 1000;
  const jobs: { fn: () => void; at: number; cancelled: boolean }[] = [];
  const schedule: ScheduleFn = (fn, ms) => {
    const job = { fn, at: t + ms, cancelled: false };
    jobs.push(job);
    return () => {
      job.cancelled = true;
    };
  };
  return {
    now: () => t,
    schedule,
    advance(ms: number) {
      t += ms;
      // run due jobs once, in order; a job may schedule another (picked next advance)
      for (const j of [...jobs]) {
        if (!j.cancelled && j.at <= t) {
          j.cancelled = true;
          j.fn();
        }
      }
    },
    pending: () => jobs.filter((j) => !j.cancelled).length,
  };
}

function makeClient(opts: {
  onFrame: (f: SimFrame) => void;
  onStatus: (s: string, err?: string | null, a?: number) => void;
  factory: SocketFactory;
  clock: ReturnType<typeof fakeClock>;
  maxAttempts?: number;
  heartbeatTimeoutMs?: number;
}) {
  return new EpisodeWebSocketClient({
    episodeId: "E1",
    baseUrl: "/ws",
    socketFactory: opts.factory,
    now: opts.clock.now,
    schedule: opts.clock.schedule,
    onFrame: opts.onFrame,
    onStatus: opts.onStatus,
    maxAttempts: opts.maxAttempts,
    heartbeatTimeoutMs: opts.heartbeatTimeoutMs,
  });
}

describe("EpisodeWebSocketClient message handling", () => {
  it("routes sim_frame to onFrame", () => {
    const { factory, sockets } = fakeFactory();
    const clock = fakeClock();
    const frames2: SimFrame[] = [];
    const statuses: string[] = [];
    const c = makeClient({ onFrame: (f) => frames2.push(f), onStatus: (s) => statuses.push(s), factory, clock });
    c.connect();
    sockets[0].fireOpen();
    sockets[0].fireMessage({ type: "sim_frame", data: frames[0] });
    expect(frames2.length).toBe(1);
    expect(frames2[0].episode_id).toBe(frames[0].episode_id);
    expect(statuses).toContain("open");
  });

  it("routes error to onStatus and keeps the last frame", () => {
    const { factory, sockets } = fakeFactory();
    const clock = fakeClock();
    let lastErr: string | null = null;
    const c = makeClient({
      onFrame: () => {},
      onStatus: (_s, err) => {
        lastErr = err ?? null;
      },
      factory,
      clock,
    });
    c.connect();
    sockets[0].fireOpen();
    sockets[0].fireMessage({ type: "sim_frame", data: frames[0] });
    sockets[0].fireMessage({ type: "error", data: { schema_version: "1.0", code: "M_E_EPISODE_NOT_FOUND", message: "x", details: {} } });
    expect(lastErr).toBe("M_E_EPISODE_NOT_FOUND");
  });

  it("heartbeat does not produce a frame", () => {
    const { factory, sockets } = fakeFactory();
    const clock = fakeClock();
    let n = 0;
    const c = makeClient({ onFrame: () => (n += 1), onStatus: () => {}, factory, clock });
    c.connect();
    sockets[0].fireOpen();
    sockets[0].fireMessage({ type: "heartbeat", data: { server_time_s: 1 } });
    expect(n).toBe(0);
  });

  it("rejects realtime frames that carry offline_labels", () => {
    const { factory, sockets } = fakeFactory();
    const clock = fakeClock();
    let n = 0;
    let err: string | null = null;
    const c = makeClient({
      onFrame: () => (n += 1),
      onStatus: (_s, e) => {
        err = e ?? null;
      },
      factory,
      clock,
    });
    c.connect();
    sockets[0].fireOpen();
    const bad = { ...frames[0], offline_labels: { pair_labels: [] } };
    sockets[0].fireMessage({ type: "sim_frame", data: bad });
    expect(n).toBe(0);
    expect(err).toContain("offline");
  });

  it("ignores malformed JSON with an error status", () => {
    const { factory, sockets } = fakeFactory();
    const clock = fakeClock();
    let err: string | null = null;
    const c = makeClient({ onFrame: () => {}, onStatus: (_s, e) => (err = e ?? null), factory, clock });
    c.connect();
    sockets[0].fireOpen();
    sockets[0].fireRaw("not json");
    expect(err).toBeTruthy();
  });
});

describe("EpisodeWebSocketClient reconnect", () => {
  it("reconnects with exponential backoff after close, up to maxAttempts", () => {
    const { factory, sockets } = fakeFactory();
    const clock = fakeClock();
    const statuses: string[] = [];
    // maxAttempts = 2 -> two reconnects, then the next close errors out.
    const c = makeClient({ onFrame: () => {}, onStatus: (s) => statuses.push(s), factory, clock, maxAttempts: 2 });
    c.connect();
    expect(sockets.length).toBe(1);
    sockets[0].fireClose(); // reconnect #1 (500ms)
    expect(statuses).toContain("reconnecting");
    clock.advance(500);
    expect(sockets.length).toBe(2);
    sockets[1].fireClose(); // reconnect #2 (1000ms)
    clock.advance(1000);
    expect(sockets.length).toBe(3);
    sockets[2].fireClose(); // attempts now == maxAttempts -> error, no socket4
    expect(statuses).toContain("error");
    clock.advance(8000);
    expect(sockets.length).toBe(3);
    c.stop();
  });

  it("stop() prevents further reconnects", () => {
    const { factory, sockets } = fakeFactory();
    const clock = fakeClock();
    const c = makeClient({ onFrame: () => {}, onStatus: () => {}, factory, clock });
    c.connect();
    sockets[0].fireOpen();
    c.stop();
    sockets[0].fireClose();
    clock.advance(10000);
    expect(sockets.length).toBe(1);
  });

  it("force-reconnects when the heartbeat times out", () => {
    const { factory, sockets } = fakeFactory();
    const clock = fakeClock();
    const c = makeClient({ onFrame: () => {}, onStatus: () => {}, factory, clock, heartbeatTimeoutMs: 5000 });
    c.connect();
    sockets[0].fireOpen();
    expect(sockets.length).toBe(1);
    // No messages for the heartbeat window -> the heartbeat job closes the socket
    // -> onclose schedules a reconnect -> advancing the clock opens a new socket.
    clock.advance(5000);
    clock.advance(500);
    expect(sockets.length).toBe(2);
    c.stop();
  });

  it("resets attempts after a successful open", () => {
    const { factory, sockets } = fakeFactory();
    const clock = fakeClock();
    const c = makeClient({ onFrame: () => {}, onStatus: () => {}, factory, clock, maxAttempts: 5 });
    c.connect();
    sockets[0].fireClose(); // attempt 1
    clock.advance(500);
    sockets[1].fireOpen(); // resets
    expect(c.getAttempts()).toBe(0);
    c.stop();
  });
});

describe("EpisodeWebSocketClient runtime URL", () => {
  it("uses the injected desktop WS base when no explicit baseUrl is passed", () => {
    window.__MULTI_CRANE_DESKTOP__ = { wsBase: "ws://127.0.0.1:8765/ws", mode: "desktop" };
    const { factory, sockets } = fakeFactory();
    const clock = fakeClock();
    const c = new EpisodeWebSocketClient({
      episodeId: "E1",
      socketFactory: factory,
      now: clock.now,
      schedule: clock.schedule,
      onFrame: () => {},
      onStatus: () => {},
    });

    c.connect();

    expect(sockets[0].url).toBe("ws://127.0.0.1:8765/ws/episodes/E1");
    c.stop();
  });
});
