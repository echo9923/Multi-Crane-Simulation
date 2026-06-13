// Right-side panel stack: crane / task / risk status + LLM log + event log.

import { CraneStatusPanel } from "./CraneStatusPanel";
import { TaskStatusPanel } from "./TaskStatusPanel";
import { RiskStatusPanel } from "./RiskStatusPanel";
import { LLMCommandLog } from "./LLMCommandLog";
import { EventLog } from "./EventLog";

export function Panels() {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 0 }}>
      <CraneStatusPanel />
      <TaskStatusPanel />
      <RiskStatusPanel />
      <LLMCommandLog />
      <EventLog />
    </div>
  );
}
