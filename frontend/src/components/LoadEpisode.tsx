// Offline episode loader entry points: local files (frames.jsonl +
// episode_manifest.json, optional logs/commands.jsonl) or a downloaded .zip.
// Download-by-id is wired in Task 08 (REST client); this component covers the
// file-based path which is fully usable without a backend.

import { useRef } from "react";
import { useStore } from "@/state/store";
import { loadEpisodeFromFiles, loadEpisodeFromZip } from "@/api/loader";

function readFile(file: File): Promise<string> {
  return file.text();
}

export function LoadEpisode() {
  const inputRef = useRef<HTMLInputElement | null>(null);
  const loadEpisode = useStore((s) => s.loadEpisode);
  const setMode = useStore((s) => s.setMode);
  const setEpisodeId = useStore((s) => s.setEpisodeId);
  const pushNotice = useStore((s) => s.pushNotice);

  const onFiles = async (files: FileList) => {
    const arr = Array.from(files);
    const zip = arr.find((f) => f.name.endsWith(".zip"));
    try {
      if (zip) {
        const loaded = await loadEpisodeFromZip(zip);
        loadEpisode(loaded.frames, loaded.manifest, null, loaded.summary, loaded.commandLog);
        setMode("replay");
        setEpisodeId(loaded.manifest?.episode_id ?? zip.name);
        if (loaded.skipped > 0) pushNotice("warn", `zip 加载跳过 ${loaded.skipped} 行`);
        if (loaded.frames.length === 0) pushNotice("error", "zip 内未找到 visual/frames.jsonl");
        return;
      }
      const framesFile = arr.find((f) => f.name.endsWith("frames.jsonl") || f.name.endsWith(".jsonl"));
      const manifestFile = arr.find((f) => f.name.includes("manifest"));
      const commandsFile = arr.find((f) => f.name.endsWith("commands.jsonl"));
      if (!framesFile) {
        pushNotice("error", "请选择 frames.jsonl 或 episode .zip");
        return;
      }
      const [framesText, manifestText, commandsText] = await Promise.all([
        readFile(framesFile),
        manifestFile ? readFile(manifestFile) : Promise.resolve(null),
        commandsFile ? readFile(commandsFile) : Promise.resolve(null),
      ]);
      const loaded = loadEpisodeFromFiles(framesText, manifestText, commandsText);
      loadEpisode(loaded.frames, loaded.manifest, null, loaded.summary, loaded.commandLog);
      setMode("replay");
      setEpisodeId(loaded.manifest?.episode_id ?? framesFile.name);
      if (loaded.skipped > 0) pushNotice("warn", `加载跳过 ${loaded.skipped} 行`);
    } catch (e) {
      pushNotice("error", `加载失败：${(e as Error).message}`);
    }
  };

  return (
    <section className="panel" data-testid="load-episode">
      <h3>加载 episode（离线）</h3>
      <div className="panel-body">
        <input
          ref={inputRef}
          type="file"
          multiple
          data-testid="file-input"
          accept=".jsonl,.json,.zip"
          onChange={(e) => e.target.files && onFiles(e.target.files)}
        />
        <div className="muted" style={{ marginTop: 6, fontSize: 11 }}>
          选择 frames.jsonl（+ episode_manifest.json / commands.jsonl）或下载的 .zip。
        </div>
        <div className="muted" style={{ marginTop: 4, fontSize: 11 }}>
          按 episode id 下载入口见 Task 08。
        </div>
      </div>
    </section>
  );
}
