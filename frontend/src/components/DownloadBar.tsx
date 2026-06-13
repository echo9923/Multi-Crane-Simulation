// Download / replay-by-id bar. "回放" downloads the episode zip and loads it
// into the offline replay path; "下载" saves the zip to disk. Errors surface as
// notices with the backend error code (e.g. M_E_DOWNLOAD_FAILED).

import { useState } from "react";
import { downloadEpisode } from "@/api/rest";
import { loadEpisodeFromZip } from "@/api/loader";
import { useStore } from "@/state/store";
import { ApiClientError } from "@/types/api";

export function DownloadBar() {
  const [id, setId] = useState("");
  const [busy, setBusy] = useState(false);
  const loadEpisode = useStore((s) => s.loadEpisode);
  const setMode = useStore((s) => s.setMode);
  const setEpisodeId = useStore((s) => s.setEpisodeId);
  const pushNotice = useStore((s) => s.pushNotice);

  const run = async (mode: "replay" | "save") => {
    const episodeId = id.trim();
    if (!episodeId) {
      pushNotice("error", "请输入 episode id");
      return;
    }
    setBusy(true);
    try {
      const blob = await downloadEpisode(episodeId, { include_visual: true });
      if (mode === "save") {
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = `${episodeId}.zip`;
        a.click();
        URL.revokeObjectURL(url);
        pushNotice("info", `已下载 ${episodeId}.zip`);
      } else {
        const loaded = await loadEpisodeFromZip(blob);
        loadEpisode(loaded.frames, loaded.manifest, null, loaded.summary, loaded.commandLog);
        setMode("replay");
        setEpisodeId(episodeId);
        if (loaded.frames.length === 0) pushNotice("error", "下载的 zip 内无 visual/frames.jsonl");
        else pushNotice("info", `已加载回放 ${episodeId}（${loaded.frames.length} 帧）`);
      }
    } catch (e) {
      const code = e instanceof ApiClientError ? e.code : "N_E_UNKNOWN";
      pushNotice("error", `下载失败：${code}`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="panel" data-testid="download-bar">
      <h3>按 episode id</h3>
      <div className="panel-body" style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        <input
          data-testid="download-id-input"
          placeholder="E-xxxxxxxxxxxx"
          value={id}
          onChange={(e) => setId(e.target.value)}
          style={{ fontSize: 12, padding: "3px 6px", background: "#1c212b", color: "var(--text)", border: "1px solid var(--line)", borderRadius: 6 }}
        />
        <div style={{ display: "flex", gap: 6 }}>
          <button data-testid="replay-by-id" disabled={busy} onClick={() => run("replay")}>
            回放
          </button>
          <button data-testid="save-zip" disabled={busy} onClick={() => run("save")}>
            下载 zip
          </button>
        </div>
        <div className="muted" style={{ fontSize: 11 }}>
          通过 GET /episodes/&#123;id&#125;/download 获取归档。
        </div>
      </div>
    </section>
  );
}
