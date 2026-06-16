import { useEffect } from "react";
import { useParams } from "react-router-dom";

import { ensureDemoLoaded } from "@/bootstrap";
import { Layout } from "@/components/Layout";
import { LeftControls } from "@/components/LeftControls";
import { Panels } from "@/components/panels/Panels";
import { SceneView } from "@/components/SceneView";
import { Timeline } from "@/components/Timeline";
import { useRealtimeEpisode } from "@/hooks/useRealtimeEpisode";
import { useWorkbenchStore } from "@/state/workbench";

export function VisualizationPage() {
  const { episodeId: routeEpisodeId } = useParams<{ episodeId: string }>();
  const currentEpisode = useWorkbenchStore((s) => s.currentEpisode);
  const effectiveEpisodeId = routeEpisodeId ?? currentEpisode?.episode_id;

  useEffect(() => {
    if (!effectiveEpisodeId) {
      ensureDemoLoaded();
    }
  }, [effectiveEpisodeId]);

  useRealtimeEpisode(effectiveEpisodeId);

  return (
    <section className="workbench-visualization" aria-labelledby="visualization-title">
      <header className="workbench-visualization-titlebar">
        <h1 id="visualization-title">3D 可视化</h1>
        <span className="muted">Module N</span>
      </header>
      <div className="workbench-visualization-embed">
        <Layout
          left={<LeftControls />}
          center={<SceneView />}
          right={<Panels />}
          bottom={<Timeline />}
        />
      </div>
    </section>
  );
}
