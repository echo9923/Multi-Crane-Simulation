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

export interface EpisodeControlResponse {
  episode_id: string;
  previous_status: string;
  status: string;
  accepted: boolean;
  reason: string | null;
}

export interface EpisodeStartRequest {
  config_path?: string | null;
  scenario?: Record<string, unknown> | null;
  experiment?: Record<string, unknown> | null;
  dataset?: Record<string, unknown> | null;
  overrides?: Record<string, unknown>;
  run_mode?: RunMode | null;
  runner?: "production" | "local" | null;
  episode_id?: string | null;
  autostart?: boolean;
}

export interface DesktopTemplate {
  template_id: string;
  name: string;
  path: string;
  scenario_id: string | null;
  experiment_id: string | null;
  description: string | null;
}

export interface DesktopTemplatesResponse {
  items: DesktopTemplate[];
}

export interface DesktopConfigTextResponse {
  yaml_text: string;
}

export interface DesktopExperimentDraftResponse {
  experiment_id: string;
  yaml_path: string;
  metadata_path: string;
}

export interface DesktopExperimentDraftLatestResponse {
  experiment_id: string | null;
  yaml_text: string | null;
  metadata: Record<string, unknown> | null;
  updated_at: string | null;
}

export interface DesktopRecentExperiment {
  experiment_id: string;
  yaml_path: string;
  metadata_path: string;
  template_id: string | null;
  last_validation_hash: string | null;
  updated_at: string | null;
}

export interface DesktopRecentExperimentsResponse {
  items: DesktopRecentExperiment[];
}

export interface DesktopRunItem {
  episode_id: string;
  path: string;
  status: string | null;
  created_at: string | null;
  summary_available: boolean;
}

export interface DesktopRunsResponse {
  items: DesktopRunItem[];
}

export interface DesktopRunFile {
  relative_path: string;
  path: string;
  size_bytes: number;
  kind: string;
}

export interface DesktopRunFilesResponse {
  episode_id: string;
  files: DesktopRunFile[];
}

export interface DesktopEnvironmentResponse {
  project_root: string;
  python_path: string | null;
  python_version: string | null;
  run_roots: string[];
  backend_port: number | null;
}

export interface DesktopLLMProviderSummary {
  provider: string;
  display_name: string;
  default_base_url: string | null;
  default_model: string;
  api_key_env: string | null;
  has_saved_key: boolean;
  key_masked: string | null;
  updated_at: string | null;
}

export interface DesktopLLMProvidersResponse {
  items: DesktopLLMProviderSummary[];
}

export interface DesktopLLMSecretSaveRequest {
  api_key: string;
  base_url?: string | null;
  model?: string | null;
}

export interface DesktopLLMConnectivityTestRequest {
  api_key?: string | null;
  base_url?: string | null;
  model?: string | null;
}

export interface DesktopLLMConnectivityTestResponse {
  ok: boolean;
  provider: string;
  base_url: string;
  latency_ms: number;
  status_code: number | null;
  model_count: number | null;
  sample_models: string[] | null;
  message: string | null;
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
