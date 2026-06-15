// Bottom timeline: scrubber + play/pause + speed. A RAF loop feeds wall-clock
// deltas to a PlaybackController; scrubbing pauses and jumps.

import { useEffect, useRef } from "react";
import { useStore } from "@/state/store";
import { PlaybackController, createStoreAdapter } from "@/playback";

const SPEEDS = [0.5, 1, 2, 4];

export function Timeline() {
  const total = useStore((s) => s.frames.length);
  const index = useStore((s) => s.currentIndex);
  const playing = useStore((s) => s.playback.playing);
  const speed = useStore((s) => s.playback.speed);
  const setFrame = useStore((s) => s.setFrame);
  const setPlaying = useStore((s) => s.setPlaying);
  const setSpeed = useStore((s) => s.setSpeed);
  const currentTime = useStore((s) => s.latestFrame?.time_s ?? 0);
  const endTime = useStore((s) => (s.frames.length ? s.frames[s.frames.length - 1].time_s : 0));

  const pcRef = useRef<PlaybackController | null>(null);
  if (!pcRef.current) pcRef.current = new PlaybackController(createStoreAdapter());

  useEffect(() => {
    const pc = pcRef.current!;
    let raf = 0;
    let last = 0;
    const loop = (ts: number) => {
      if (last === 0) last = ts;
      const dt = (ts - last) / 1000;
      last = ts;
      pc.tick(dt);
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
  }, []);

  const max = Math.max(0, total - 1);
  const disabled = total === 0;

  return (
    <div className="timeline" data-testid="timeline" style={{ display: "flex", alignItems: "center", gap: 12 }}>
      <button
        className="play-btn"
        data-testid="play-pause"
        onClick={() => pcRef.current!.toggle()}
        disabled={disabled}
        title={playing ? "暂停" : "播放"}
      >
        {playing ? "❚❚" : "▶"}
      </button>
      <input
        data-testid="scrubber"
        type="range"
        min={0}
        max={max}
        value={index}
        disabled={disabled}
        style={{ flex: 1 }}
        onChange={(e) => {
          setPlaying(false);
          setFrame(Number(e.target.value));
        }}
      />
      <span className="muted" style={{ fontVariantNumeric: "tabular-nums" }}>
        {currentTime.toFixed(1)}s / {endTime.toFixed(1)}s
      </span>
      <select
        data-testid="speed"
        value={speed}
        disabled={disabled}
        onChange={(e) => setSpeed(Number(e.target.value))}
        title="倍速"
      >
        {SPEEDS.map((s) => (
          <option key={s} value={s}>
            {s}×
          </option>
        ))}
      </select>
      <span className="muted">
        帧 {total === 0 ? 0 : index + 1}/{total}
      </span>
    </div>
  );
}
