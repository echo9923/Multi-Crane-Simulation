import { describe, it, expect, vi, beforeEach } from "vitest";
import { validateScenario, downloadEpisode, getEpisodeState } from "@/api/rest";
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
