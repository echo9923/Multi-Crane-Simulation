import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AppRoutes } from "@/App";
import { useStore } from "@/state/store";
import { useWorkbenchStore } from "@/state/workbench";

function ok(data: unknown) {
  return Promise.resolve(
    new Response(JSON.stringify({ code: 0, data, message: "ok" }), {
      headers: { "content-type": "application/json" },
    }),
  );
}

const renderYaml = [
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

const patchedYaml = renderYaml.replace("num_cranes: 4", "num_cranes: 6");

function installFetchMock() {
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.includes("/desktop/templates")) {
      return ok({
        items: [
          {
            template_id: "demo",
            name: "Demo",
            path: "configs/demo.yaml",
            scenario_id: "demo_scenario",
            experiment_id: "demo_experiment",
            description: "Demo template",
          },
        ],
      });
    }
    if (url.includes("/desktop/config/render")) {
      return ok({ yaml_text: renderYaml });
    }
    if (url.includes("/desktop/config/patch")) {
      return ok({ yaml_text: patchedYaml });
    }
    if (url.includes("/scenarios/validate")) {
      return ok({
        valid: true,
        resolved_config_hash: "hash",
        warnings: [],
        errors: [],
      });
    }
    throw new Error(`unexpected URL ${url}`);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function renderWorkbench(initialPath = "/config") {
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <AppRoutes />
    </MemoryRouter>,
  );
}

function yamlTextarea() {
  return screen.getByLabelText("高级 YAML") as HTMLTextAreaElement;
}

function requestBodyFor(fetchMock: ReturnType<typeof vi.mocked<typeof fetch>>, path: string) {
  const call = fetchMock.mock.calls.find(([url]) => String(url).includes(path));
  expect(call).toBeTruthy();
  const init = call?.[1] as RequestInit;
  expect(typeof init.body).toBe("string");
  return JSON.parse(init.body as string) as Record<string, unknown>;
}

describe("workbench configuration flow", () => {
  beforeEach(() => {
    useStore.getState().reset();
    useWorkbenchStore.getState().resetWorkbench();
    vi.restoreAllMocks();
    installFetchMock();
  });

  it("loads templates and renders YAML from the first template", async () => {
    const fetchMock = vi.mocked(fetch);
    renderWorkbench();

    fireEvent.click(screen.getByRole("button", { name: "加载模板" }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining("/desktop/templates"),
        expect.anything(),
      );
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining("/desktop/config/render"),
        expect.anything(),
      );
    });
    expect(yamlTextarea().value).toContain("scenario:");
    expect(useWorkbenchStore.getState().selectedTemplateId).toBe("demo");
  });

  it("patches YAML from form edits", async () => {
    const fetchMock = vi.mocked(fetch);
    renderWorkbench();

    fireEvent.click(screen.getByRole("button", { name: "加载模板" }));
    await waitFor(() => expect(yamlTextarea().value).toContain("scenario:"));

    fireEvent.change(screen.getByLabelText("塔吊数量"), {
      target: { value: "6" },
    });
    fireEvent.click(screen.getByRole("button", { name: "同步表单到 YAML" }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining("/desktop/config/patch"),
        expect.anything(),
      );
    });
    expect(yamlTextarea().value).toContain("num_cranes: 6");
  });

  it("patches backend-valid LLM provider values", async () => {
    const fetchMock = vi.mocked(fetch);
    renderWorkbench();

    fireEvent.click(screen.getByRole("button", { name: "加载模板" }));
    await waitFor(() => expect(yamlTextarea().value).toContain("scenario:"));

    const providerSelect = screen.getByLabelText("LLM Provider") as HTMLSelectElement;
    expect(Array.from(providerSelect.options).map((option) => option.value)).toEqual([
      "deepseek",
      "minimax",
      "mock",
      "replay",
    ]);

    fireEvent.change(providerSelect, { target: { value: "mock" } });
    fireEvent.click(screen.getByRole("button", { name: "同步表单到 YAML" }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining("/desktop/config/patch"),
        expect.anything(),
      );
    });
    const body = requestBodyFor(fetchMock, "/desktop/config/patch");
    const patches = body.patches as Record<string, unknown>;
    expect(patches["experiment.llm.provider"]).toBe("mock");
  });

  it("does not patch crane count to zero when the field is cleared", async () => {
    const fetchMock = vi.mocked(fetch);
    renderWorkbench();

    fireEvent.click(screen.getByRole("button", { name: "加载模板" }));
    await waitFor(() => expect(yamlTextarea().value).toContain("scenario:"));

    fireEvent.change(screen.getByLabelText("塔吊数量"), {
      target: { value: "" },
    });
    fireEvent.click(screen.getByRole("button", { name: "同步表单到 YAML" }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining("/desktop/config/patch"),
        expect.anything(),
      );
    });
    const body = requestBodyFor(fetchMock, "/desktop/config/patch");
    const patches = body.patches as Record<string, unknown>;
    expect(patches["scenario.layout.num_cranes"]).toBe(4);
  });

  it("validates YAML through the backend", async () => {
    const fetchMock = vi.mocked(fetch);
    renderWorkbench();

    fireEvent.click(screen.getByRole("button", { name: "加载模板" }));
    await waitFor(() => expect(yamlTextarea().value).toContain("scenario:"));
    fireEvent.click(screen.getByRole("button", { name: "校验配置" }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining("/scenarios/validate"),
        expect.anything(),
      );
    });
    expect(screen.getByText("校验通过")).toBeTruthy();
  });

  it("shows the current experiment summary on the experiment page", () => {
    useWorkbenchStore.getState().setYamlText(
      [
        "scenario:",
        "  scenario_id: s",
        "  layout:",
        "    num_cranes: 4",
        "experiment:",
        "  experiment_id: e",
        "  sim:",
        "    duration_s: 3600",
        "  llm:",
        "    provider: openai",
      ].join("\n"),
    );

    renderWorkbench("/");

    expect(screen.getByText("e")).toBeTruthy();
    expect(screen.getByText("4 台塔吊")).toBeTruthy();
  });
});
