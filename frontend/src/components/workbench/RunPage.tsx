import { useEffect } from "react";
import { Link } from "react-router-dom";

import { buildStartRequest } from "@/api/config";
import {
  getEpisodeState,
  listDesktopLLMProviders,
  pauseEpisode,
  resumeEpisode,
  startEpisode,
  stopEpisode,
} from "@/api/rest";
import { useStore } from "@/state/store";
import { useWorkbenchStore } from "@/state/workbench";
import { findCuratedScenario } from "@/workbench/curatedScenarios";

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
const REAL_PROVIDERS = new Set(["deepseek", "minimax", "siliconflow"]);

function isTerminalStatus(status: string | null | undefined): boolean {
  return terminalStatuses.has(status ?? "");
}

function errorMessage(error: unknown): string {
  const message = error instanceof Error ? error.message : String(error);
  const code =
    error && typeof error === "object" ? (error as { code?: unknown }).code : null;
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

function stepClass(ok: boolean) {
  return `chip${ok ? " chip-ok" : ""}`;
}

export function RunPage() {
  const yamlText = useWorkbenchStore((s) => s.yamlText);
  const form = useWorkbenchStore((s) => s.form);
  const summary = useWorkbenchStore((s) => s.summary);
  const validation = useWorkbenchStore((s) => s.validation);
  const validationError = useWorkbenchStore((s) => s.validationError);
  const currentEpisode = useWorkbenchStore((s) => s.currentEpisode);
  const episodeState = useWorkbenchStore((s) => s.episodeState);
  const currentEpisodeStale = useWorkbenchStore((s) => s.currentEpisodeStale);
  const providerSummaries = useWorkbenchStore((s) => s.providerSummaries);
  const busy = useWorkbenchStore((s) => s.busy);
  const setValidation = useWorkbenchStore((s) => s.setValidation);
  const setCurrentEpisode = useWorkbenchStore((s) => s.setCurrentEpisode);
  const setEpisodeState = useWorkbenchStore((s) => s.setEpisodeState);
  const setProviderSummaries = useWorkbenchStore((s) => s.setProviderSummaries);
  const setBusy = useWorkbenchStore((s) => s.setBusy);
  const startLiveEpisode = useStore((s) => s.startLiveEpisode);
  const setLegacyEpisodeId = useStore((s) => s.setEpisodeId);
  const setLegacyMode = useStore((s) => s.setMode);

  const episodeId = currentEpisode?.episode_id ?? null;
  const status = episodeState?.status ?? currentEpisode?.status ?? null;
  const frameIndex = episodeState?.frame_index ?? null;
  const runDir = episodeState?.run_dir ?? currentEpisode?.run_dir ?? null;
  const isTerminal = isTerminalStatus(status);
  const selectedScenario = findCuratedScenario(summary?.scenarioId);
  const selectedProviderSummary =
    providerSummaries.find((provider) => provider.provider === form.llmProvider) ?? null;
  const scenarioReady = Boolean(selectedScenario && yamlText.trim());
  const providerAllowed = REAL_PROVIDERS.has(form.llmProvider);
  const apiKeyReady = providerAllowed && selectedProviderSummary?.has_saved_key === true;
  const validationReady =
    validation?.valid === true && validation.manual_task_validation?.valid !== false;
  const canStart = scenarioReady && providerAllowed && apiKeyReady && validationReady;
  const canRefreshEpisode = Boolean(episodeId);
  const canControlEpisode = Boolean(episodeId && !currentEpisodeStale);
  const canPause = canControlEpisode && status === "running";
  const canResume = canControlEpisode && status === "paused";
  const canStop = canControlEpisode && !isTerminal;
  const showStaleControlNotice = currentEpisodeStale && !isTerminal;

  useEffect(() => {
    let cancelled = false;
    const loadProviders = async () => {
      try {
        const result = await listDesktopLLMProviders();
        if (!cancelled) setProviderSummaries(result.items);
      } catch {
        if (!cancelled) setProviderSummaries([]);
      }
    };
    void loadProviders();
    return () => {
      cancelled = true;
    };
  }, [setProviderSummaries]);

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
        <h1>运行仿真</h1>
        <p className="muted">
          运行页是唯一启动入口。确认场景、API Key 和校验状态后，启动 interactive_server / production 仿真。
        </p>
      </header>

      {validationError ? (
        <div className="workbench-notice" role="alert">
          {validationError}
        </div>
      ) : null}

      <section className="workbench-panel workbench-config-section">
        <div className="workbench-config-section-header">
          <h2>流程状态</h2>
          <p className="workbench-help">
            三项都准备好之后才能开始运行，避免未选场景或未校验配置直接启动。
          </p>
        </div>
        <div className="workbench-config-toolbar">
          <span className={stepClass(scenarioReady)}>
            {scenarioReady ? "场景已选择" : "场景未选择"}
          </span>
          <span className={stepClass(apiKeyReady)}>
            {apiKeyReady ? "API Key 已配置" : "API Key 未配置"}
          </span>
          <span className={stepClass(validationReady)}>
            {validationReady ? "校验通过" : "校验未通过"}
          </span>
        </div>
        <dl className="workbench-summary-grid">
          <div>
            <dt>当前场景</dt>
            <dd>{summary?.scenarioId ?? "未选择"}</dd>
          </div>
          <div>
            <dt>Provider</dt>
            <dd>{form.llmProvider || "-"}</dd>
          </div>
          <div>
            <dt>运行模式</dt>
            <dd>interactive_server / production</dd>
          </div>
          <div>
            <dt>Config Hash</dt>
            <dd>{validation?.resolved_config_hash ?? "-"}</dd>
          </div>
        </dl>
        <div className="workbench-config-toolbar">
          <button type="button" onClick={startRun} disabled={busy || !canStart}>
            开始运行
          </button>
          {!scenarioReady ? <Link to="/">选择场景</Link> : null}
          {scenarioReady && !validationReady ? <Link to="/config">去校验场景</Link> : null}
          {busy ? <span className="chip">处理中</span> : null}
        </div>
      </section>

      {showStaleControlNotice ? (
        <div className="workbench-notice" role="status">
          当前配置已在此 Episode 启动后发生变化。请启动新的 Episode 后再发送暂停、继续或停止控制。
        </div>
      ) : null}

      {isTerminal ? (
        <div className="workbench-notice" role="status">
          运行已完成，当前 Episode 处于终态：{displayValue(status)}。
        </div>
      ) : null}

      <section className="workbench-panel">
        <div className="workbench-config-section-header">
          <h2>运行状态</h2>
        </div>
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
        <div className="workbench-config-toolbar">
          <button type="button" onClick={pauseRun} disabled={busy || !canPause}>
            暂停
          </button>
          <button type="button" onClick={resumeRun} disabled={busy || !canResume}>
            继续
          </button>
          <button type="button" onClick={stopRun} disabled={busy || !canStop}>
            停止
          </button>
          <button type="button" onClick={refreshRun} disabled={busy || !canRefreshEpisode}>
            刷新状态
          </button>
          {episodeId ? (
            <Link className="button-link" to={`/live/${episodeId}`}>
              打开 3D 观察
            </Link>
          ) : null}
        </div>
      </section>

      <section className="workbench-panel workbench-run-panel">
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
      </section>
    </section>
  );
}
