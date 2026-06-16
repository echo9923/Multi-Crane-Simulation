// Module M REST client. Browser JSON calls default to /api (the Vite dev proxy
// strips the prefix); desktop runtime can inject an absolute backend base.
// Success responses are unwrapped
// from {code:0,data,message}; error responses (code is an M_E_* string) raise
// ApiClientError. The download endpoint returns a raw zip (not wrapped).

import type {
  ApiResponse,
  DatasetListResponse,
  DesktopConfigTextResponse,
  DesktopEnvironmentResponse,
  DesktopExperimentDraftResponse,
  DesktopRecentExperimentsResponse,
  DesktopRunFilesResponse,
  DesktopRunsResponse,
  DesktopTemplatesResponse,
  EpisodeControlResponse,
  EpisodeStartRequest,
  EpisodeStartResponse,
  EpisodeStateResponse,
  ScenarioValidateRequest,
  ScenarioValidateResult,
} from "@/types/api";
import { ApiClientError } from "@/types/api";
import type { EpisodeSummary } from "@/types/sim";
import { getApiBase } from "@/runtime";

function apiBase(): string {
  return getApiBase();
}

async function request<T>(
  method: "GET" | "POST",
  path: string,
  body?: unknown,
  init?: { signal?: AbortSignal },
): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${apiBase()}${path}`, {
      method,
      headers: body != null ? { "content-type": "application/json" } : undefined,
      body: body != null ? JSON.stringify(body) : undefined,
      signal: init?.signal,
    });
  } catch (e) {
    throw new ApiClientError(`network error: ${(e as Error).message}`, {
      code: "N_E_TRANSPORT",
    });
  }

  const text = await res.text();
  let json: unknown = null;
  if (text.length > 0) {
    try {
      json = JSON.parse(text);
    } catch {
      throw new ApiClientError(`invalid JSON response (status ${res.status})`, {
        status: res.status,
      });
    }
  }

  const env = json as Partial<ApiResponse<T>> & { code?: unknown; message?: string; details?: Record<string, unknown> };
  if (env && env.code === 0 && "data" in env) {
    return env.data as T;
  }
  throw new ApiClientError(env?.message ?? `request failed (status ${res.status})`, {
    code: typeof env?.code === "string" ? env.code : "N_E_UNKNOWN",
    details: env?.details ?? {},
    status: res.status,
  });
}

export function validateScenario(req: ScenarioValidateRequest, init?: { signal?: AbortSignal }) {
  return request<ScenarioValidateResult>("POST", "/scenarios/validate", req, init);
}

export function getEpisodeState(episodeId: string, init?: { signal?: AbortSignal }) {
  return request<EpisodeStateResponse>("GET", `/episodes/${episodeId}/state`, undefined, init);
}

export function getEpisodeSummary(episodeId: string, init?: { signal?: AbortSignal }) {
  return request<EpisodeSummary>("GET", `/episodes/${episodeId}/summary`, undefined, init);
}

export function startEpisode(req: EpisodeStartRequest, init?: { signal?: AbortSignal }) {
  return request<EpisodeStartResponse>("POST", "/episodes/start", req, init);
}

export function pauseEpisode(episodeId: string, init?: { signal?: AbortSignal }) {
  return request<EpisodeControlResponse>("POST", `/episodes/${episodeId}/pause`, undefined, init);
}

export function resumeEpisode(episodeId: string, init?: { signal?: AbortSignal }) {
  return request<EpisodeControlResponse>("POST", `/episodes/${episodeId}/resume`, undefined, init);
}

export function stopEpisode(episodeId: string, init?: { signal?: AbortSignal }) {
  return request<EpisodeControlResponse>("POST", `/episodes/${episodeId}/stop`, undefined, init);
}

export function listDatasets(limit = 50, offset = 0, init?: { signal?: AbortSignal }) {
  return request<DatasetListResponse>("GET", `/datasets?limit=${limit}&offset=${offset}`, undefined, init);
}

export function listDesktopTemplates(init?: { signal?: AbortSignal }) {
  return request<DesktopTemplatesResponse>("GET", "/desktop/templates", undefined, init);
}

export function renderDesktopConfig(templateId: string, coreOverrides: Record<string, unknown>, init?: { signal?: AbortSignal }) {
  return request<DesktopConfigTextResponse>("POST", "/desktop/config/render", { template_id: templateId, core_overrides: coreOverrides }, init);
}

export function patchDesktopConfig(yamlText: string, patches: Record<string, unknown>, init?: { signal?: AbortSignal }) {
  return request<DesktopConfigTextResponse>("POST", "/desktop/config/patch", { yaml_text: yamlText, patches }, init);
}

export function saveDesktopDraft(experimentId: string, yamlText: string, metadata: Record<string, unknown>, init?: { signal?: AbortSignal }) {
  return request<DesktopExperimentDraftResponse>("POST", "/desktop/experiments/draft", { experiment_id: experimentId, yaml_text: yamlText, metadata }, init);
}

export function listRecentExperiments(init?: { signal?: AbortSignal }) {
  return request<DesktopRecentExperimentsResponse>("GET", "/desktop/experiments/recent", undefined, init);
}

export function listDesktopRuns(init?: { signal?: AbortSignal }) {
  return request<DesktopRunsResponse>("GET", "/desktop/runs", undefined, init);
}

export function listDesktopRunFiles(episodeId: string, init?: { signal?: AbortSignal }) {
  return request<DesktopRunFilesResponse>("GET", `/desktop/runs/${episodeId}/files`, undefined, init);
}

export function getDesktopEnvironment(init?: { signal?: AbortSignal }) {
  return request<DesktopEnvironmentResponse>("GET", "/desktop/environment", undefined, init);
}

export interface DownloadOpts {
  include_logs?: boolean;
  include_data?: boolean;
  include_visual?: boolean;
}

/** Download an episode run archive (raw application/zip). Throws on !ok. */
export async function downloadEpisode(episodeId: string, opts: DownloadOpts = {}): Promise<Blob> {
  const params = new URLSearchParams();
  if (opts.include_logs !== undefined) params.set("include_logs", String(opts.include_logs));
  if (opts.include_data !== undefined) params.set("include_data", String(opts.include_data));
  if (opts.include_visual !== undefined) params.set("include_visual", String(opts.include_visual));
  const qs = params.toString();
  const base = apiBase();
  let res: Response;
  try {
    res = await fetch(`${base}/episodes/${episodeId}/download${qs ? `?${qs}` : ""}`);
  } catch (e) {
    throw new ApiClientError(`network error: ${(e as Error).message}`, { code: "N_E_TRANSPORT" });
  }
  if (!res.ok) {
    let code = "M_E_DOWNLOAD_FAILED";
    try {
      const j = (await res.json()) as { code?: string };
      if (j?.code) code = j.code;
    } catch {
      /* non-JSON error body */
    }
    throw new ApiClientError(`download failed (status ${res.status})`, { code, status: res.status });
  }
  return res.blob();
}
