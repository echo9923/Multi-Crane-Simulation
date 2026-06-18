import { useEffect } from "react";
import { Link } from "react-router-dom";

import { buildStartRequest, buildValidateRequest } from "@/api/config";
import {
  getEpisodeState,
  pauseEpisode,
  resumeEpisode,
  startEpisode,
  stopEpisode,
  validateScenario,
} from "@/api/rest";
import { useStore } from "@/state/store";
import { useWorkbenchStore } from "@/state/workbench";

const modulePipeline = ["C", "D", "E", "F", "G", "H", "I", "L"];
const terminalStatuses = new Set([
  "completed",
  "timeout",
  "failed_collision",
  "failed_invalid_state",
  "llm_failed",
  "failed_replay_mismatch",
  "failed_recovery_blocked",
  "failed_recovery_timeout",
  "stopped_by_user",
]);

function isTerminalStatus(status: string | null | undefined): boolean {
  return terminalStatuses.has(status ?? "");
}

function errorMessage(error: unknown): string {
  const message = error instanceof Error ? error.message : String(error);
  const code =
    error && typeof error === "object"
      ? (error as { code?: unknown }).code
      : null;
  return typeof code === "string" && code ? `${code}: ${message}` : message;
}

function displayValue(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === "") return "-";
  return String(value);
}

function moduleEvidence(
  moduleId: string,
  status: string | null,
  frameIndex: number | null,
  runDir: string | null,
) {
  if (moduleId === "C") {
    return { chip: status ? "state" : "idle", detail: status ? `episode state: ${status}` : "no episode" };
  }
  if (moduleId === "D") {
    return {
      chip: frameIndex && frameIndex > 0 ? "observed" : "waiting",
      detail: frameIndex && frameIndex > 0 ? `frame index ${frameIndex}` : "no frame",
    };
  }
  if (moduleId === "E") {
    return {
      chip: status === "running" || status === "paused" ? "active" : status ?? "idle",
      detail: "runtime scheduler",
    };
  }
  if (moduleId === "F") {
    return { chip: status === "running" ? "active" : "standby", detail: "LLM path" };
  }
  if (moduleId === "G") {
    return {
      chip: frameIndex && frameIndex > 0 ? "synced" : "waiting",
      detail: "simulation frame",
    };
  }
  if (moduleId === "H") {
    return {
      chip: status === "paused" ? "paused" : status === "running" ? "ready" : "standby",
      detail: "control loop",
    };
  }
  if (moduleId === "I") {
    return {
      chip: terminalStatuses.has(status ?? "") ? "final" : status === "running" ? "live" : "pending",
      detail: "episode lifecycle",
    };
  }
  return { chip: runDir ? "writing" : "waiting", detail: runDir ?? "no run_dir" };
}

export function RunPage() {
  const yamlText = useWorkbenchStore((s) => s.yamlText);
  const validation = useWorkbenchStore((s) => s.validation);
  const validationError = useWorkbenchStore((s) => s.validationError);
  const currentEpisode = useWorkbenchStore((s) => s.currentEpisode);
  const episodeState = useWorkbenchStore((s) => s.episodeState);
  const currentEpisodeStale = useWorkbenchStore((s) => s.currentEpisodeStale);
  const busy = useWorkbenchStore((s) => s.busy);
  const setValidation = useWorkbenchStore((s) => s.setValidation);
  const setCurrentEpisode = useWorkbenchStore((s) => s.setCurrentEpisode);
  const setEpisodeState = useWorkbenchStore((s) => s.setEpisodeState);
  const setBusy = useWorkbenchStore((s) => s.setBusy);
  const startLiveEpisode = useStore((s) => s.startLiveEpisode);
  const setLegacyEpisodeId = useStore((s) => s.setEpisodeId);
  const setLegacyMode = useStore((s) => s.setMode);

  const episodeId = currentEpisode?.episode_id ?? null;
  const status = episodeState?.status ?? currentEpisode?.status ?? null;
  const frameIndex = episodeState?.frame_index ?? null;
  const runDir = episodeState?.run_dir ?? currentEpisode?.run_dir ?? null;
  const isTerminal = isTerminalStatus(status);
  const canRefreshEpisode = Boolean(episodeId);
  const canControlEpisode = Boolean(episodeId && !currentEpisodeStale);
  const canPause = canControlEpisode && status === "running";
  const canResume = canControlEpisode && status === "paused";
  const canStop = canControlEpisode && !isTerminal;
  const refreshState = async (id = episodeId) => {
    if (!id) return;
    const state = await getEpisodeState(id);
    setEpisodeState(state);
  };

  useEffect(() => {
    if (!episodeId || currentEpisodeStale || isTerminal) return;
    let cancelled = false;
    const refresh = async () => {
      try {
        const state = await getEpisodeState(episodeId);
        if (!cancelled) setEpisodeState(state);
      } catch {
        // Explicit refresh actions surface errors; polling stays quiet.
      }
    };
    const timer = window.setInterval(refresh, 1000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [currentEpisodeStale, episodeId, isTerminal, setEpisodeState]);

  const runAction = async (action: () => Promise<void>) => {
    if (useWorkbenchStore.getState().busy) return;
    setBusy(true);
    setValidation(validation, null);
    try {
      await action();
    } catch (error) {
      setValidation(validation, errorMessage(error));
    } finally {
      setBusy(false);
    }
  };

  const validateYaml = () =>
    runAction(async () => {
      const result = await validateScenario(buildValidateRequest(yamlText));
      setValidation(result);
    });

  const startRun = () =>
    runAction(async () => {
      const req = buildStartRequest(yamlText);
      const started = await startEpisode({
        ...req,
        run_mode: "interactive_server",
        runner: "production",
        autostart: true,
      });
      setCurrentEpisode(started);
      startLiveEpisode(started.episode_id);
      await refreshState(started.episode_id);
    });

  const pauseRun = () =>
    runAction(async () => {
      if (!episodeId) return;
      await pauseEpisode(episodeId);
      await refreshState(episodeId);
    });

  const resumeRun = () =>
    runAction(async () => {
      if (!episodeId) return;
      await resumeEpisode(episodeId);
      await refreshState(episodeId);
    });

  const stopRun = () =>
    runAction(async () => {
      if (!episodeId) return;
      let clearLegacy = false;
      let stopError: unknown = null;
      try {
        const response = await stopEpisode(episodeId);
        clearLegacy = response.accepted || response.reason === "already_terminal";
      } catch (error) {
        stopError = error;
      }
      try {
        await refreshState(episodeId);
        clearLegacy =
          clearLegacy ||
          isTerminalStatus(useWorkbenchStore.getState().episodeState?.status);
      } catch {
        // Preserve live state when transport failed and terminal state is unknown.
      }
      if (clearLegacy) {
        setLegacyMode("idle");
        setLegacyEpisodeId(null);
      }
      if (stopError && !clearLegacy) {
        throw stopError;
      }
    });

  const refreshRun = () =>
    runAction(async () => {
      await refreshState();
    });

  return (
    <section className="workbench-page">
      <header className="workbench-page-header">
        <h1>运行</h1>
        <p className="muted">启动实验、查看运行状态，并衔接实时 Episode。</p>
      </header>

      <div className="workbench-config-toolbar">
        <button type="button" onClick={validateYaml} disabled={busy || !yamlText}>
          校验
        </button>
        <button type="button" onClick={startRun} disabled={busy || !yamlText}>
          启动
        </button>
        <button type="button" onClick={pauseRun} disabled={busy || !canPause}>
          暂停
        </button>
        <button type="button" onClick={resumeRun} disabled={busy || !canResume}>
          继续
        </button>
        <button type="button" onClick={stopRun} disabled={busy || !canStop}>
          停止
        </button>
        {episodeId ? <Link to={`/live/${episodeId}`}>Live 3D</Link> : null}
        <button type="button" onClick={refreshRun} disabled={busy || !canRefreshEpisode}>
          刷新状态
        </button>
        {validation?.valid ? <span className="chip chip-ok">校验通过</span> : null}
        {busy ? <span className="chip">处理中</span> : null}
      </div>

      {validationError ? (
        <div className="workbench-notice" role="alert">
          {validationError}
        </div>
      ) : null}

      {currentEpisodeStale ? (
        <div className="workbench-notice" role="status">
          Config changed after this Episode started. Start a new Episode before sending controls.
        </div>
      ) : null}

      <div className="workbench-panel">
        <h2>运行控制</h2>
        <dl className="workbench-summary-grid">
          <div>
            <dt>Episode</dt>
            <dd>{displayValue(episodeState?.episode_id ?? currentEpisode?.episode_id)}</dd>
          </div>
          <div>
            <dt>Status</dt>
            <dd>{displayValue(status)}</dd>
          </div>
          <div>
            <dt>Frame</dt>
            <dd>{frameIndex !== null ? `frame ${frameIndex}` : "-"}</dd>
          </div>
          <div>
            <dt>Time</dt>
            <dd>{episodeState ? `${episodeState.time_s}s` : "-"}</dd>
          </div>
          <div>
            <dt>Run Dir</dt>
            <dd>{displayValue(runDir)}</dd>
          </div>
          <div>
            <dt>Terminal Reason</dt>
            <dd>{displayValue(episodeState?.terminal_reason)}</dd>
          </div>
        </dl>
      </div>

      <div className="workbench-panel workbench-run-panel">
        <h2>模块流水线</h2>
        <div className="workbench-module-grid">
          {modulePipeline.map((moduleId) => {
            const evidence = moduleEvidence(moduleId, status, frameIndex, runDir);
            return (
              <div className="workbench-module-card" key={moduleId}>
                <span className="workbench-module-id">Module {moduleId}</span>
                <span className="chip">{evidence.chip}</span>
                <span className="muted">{evidence.detail}</span>
              </div>
            );
          })}
        </div>
      </div>
    </section>
  );
}
