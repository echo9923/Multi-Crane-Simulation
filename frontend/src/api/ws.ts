// Realtime WebSocket client for WS /ws/episodes/{episode_id}. Handles the three
// backend message types (sim_frame / error / heartbeat), exponential-backoff
// reconnect, heartbeat-timeout reconnect, and graceful stop.
//
// The socket factory, clock (now), and scheduler are injectable so reconnect
// sequences and heartbeat timeouts are fully unit-testable without real timers.

import type { SimFrame } from "@/types/sim";
import type { ApiError } from "@/types/api";
import type { ConnectionStatus } from "@/state/store";

export type WSMessage =
  | { type: "sim_frame"; data: SimFrame }
  | { type: "error"; data: ApiError }
  | { type: "heartbeat"; data: { server_time_s: number } };

export interface WebSocketLike {
  readyState: number;
  onopen: (() => void) | null;
  onmessage: ((e: { data: string }) => void) | null;
  onclose: (() => void) | null;
  onerror: ((e: unknown) => void) | null;
  close(): void;
}

export type SocketFactory = (url: string) => WebSocketLike;
export type ScheduleFn = (fn: () => void, ms: number) => () => void; // returns cancel

export interface WSClientOptions {
  episodeId: string;
  baseUrl?: string; // default: built from window.location, path prefix "/ws"
  socketFactory?: SocketFactory;
  onFrame: (frame: SimFrame) => void;
  onStatus: (status: ConnectionStatus, error?: string | null, attempts?: number) => void;
  maxAttempts?: number;
  heartbeatTimeoutMs?: number;
  now?: () => number;
  schedule?: ScheduleFn;
}

function defaultNow(): number {
  return typeof performance !== "undefined" && performance.now ? performance.now() : Date.now();
}

function defaultSchedule(fn: () => void, ms: number): () => void {
  const h = setTimeout(fn, ms);
  return () => clearTimeout(h);
}

function defaultSocketFactory(url: string): WebSocketLike {
  return new WebSocket(url) as unknown as WebSocketLike;
}

function defaultUrl(episodeId: string): string {
  if (typeof window !== "undefined" && window.location) {
    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    return `${proto}//${window.location.host}/ws/episodes/${episodeId}`;
  }
  return `/ws/episodes/${episodeId}`;
}

export class EpisodeWebSocketClient {
  private socket: WebSocketLike | null = null;
  private attempts = 0;
  private stopped = false;
  private lastMsgAt: number;
  private heartbeatCancel: (() => void) | null = null;
  private reconnectCancel: (() => void) | null = null;

  private readonly now: () => number;
  private readonly schedule: ScheduleFn;
  private readonly socketFactory: SocketFactory;
  private readonly url: string;
  private readonly maxAttempts: number;
  private readonly heartbeatTimeoutMs: number;
  private readonly baseDelayMs = 500;
  private readonly maxDelayMs = 8000;

  constructor(private readonly opts: WSClientOptions) {
    this.now = opts.now ?? defaultNow;
    this.schedule = opts.schedule ?? defaultSchedule;
    this.socketFactory = opts.socketFactory ?? defaultSocketFactory;
    this.url = opts.baseUrl
      ? `${opts.baseUrl}/episodes/${opts.episodeId}`
      : defaultUrl(opts.episodeId);
    this.maxAttempts = opts.maxAttempts ?? 8;
    this.heartbeatTimeoutMs = opts.heartbeatTimeoutMs ?? 15000;
    this.lastMsgAt = this.now();
  }

  connect(): void {
    this.stopped = false;
    this.attempts = 0;
    this.openSocket();
  }

  getAttempts(): number {
    return this.attempts;
  }

  stop(): void {
    this.stopped = true;
    this.disposeTimers();
    if (this.socket) {
      this.socket.onclose = null;
      this.socket.close();
      this.socket = null;
    }
    this.opts.onStatus("idle");
  }

  private openSocket(): void {
    this.opts.onStatus(this.attempts === 0 ? "connecting" : "reconnecting", null, this.attempts);
    const sock = this.socketFactory(this.url);
    this.socket = sock;
    sock.onopen = () => {
      this.attempts = 0;
      this.lastMsgAt = this.now();
      this.opts.onStatus("open", null, 0);
      this.armHeartbeat();
    };
    sock.onmessage = (e) => this.handleMessage(e.data);
    sock.onclose = () => {
      this.disposeTimers();
      if (!this.stopped) this.scheduleReconnect();
    };
    sock.onerror = () => {
      this.opts.onStatus("error", "websocket error", this.attempts);
    };
  }

  private handleMessage(data: string): void {
    this.lastMsgAt = this.now();
    let msg: WSMessage;
    try {
      msg = JSON.parse(data) as WSMessage;
    } catch {
      this.opts.onStatus("error", "malformed message");
      return;
    }
    if (!msg || typeof msg.type !== "string") {
      this.opts.onStatus("error", "unknown message");
      return;
    }
    if (msg.type === "sim_frame") {
      const frame = (msg as { data: SimFrame }).data;
      if (!frame) {
        this.opts.onStatus("error", "sim_frame missing data");
        return;
      }
      // Realtime frames must never carry offline_labels.
      if (frame.offline_labels != null) {
        this.opts.onStatus("error", "realtime frame must not include offline labels");
        return;
      }
      this.opts.onFrame(frame);
      this.armHeartbeat();
    } else if (msg.type === "error") {
      const err = (msg as { data: ApiError }).data;
      this.opts.onStatus("error", err?.code ?? "error");
    } else if (msg.type === "heartbeat") {
      this.armHeartbeat();
    }
  }

  private armHeartbeat(): void {
    this.heartbeatCancel?.();
    this.heartbeatCancel = this.schedule(() => {
      const idle = this.now() - this.lastMsgAt;
      if (idle >= this.heartbeatTimeoutMs) {
        // No recent traffic: force a reconnect.
        this.socket?.close();
      } else {
        this.armHeartbeat();
      }
    }, this.heartbeatTimeoutMs);
  }

  private scheduleReconnect(): void {
    if (this.stopped) return;
    if (this.attempts >= this.maxAttempts) {
      this.opts.onStatus("error", "max reconnect attempts reached", this.attempts);
      return;
    }
    this.attempts += 1;
    const delay = Math.min(this.maxDelayMs, this.baseDelayMs * 2 ** (this.attempts - 1));
    this.opts.onStatus("reconnecting", null, this.attempts);
    this.reconnectCancel = this.schedule(() => this.openSocket(), delay);
  }

  private disposeTimers(): void {
    this.heartbeatCancel?.();
    this.heartbeatCancel = null;
    this.reconnectCancel?.();
    this.reconnectCancel = null;
  }
}
