// Mounts the Three.js controller into the center canvas and drives it from the
// store. The controller updates imperatively on frame changes so React never
// re-renders at frame rate.

import { useEffect, useRef } from "react";
import { ThreeSceneController } from "@/three/ThreeSceneController";
import { useStore } from "@/state/store";
import { manifestFromFrame } from "@/three/model/liveManifest";

export function SceneView() {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const controllerRef = useRef<ThreeSceneController | null>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctrl = new ThreeSceneController({ canvas });
    controllerRef.current = ctrl;

    // Build the static scene from config/manifest if available; in live mode
    // (neither present) defer to the first frame via ensureStatic().
    const ensureStatic = () => {
      const s = useStore.getState();
      if (ctrl.hasStatic()) return;
      if (s.config || s.manifest) {
        ctrl.buildStatic(s.config, s.manifest);
      } else if (s.latestFrame) {
        ctrl.buildStatic(null, manifestFromFrame(s.latestFrame));
      } else {
        ctrl.buildStatic(null, null);
      }
    };

    ensureStatic();
    const initialFrame = useStore.getState().latestFrame;
    if (initialFrame) ctrl.applyFrame(initialFrame);

    const resize = () => {
      const r = canvas.getBoundingClientRect();
      ctrl.resize(r.width, r.height);
    };
    resize();
    const ro = new ResizeObserver(resize);
    ro.observe(canvas);

    // Imperative frame / config updates (no React re-render per frame).
    const unsub = useStore.subscribe((s, prev) => {
      if (s.latestFrame !== prev.latestFrame && s.latestFrame) {
        ensureStatic();
        ctrl.applyFrame(s.latestFrame);
      }
      if (s.config !== prev.config || s.manifest !== prev.manifest) {
        // Explicit episode reload: rebuild the static scene.
        ctrl.buildStatic(s.config, s.manifest);
        if (s.latestFrame) ctrl.applyFrame(s.latestFrame);
      }
      if (s.ui.showRisk !== prev.ui.showRisk) {
        ctrl.setShowRisk(s.ui.showRisk);
      }
      if (s.ui.showZones !== prev.ui.showZones) {
        ctrl.setShowZones(s.ui.showZones);
      }
    });

    return () => {
      unsub();
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
