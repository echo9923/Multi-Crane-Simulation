import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import {
  listDesktopLLMProviders,
  saveDesktopLLMProviderSecret,
  testDesktopLLMProvider,
  validateScenario,
} from "@/api/rest";
import { buildValidateRequest } from "@/api/config";
import { useWorkbenchStore } from "@/state/workbench";
import type {
  DesktopLLMConnectivityTestResponse,
  DesktopLLMProviderSummary,
} from "@/types/api";
import {
  applyCoreFormToYaml,
  extractScenarioMetadata,
  extractYamlTaskPreview,
  formatConfigError,
  validationReportsToTaskPreview,
} from "@/workbench/configModel";
import { findCuratedScenario, scenarioMetadataFallback } from "@/workbench/curatedScenarios";

type ProviderForm = {
  apiKey: string;
  baseUrl: string;
  model: string;
};

const REAL_LLM_PROVIDERS = new Set(["deepseek", "minimax", "siliconflow"]);

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function providerDefaults(provider: DesktopLLMProviderSummary): ProviderForm {
  return {
    apiKey: "",
    baseUrl: provider.default_base_url ?? "",
    model: provider.default_model,
  };
}

function providerFormFromSummary(
  provider: DesktopLLMProviderSummary,
  currentProvider: string,
  currentForm: { llmBaseUrl: string; llmModel: string },
): ProviderForm {
  if (provider.provider === currentProvider) {
    return {
      apiKey: "",
      baseUrl: currentForm.llmBaseUrl || provider.default_base_url || "",
      model: currentForm.llmModel || provider.default_model,
    };
  }
  return providerDefaults(provider);
}

function providerStatus(provider: DesktopLLMProviderSummary | null): string {
  if (!provider) return "Provider 信息尚未加载";
  if (!REAL_LLM_PROVIDERS.has(provider.provider)) return "该 Provider 不开放普通运行";
  return provider.has_saved_key && provider.key_masked
    ? `已保存：${provider.key_masked}`
    : "未保存 API Key";
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
    bits.push(`模型示例：${result.sample_models.join(", ")}`);
  }
  return bits.join(" · ");
}

function formatHeight(value: number | null) {
  return value === null ? "-" : `${Number(value.toFixed(2))} m`;
}

function hasPassingManualValidation(validation: ReturnType<typeof useWorkbenchStore.getState>["validation"]) {
  if (!validation?.valid) return false;
  return validation.manual_task_validation?.valid !== false;
}

export function ConfigurationPage() {
  const yamlText = useWorkbenchStore((s) => s.yamlText);
  const form = useWorkbenchStore((s) => s.form);
  const summary = useWorkbenchStore((s) => s.summary);
  const validation = useWorkbenchStore((s) => s.validation);
  const validationError = useWorkbenchStore((s) => s.validationError);
  const busy = useWorkbenchStore((s) => s.busy);
  const setBusy = useWorkbenchStore((s) => s.setBusy);
  const setFormPatch = useWorkbenchStore((s) => s.setFormPatch);
  const setYamlText = useWorkbenchStore((s) => s.setYamlText);
  const setValidation = useWorkbenchStore((s) => s.setValidation);
  const setProviderSummaries = useWorkbenchStore((s) => s.setProviderSummaries);

  const [providers, setProviders] = useState<DesktopLLMProviderSummary[]>([]);
  const [selectedProvider, setSelectedProvider] = useState(form.llmProvider || "deepseek");
  const [forms, setForms] = useState<Record<string, ProviderForm>>({});
  const [secretStatus, setSecretStatus] = useState("Provider 信息尚未加载");
  const [providerBusy, setProviderBusy] = useState(false);

  const selectedSummary = useMemo(
    () => providers.find((provider) => provider.provider === selectedProvider) ?? null,
    [providers, selectedProvider],
  );
  const selectedForm = forms[selectedProvider] ?? {
    apiKey: "",
    baseUrl: form.llmBaseUrl,
    model: form.llmModel,
  };
  const metadata = yamlText.trim()
    ? extractScenarioMetadata(yamlText, scenarioMetadataFallback(summary?.scenarioId))
    : scenarioMetadataFallback(summary?.scenarioId);
  const taskPreview =
    validation?.manual_task_validation?.task_reports?.length
      ? validationReportsToTaskPreview(validation.manual_task_validation.task_reports)
      : yamlText.trim()
        ? extractYamlTaskPreview(yamlText)
        : [];
  const selectedCurated = findCuratedScenario(summary?.scenarioId);
  const validationPassed = hasPassingManualValidation(validation);

  const updateProviderConfig = (
    providerId: string,
    patch: Partial<ProviderForm>,
  ) => {
    setForms((current) => ({
      ...current,
      [providerId]: {
        ...(current[providerId] ?? { apiKey: "", baseUrl: "", model: "" }),
        ...patch,
      },
    }));
  };

  const applyProviderToYaml = (
    providerId: string,
    providerForm: ProviderForm,
  ) => {
    const nextForm = {
      ...form,
      llmProvider: providerId,
      llmBaseUrl: providerForm.baseUrl,
      llmModel: providerForm.model,
      llmApiKeyEnv: "",
    };
    setFormPatch(nextForm);
    if (yamlText.trim()) {
      setYamlText(applyCoreFormToYaml(yamlText, nextForm, {
        "experiment.llm.api_key_env": undefined,
      }));
    }
    setValidation(null, null);
  };

  const removeApiKeyEnvFromYaml = () => {
    setFormPatch({ llmApiKeyEnv: "" });
    if (yamlText.trim()) {
      setYamlText(applyCoreFormToYaml(yamlText, { ...form, llmApiKeyEnv: "" }, {
        "experiment.llm.api_key_env": undefined,
      }));
    }
    setValidation(null, null);
  };

  useEffect(() => {
    let cancelled = false;
    const loadProviders = async () => {
      setProviderBusy(true);
      try {
        const result = await listDesktopLLMProviders();
        if (cancelled) return;
        const realProviders = result.items.filter((provider) =>
          REAL_LLM_PROVIDERS.has(provider.provider),
        );
        setProviders(realProviders);
        setProviderSummaries(realProviders);
        setForms((current) => {
          const next = { ...current };
          for (const provider of realProviders) {
            next[provider.provider] =
              next[provider.provider] ??
              providerFormFromSummary(provider, form.llmProvider, form);
          }
          return next;
        });
        const providerId =
          realProviders.find((provider) => provider.provider === form.llmProvider)?.provider ??
          realProviders[0]?.provider ??
          selectedProvider;
        setSelectedProvider(providerId);
        const provider = realProviders.find((item) => item.provider === providerId) ?? null;
        setSecretStatus(providerStatus(provider));
      } catch (error) {
        if (!cancelled) setSecretStatus(`加载 Provider 失败：${errorText(error)}`);
      } finally {
        if (!cancelled) setProviderBusy(false);
      }
    };
    void loadProviders();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    setSecretStatus(providerStatus(selectedSummary));
  }, [selectedSummary]);

  const changeProvider = (providerId: string) => {
    const provider = providers.find((item) => item.provider === providerId) ?? null;
    const nextForm = forms[providerId] ?? (provider ? providerDefaults(provider) : selectedForm);
    setSelectedProvider(providerId);
    applyProviderToYaml(providerId, nextForm);
    setSecretStatus(providerStatus(provider));
  };

  const saveKey = async () => {
    if (!REAL_LLM_PROVIDERS.has(selectedProvider)) {
      setSecretStatus("当前 Provider 不开放普通运行");
      return;
    }
    if (!selectedForm.apiKey.trim()) {
      setSecretStatus("请输入 API Key 后再保存");
      return;
    }
    setProviderBusy(true);
    try {
      const result = await saveDesktopLLMProviderSecret(selectedProvider, {
        api_key: selectedForm.apiKey,
        base_url: selectedForm.baseUrl || null,
        model: selectedForm.model || null,
      });
      const nextProviders = providers.map((item) =>
        item.provider === result.provider ? result : item,
      );
      setProviders(nextProviders);
      setProviderSummaries(nextProviders);
      updateProviderConfig(selectedProvider, { apiKey: "" });
      removeApiKeyEnvFromYaml();
      setSecretStatus(providerStatus(result));
    } catch (error) {
      setSecretStatus(`保存失败：${errorText(error)}`);
    } finally {
      setProviderBusy(false);
    }
  };

  const testKey = async () => {
    if (!REAL_LLM_PROVIDERS.has(selectedProvider)) {
      setSecretStatus("当前 Provider 不开放普通运行");
      return;
    }
    setProviderBusy(true);
    try {
      const result = await testDesktopLLMProvider(selectedProvider, {
        api_key: selectedForm.apiKey || null,
        base_url: selectedForm.baseUrl || null,
        model: selectedForm.model || null,
      });
      setSecretStatus(testResultText(result));
    } catch (error) {
      setSecretStatus(`测试失败：${errorText(error)}`);
    } finally {
      setProviderBusy(false);
    }
  };

  const validate = async () => {
    setBusy(true);
    try {
      const result = await validateScenario(buildValidateRequest(yamlText));
      setValidation(result, null);
    } catch (error) {
      setValidation(null, formatConfigError(error));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="workbench-page">
      <header className="workbench-page-header">
        <h1>配置 API Key</h1>
        <p className="muted">
          当前页面只处理模型 Provider、本机密钥和运行前校验。场景结构、塔吊、区域和任务保持由内置 YAML 管理。
        </p>
      </header>

      {!selectedCurated ? (
        <div className="workbench-notice" role="status">
          尚未选择场景。请先回到场景页选择一个内置场景。
        </div>
      ) : null}

      {validationError ? (
        <div className="workbench-notice" role="alert">
          {validationError}
        </div>
      ) : null}

      <section className="workbench-panel workbench-config-section">
        <div className="workbench-config-section-header">
          <h2>当前场景：{metadata.name}</h2>
          <p className="workbench-help">{metadata.purpose}</p>
        </div>
        <div className="workbench-field-grid compact">
          <div>
            <span className="workbench-help">任务</span>
            <strong>{metadata.taskCount} 个</strong>
          </div>
          <div>
            <span className="workbench-help">塔吊</span>
            <strong>{metadata.craneCount} 台</strong>
          </div>
          <div>
            <span className="workbench-help">高位塔吊</span>
            <strong>{metadata.hasElevatedCrane ? "是" : "否"}</strong>
          </div>
          <div className="workbench-field-wide">
            <span className="workbench-help">主要风险</span>
            <strong>{metadata.primaryCrossRisk}</strong>
          </div>
        </div>
      </section>

      <section className="workbench-panel workbench-config-section">
        <div className="workbench-config-section-header">
          <h2>Provider 与密钥</h2>
          <p className="workbench-help">
            API Key 只保存到本机 secret store，不写入 YAML。普通运行只开放 DeepSeek、MiniMax 和 SiliconFlow。
          </p>
        </div>
        <div className="workbench-field-grid">
          <div className="workbench-field">
            <div className="workbench-field-heading">
              <label htmlFor="config-provider">Provider</label>
            </div>
            <select
              id="config-provider"
              value={selectedProvider}
              onChange={(event) => changeProvider(event.target.value)}
              disabled={providerBusy}
            >
              {providers.map((provider) => (
                <option key={provider.provider} value={provider.provider}>
                  {provider.display_name}
                </option>
              ))}
            </select>
          </div>
          <div className="workbench-field">
            <div className="workbench-field-heading">
              <label htmlFor="config-api-key">API Key</label>
            </div>
            <input
              id="config-api-key"
              type="password"
              value={selectedForm.apiKey}
              onChange={(event) =>
                updateProviderConfig(selectedProvider, { apiKey: event.target.value })
              }
              disabled={providerBusy || !REAL_LLM_PROVIDERS.has(selectedProvider)}
              placeholder="输入 API Key"
            />
          </div>
          <div className="workbench-field-wide">
            <span className={selectedSummary?.has_saved_key ? "chip chip-ok" : "chip"}>
              {secretStatus}
            </span>
          </div>
        </div>

        <details className="workbench-advanced-provider">
          <summary>高级 Provider 设置</summary>
          <div className="workbench-field-grid">
            <div className="workbench-field">
              <div className="workbench-field-heading">
                <label htmlFor="config-base-url">Base URL</label>
              </div>
              <input
                id="config-base-url"
                value={selectedForm.baseUrl}
                onChange={(event) => {
                  updateProviderConfig(selectedProvider, { baseUrl: event.target.value });
                  applyProviderToYaml(selectedProvider, {
                    ...selectedForm,
                    baseUrl: event.target.value,
                  });
                }}
              />
            </div>
            <div className="workbench-field">
              <div className="workbench-field-heading">
                <label htmlFor="config-model">Model</label>
              </div>
              <input
                id="config-model"
                value={selectedForm.model}
                onChange={(event) => {
                  updateProviderConfig(selectedProvider, { model: event.target.value });
                  applyProviderToYaml(selectedProvider, {
                    ...selectedForm,
                    model: event.target.value,
                  });
                }}
              />
            </div>
          </div>
        </details>

        <div className="workbench-config-toolbar">
          <button type="button" onClick={saveKey} disabled={providerBusy}>
            保存 Key
          </button>
          <button type="button" onClick={testKey} disabled={providerBusy}>
            测试连接
          </button>
          <button type="button" onClick={validate} disabled={busy || !yamlText.trim()}>
            校验场景
          </button>
        </div>
      </section>

      <section className="workbench-panel workbench-config-section">
        <div className="workbench-config-section-header">
          <h2>校验结果</h2>
          <p className="workbench-help">
            校验会解析配置、生成 resolved config，并检查手工任务的取货/卸货可达性。
          </p>
        </div>
        <dl className="workbench-summary-grid">
          <div>
            <dt>配置校验</dt>
            <dd>{validation?.valid ? "配置校验：通过" : "配置校验：未通过"}</dd>
          </div>
          <div>
            <dt>手工任务校验</dt>
            <dd>
              {validation?.manual_task_validation
                ? `手工任务校验：${validation.manual_task_validation.task_count}/${validation.manual_task_validation.expected_task_count ?? validation.manual_task_validation.task_count} ${
                    validation.manual_task_validation.valid ? "可达" : "不可达"
                  }`
                : "手工任务校验：未校验"}
            </dd>
          </div>
          <div>
            <dt>Config Hash</dt>
            <dd>{validation?.resolved_config_hash ?? "-"}</dd>
          </div>
        </dl>

        <div className="workbench-table-wrap">
          <table aria-label="任务可达性">
            <thead>
              <tr>
                <th>task_id</th>
                <th>crane_id</th>
                <th>pickup_zone_id</th>
                <th>dropoff_zone_id</th>
                <th>load_type</th>
                <th>priority</th>
                <th>pickup height</th>
                <th>dropoff height</th>
                <th>reachability status</th>
              </tr>
            </thead>
            <tbody>
              {taskPreview.length === 0 ? (
                <tr>
                  <td colSpan={9}>暂无任务预览。</td>
                </tr>
              ) : (
                taskPreview.map((task) => (
                  <tr key={`${task.taskId}-${task.source}`}>
                    <td>{task.taskId}</td>
                    <td>{task.craneId}</td>
                    <td>{task.pickupZoneId}</td>
                    <td>{task.dropoffZoneId}</td>
                    <td>{task.loadType}</td>
                    <td>{task.priority}</td>
                    <td>{formatHeight(task.pickupHeightM)}</td>
                    <td>{formatHeight(task.dropoffHeightM)}</td>
                    <td>{task.reachabilityStatus}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>

        <div className="workbench-config-toolbar">
          <Link
            className={`button-link${validationPassed ? "" : " disabled"}`}
            to={validationPassed ? "/run" : "#"}
            aria-disabled={!validationPassed}
          >
            下一步：运行
          </Link>
        </div>
      </section>

      <details className="workbench-panel workbench-yaml-preview">
        <summary>高级：查看 YAML</summary>
        <textarea
          aria-label="高级：查看 YAML"
          value={yamlText}
          readOnly
          spellCheck={false}
        />
      </details>
    </section>
  );
}
