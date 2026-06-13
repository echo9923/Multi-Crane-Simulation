// Deterministic playback controller. Advances a playhead in SimFrame.time_s
// space; the RAF loop in the Timeline feeds wall-clock deltas to tick(), which
// is also callable directly from tests (no timers needed).

import type { SimFrame } from "@/types/sim";
import { seekIndexByTime, useStore } from "@/state/store";

export interface PlaybackAdapter {
  getFrames(): SimFrame[];
  getCurrentIndex(): number;
  getPlaying(): boolean;
  getSpeed(): number;
  setFrame(i: number): void;
  setPlaying(playing: boolean): void;
}

export function createStoreAdapter(store = useStore): PlaybackAdapter {
  return {
    getFrames: () => store.getState().frames,
    getCurrentIndex: () => store.getState().currentIndex,
    getPlaying: () => store.getState().playback.playing,
    getSpeed: () => store.getState().playback.speed,
    setFrame: (i) => store.getState().setFrame(i),
    setPlaying: (b) => store.getState().setPlaying(b),
  };
}

export class PlaybackController {
  /** Current playhead in episode time_s. */
  playhead = 0;

  constructor(private adapter: PlaybackAdapter) {}

  play(): void {
    const frames = this.adapter.getFrames();
    if (frames.length === 0) return;
    const cur = this.adapter.getCurrentIndex();
    this.playhead = frames[cur]?.time_s ?? 0;
    this.adapter.setPlaying(true);
  }

  pause(): void {
    this.adapter.setPlaying(false);
  }

  toggle(): void {
    if (this.adapter.getPlaying()) this.pause();
    else this.play();
  }

  /**
   * Advance the playhead by `realSeconds` of wall-clock time, scaled by speed.
   * Returns true while still playing, false when paused or reached the end.
   */
  tick(realSeconds: number): boolean {
    const frames = this.adapter.getFrames();
    if (!this.adapter.getPlaying() || frames.length === 0) return false;
    this.playhead += realSeconds * this.adapter.getSpeed();
    const lastTime = frames[frames.length - 1].time_s;
    if (this.playhead >= lastTime) {
      this.playhead = lastTime;
      this.adapter.setFrame(frames.length - 1);
      this.adapter.setPlaying(false);
      return false;
    }
    this.adapter.setFrame(seekIndexByTime(frames, this.playhead));
    return true;
  }
}
