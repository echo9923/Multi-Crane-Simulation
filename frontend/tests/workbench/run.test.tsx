import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AppRoutes } from "@/App";
import { useStore } from "@/state/store";
import { useWorkbenchStore } from "@/state/workbench";

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
  "  scenario_id: demo_scenario",
  "  layout:",
  "    num_cranes: 4",
  "experiment:",
  "  experiment_id: demo_experiment",
  "  sim:",
  "    duration_s: 7200",
  "  llm:",
  "    provider: deepseek",
].join("\n");

const runningState = {
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
  options: { startResponse?: Promise<Response>; validateData?: unknown } = {},
) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.includes("/scenarios/validate")) {
      return ok(
        options.validateData ?? {
          valid: true,
          resolved_config_hash: "hash",
          warnings: [],
          errors: [],
        },
      );
    }
    if (url.includes("/episodes/start")) {
      return options.startResponse ?? ok(startedEpisode);
    }
    if (url.includes("/episodes/E1/state")) {
      return ok(runningState);
    }
    if (url.includes("/episodes/E1/pause")) {
      return ok({
        episode_id: "E1",
        previous_status: "running",
        status: "paused",
        accepted: true,
        reason: null,
      });
    }
    if (url.includes("/episodes/E1/resume")) {
      return ok({
        episode_id: "E1",
        previous_status: "paused",
        status: "running",
        accepted: true,
        reason: null,
      });
    }
    if (url.includes("/episodes/E1/stop")) {
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

describe("workbench run controls", () => {
  beforeEach(() => {
    useStore.getState().reset();
    useWorkbenchStore.getState().resetWorkbench();
    useWorkbenchStore.getState().setYamlText(minimalYaml);
    vi.restoreAllMocks();
    installFetchMock();
  });

  it("starts an interactive server episode and syncs live runtime state", async () => {
    const fetchMock = vi.mocked(fetch);
    renderRunPage();

    fireEvent.click(screen.getByRole("button", { name: "启动" }));

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
  });

  it("supports pause resume and stop controls with state refreshes", async () => {
    const fetchMock = vi.mocked(fetch);
    renderRunPage();

    fireEvent.click(screen.getByRole("button", { name: "启动" }));
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

    const startButton = screen.getByRole("button", { name: "启动" }) as HTMLButtonElement;
    fireEvent.click(startButton);
    fireEvent.click(startButton);

    await waitFor(() => {
      expect(fetchCallCount(fetchMock, "/episodes/start")).toBe(1);
      for (const label of ["校验", "启动", "暂停", "继续", "停止", "刷新状态"]) {
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

    fireEvent.click(screen.getByRole("button", { name: "启动" }));
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

  it("shows an alert and does not start when YAML parsing fails", async () => {
    const fetchMock = vi.mocked(fetch);
    useWorkbenchStore.getState().setYamlText("scenario:\n  - broken: [");
    renderRunPage();

    fireEvent.click(screen.getByRole("button", { name: "启动" }));

    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(fetchCallCount(fetchMock, "/episodes/start")).toBe(0);
  });

  it("includes backend error codes in failed action alerts", async () => {
    vi.restoreAllMocks();
    installFetchMock({
      startResponse: errorEnvelope("M_E_CONFIG_INVALID", "malformed"),
    });
    renderRunPage();

    fireEvent.click(screen.getByRole("button", { name: "启动" }));

    expect((await screen.findByRole("alert")).textContent).toContain(
      "M_E_CONFIG_INVALID: malformed",
    );
  });

  it("validates YAML and shows module pipeline entries", async () => {
    const fetchMock = vi.mocked(fetch);
    renderRunPage();

    fireEvent.click(screen.getByRole("button", { name: "校验" }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining("/scenarios/validate"),
        expect.anything(),
      );
    });
    expect(screen.getByText("校验通过")).toBeTruthy();
    expect(useWorkbenchStore.getState().validation?.valid).toBe(true);
    for (const moduleId of ["C", "D", "E", "F", "G", "H", "I", "L"]) {
      expect(screen.getByText(`Module ${moduleId}`)).toBeTruthy();
    }
  });

  it("shows validation error details when backend validation fails", async () => {
    vi.restoreAllMocks();
    const fetchMock = installFetchMock({
      validateData: {
        valid: false,
        resolved_config_hash: null,
        warnings: [{ message: "wind uses default" }],
        errors: [
          {
            schema_version: "1.0",
            code: "CFG_E_BOUNDARY",
            message: "bad boundary",
            details: {},
          },
        ],
      },
    });
    renderRunPage();

    fireEvent.click(screen.getByRole("button", { name: "校验" }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining("/scenarios/validate"),
        expect.anything(),
      );
    });
    expect(screen.getByText("校验未通过")).toBeTruthy();
    expect(screen.getByText("CFG_E_BOUNDARY")).toBeTruthy();
    expect(screen.getByText("bad boundary")).toBeTruthy();
    expect(screen.getByText("wind uses default")).toBeTruthy();
  });
});
