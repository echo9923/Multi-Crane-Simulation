// Scenario config upload. Parsing + secret scrub happen in the browser; the
// actual validation authority is the backend POST /scenarios/validate. The
// frontend only displays valid/warnings/errors and never starts a run from here.

import { useRef, useState } from "react";
import { validateScenario } from "@/api/rest";
import { buildValidateRequest } from "@/api/config";
import { fileText } from "@/api/file";
import { ApiClientError } from "@/types/api";
import type { ScenarioValidateResult } from "@/types/api";

export function ConfigPage() {
  const inputRef = useRef<HTMLInputElement | null>(null);
  const [result, setResult] = useState<ScenarioValidateResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const onFile = async (file: File) => {
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const text = await fileText(file);
      const req = buildValidateRequest(text);
      const res = await validateScenario(req);
      setResult(res);
    } catch (e) {
      if (e instanceof ApiClientError) {
        setError(`${e.code}: ${e.message}`);
      } else {
        setError((e as Error).message);
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <div style={{ padding: 24, maxWidth: 720 }}>
      <h2 style={{ marginTop: 0 }}>场景配置校验</h2>
      <p className="muted">
        上传 scenario/experiment 配置（JSON 或 YAML）。前端只触发后端 <code>validate</code>，权威校验在后端完成。
      </p>
      <input
        ref={inputRef}
        type="file"
        data-testid="config-file-input"
        accept=".json,.yaml,.yml"
        onChange={(e) => e.target.files?.[0] && onFile(e.target.files[0])}
      />
      {busy && <div className="muted">校验中…</div>}
      {error && (
        <div className="panel" data-testid="config-error" style={{ borderColor: "#ef4444" }}>
          <div className="panel-body" style={{ color: "#ef4444" }}>{error}</div>
        </div>
      )}
      {result && (
        <div className="panel" data-testid="config-result">
          <h3>校验结果：{result.valid ? "✓ 通过" : "✗ 未通过"}</h3>
          <div className="panel-body">
            {result.resolved_config_hash && (
              <div className="muted">hash: {result.resolved_config_hash}</div>
            )}
            {result.warnings.length > 0 && (
              <>
                <div className="section-label">warnings</div>
                <pre className="blob">{JSON.stringify(result.warnings, null, 2)}</pre>
              </>
            )}
            {result.errors.length > 0 && (
              <>
                <div className="section-label">errors</div>
                <pre className="blob" style={{ color: "#ef4444" }}>
                  {JSON.stringify(result.errors, null, 2)}
                </pre>
              </>
            )}
            {result.valid && result.warnings.length === 0 && result.errors.length === 0 && (
              <span className="muted">无警告或错误。</span>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
