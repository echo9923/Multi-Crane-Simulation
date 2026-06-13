// LLM instruction log. Each row expands to six sections: observation, messages,
// raw_response, parsed_command, executed_command, validation_errors. Sources:
// offline logs/commands.jsonl (preferred) or, when absent, the current frame's
// per-crane current_command (degraded, sections beyond the parsed command empty).

import { useState } from "react";
import { useStore } from "@/state/store";
import type { CommandLogRow, LLMMessage } from "@/types/logs";

const SECTIONS: { key: keyof CommandLogRow; label: string }[] = [
  { key: "observation", label: "observation" },
  { key: "messages", label: "messages" },
  { key: "raw_llm_response", label: "raw_response" },
  { key: "parsed_command", label: "parsed_command" },
  { key: "executed_command", label: "executed_command" },
  { key: "validation_errors", label: "validation_errors" },
];

// Defensive masking: never render raw secret-looking values even if a backend
// slip let one through. (Backend already scrubs these.)
function maskSecrets(s: string): string {
  return s
    .replace(/(api[_-]?key|authorization|token|secret)["'\s:=]+(["^'\s,}]+)/gi, '$1 "***"')
    .replace(/sk-[A-Za-z0-9]{8,}/g, "sk-***");
}

function Blob({ value }: { value: unknown }) {
  if (value == null || (Array.isArray(value) && value.length === 0)) {
    return <span className="muted">无</span>;
  }
  const text = maskSecrets(typeof value === "string" ? value : JSON.stringify(value, null, 2));
  return <pre className="blob">{text}</pre>;
}

function Messages({ msgs }: { msgs: LLMMessage[] | undefined }) {
  if (!msgs || msgs.length === 0) return <span className="muted">无</span>;
  return (
    <div>
      {msgs.map((m, i) => (
        <div key={i} style={{ marginBottom: 4 }}>
          <span className="chip">{m.role}</span>
          <span style={{ fontSize: 11 }}>{maskSecrets(m.content)}</span>
        </div>
      ))}
    </div>
  );
}

function Row({ row }: { row: CommandLogRow }) {
  const [open, setOpen] = useState(false);
  const validationErrors = row.validation_errors;
  const hasErrors = Array.isArray(validationErrors) && validationErrors.length > 0;
  return (
    <div className="cmd" data-testid="cmd-row">
      <div
        className="cmd-summary clickable"
        role="button"
        tabIndex={0}
        onClick={() => setOpen((o) => !o)}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") setOpen((o) => !o);
        }}
      >
        <span className="chip">{row.crane_id ?? "?"}</span>
        <span className="muted">t={row.time_s?.toFixed(1) ?? "?"}s</span>{" "}
        {String(row.reason ?? row.attention_target ?? "")}
        {hasErrors && (
          <span className="chip" style={{ color: "#ef4444", marginLeft: 6 }}>
            {validationErrors!.length} validation error(s)
          </span>
        )}
        <span className="muted" style={{ marginLeft: "auto" }}>
          {open ? "▾" : "▸"}
        </span>
      </div>
      {open &&
        SECTIONS.map((sec) => (
          <div key={sec.key}>
            <div className="section-label">{sec.label}</div>
            {sec.key === "messages" ? (
              <Messages msgs={row.messages} />
            ) : (
              <Blob value={row[sec.key]} />
            )}
          </div>
        ))}
    </div>
  );
}

export function LLMCommandLog() {
  const commandLog = useStore((s) => s.commandLog);
  const frame = useStore((s) => s.latestFrame);

  // Degraded path: no command log loaded — synthesize minimal rows from the
  // current frame's per-crane current_command so the panel is never empty.
  const rows: CommandLogRow[] =
    commandLog.length > 0
      ? commandLog
      : (frame?.cranes ?? [])
          .filter((c) => c.current_command)
          .map((c) => ({
            crane_id: c.crane_id,
            time_s: frame?.time_s,
            parsed_command: c.current_command,
          }));

  return (
    <section className="panel" data-testid="llm-command-log">
      <h3>LLM 指令日志（{rows.length}）</h3>
      <div className="panel-body">
        {rows.length === 0 ? (
          <span className="muted">无 LLM 指令记录</span>
        ) : (
          rows.map((r, i) => <Row key={`${r.decision_index ?? i}-${r.crane_id ?? i}`} row={r} />)
        )}
      </div>
    </section>
  );
}
