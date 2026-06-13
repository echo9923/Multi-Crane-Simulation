// Mirror of Module M REST contract (backend/app/api/schemas.py).
// API_SCHEMA_VERSION "1.0".

import type { SimFrame, EpisodeSummary } from "./sim";

export const API_SCHEMA_VERSION = "1.0";

// Universal success envelope.
export interface ApiResponse<T = unknown> {
  code: 0;
  data: T;
  message: string;
}

export interface ApiError {
  schema_version: string;
  code: string; // M_E_* error code
  message: string;
  details: Record<string, unknown>;
}

export interface ApiErrorResponse {
  code: string;
  data: null;
  message: string;
  details: Record<string, unknown>;
}

export type RunMode = "offline_batch" | "offline_replay" | "interactive_server";

export interface ScenarioValidateRequest {
  config_path?: string | null;
  scenario?: Record<string, unknown> | null;
  experiment?: Record<string, unknown> | null;
  dataset?: Record<string, unknown> | null;
  overrides?: Record<string, unknown>;
}

export interface ScenarioValidateResult {
  valid: boolean;
  resolved_config_hash: string | null;
  warnings: Record<string, unknown>[];
  errors: ApiError[];
}

export interface EpisodeStateResponse {
  episode_id: string;
  status: string;
  frame_index: number;
  time_s: number;
  run_dir: string | null;
  last_frame: SimFrame | null;
  terminal_reason: string | null;
  metrics: Record<string, unknown>;
}

export interface EpisodeStartResponse {
  episode_id: string;
  run_id: string | null;
  run_dir: string | null;
  status: string;
  resolved_config_hash: string | null;
  websocket_url: string | null;
}

export interface DatasetListItem {
  dataset_id: string;
  path: string;
  created_at: string | null;
  num_episodes: number | null;
  summary_available: boolean;
}

export interface DatasetListResponse {
  items: DatasetListItem[];
  total: number;
  limit: number;
  offset: number;
}

// Frontend error thrown by the REST client when the backend returns an
// ApiErrorResponse (code is an M_E_* string) or the transport fails.
export class ApiClientError extends Error {
  readonly code: string;
  readonly details: Record<string, unknown>;
  readonly status: number;
  constructor(
    message: string,
    opts: { code?: string; details?: Record<string, unknown>; status?: number } = {},
  ) {
    super(message);
    this.name = "ApiClientError";
    this.code = opts.code ?? "N_E_TRANSPORT";
    this.details = opts.details ?? {};
    this.status = opts.status ?? 0;
  }
}
