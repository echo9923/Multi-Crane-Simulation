import { Link } from "react-router-dom";

import { listDesktopTemplates, renderDesktopConfig } from "@/api/rest";
import { useStore } from "@/state/store";
import { useWorkbenchStore } from "@/state/workbench";
import { formatConfigError, yamlToCoreForm } from "@/workbench/configModel";
import { CURATED_SCENARIOS, findCuratedScenario } from "@/workbench/curatedScenarios";

function statusText(value: boolean) {
  return value ? "含高位塔吊" : "无高位塔吊";
}

export function ExperimentPage() {
  const summary = useWorkbenchStore((s) => s.summary);
  const busy = useWorkbenchStore((s) => s.busy);
  const validationError = useWorkbenchStore((s) => s.validationError);
  const setBusy = useWorkbenchStore((s) => s.setBusy);
  const setTemplates = useWorkbenchStore((s) => s.setTemplates);
  const setTemplate = useWorkbenchStore((s) => s.setTemplate);
  const setYamlText = useWorkbenchStore((s) => s.setYamlText);
  const setFormPatch = useWorkbenchStore((s) => s.setFormPatch);
  const setValidation = useWorkbenchStore((s) => s.setValidation);
  const clearCurrentEpisode = useWorkbenchStore((s) => s.clearCurrentEpisode);
  const resetVisualizationStore = useStore((s) => s.reset);

  const selectedScenario = findCuratedScenario(summary?.scenarioId);

  const loadScenario = async (scenarioId: string) => {
    if (useWorkbenchStore.getState().busy) return;
    const previousScenarioId = useWorkbenchStore.getState().summary?.scenarioId;
    setBusy(true);
    setValidation(null, null);
    try {
      const templates = await listDesktopTemplates();
      setTemplates(templates.items);
      const template = templates.items.find((item) => item.template_id === scenarioId);
      if (!template) {
        throw new Error(`未找到内置场景 ${scenarioId}`);
      }
      const rendered = await renderDesktopConfig(template.template_id, {});
      setTemplate(template.template_id);
      setYamlText(rendered.yaml_text, { markEpisodeStale: false });
      setFormPatch(yamlToCoreForm(rendered.yaml_text));
      if (previousScenarioId !== scenarioId) {
        clearCurrentEpisode();
        resetVisualizationStore();
      }
    } catch (error) {
      setValidation(null, formatConfigError(error));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="workbench-page">
      <header className="workbench-page-header">
        <h1>选择场景</h1>
        <p className="muted">
          当前阶段只开放三个确定好的群塔吊运场景。先选择场景，再配置 API Key，最后进入运行页启动仿真。
        </p>
      </header>

      {validationError ? (
        <div className="workbench-notice" role="alert">
          {validationError}
        </div>
      ) : null}

      <div className="workbench-card-list">
        {CURATED_SCENARIOS.map((scenario, index) => {
          const selected = summary?.scenarioId === scenario.scenarioId;
          return (
            <article
              className={`workbench-panel workbench-scenario-card${selected ? " selected" : ""}`}
              key={scenario.scenarioId}
            >
              <div className="workbench-scenario-card-main">
                <div>
                  <h2>{scenario.name}</h2>
                  <p className="workbench-help">{scenario.purpose}</p>
                </div>
                <button
                  type="button"
                  onClick={() => void loadScenario(scenario.scenarioId)}
                  disabled={busy}
                >
                  选择 场景 {index + 1}
                </button>
              </div>
              <div className="workbench-scenario-facts">
                <span>{scenario.craneCount} 台塔吊</span>
                <span>{scenario.buildingCount} 栋建筑</span>
                <span>{scenario.taskCount} 个任务</span>
                <span>{statusText(scenario.hasElevatedCrane)}</span>
              </div>
              <p className="workbench-help">
                主要风险：{scenario.primaryCrossRisk}
              </p>
            </article>
          );
        })}
      </div>

      <section className="workbench-panel workbench-config-section">
        <div className="workbench-config-section-header">
          <h2>当前选择</h2>
          <p className="workbench-help">
            {selectedScenario
              ? selectedScenario.purpose
              : "还没有选择场景。请选择上方任一场景后继续。"}
          </p>
        </div>
        <div className="workbench-config-toolbar">
          <span className={selectedScenario ? "chip chip-ok" : "chip"}>
            当前选择：{summary?.scenarioId ?? "未选择"}
          </span>
          <Link
            className={`button-link${selectedScenario ? "" : " disabled"}`}
            to={selectedScenario ? "/config" : "#"}
            aria-disabled={!selectedScenario}
          >
            下一步：配置 API Key
          </Link>
        </div>
      </section>
    </section>
  );
}
