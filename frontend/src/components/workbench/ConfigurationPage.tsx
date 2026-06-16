import {
  listDesktopTemplates,
  patchDesktopConfig,
  renderDesktopConfig,
  validateScenario,
} from "@/api/rest";
import { buildValidateRequest } from "@/api/config";
import { useWorkbenchStore } from "@/state/workbench";
import { coreFormToPatches } from "@/workbench/configModel";

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function positiveNumberOrNull(value: string): number | null {
  const next = Number(value);
  return Number.isFinite(next) && next > 0 ? next : null;
}

export function ConfigurationPage() {
  const templates = useWorkbenchStore((s) => s.templates);
  const selectedTemplateId = useWorkbenchStore((s) => s.selectedTemplateId);
  const yamlText = useWorkbenchStore((s) => s.yamlText);
  const form = useWorkbenchStore((s) => s.form);
  const validation = useWorkbenchStore((s) => s.validation);
  const validationError = useWorkbenchStore((s) => s.validationError);
  const busy = useWorkbenchStore((s) => s.busy);
  const setTemplates = useWorkbenchStore((s) => s.setTemplates);
  const setTemplate = useWorkbenchStore((s) => s.setTemplate);
  const setYamlText = useWorkbenchStore((s) => s.setYamlText);
  const setFormPatch = useWorkbenchStore((s) => s.setFormPatch);
  const setValidation = useWorkbenchStore((s) => s.setValidation);
  const setBusy = useWorkbenchStore((s) => s.setBusy);

  const loadTemplate = async () => {
    setBusy(true);
    setValidation(null);
    try {
      const result = await listDesktopTemplates();
      setTemplates(result.items);
      const first = result.items[0];
      if (!first) {
        setTemplate(null);
        throw new Error("没有可用模板");
      }
      setTemplate(first.template_id);
      const rendered = await renderDesktopConfig(
        first.template_id,
        coreFormToPatches(form),
      );
      setYamlText(rendered.yaml_text);
    } catch (error) {
      setValidation(null, errorMessage(error));
    } finally {
      setBusy(false);
    }
  };

  const syncYaml = async () => {
    setBusy(true);
    setValidation(null);
    try {
      const patched = await patchDesktopConfig(yamlText, coreFormToPatches(form));
      setYamlText(patched.yaml_text);
    } catch (error) {
      setValidation(null, errorMessage(error));
    } finally {
      setBusy(false);
    }
  };

  const validateYaml = async () => {
    setBusy(true);
    try {
      const result = await validateScenario(buildValidateRequest(yamlText));
      setValidation(result);
    } catch (error) {
      setValidation(null, errorMessage(error));
    } finally {
      setBusy(false);
    }
  };

  const selectedTemplate = templates.find(
    (item) => item.template_id === selectedTemplateId,
  );

  return (
    <section className="workbench-page">
      <header className="workbench-page-header">
        <h1>配置</h1>
        <p className="muted">维护场景参数、仿真时长和 LLM 运行配置。</p>
      </header>

      <div className="workbench-config-toolbar">
        <button type="button" onClick={loadTemplate} disabled={busy}>
          加载模板
        </button>
        <button type="button" onClick={syncYaml} disabled={busy || !yamlText}>
          同步表单到 YAML
        </button>
        <button type="button" onClick={validateYaml} disabled={busy || !yamlText}>
          校验配置
        </button>
        {selectedTemplate ? (
          <span className="chip">模板 {selectedTemplate.name}</span>
        ) : null}
        {validation?.valid ? <span className="chip chip-ok">校验通过</span> : null}
        {validation && !validation.valid ? (
          <span className="chip chip-warn">校验未通过</span>
        ) : null}
      </div>

      {validationError ? (
        <div className="workbench-notice" role="alert">
          {validationError}
        </div>
      ) : null}

      <div className="workbench-config-grid">
        <div className="workbench-panel">
          <h2>核心表单</h2>
          <div className="workbench-form-grid">
            <label>
              <span>塔吊数量</span>
              <input
                type="number"
                min={1}
                value={form.numCranes}
                onChange={(event) => {
                  const next = positiveNumberOrNull(event.target.value);
                  if (next !== null) setFormPatch({ numCranes: next });
                }}
              />
            </label>
            <label>
              <span>仿真时长</span>
              <input
                type="number"
                min={1}
                value={form.durationS}
                onChange={(event) => {
                  const next = positiveNumberOrNull(event.target.value);
                  if (next !== null) setFormPatch({ durationS: next });
                }}
              />
            </label>
            <label>
              <span>LLM Provider</span>
              <select
                value={form.llmProvider}
                onChange={(event) =>
                  setFormPatch({ llmProvider: event.target.value })
                }
              >
                <option value="deepseek">deepseek</option>
                <option value="minimax">minimax</option>
                <option value="mock">mock</option>
                <option value="replay">replay</option>
              </select>
            </label>
            <label>
              <span>模型</span>
              <input
                type="text"
                value={form.llmModel}
                onChange={(event) => setFormPatch({ llmModel: event.target.value })}
              />
            </label>
            <label>
              <span>API Key Env</span>
              <input
                type="text"
                value={form.llmApiKeyEnv}
                onChange={(event) =>
                  setFormPatch({ llmApiKeyEnv: event.target.value })
                }
              />
            </label>
            <label>
              <span>安全模式</span>
              <select
                value={form.safetyMode}
                onChange={(event) =>
                  setFormPatch({ safetyMode: event.target.value })
                }
              >
                <option value="S0">S0</option>
                <option value="S1">S1</option>
                <option value="S2">S2</option>
              </select>
            </label>
          </div>
        </div>

        <div className="workbench-panel workbench-yaml-panel">
          <label className="workbench-yaml-label" htmlFor="workbench-yaml">
            高级 YAML
          </label>
          <textarea
            id="workbench-yaml"
            value={yamlText}
            onChange={(event) => setYamlText(event.target.value)}
            spellCheck={false}
          />
        </div>
      </div>
    </section>
  );
}
