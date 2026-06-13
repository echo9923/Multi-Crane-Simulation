// Global application state (Zustand). The 3D controller subscribes to frame
// changes imperatively; React panels subscribe to derived slices. This keeps the
// 10 FPS frame stream from forcing React re-renders of the whole tree.

import { create } from "zustand";
import type { SimFrame, EpisodeManifest, EpisodeSummary } from "@/types/sim";
import type { ResolvedConfig } from "@/types/config";

export type AppMode = "replay" | "live" | "idle";

export type ConnectionStatus =
  | "idle"
  | "connecting"
  | "open"
  | "reconnecting"
  | "error";

export interface PlaybackState {
  playing: boolean;
  speed: number; // multiplier
}

export interface ConnectionState {
  status: ConnectionStatus;
  error: string | null;
  attempts: number;
  lastServerTimeS: number | null;
}

export interface UIState {
  selectedCraneId: string | null;
  followCraneId: string | null;
  showRisk: boolean;
  showZones: boolean;
}

export interface AppState {
  mode: AppMode;
  episodeId: string | null;
  config: ResolvedConfig | null;
  manifest: EpisodeManifest | null;
  summary: EpisodeSummary | null;

  // Offline replay: full frame buffer in memory.
  frames: SimFrame[];
  currentIndex: number;
  latestFrame: SimFrame | null;

  playback: PlaybackState;
  connection: ConnectionState;
  ui: UIState;

  // Notifications surfaced to the UI (parse errors, skipped rows, etc.).
  notices: { kind: "info" | "warn" | "error"; text: string }[];

  // ---- actions ----
  loadEpisode: (
    frames: SimFrame[],
    manifest: EpisodeManifest | null,
    config?: ResolvedConfig | null,
    summary?: EpisodeSummary | null,
  ) => void;
  setEpisodeId: (id: string | null) => void;
  setMode: (mode: AppMode) => void;
  setFrame: (index: number) => void;
  stepFrame: (delta: number) => void;
  pushRealtimeFrame: (frame: SimFrame) => void;
  setPlaying: (playing: boolean) => void;
  setSpeed: (speed: number) => void;
  seekToTime: (timeS: number) => number;
  setConnection: (patch: Partial<ConnectionState>) => void;
  setUI: (patch: Partial<UIState>) => void;
  pushNotice: (kind: "info" | "warn" | "error", text: string) => void;
  clearNotices: () => void;
  reset: () => void;
}

const initialPlayback: PlaybackState = { playing: false, speed: 1 };
const initialConnection: ConnectionState = {
  status: "idle",
  error: null,
  attempts: 0,
  lastServerTimeS: null,
};
const initialUI: UIState = {
  selectedCraneId: null,
  followCraneId: null,
  showRisk: true,
  showZones: true,
};

// Binary search for the frame whose time_s is closest to (<=) target.
export function seekIndexByTime(frames: SimFrame[], timeS: number): number {
  if (frames.length === 0) return 0;
  if (timeS <= frames[0].time_s) return 0;
  if (timeS >= frames[frames.length - 1].time_s) return frames.length - 1;
  let lo = 0;
  let hi = frames.length - 1;
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1;
    if (frames[mid].time_s <= timeS) lo = mid;
    else hi = mid - 1;
  }
  return lo;
}

export const useStore = create<AppState>((set, get) => ({
  mode: "idle",
  episodeId: null,
  config: null,
  manifest: null,
  summary: null,
  frames: [],
  currentIndex: 0,
  latestFrame: null,
  playback: { ...initialPlayback },
  connection: { ...initialConnection },
  ui: { ...initialUI },
  notices: [],

  loadEpisode: (frames, manifest, config = null, summary = null) =>
    set({
      frames,
      manifest,
      config,
      summary,
      currentIndex: frames.length > 0 ? 0 : 0,
      latestFrame: frames.length > 0 ? frames[0] : null,
      playback: { ...initialPlayback },
      notices:
        frames.length === 0
          ? [{ kind: "warn", text: "无可用帧" }]
          : get().notices,
    }),

  setEpisodeId: (id) => set({ episodeId: id }),
  setMode: (mode) => set({ mode }),

  setFrame: (index) => {
    const { frames } = get();
    const clamped = frames.length === 0 ? 0 : Math.max(0, Math.min(index, frames.length - 1));
    set({ currentIndex: clamped, latestFrame: frames[clamped] ?? null });
  },

  stepFrame: (delta) => {
    const { currentIndex } = get();
    get().setFrame(currentIndex + delta);
  },

  pushRealtimeFrame: (frame) =>
    set({ latestFrame: frame, episodeId: frame.episode_id }),

  setPlaying: (playing) => set((s) => ({ playback: { ...s.playback, playing } })),
  setSpeed: (speed) => set((s) => ({ playback: { ...s.playback, speed } })),

  seekToTime: (timeS) => {
    const idx = seekIndexByTime(get().frames, timeS);
    get().setFrame(idx);
    return idx;
  },

  setConnection: (patch) =>
    set((s) => ({ connection: { ...s.connection, ...patch } })),

  setUI: (patch) => set((s) => ({ ui: { ...s.ui, ...patch } })),

  pushNotice: (kind, text) =>
    set((s) => ({ notices: [...s.notices, { kind, text }] })),
  clearNotices: () => set({ notices: [] }),

  reset: () =>
    set({
      mode: "idle",
      episodeId: null,
      config: null,
      manifest: null,
      summary: null,
      frames: [],
      currentIndex: 0,
      latestFrame: null,
      playback: { ...initialPlayback },
      connection: { ...initialConnection },
      ui: { ...initialUI },
      notices: [],
    }),
}));
