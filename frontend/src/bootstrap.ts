// Demo bootstrap: loads the bundled sample episode so the app shows motion on
// first launch without requiring a backend or uploaded files. Real loading
// (download zip / local file) lives in Task 06.

import { useStore } from "@/state/store";
import { parseFramesJsonl, parseManifest } from "@/api/loader";
import demoFrames from "../tests/fixtures/frames.jsonl?raw";
import demoManifest from "../tests/fixtures/episode_manifest.json?raw";

export function loadDemoEpisode(): void {
  const { frames, skipped } = parseFramesJsonl(demoFrames);
  const manifest = parseManifest(demoManifest);
  useStore.getState().loadEpisode(frames, manifest);
  useStore.getState().setMode("replay");
  useStore.getState().setEpisodeId(manifest?.episode_id ?? "E-DEMO0001");
  if (skipped > 0) {
    useStore.getState().pushNotice("warn", `demo 加载跳过 ${skipped} 行`);
  }
}

export function ensureDemoLoaded(): void {
  if (useStore.getState().frames.length === 0 && useStore.getState().latestFrame === null) {
    loadDemoEpisode();
  }
}
