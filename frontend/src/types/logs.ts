// Frontend-facing shapes for the offline LLM command log and event log. These
// mirror backend logs/commands.jsonl (CommandLogEntry) and the per-frame events
// (EventLogEntry) but are intentionally loose: panels only display them.

import type { RiskLevel } from "./sim";

export interface LLMMessage {
  role: string;
  content: string;
}

export interface CommandLogRow {
  schema_version?: string;
  decision_index?: number;
  episode_id?: string;
  crane_id?: string;
  time_s?: number;
  operator_id?: string;
  operator_profile?: string;
  observation_id?: string;
  provider?: string;
  model?: string;
  observation?: unknown;
  messages?: LLMMessage[];
  raw_llm_response?: unknown;
  parsed_command?: unknown;
  executed_command?: unknown;
  validation_errors?: unknown[];
  modified_by_intervention?: boolean;
  latency_ms?: number;
  retry_count?: number;
  confidence?: number;
  reason?: string;
  [key: string]: unknown;
}

export interface EventRow {
  event_id?: string;
  event_type?: string;
  episode_id?: string;
  scenario_id?: string;
  frame?: number;
  time_s?: number;
  crane_ids?: string[];
  risk_level?: RiskLevel;
  distance_min_raw_now_m?: number | null;
  clearance_min_now_m?: number | null;
  details?: unknown;
  [key: string]: unknown;
}
