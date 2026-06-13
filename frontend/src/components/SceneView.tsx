// Mounts the Three.js controller into the center canvas and drives it from the
// store. The controller updates imperatively on frame changes so React never
// re-renders at frame rate.

import { useEffect, useRef } from "react";
import { ThreeSceneController } from "@/three/ThreeSceneController";
import { useStore } from "@/state/store";

export function SceneView() {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const controllerRef = useRef<ThreeSceneController | null>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctrl = new ThreeSceneController({ canvas });
    controllerRef.current = ctrl;

    const st = useStore.getState();
    ctrl.buildStatic(st.config, st.manifest);
    if (st.latestFrame) ctrl.applyFrame(st.latestFrame);

    const resize = () => {
      const r = canvas.getBoundingClientRect();
      ctrl.resize(r.width, r.height);
    };
    resize();
    const ro = new ResizeObserver(resize);
    ro.observe(canvas);

    // Re-render frames without going through React state (imperative path).
    const unsubFrame = useStore.subscribe((s, prev) => {
      if (s.latestFrame !== prev.latestFrame && s.latestFrame) {
        ctrl.applyFrame(s.latestFrame);
      }
      if (s.config !== prev.config || s.manifest !== prev.manifest) {
        ctrl.buildStatic(s.config, s.manifest);
        if (s.latestFrame) ctrl.applyFrame(s.latestFrame);
      }
      if (s.ui.showRisk !== prev.ui.showRisk) {
        ctrl.setShowRisk(s.ui.showRisk);
      }
    });

    return () => {
      unsubFrame();
      ro.disconnect();
      ctrl.dispose();
      controllerRef.current = null;
    };
  }, []);

  return (
    <canvas
      ref={canvasRef}
      data-testid="scene-canvas"
      style={{ width: "100%", height: "100%", display: "block" }}
    />
  );
}
