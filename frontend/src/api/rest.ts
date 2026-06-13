// Module M REST client. All JSON calls go through /api (the Vite dev proxy strips
// the prefix to the backend at 127.0.0.1:8000). Success responses are unwrapped
// from {code:0,data,message}; error responses (code is an M_E_* string) raise
// ApiClientError. The download endpoint returns a raw zip (not wrapped).

import type {
  ApiResponse,
  ScenarioValidateRequest,
  ScenarioValidateResult,
  EpisodeStateResponse,
  DatasetListResponse,
} from "@/types/api";
import { ApiClientError } from "@/types/api";
import type { EpisodeSummary } from "@/types/sim";

const API_BASE = "/api";

async function request<T>(
  method: "GET" | "POST",
  path: string,
  body?: unknown,
  init?: { signal?: AbortSignal },
): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, {
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

export function listDatasets(limit = 50, offset = 0, init?: { signal?: AbortSignal }) {
  return request<DatasetListResponse>("GET", `/datasets?limit=${limit}&offset=${offset}`, undefined, init);
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
  let res: Response;
  try {
    res = await fetch(`${API_BASE}/episodes/${episodeId}/download${qs ? `?${qs}` : ""}`);
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
