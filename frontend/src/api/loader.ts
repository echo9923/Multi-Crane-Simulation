// Offline episode loaders. parseFramesJsonl / parseManifest are the stable core;
// Task 06 extends this module with zip and file-based loaders.

import type { SimFrame, EpisodeManifest, EpisodeSummary } from "@/types/sim";
import type { CommandLogRow, EventRow } from "@/types/logs";

export interface FramesParseResult {
  frames: SimFrame[];
  skipped: number;
}

export function parseFramesJsonl(text: string): FramesParseResult {
  const frames: SimFrame[] = [];
  let skipped = 0;
  for (const raw of text.split("\n")) {
    const line = raw.trim();
    if (line.length === 0) continue;
    try {
      frames.push(JSON.parse(line) as SimFrame);
    } catch {
      skipped += 1;
    }
  }
  return { frames, skipped };
}

export function parseManifest(json: string): EpisodeManifest | null {
  try {
    return JSON.parse(json) as EpisodeManifest;
  } catch {
    return null;
  }
}

export function parseSummary(json: string): EpisodeSummary | null {
  try {
    return JSON.parse(json) as EpisodeSummary;
  } catch {
    return null;
  }
}

export function parseCommandLog(text: string): { rows: CommandLogRow[]; skipped: number } {
  const rows: CommandLogRow[] = [];
  let skipped = 0;
  for (const raw of text.split("\n")) {
    const line = raw.trim();
    if (line.length === 0) continue;
    try {
      rows.push(JSON.parse(line) as CommandLogRow);
    } catch {
      skipped += 1;
    }
  }
  return { rows, skipped };
}

/** Flatten all events across loaded frames into a single chronological list. */
export function collectEventsFromFrames(frames: SimFrame[]): EventRow[] {
  const out: EventRow[] = [];
  for (const f of frames) {
    for (const e of f.events) {
      out.push(e as EventRow);
    }
  }
  return out;
}

