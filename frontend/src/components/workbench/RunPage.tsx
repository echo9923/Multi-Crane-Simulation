import { buildValidateRequest } from "@/api/config";
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

function issueField(issue: unknown, key: "code" | "message" | "text"): string | null {
  if (!issue || typeof issue !== "object") return null;
  const value = (issue as Record<string, unknown>)[key];
  return typeof value === "string" && value ? value : null;
}

function issueMessage(issue: unknown): string {
  return issueField(issue, "message") ?? issueField(issue, "text") ?? String(issue);
}

export function RunPage() {
  const yamlText = useWorkbenchStore((s) => s.yamlText);
  const validation = useWorkbenchStore((s) => s.validation);
  const validationError = useWorkbenchStore((s) => s.validationError);
  const currentEpisode = useWorkbenchStore((s) => s.currentEpisode);
  const episodeState = useWorkbenchStore((s) => s.episodeState);
  const busy = useWorkbenchStore((s) => s.busy);
  const setValidation = useWorkbenchStore((s) => s.setValidation);
  const setCurrentEpisode = useWorkbenchStore((s) => s.setCurrentEpisode);
  const setEpisodeState = useWorkbenchStore((s) => s.setEpisodeState);
  const setBusy = useWorkbenchStore((s) => s.setBusy);
  const setLegacyEpisodeId = useStore((s) => s.setEpisodeId);
  const setLegacyMode = useStore((s) => s.setMode);

  const episodeId = currentEpisode?.episode_id ?? null;
  const canUseEpisode = Boolean(episodeId);
  const validationErrors = validation?.errors ?? [];
  const validationWarnings = validation?.warnings ?? [];
  const hasValidationDetails =
    Boolean(validation && !validation.valid) &&
    (validationErrors.length > 0 || validationWarnings.length > 0);

  const refreshState = async (id = episodeId) => {
    if (!id) return;
    const state = await getEpisodeState(id);
    setEpisodeState(state);
  };

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
      const req = buildValidateRequest(yamlText);
      const started = await startEpisode({
        ...req,
        run_mode: "interactive_server",
        runner: "production",
        autostart: true,
      });
      setCurrentEpisode(started);
      setLegacyEpisodeId(started.episode_id);
      setLegacyMode("live");
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
      await stopEpisode(episodeId);
      await refreshState(episodeId);
      setLegacyMode("idle");
      setLegacyEpisodeId(null);
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
        <button type="button" onClick={pauseRun} disabled={busy || !canUseEpisode}>
          暂停
        </button>
        <button type="button" onClick={resumeRun} disabled={busy || !canUseEpisode}>
          继续
        </button>
        <button type="button" onClick={stopRun} disabled={busy || !canUseEpisode}>
          停止
        </button>
        <button type="button" onClick={refreshRun} disabled={busy || !canUseEpisode}>
          刷新状态
        </button>
        {validation?.valid ? <span className="chip chip-ok">校验通过</span> : null}
        {validation && !validation.valid ? (
          <span className="chip chip-warn">校验未通过</span>
        ) : null}
        {busy ? <span className="chip">处理中</span> : null}
      </div>

      {validationError ? (
        <div className="workbench-notice" role="alert">
          {validationError}
        </div>
      ) : null}

      {hasValidationDetails ? (
        <div className="workbench-validation-details" aria-label="校验详情">
          {validationErrors.length > 0 ? (
            <div>
              <h3>错误</h3>
              <ul>
                {validationErrors.map((issue, index) => (
                  <li key={`error-${index}`}>
                    {issueField(issue, "code") ? (
                      <span className="workbench-validation-code">
                        {issueField(issue, "code")}
                      </span>
                    ) : null}
                    <span>{issueMessage(issue)}</span>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
          {validationWarnings.length > 0 ? (
            <div>
              <h3>警告</h3>
              <ul>
                {validationWarnings.map((issue, index) => (
                  <li key={`warning-${index}`}>
                    {issueField(issue, "code") ? (
                      <span className="workbench-validation-code">
                        {issueField(issue, "code")}
                      </span>
                    ) : null}
                    <span>{issueMessage(issue)}</span>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
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
            <dd>{displayValue(episodeState?.status ?? currentEpisode?.status)}</dd>
          </div>
          <div>
            <dt>Frame</dt>
            <dd>{episodeState ? `frame ${episodeState.frame_index}` : "-"}</dd>
          </div>
          <div>
            <dt>Time</dt>
            <dd>{episodeState ? `${episodeState.time_s}s` : "-"}</dd>
          </div>
          <div>
            <dt>Run Dir</dt>
            <dd>{displayValue(episodeState?.run_dir ?? currentEpisode?.run_dir)}</dd>
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
          {modulePipeline.map((moduleId) => (
            <div className="workbench-module-card" key={moduleId}>
              <span className="workbench-module-id">Module {moduleId}</span>
              <span className="chip">待接入</span>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
