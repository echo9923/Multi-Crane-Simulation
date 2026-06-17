import { describe, it, expect, vi, beforeEach } from "vitest";
import {
  downloadEpisode,
  getDesktopEnvironment,
  getEpisodeState,
  listDesktopTemplates,
  pauseEpisode,
  renderDesktopConfig,
  startEpisode,
  validateScenario,
} from "@/api/rest";
import { ApiClientError } from "@/types/api";

type FetchImpl = (input: string, init?: RequestInit) => Promise<Partial<Response> & { ok: boolean; status: number }>;

function setFetch(impl: FetchImpl) {
  global.fetch = vi.fn(impl as unknown as typeof fetch) as unknown as typeof fetch;
}

function jsonRes(body: unknown, status = 200) {
  return Promise.resolve({
    ok: status >= 200 && status < 300,
    status,
    text: async () => JSON.stringify(body),
    json: async () => body,
    blob: async () => new Blob([JSON.stringify(body)]),
  });
}

beforeEach(() => {
  global.fetch = vi.fn(async () => jsonRes({})) as unknown as typeof fetch;
  window.history.replaceState(null, "", "/");
  delete window.__MULTI_CRANE_DESKTOP__;
});

describe("validateScenario", () => {
  it("unwraps data on success", async () => {
    setFetch(async () =>
      jsonRes({ code: 0, data: { valid: true, resolved_config_hash: "h", warnings: [], errors: [] }, message: "ok" }),
    );
    const r = await validateScenario({ scenario: {} });
    expect(r.valid).toBe(true);
  });

  it("throws ApiClientError with the M_E_* code on a business error", async () => {
    setFetch(async () => jsonRes({ code: "M_E_CONFIG_INVALID", data: null, message: "bad", details: { x: 1 } }, 422));
    await expect(validateScenario({ scenario: {} })).rejects.toMatchObject({ code: "M_E_CONFIG_INVALID" });
  });

  it("preserves backend validation details on business errors", async () => {
    const details = {
      field_path: "experiment.llm.max_retries",
      errors: [{ loc: ["experiment", "llm", "max_retries"], input: "1.0" }],
    };
    setFetch(async () =>
      jsonRes(
        {
          code: "M_E_CONFIG_INVALID",
          data: null,
          message: "Input should be a valid integer, unable to parse string as an integer",
          details,
        },
        422,
      ),
    );

    await expect(validateScenario({ scenario: {} })).rejects.toMatchObject({
      code: "M_E_CONFIG_INVALID",
      details,
    });
  });

  it("throws N_E_TRANSPORT on a network failure", async () => {
    setFetch(async () => {
      throw new Error("offline");
    });
    const p = validateScenario({ scenario: {} });
    await expect(p).rejects.toBeInstanceOf(ApiClientError);
    await expect(p).rejects.toMatchObject({ code: "N_E_TRANSPORT" });
  });
});

describe("getEpisodeState", () => {
  it("unwraps the state payload", async () => {
    setFetch(async () =>
      jsonRes({
        code: 0,
        data: { episode_id: "E1", status: "running", frame_index: 3, time_s: 1.5, run_dir: null, last_frame: null, terminal_reason: null, metrics: {} },
        message: "ok",
      }),
    );
    const s = await getEpisodeState("E1");
    expect(s.episode_id).toBe("E1");
    expect(s.frame_index).toBe(3);
  });
});

describe("downloadEpisode", () => {
  it("returns a Blob on ok", async () => {
    setFetch(async () => ({ ok: true, status: 200, blob: async () => new Blob(["zip"]) } as unknown as Response));
    const b = await downloadEpisode("E1");
    expect(b).toBeInstanceOf(Blob);
  });

  it("throws M_E_DOWNLOAD_FAILED on !ok with JSON error body", async () => {
    setFetch(async () => ({ ok: false, status: 500, json: async () => ({ code: "M_E_DOWNLOAD_FAILED" }) } as unknown as Response));
    await expect(downloadEpisode("E1")).rejects.toMatchObject({ code: "M_E_DOWNLOAD_FAILED" });
  });

  it("falls back to M_E_DOWNLOAD_FAILED on non-JSON error body", async () => {
    setFetch(async () => ({ ok: false, status: 502, json: async () => { throw new Error("nope"); } } as unknown as Response));
    await expect(downloadEpisode("E1")).rejects.toMatchObject({ code: "M_E_DOWNLOAD_FAILED" });
  });
});

describe("desktop REST endpoints", () => {
  it("uses the injected desktop API base", async () => {
    window.__MULTI_CRANE_DESKTOP__ = { apiBase: "http://127.0.0.1:8765", mode: "desktop" };
    setFetch(async () =>
      jsonRes({
        code: 0,
        data: { project_root: "/repo", python_path: null, python_version: null, run_roots: [], backend_port: 8765 },
        message: "ok",
      }),
    );

    await getDesktopEnvironment();

    expect(global.fetch).toHaveBeenCalledWith("http://127.0.0.1:8765/desktop/environment", expect.any(Object));
  });

  it("starts and pauses episodes", async () => {
    setFetch(async (input) => {
      if (input === "/api/episodes/start") {
        return jsonRes({
          code: 0,
          data: { episode_id: "E1", run_id: null, run_dir: null, status: "running", resolved_config_hash: null, websocket_url: null },
          message: "ok",
        });
      }
      return jsonRes({
        code: 0,
        data: { episode_id: "E1", previous_status: "running", status: "paused", accepted: true, reason: null },
        message: "ok",
      });
    });

    const started = await startEpisode({ autostart: true });
    const paused = await pauseEpisode("E1");

    expect(started.episode_id).toBe("E1");
    expect(paused.status).toBe("paused");
    expect(global.fetch).toHaveBeenCalledWith("/api/episodes/start", expect.objectContaining({ method: "POST" }));
    expect(global.fetch).toHaveBeenCalledWith("/api/episodes/E1/pause", expect.objectContaining({ method: "POST" }));
  });

  it("lists templates and renders desktop config", async () => {
    setFetch(async (input) => {
      if (input === "/api/desktop/templates") {
        return jsonRes({
          code: 0,
          data: { items: [{ template_id: "t1", name: "Template", path: "/tmp/t.yaml", scenario_id: null, experiment_id: null, description: null }] },
          message: "ok",
        });
      }
      return jsonRes({ code: 0, data: { yaml_text: "scenario: {}" }, message: "ok" });
    });

    const templates = await listDesktopTemplates();
    const rendered = await renderDesktopConfig("t1", { speed: 2 });

    expect(templates.items[0].template_id).toBe("t1");
    expect(rendered.yaml_text).toBe("scenario: {}");
    expect(global.fetch).toHaveBeenCalledWith("/api/desktop/templates", expect.objectContaining({ method: "GET" }));
    expect(global.fetch).toHaveBeenCalledWith(
      "/api/desktop/config/render",
      expect.objectContaining({ method: "POST", body: JSON.stringify({ template_id: "t1", core_overrides: { speed: 2 } }) }),
    );
  });
});
