import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AppRoutes } from "@/App";
import { useStore } from "@/state/store";
import { useWorkbenchStore } from "@/state/workbench";

const originalCreateObjectURLDescriptor = Object.getOwnPropertyDescriptor(
  URL,
  "createObjectURL",
);
const originalRevokeObjectURLDescriptor = Object.getOwnPropertyDescriptor(
  URL,
  "revokeObjectURL",
);

function ok(data: unknown, init?: ResponseInit) {
  return Promise.resolve(
    new Response(JSON.stringify({ code: 0, data, message: "ok" }), {
      headers: { "content-type": "application/json" },
      ...init,
    }),
  );
}

function zipResponse() {
  return Promise.resolve(
    new Response(new Blob(["zip"], { type: "application/zip" }), {
      status: 200,
      headers: { "content-type": "application/zip" },
    }),
  );
}

function installFetchMock() {
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.includes("/desktop/runs/E1/files")) {
      return ok({
        episode_id: "E1",
        files: [
          {
            relative_path: "visual/frames.jsonl",
            path: "/repo/runs/E1/visual/frames.jsonl",
            size_bytes: 512,
            kind: "visual",
          },
        ],
      });
    }
    if (url.includes("/desktop/runs")) {
      return ok({
        items: [
          {
            episode_id: "E1",
            path: "runs/E1",
            status: "completed",
            created_at: "2026-06-16T10:00:00Z",
            summary_available: true,
          },
        ],
      });
    }
    if (url.includes("/desktop/environment")) {
      return ok({
        project_root: "/repo",
        python_path: "/usr/bin/python",
        python_version: "3.12.0",
        run_roots: ["/repo/runs"],
        backend_port: 8765,
      });
    }
    if (url.includes("/episodes/E1/download")) {
      return zipResponse();
    }
    throw new Error(`unexpected URL ${url}`);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function seedCurrentEpisode(runDir: string | null = "runs/E1") {
  useWorkbenchStore.getState().setCurrentEpisode({
    episode_id: "E1",
    run_id: null,
    run_dir: runDir,
    status: "completed",
    resolved_config_hash: "h",
    websocket_url: null,
  });
}

function renderWorkbench(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AppRoutes />
    </MemoryRouter>,
  );
}

function installObjectUrlStubs() {
  const createObjectURL = vi.fn(() => "blob:episode");
  const revokeObjectURL = vi.fn();
  Object.defineProperty(URL, "createObjectURL", {
    configurable: true,
    value: createObjectURL,
  });
  Object.defineProperty(URL, "revokeObjectURL", {
    configurable: true,
    value: revokeObjectURL,
  });
  return { createObjectURL, revokeObjectURL };
}

function restoreUrlDescriptor(
  name: "createObjectURL" | "revokeObjectURL",
  descriptor: PropertyDescriptor | undefined,
) {
  if (descriptor) {
    Object.defineProperty(URL, name, descriptor);
  } else {
    delete URL[name];
  }
}

describe("workbench data export and settings pages", () => {
  beforeEach(() => {
    delete window.__MULTI_CRANE_DESKTOP__;
    delete window.multiCraneDesktop;
    useStore.getState().reset();
    useWorkbenchStore.getState().resetWorkbench();
    seedCurrentEpisode();
    vi.restoreAllMocks();
    installFetchMock();
  });

  afterEach(() => {
    delete window.__MULTI_CRANE_DESKTOP__;
    delete window.multiCraneDesktop;
    restoreUrlDescriptor("createObjectURL", originalCreateObjectURLDescriptor);
    restoreUrlDescriptor("revokeObjectURL", originalRevokeObjectURLDescriptor);
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("refreshes the current episode file list", async () => {
    const fetchMock = vi.mocked(fetch);
    renderWorkbench("/data");

    fireEvent.click(screen.getByRole("button", { name: "刷新文件清单" }));

    expect(await screen.findByText("visual/frames.jsonl")).toBeTruthy();
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("/desktop/runs/E1/files"),
      expect.anything(),
    );
  });

  it("refreshes the desktop run list", async () => {
    const fetchMock = vi.mocked(fetch);
    renderWorkbench("/data");

    fireEvent.click(screen.getByRole("button", { name: "刷新运行列表" }));

    const runsTable = await screen.findByRole("table", { name: "运行列表" });
    expect(within(runsTable).getByText("E1")).toBeTruthy();
    expect(within(runsTable).getByText("completed")).toBeTruthy();
    expect(within(runsTable).getByText("runs/E1")).toBeTruthy();
    expect(within(runsTable).getByText("yes")).toBeTruthy();
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("/desktop/runs"),
      expect.anything(),
    );
  });

  it("downloads the current episode zip and revokes the object URL", async () => {
    const fetchMock = vi.mocked(fetch);
    const clickSpy = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(() => undefined);
    const { createObjectURL, revokeObjectURL } = installObjectUrlStubs();
    renderWorkbench("/data");

    fireEvent.click(screen.getByRole("button", { name: "下载 zip" }));

    await waitFor(() => {
      expect(
        fetchMock.mock.calls.some(([url]) =>
          String(url).includes("/episodes/E1/download"),
        ),
      ).toBe(true);
      expect(createObjectURL).toHaveBeenCalledTimes(1);
      expect(clickSpy).toHaveBeenCalledTimes(1);
      expect(revokeObjectURL).toHaveBeenCalledWith("blob:episode");
    });
  });

  it("shows a visible fallback when object URL downloads are unsupported", async () => {
    const fetchMock = vi.mocked(fetch);
    Object.defineProperty(URL, "createObjectURL", {
      configurable: true,
      value: undefined,
    });
    Object.defineProperty(URL, "revokeObjectURL", {
      configurable: true,
      value: undefined,
    });
    renderWorkbench("/data");

    fireEvent.click(screen.getByRole("button", { name: "下载 zip" }));

    await waitFor(() => {
      expect(
        fetchMock.mock.calls.some(([url]) =>
          String(url).includes("/episodes/E1/download"),
        ),
      ).toBe(true);
    });
    expect((await screen.findByRole("status")).textContent).toContain(
      "当前环境无法创建下载链接",
    );
  });

  it("opens the current run directory through the desktop bridge", async () => {
    const openPath = vi.fn().mockResolvedValue({ ok: true });
    window.multiCraneDesktop = { openPath };
    renderWorkbench("/data");

    fireEvent.click(screen.getByRole("button", { name: "打开 run 目录" }));

    await waitFor(() => {
      expect(openPath).toHaveBeenCalledWith("runs/E1");
    });
  });

  it("shows a browser fallback when opening a run directory outside desktop", async () => {
    renderWorkbench("/data");

    fireEvent.click(screen.getByRole("button", { name: "打开 run 目录" }));

    expect((await screen.findByRole("status")).textContent).toContain(
      "浏览器模式无法打开本地目录",
    );
  });

  it("shows runtime and backend environment details", async () => {
    window.__MULTI_CRANE_DESKTOP__ = {
      apiBase: "http://127.0.0.1:8765/api",
      wsBase: "ws://127.0.0.1:8765/ws",
      backendPort: 8765,
      mode: "desktop",
    };
    renderWorkbench("/settings");

    fireEvent.click(screen.getByRole("button", { name: "刷新环境" }));

    expect(await screen.findByText("/repo")).toBeTruthy();
    expect(screen.getAllByText("8765").length).toBeGreaterThan(0);
    expect(screen.getByText("deepseek")).toBeTruthy();
    expect(screen.getByText("minimax")).toBeTruthy();
    expect(screen.getByText("mock")).toBeTruthy();
    expect(screen.getByText("replay")).toBeTruthy();
    expect(screen.queryByRole("option", { name: /OpenAI-compatible/i })).toBeNull();
  });
});
