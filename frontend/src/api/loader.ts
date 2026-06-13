// Offline episode loaders. parseFramesJsonl / parseManifest are the stable core;
// Task 06 extends this module with zip and file-based loaders.

import { unzipSync, strFromU8 } from "fflate";
import type { SimFrame, EpisodeManifest, EpisodeSummary } from "@/types/sim";
import type { CommandLogRow, EventRow } from "@/types/logs";

export { seekIndexByTime } from "@/state/store";

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

export interface LoadedEpisode {
  frames: SimFrame[];
  skipped: number;
  manifest: EpisodeManifest | null;
  summary: EpisodeSummary | null;
  commandLog: CommandLogRow[];
}

/** Parse a frames.jsonl text and an optional manifest into a LoadedEpisode. */
export function loadEpisodeFromFiles(
  framesText: string,
  manifestText?: string | null,
  commandsText?: string | null,
): LoadedEpisode {
  const r = parseFramesJsonl(framesText);
  return {
    frames: r.frames,
    skipped: r.skipped,
    manifest: manifestText ? parseManifest(manifestText) : null,
    summary: null,
    commandLog: commandsText ? parseCommandLog(commandsText).rows : [],
  };
}

/**
 * Unpack a backend episode download zip (in-memory) and read visual/frames.jsonl,
 * visual/episode_manifest.json, metadata/episode_summary.json and
 * logs/commands.jsonl. config/resolved_config.yaml is intentionally not parsed
 * (no YAML dependency); the scene falls back to the manifest for static layout.
 *
 * Accepts a Blob (browser File upload / fetch), ArrayBuffer, or Uint8Array so it
 * is testable without a real Blob implementation.
 */
export async function loadEpisodeFromZip(
  src: Blob | ArrayBuffer | Uint8Array,
): Promise<LoadedEpisode> {
  const buf = await toUint8Array(src);
  const entries = unzipSync(buf);
  const read = (path: string): string | null =>
    entries[path] ? strFromU8(entries[path]) : null;

  const framesText = read("visual/frames.jsonl");
  const manifestText = read("visual/episode_manifest.json");
  const summaryText = read("metadata/episode_summary.json");
  const commandsText = read("logs/commands.jsonl");

  const r = framesText ? parseFramesJsonl(framesText) : { frames: [], skipped: 0 };
  return {
    frames: r.frames,
    skipped: r.skipped,
    manifest: manifestText ? parseManifest(manifestText) : null,
    summary: summaryText ? parseSummary(summaryText) : null,
    commandLog: commandsText ? parseCommandLog(commandsText).rows : [],
  };
}

async function toUint8Array(src: Blob | ArrayBuffer | Uint8Array): Promise<Uint8Array> {
  if (src instanceof Uint8Array) return src;
  if (src instanceof ArrayBuffer) return new Uint8Array(src);
  const ab =
    typeof src.arrayBuffer === "function"
      ? await src.arrayBuffer()
      : await blobToArrayBufferFallback(src);
  return new Uint8Array(ab);
}

// For environments (jsdom) where Blob.arrayBuffer() is missing.
function blobToArrayBufferFallback(blob: Blob): Promise<ArrayBuffer> {
  return new Promise((resolve, reject) => {
    const fr = new FileReader();
    fr.onload = () => resolve(fr.result as ArrayBuffer);
    fr.onerror = () => reject(fr.error ?? new Error("FileReader error"));
    fr.readAsArrayBuffer(blob);
  });
}



