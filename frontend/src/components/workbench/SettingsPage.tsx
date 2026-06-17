import { useEffect, useMemo, useState } from "react";

import {
  deleteDesktopLLMProviderSecret,
  getDesktopEnvironment,
  listDesktopLLMProviders,
  saveDesktopLLMProviderSecret,
  testDesktopLLMProvider,
} from "@/api/rest";
import { getRuntimeConfig } from "@/runtime";
import type {
  DesktopEnvironmentResponse,
  DesktopLLMConnectivityTestResponse,
  DesktopLLMProviderSummary,
} from "@/types/api";

type ProviderForm = {
  apiKey: string;
  baseUrl: string;
  model: string;
};

const REAL_PROVIDERS = new Set(["deepseek", "minimax", "siliconflow"]);

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

function isRealProvider(provider: string): boolean {
  return REAL_PROVIDERS.has(provider);
}

function providerForm(provider: DesktopLLMProviderSummary): ProviderForm {
  return {
    apiKey: "",
    baseUrl: provider.default_base_url ?? "",
    model: provider.default_model,
  };
}

function providerStatusText(provider: DesktopLLMProviderSummary): string {
  if (!isRealProvider(provider.provider)) return "无需 API Key";
  if (provider.has_saved_key && provider.key_masked) {
    return `已保存 ${provider.key_masked}`;
  }
  return "未保存";
}

function testResultText(result: DesktopLLMConnectivityTestResponse | null): string {
  if (!result) return "";
  const bits = [
    result.ok ? "连接成功" : "连接失败",
    result.message,
    result.status_code !== null ? `HTTP ${result.status_code}` : null,
    `${result.latency_ms.toFixed(0)} ms`,
  ].filter(Boolean);
  if (result.sample_models?.length) {
    bits.push(`模型示例: ${result.sample_models.join(", ")}`);
  }
  return bits.join(" · ");
}

export function SettingsPage() {
  const runtime = getRuntimeConfig();
  const [environment, setEnvironment] =
    useState<DesktopEnvironmentResponse | null>(null);
  const [providers, setProviders] = useState<DesktopLLMProviderSummary[]>([]);
  const [forms, setForms] = useState<Record<string, ProviderForm>>({});
  const [testResults, setTestResults] = useState<
    Record<string, DesktopLLMConnectivityTestResponse | null>
  >({});
  const [selectedProvider, setSelectedProvider] = useState("siliconflow");
  const [status, setStatus] = useState("环境信息尚未刷新。");
  const [busy, setBusy] = useState(false);
  const [providerBusy, setProviderBusy] = useState<string | null>(null);

  const selectedSummary = useMemo(
    () => providers.find((item) => item.provider === selectedProvider) ?? null,
    [providers, selectedProvider],
  );

  const selectedForm = forms[selectedProvider] ?? {
    apiKey: "",
    baseUrl: "",
    model: "",
  };

  const mergeProvider = (next: DesktopLLMProviderSummary) => {
    setProviders((items) =>
      items.map((item) => (item.provider === next.provider ? next : item)),
    );
  };

  const loadProviders = async () => {
    setProviderBusy("load");
    try {
      const result = await listDesktopLLMProviders();
      setProviders(result.items);
      setForms((current) => {
        const next = { ...current };
        for (const provider of result.items) {
          next[provider.provider] = next[provider.provider] ?? providerForm(provider);
        }
        return next;
      });
      if (!result.items.some((item) => item.provider === selectedProvider)) {
        setSelectedProvider(result.items[0]?.provider ?? "siliconflow");
      }
      setStatus("已加载 LLM Provider 设置。");
    } catch (error) {
      setStatus(errorMessage(error));
    } finally {
      setProviderBusy(null);
    }
  };

  useEffect(() => {
    void loadProviders();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

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

  const updateForm = (provider: string, patch: Partial<ProviderForm>) => {
    setForms((current) => ({
      ...current,
      [provider]: {
        ...(current[provider] ?? { apiKey: "", baseUrl: "", model: "" }),
        ...patch,
      },
    }));
    setTestResults((current) => ({ ...current, [provider]: null }));
  };

  const saveSecret = async (provider: string) => {
    const form = forms[provider];
    if (!form?.apiKey.trim()) {
      setStatus("请输入 API Key 后再保存。");
      return;
    }
    setProviderBusy(provider);
    try {
      const result = await saveDesktopLLMProviderSecret(provider, {
        api_key: form.apiKey,
        base_url: form.baseUrl || null,
        model: form.model || null,
      });
      mergeProvider(result);
      updateForm(provider, { apiKey: "" });
      setStatus(`${result.display_name} API Key 已保存。`);
    } catch (error) {
      setStatus(errorMessage(error));
    } finally {
      setProviderBusy(null);
    }
  };

  const deleteSecret = async (provider: string) => {
    setProviderBusy(provider);
    try {
      const result = await deleteDesktopLLMProviderSecret(provider);
      mergeProvider(result);
      setStatus(`${result.display_name} API Key 已删除。`);
    } catch (error) {
      setStatus(errorMessage(error));
    } finally {
      setProviderBusy(null);
    }
  };

  const testProvider = async (provider: string) => {
    const form = forms[provider];
    setProviderBusy(provider);
    try {
      const result = await testDesktopLLMProvider(provider, {
        api_key: form?.apiKey || null,
        base_url: form?.baseUrl || null,
        model: form?.model || null,
      });
      setTestResults((current) => ({ ...current, [provider]: result }));
      setStatus(result.ok ? "连通性测试成功。" : "连通性测试失败。");
    } catch (error) {
      setStatus(errorMessage(error));
    } finally {
      setProviderBusy(null);
    }
  };

  return (
    <section className="workbench-page">
      <header className="workbench-page-header">
        <h1>设置</h1>
        <p className="muted">管理桌面端偏好、服务地址、运行环境和 LLM Provider。</p>
      </header>

      <div className="workbench-config-toolbar">
        <button type="button" onClick={refreshEnvironment} disabled={busy}>
          刷新环境
        </button>
        <button type="button" onClick={loadProviders} disabled={providerBusy === "load"}>
          刷新 Provider
        </button>
        {busy || providerBusy ? <span className="chip">处理中</span> : null}
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
        <div className="workbench-field">
          <div className="workbench-field-heading">
            <label htmlFor="settings-provider">Provider</label>
            <span className="workbench-field-tooltip" title="选择要保存或测试的模型供应商。">
              ?
            </span>
          </div>
          <select
            id="settings-provider"
            value={selectedProvider}
            onChange={(event) => setSelectedProvider(event.target.value)}
          >
            {providers.map((provider) => (
              <option value={provider.provider} key={provider.provider}>
                {provider.display_name}
              </option>
            ))}
          </select>
          <p className="workbench-help">mock/replay 不需要 API Key。</p>
        </div>

        {selectedSummary ? (
          <div className="workbench-module-grid">
            <div className="workbench-module-card">
              <span className="workbench-module-id">{selectedSummary.provider}</span>
              <span className={selectedSummary.has_saved_key ? "chip chip-ok" : "chip"}>
                {providerStatusText(selectedSummary)}
              </span>
              <span className="muted">
                {selectedSummary.updated_at ? `更新于 ${selectedSummary.updated_at}` : "未保存本机密钥"}
              </span>
            </div>
          </div>
        ) : null}

        {selectedSummary && isRealProvider(selectedSummary.provider) ? (
          <div className="workbench-form-grid">
            <div className="workbench-field">
              <div className="workbench-field-heading">
                <label htmlFor="settings-api-key">API Key</label>
                <span className="workbench-field-tooltip" title="保存后只显示脱敏摘要。">
                  ?
                </span>
              </div>
              <input
                id="settings-api-key"
                type="password"
                value={selectedForm.apiKey}
                onChange={(event) =>
                  updateForm(selectedSummary.provider, { apiKey: event.target.value })
                }
                placeholder={
                  selectedSummary.has_saved_key ? "留空则使用已保存 Key 测试" : "输入 API Key"
                }
              />
              <p className="workbench-help">
                环境变量默认名：{displayValue(selectedSummary.api_key_env)}
              </p>
            </div>

            <div className="workbench-field">
              <div className="workbench-field-heading">
                <label htmlFor="settings-base-url">Base URL</label>
                <span className="workbench-field-tooltip" title="用于连通性测试和保存偏好。">
                  ?
                </span>
              </div>
              <input
                id="settings-base-url"
                value={selectedForm.baseUrl}
                onChange={(event) =>
                  updateForm(selectedSummary.provider, { baseUrl: event.target.value })
                }
              />
              <p className="workbench-help">
                默认：{displayValue(selectedSummary.default_base_url)}
              </p>
            </div>

            <div className="workbench-field">
              <div className="workbench-field-heading">
                <label htmlFor="settings-model">模型</label>
                <span className="workbench-field-tooltip" title="模型名不做封闭校验。">
                  ?
                </span>
              </div>
              <input
                id="settings-model"
                value={selectedForm.model}
                onChange={(event) =>
                  updateForm(selectedSummary.provider, { model: event.target.value })
                }
              />
              <p className="workbench-help">
                默认：{displayValue(selectedSummary.default_model)}
              </p>
            </div>

            <div className="workbench-config-toolbar">
              <button
                type="button"
                onClick={() => saveSecret(selectedSummary.provider)}
                disabled={providerBusy === selectedSummary.provider}
              >
                保存 API Key
              </button>
              <button
                type="button"
                onClick={() => testProvider(selectedSummary.provider)}
                disabled={providerBusy === selectedSummary.provider}
              >
                测试连通性
              </button>
              <button
                type="button"
                onClick={() => deleteSecret(selectedSummary.provider)}
                disabled={
                  providerBusy === selectedSummary.provider ||
                  !selectedSummary.has_saved_key
                }
              >
                删除保存 Key
              </button>
            </div>

            {testResults[selectedSummary.provider] ? (
              <div className="workbench-notice" role="status">
                {testResultText(testResults[selectedSummary.provider])}
              </div>
            ) : null}
          </div>
        ) : (
          <p className="muted">该 provider 不需要 API Key，也不会发起真实供应商连通性测试。</p>
        )}
      </div>
    </section>
  );
}
