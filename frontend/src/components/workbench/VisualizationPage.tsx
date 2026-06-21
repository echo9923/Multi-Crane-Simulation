import { useState } from "react";
import { useParams } from "react-router-dom";

import { DownloadBar } from "@/components/DownloadBar";
import { Layout } from "@/components/Layout";
import { LoadEpisode } from "@/components/LoadEpisode";
import { ObservationControls } from "@/components/LeftControls";
import { Panels } from "@/components/panels/Panels";
import { SceneView } from "@/components/SceneView";
import { SceneOverlays } from "@/components/SceneOverlays";
import { Timeline } from "@/components/Timeline";
import { useRealtimeEpisode } from "@/hooks/useRealtimeEpisode";
import { useStore } from "@/state/store";
import { useWorkbenchStore } from "@/state/workbench";

type VisualizationMode = "live" | "offline";

function DisplayControls() {
  return (
    <div className="left-stack">
      <ObservationControls />
    </div>
  );
}

function OfflineControls() {
  return (
    <div className="left-stack">
      <LoadEpisode />
      <DownloadBar />
      <ObservationControls />
    </div>
  );
}

export function VisualizationPage() {
  const { episodeId: routeEpisodeId } = useParams<{ episodeId: string }>();
  const currentEpisode = useWorkbenchStore((s) => s.currentEpisode);
  const prepareOfflineReplay = useStore((s) => s.prepareOfflineReplay);
  const offlineFrameCount = useStore((s) => s.frames.length);
  const effectiveEpisodeId = routeEpisodeId ?? currentEpisode?.episode_id;
  const [mode, setMode] = useState<VisualizationMode>("live");
  const liveMode = mode === "live";

  useRealtimeEpisode(liveMode ? effectiveEpisodeId : undefined);

  const showLiveMode = () => setMode("live");
  const showOfflineMode = () => {
    setMode("offline");
    prepareOfflineReplay();
  };

  return (
    <section className="workbench-visualization" aria-labelledby="visualization-title">
      <header className="workbench-visualization-titlebar">
        <h1 id="visualization-title">3D 观察</h1>
        <div className="workbench-mode-tabs" role="group" aria-label="3D 观察模式">
          <button
            type="button"
            className={liveMode ? "active" : ""}
            aria-pressed={liveMode}
            onClick={showLiveMode}
          >
            实时观察
          </button>
          <button
            type="button"
            className={!liveMode ? "active" : ""}
            aria-pressed={!liveMode}
            onClick={showOfflineMode}
          >
            离线回放
          </button>
        </div>
        <span className="muted">
          {liveMode && effectiveEpisodeId ? `实时 Episode：${effectiveEpisodeId}` : "Module N"}
        </span>
      </header>
      {liveMode && !effectiveEpisodeId ? (
        <div className="workbench-notice" role="status">
          当前没有实时 Episode。请先到运行页启动仿真，或切换到离线回放加载本地数据。
        </div>
      ) : null}
      {!liveMode && offlineFrameCount === 0 ? (
        <div className="workbench-notice" role="status">
          离线回放尚未加载数据。请选择本地 frames.jsonl 或下载的 episode zip。
        </div>
      ) : null}
      <div className="workbench-visualization-embed">
        <Layout
          left={liveMode ? <DisplayControls /> : <OfflineControls />}
          center={
            <>
              <SceneView />
              <SceneOverlays />
            </>
          }
          right={<Panels />}
          bottom={<Timeline />}
        />
      </div>
    </section>
  );
}
