import { useWorkbenchStore } from "@/state/workbench";

export function ExperimentPage() {
  const summary = useWorkbenchStore((s) => s.summary);
  const validation = useWorkbenchStore((s) => s.validation);
  const validationError = useWorkbenchStore((s) => s.validationError);
  const validationText = validationError
    ? "校验错误"
    : validation?.valid
      ? "校验通过"
      : validation
        ? "校验未通过"
        : "未校验";

  return (
    <section className="workbench-page">
      <header className="workbench-page-header">
        <h1>实验</h1>
        <p className="muted">选择模板、整理实验摘要，并准备群塔仿真运行。</p>
      </header>
      <div className="workbench-panel">
        <h2>实验概览</h2>
        <dl className="workbench-summary-grid">
          <div>
            <dt>实验 ID</dt>
            <dd>{summary?.experimentId ?? "未创建"}</dd>
          </div>
          <div>
            <dt>场景 ID</dt>
            <dd>{summary?.scenarioId ?? "未选择"}</dd>
          </div>
          <div>
            <dt>塔吊数量</dt>
            <dd>{summary ? `${summary.numCranes} 台塔吊` : "未设置"}</dd>
          </div>
          <div>
            <dt>仿真时长</dt>
            <dd>{summary ? `${summary.durationS} s` : "未设置"}</dd>
          </div>
          <div>
            <dt>LLM Provider</dt>
            <dd>{summary?.llmProvider ?? "未设置"}</dd>
          </div>
          <div>
            <dt>校验状态</dt>
            <dd>{validationText}</dd>
          </div>
        </dl>
      </div>
    </section>
  );
}
