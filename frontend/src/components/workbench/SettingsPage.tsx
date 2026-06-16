import { useState } from "react";

import { getDesktopEnvironment } from "@/api/rest";
import { getRuntimeConfig } from "@/runtime";
import type { DesktopEnvironmentResponse } from "@/types/api";

function displayValue(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === "") return "-";
  return String(value);
}

function errorMessage(error: unknown): string {
  const message = error instanceof Error ? error.message : String(error);
  const code =
    error && typeof error === "object"
      ? (error as { code?: unknown }).code
      : null;
  return typeof code === "string" && code ? `${code}: ${message}` : message;
}

const supportedProviders = ["deepseek", "minimax", "mock", "replay"];

export function SettingsPage() {
  const runtime = getRuntimeConfig();
  const [environment, setEnvironment] =
    useState<DesktopEnvironmentResponse | null>(null);
  const [status, setStatus] = useState("环境信息尚未刷新。");
  const [busy, setBusy] = useState(false);

  const refreshEnvironment = async () => {
    if (busy) return;
    setBusy(true);
    try {
      const result = await getDesktopEnvironment();
      setEnvironment(result);
      setStatus("已刷新后端运行环境。");
    } catch (error) {
      setStatus(errorMessage(error));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="workbench-page">
      <header className="workbench-page-header">
        <h1>设置</h1>
        <p className="muted">管理桌面端偏好、服务地址和运行环境。</p>
      </header>

      <div className="workbench-config-toolbar">
        <button type="button" onClick={refreshEnvironment} disabled={busy}>
          刷新环境
        </button>
        {busy ? <span className="chip">处理中</span> : null}
      </div>

      <div className="workbench-notice" role="status">
        {status}
      </div>

      <div className="workbench-panel">
        <h2>桌面运行时</h2>
        <dl className="workbench-summary-grid">
          <div>
            <dt>Mode</dt>
            <dd>{runtime.mode}</dd>
          </div>
          <div>
            <dt>API Base</dt>
            <dd>{displayValue(runtime.apiBase ?? "/api")}</dd>
          </div>
          <div>
            <dt>WS Base</dt>
            <dd>{displayValue(runtime.wsBase ?? "/ws")}</dd>
          </div>
          <div>
            <dt>Backend Port</dt>
            <dd>{displayValue(runtime.backendPort)}</dd>
          </div>
        </dl>
      </div>

      <div className="workbench-panel">
        <h2>后端环境</h2>
        <dl className="workbench-summary-grid">
          <div>
            <dt>Project Root</dt>
            <dd>{displayValue(environment?.project_root)}</dd>
          </div>
          <div>
            <dt>Python</dt>
            <dd>{displayValue(environment?.python_path)}</dd>
          </div>
          <div>
            <dt>Python Version</dt>
            <dd>{displayValue(environment?.python_version)}</dd>
          </div>
          <div>
            <dt>Backend Port</dt>
            <dd>{displayValue(environment?.backend_port)}</dd>
          </div>
          <div>
            <dt>Run Roots</dt>
            <dd>{environment?.run_roots.length ? environment.run_roots.join(", ") : "-"}</dd>
          </div>
        </dl>
      </div>

      <div className="workbench-panel">
        <h2>LLM Provider</h2>
        <p className="muted">当前后端支持以下 provider 值：</p>
        <div className="workbench-module-grid">
          {supportedProviders.map((provider) => (
            <div className="workbench-module-card" key={provider}>
              <span className="workbench-module-id">{provider}</span>
              <span className="chip chip-ok">已支持</span>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
