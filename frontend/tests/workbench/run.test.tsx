import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AppRoutes } from "@/App";
import { useStore } from "@/state/store";
import { useWorkbenchStore } from "@/state/workbench";
import type { EpisodeStateResponse } from "@/types/api";

function envelope(data: unknown) {
  return new Response(JSON.stringify({ code: 0, data, message: "ok" }), {
    headers: { "content-type": "application/json" },
  });
}

function ok(data: unknown) {
  return Promise.resolve(envelope(data));
}

function errorEnvelope(code: string, message: string) {
  return Promise.resolve(
    new Response(
      JSON.stringify({ code, data: null, message, details: {} }),
      { headers: { "content-type": "application/json" }, status: 400 },
    ),
  );
}

const minimalYaml = [
  "scenario:",
  "  scenario_id: curated_dense_highrise_ground",
  "  layout:",
  "    num_cranes: 4",
  "experiment:",
  "  experiment_id: curated_dense_highrise_ground",
  "  sim:",
  "    duration_s: 7200",
  "  llm:",
  "    provider: deepseek",
].join("\n");

const yamlWithApiKey = [
  "scenario:",
  "  scenario_id: curated_dense_highrise_ground",
  "  layout:",
  "    num_cranes: 4",
  "experiment:",
  "  experiment_id: curated_dense_highrise_ground",
  "  sim:",
  "    duration_s: 7200",
  "  llm:",
  "    provider: deepseek",
  "    api_key: sk-real-secret-123456",
].join("\n");

const runningState: EpisodeStateResponse = {
  episode_id: "E1",
  status: "running",
  frame_index: 3,
  time_s: 1.5,
  run_dir: "runs/E1",
  last_frame: null,
  terminal_reason: null,
  metrics: {},
};

const startedEpisode = {
  episode_id: "E1",
  run_id: "R1",
  run_dir: "runs/E1",
  status: "running",
  resolved_config_hash: "hash",
  websocket_url: "/ws/episodes/E1",
};

function installFetchMock(
  options: {
    startResponse?: Promise<Response>;
    validateData?: unknown;
    validateResponse?: Promise<Response>;
    stopResponse?: Promise<Response> | (() => Promise<Response>);
    stateAfterStop?: EpisodeStateResponse;
    providerHasSavedKey?: boolean;
    provider?: string;
  } = {},
) {
  let currentState: EpisodeStateResponse = { ...runningState };
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.includes("/desktop/llm/providers")) {
      return ok({
        items: [
          {
            provider: options.provider ?? "deepseek",
            display_name: "DeepSeek",
            default_base_url: "https://api.deepseek.com/v1",
            default_model: "deepseek-chat",
            api_key_env: null,
            has_saved_key: options.providerHasSavedKey ?? true,
            key_masked: (options.providerHasSavedKey ?? true) ? "ds-****1234" : null,
            updated_at: (options.providerHasSavedKey ?? true)
              ? "2026-06-20T00:00:00Z"
              : null,
          },
        ],
      });
    }
    if (url.includes("/scenarios/validate")) {
      if (options.validateResponse) return options.validateResponse;
      return ok(
        options.validateData ?? {
          valid: true,
          resolved_config_hash: "hash",
        },
      );
    }
    if (url.includes("/episodes/start")) {
      currentState = { ...runningState };
      return options.startResponse ?? ok(startedEpisode);
    }
    if (url.includes("/episodes/E1/state")) {
      return ok(currentState);
    }
    if (url.includes("/episodes/E1/pause")) {
      currentState = { ...currentState, status: "paused" };
      return ok({
        episode_id: "E1",
        previous_status: "running",
        status: "paused",
        accepted: true,
        reason: null,
      });
    }
    if (url.includes("/episodes/E1/resume")) {
      currentState = { ...currentState, status: "running" };
      return ok({
        episode_id: "E1",
        previous_status: "paused",
        status: "running",
        accepted: true,
        reason: null,
      });
    }
    if (url.includes("/episodes/E1/stop")) {
      if (typeof options.stopResponse === "function") return options.stopResponse();
      if (options.stopResponse) return options.stopResponse;
      currentState = options.stateAfterStop ?? { ...currentState, status: "stopped_by_user", terminal_reason: "stopped_by_user" };
      return ok({
        episode_id: "E1",
        previous_status: "running",
        status: "stopped",
        accepted: true,
        reason: null,
      });
    }
    throw new Error(`unexpected URL ${url}`);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function renderRunPage() {
  return render(
    <MemoryRouter initialEntries={["/run"]}>
      <AppRoutes />
    </MemoryRouter>,
  );
}

function requestBodyFor(fetchMock: ReturnType<typeof vi.mocked<typeof fetch>>, path: string) {
  const call = fetchMock.mock.calls.find(([url]) => String(url).includes(path));
  expect(call).toBeTruthy();
  const init = call?.[1] as RequestInit;
  expect(typeof init.body).toBe("string");
  return JSON.parse(init.body as string) as Record<string, unknown>;
}

function fetchCallCount(fetchMock: ReturnType<typeof vi.mocked<typeof fetch>>, path: string) {
  return fetchMock.mock.calls.filter(([url]) => String(url).includes(path)).length;
}

function markValidationReady() {
  useWorkbenchStore.getState().setValidation({
    valid: true,
    resolved_config_hash: "hash",
    manual_task_validation: {
      valid: true,
      task_count: 1,
      expected_task_count: 1,
      task_reports: [],
      warnings: [],
      blocking_reasons: [],
    },
  });
}

async function clickStartWhenReady() {
  await waitFor(() => {
    expect(screen.getByText(/API Key .*配置/)).toBeTruthy();
    expect(
      (screen.getByRole("button", { name: "开始运行" }) as HTMLButtonElement).disabled,
    ).toBe(false);
  });
  fireEvent.click(screen.getByRole("button", { name: "开始运行" }));
}

describe("workbench run controls", () => {
  beforeEach(() => {
    useStore.getState().reset();
    useWorkbenchStore.getState().resetWorkbench();
    useWorkbenchStore.getState().setYamlText(minimalYaml);
    markValidationReady();
    vi.restoreAllMocks();
    installFetchMock();
  });

  it("does not start when a real provider only has api_key_env but no saved local key", async () => {
    vi.restoreAllMocks();
    const fetchMock = installFetchMock({ providerHasSavedKey: false });
    useWorkbenchStore.getState().setFormPatch({ llmApiKeyEnv: "DEEPSEEK_API_KEY" });

    renderRunPage();

    await waitFor(() => expect(screen.getByText("API Key 未配置")).toBeTruthy());
    const startButton = screen.getByRole("button", { name: "开始运行" }) as HTMLButtonElement;
    expect(startButton.disabled).toBe(true);
    fireEvent.click(startButton);
    expect(fetchCallCount(fetchMock, "/episodes/start")).toBe(0);
  });

  it("starts an interactive server episode and syncs live runtime state", async () => {
    const fetchMock = vi.mocked(fetch);
    renderRunPage();

    expect(screen.queryByRole("button", { name: "校验" })).toBeNull();
    await clickStartWhenReady();

    await waitFor(() => {
      expect(screen.getByText("E1")).toBeTruthy();
      expect(screen.getByText("running")).toBeTruthy();
      expect(screen.getByText("frame 3")).toBeTruthy();
    });
    expect(useWorkbenchStore.getState().currentEpisode?.episode_id).toBe("E1");
    expect(useStore.getState().mode).toBe("live");
    expect(useStore.getState().episodeId).toBe("E1");

    const body = requestBodyFor(fetchMock, "/episodes/start");
    expect(body.run_mode).toBe("interactive_server");
    expect(body.runner).toBe("production");
    expect(body.autostart).toBe(true);
    expect(body.config_path).toBeUndefined();
    expect(body.scenario).toMatchObject({
      scenario_id: "curated_dense_highrise_ground",
      layout: { num_cranes: 4 },
    });
    expect(body.experiment).toMatchObject({
      experiment_id: "curated_dense_highrise_ground",
      sim: { duration_s: 7200 },
      llm: { provider: "deepseek" },
    });
    expect(screen.queryByText(/当前配置已在此 Episode 启动后发生变化/)).toBeNull();
  });

  it("shows completed episodes as terminal instead of stale config control errors", async () => {
    vi.restoreAllMocks();
    installFetchMock();
    useWorkbenchStore.getState().setCurrentEpisode({
      ...startedEpisode,
      status: "completed",
    });
    useWorkbenchStore.getState().setEpisodeState({
      ...runningState,
      status: "completed",
      frame_index: 11,
      time_s: 2.2,
      terminal_reason: "completed",
    });
    useWorkbenchStore.getState().setYamlText(
      minimalYaml.replace("duration_s: 7200", "duration_s: 3600"),
    );

    renderRunPage();

    expect(screen.queryByText(/当前配置已在此 Episode 启动后发生变化/)).toBeNull();
    expect(screen.getByText(/运行已完成/)).toBeTruthy();
    expect(screen.getAllByText("completed").length).toBeGreaterThan(0);
  });

  it("removes inline and environment key fields from the start request", async () => {
    const fetchMock = vi.mocked(fetch);
    useWorkbenchStore.getState().setYamlText(yamlWithApiKey);
    renderRunPage();

    await clickStartWhenReady();
    await screen.findByText("frame 3");
    const startBody = requestBodyFor(fetchMock, "/episodes/start");
    const llm = ((startBody.experiment as Record<string, unknown>).llm ?? {}) as Record<
      string,
      unknown
    >;
    expect(llm.api_key).toBeUndefined();
    expect(llm.api_key_env).toBeUndefined();
  });

  it("supports pause resume and stop controls with state refreshes", async () => {
    const fetchMock = vi.mocked(fetch);
    renderRunPage();

    await clickStartWhenReady();
    await screen.findByText("frame 3");

    fireEvent.click(screen.getByRole("button", { name: "暂停" }));
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining("/episodes/E1/pause"),
        expect.anything(),
      );
      expect(fetchCallCount(fetchMock, "/episodes/E1/state")).toBeGreaterThanOrEqual(
        2,
      );
    });

    fireEvent.click(screen.getByRole("button", { name: "继续" }));
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining("/episodes/E1/resume"),
        expect.anything(),
      );
      expect(fetchCallCount(fetchMock, "/episodes/E1/state")).toBeGreaterThanOrEqual(
        3,
      );
    });

    fireEvent.click(screen.getByRole("button", { name: "停止" }));
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining("/episodes/E1/stop"),
        expect.anything(),
      );
      expect(fetchCallCount(fetchMock, "/episodes/E1/state")).toBeGreaterThanOrEqual(
        4,
      );
    });
  });

  it("prevents duplicate start requests while a run action is busy", async () => {
    let resolveStart!: (response: Response) => void;
    const pendingStart = new Promise<Response>((resolve) => {
      resolveStart = resolve;
    });
    vi.restoreAllMocks();
    const fetchMock = installFetchMock({ startResponse: pendingStart });
    renderRunPage();

    await waitFor(() => {
      expect((screen.getByRole("button", { name: "开始运行" }) as HTMLButtonElement).disabled).toBe(
        false,
      );
    });
    const startButton = screen.getByRole("button", { name: "开始运行" }) as HTMLButtonElement;
    fireEvent.click(startButton);
    fireEvent.click(startButton);

    await waitFor(() => {
      expect(fetchCallCount(fetchMock, "/episodes/start")).toBe(1);
      for (const label of ["开始运行", "暂停", "继续", "停止", "刷新状态"]) {
        expect(
          (screen.getByRole("button", { name: label }) as HTMLButtonElement)
            .disabled,
        ).toBe(true);
      }
    });

    resolveStart(envelope(startedEpisode));

    await waitFor(() => {
      expect(screen.getByText("E1")).toBeTruthy();
      expect(screen.getByText("frame 3")).toBeTruthy();
    });
    expect(fetchCallCount(fetchMock, "/episodes/start")).toBe(1);
  });

  it("clears legacy live runtime state after stopping an episode", async () => {
    const fetchMock = vi.mocked(fetch);
    renderRunPage();

    await clickStartWhenReady();
    await screen.findByText("frame 3");
    expect(useStore.getState().mode).toBe("live");
    expect(useStore.getState().episodeId).toBe("E1");

    fireEvent.click(screen.getByRole("button", { name: "停止" }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining("/episodes/E1/stop"),
        expect.anything(),
      );
      expect(fetchCallCount(fetchMock, "/episodes/E1/state")).toBeGreaterThanOrEqual(
        2,
      );
    });
    expect(useStore.getState().mode).toBe("idle");
    expect(useStore.getState().episodeId).toBeNull();
    expect(useWorkbenchStore.getState().currentEpisode?.episode_id).toBe("E1");
    expect(screen.getByText("E1")).toBeTruthy();
  });

  it("clears legacy live runtime state when stop reports an already terminal episode", async () => {
    vi.restoreAllMocks();
    installFetchMock({
      stopResponse: ok({
        episode_id: "E1",
        previous_status: "completed",
        status: "completed",
        accepted: false,
        reason: "already_terminal",
      }),
      stateAfterStop: { ...runningState, status: "completed", terminal_reason: "completed" },
    });
    renderRunPage();

    await clickStartWhenReady();
    await screen.findByText("frame 3");
    fireEvent.click(screen.getByRole("button", { name: "停止" }));

    await waitFor(() => {
      expect(useStore.getState().mode).toBe("idle");
      expect(useStore.getState().episodeId).toBeNull();
    });
  });

  it("keeps legacy live runtime state when stop transport fails and state cannot confirm terminal", async () => {
    vi.restoreAllMocks();
    const fetchMock = installFetchMock({
      stopResponse: () => Promise.reject(new Error("network down")),
    });
    renderRunPage();

    await clickStartWhenReady();
    await screen.findByText("frame 3");
    fireEvent.click(screen.getByRole("button", { name: "停止" }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining("/episodes/E1/stop"),
        expect.anything(),
      );
      expect(screen.getByRole("alert").textContent).toContain("network");
    });
    expect(useStore.getState().mode).toBe("live");
    expect(useStore.getState().episodeId).toBe("E1");
  });

  it("keeps start disabled and does not parse-start when the selected scene is invalid", async () => {
    const fetchMock = vi.mocked(fetch);
    useWorkbenchStore.getState().setYamlText("scenario:\n  - broken: [");
    renderRunPage();

    const startButton = screen.getByRole("button", { name: "开始运行" }) as HTMLButtonElement;
    expect(startButton.disabled).toBe(true);
    fireEvent.click(startButton);

    expect(fetchCallCount(fetchMock, "/episodes/start")).toBe(0);
  });

  it("includes backend error codes in failed action alerts", async () => {
    vi.restoreAllMocks();
    installFetchMock({
      startResponse: errorEnvelope("M_E_CONFIG_INVALID", "malformed"),
    });
    renderRunPage();

    await clickStartWhenReady();

    expect((await screen.findByRole("alert")).textContent).toContain(
      "M_E_CONFIG_INVALID: malformed",
    );
  });

  it("shows module pipeline entries without exposing a validation action", () => {
    renderRunPage();

    expect(screen.queryByRole("button", { name: "校验" })).toBeNull();
    expect(screen.getByText("校验通过")).toBeTruthy();
    expect(useWorkbenchStore.getState().validation?.valid).toBe(true);
    for (const moduleId of ["C", "D", "E", "F", "G", "H", "I", "L"]) {
      expect(screen.getByText(`Module ${moduleId}`)).toBeTruthy();
    }
  });
});
