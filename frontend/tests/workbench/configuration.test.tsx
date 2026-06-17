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

function apiError(message: string, details: Record<string, unknown>) {
  return Promise.resolve(
    new Response(
      JSON.stringify({
        code: "M_E_CONFIG_INVALID",
        data: null,
        message,
        details,
      }),
      {
        status: 422,
        headers: { "content-type": "application/json" },
      },
    ),
  );
}

const renderYaml = [
  "scenario:",
  "  scenario_id: demo_scenario",
  "  seed: 20260614",
  "  site:",
  "    coordinate_system: ENU",
  "    boundary:",
  "      x_min: -80",
  "      x_max: 80",
  "      y_min: -80",
  "      y_max: 80",
  "      z_min: 0",
  "      z_max: 60",
  "  layout:",
  "    num_cranes: 4",
  "    mode: manual",
  "    overlap_level: medium",
  "    height_strategy: mixed",
  "    coverage_target: balanced",
  "    slew_mode_default: continuous",
  "    max_sampling_attempts: 500",
  "  cranes:",
  "    - crane_id: C1",
  "      model_id: demo_flat_top_45m",
  "      base: [-18, -18, 0]",
  "      mast_height_m: 30",
  "      theta_init_deg: -135",
  "      slew:",
  "        mode: continuous",
  "  tasks:",
  "    generation_mode: manual",
  "    num_tasks_per_crane: 2",
  "  weather:",
  "    mode: constant",
  "    wind:",
  "      base_speed_m_s: 3",
  "      gust_speed_m_s: 5",
  "      direction_deg: 90",
  "    visibility:",
  "      base_level: good",
  "experiment:",
  "  experiment_id: demo_experiment",
  "  seed: 20260614",
  "  sim:",
  "    duration_s: 7200",
  "    dt: 0.2",
  "    min_duration_s: 0",
  "    stop_when_all_tasks_done: true",
  "    physics_hz: 5",
  "    controller_hz: 5",
  "    llm_decision_interval_s: 1.0",
  "  runtime:",
  "    mode: offline_batch",
  "    replay_mode: false",
  "    llm_cache_enabled: true",
  "  llm:",
  "    enabled: true",
  "    provider: deepseek",
  "    model: deepseek-v4-flash",
  "    base_url: https://api.deepseek.com",
  "    api_key_env: DEEPSEEK_API_KEY",
  "    temperature: 0.2",
  "    timeout_s: 30",
  "    max_retries: 1",
  "    max_consecutive_failures: 10",
  "    fallback_policy: neutral_stop",
  "    scheduling:",
  "      max_concurrent_requests: 4",
  "  risk_prompt_mode: R1",
  "  safety_mode: S1",
  "  output:",
  "    run_root: runs/desktop",
  "    save_visual_frames: true",
  "    save_parquet: true",
  "    save_replay: true",
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

  it("renders visual configuration sections and keeps YAML preview read-only by default", async () => {
    renderWorkbench();

    fireEvent.click(screen.getByRole("button", { name: "加载模板" }));
    await waitFor(() => expect(yamlTextarea().value).toContain("scenario:"));

    expect(screen.getByRole("heading", { name: "基础" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "场地" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "塔吊" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "区域" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "LLM 与输出" })).toBeTruthy();
    expect(yamlTextarea().readOnly).toBe(true);
  });

  it("toggles advanced YAML editing", async () => {
    renderWorkbench();

    fireEvent.click(screen.getByRole("button", { name: "加载模板" }));
    await waitFor(() => expect(yamlTextarea().value).toContain("scenario:"));

    fireEvent.click(screen.getByRole("checkbox", { name: "高级 YAML 编辑" }));

    expect(yamlTextarea().readOnly).toBe(false);
  });

  it("sends typed numeric and select patches from visual fields", async () => {
    const fetchMock = vi.mocked(fetch);
    renderWorkbench();

    fireEvent.click(screen.getByRole("button", { name: "加载模板" }));
    await waitFor(() => expect(yamlTextarea().value).toContain("scenario:"));

    fireEvent.change(screen.getByLabelText("随机种子"), {
      target: { value: "20260618" },
    });
    fireEvent.change(screen.getByLabelText("坐标系"), {
      target: { value: "ENU" },
    });
    fireEvent.change(screen.getByLabelText("最大重试次数"), {
      target: { value: "2" },
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
    expect(patches["scenario.seed"]).toBe(20260618);
    expect(patches["scenario.site.coordinate_system"]).toBe("ENU");
    expect(patches["experiment.llm.max_retries"]).toBe(2);
  });

  it("updates the YAML preview immediately when visual fields change", async () => {
    renderWorkbench();

    fireEvent.click(screen.getByRole("button", { name: "加载模板" }));
    await waitFor(() => expect(yamlTextarea().value).toContain("scenario:"));

    fireEvent.change(screen.getByLabelText("塔吊数量"), {
      target: { value: "5" },
    });
    fireEvent.change(screen.getByLabelText("最大重试次数"), {
      target: { value: "3" },
    });

    expect(yamlTextarea().value).toContain("num_cranes: 5");
    expect(yamlTextarea().value).toContain("max_retries: 3");
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

  it("shows field-specific config errors from the backend", async () => {
    const fetchMock = vi.mocked(fetch);
    fetchMock.mockImplementation(async (input: RequestInfo | URL) => {
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
        return apiError(
          "Input should be a valid integer, unable to parse string as an integer",
          {
            field_path: "experiment.llm.max_retries",
            errors: [
              {
                loc: ["experiment", "llm", "max_retries"],
                input: "1.0",
              },
            ],
          },
        );
      }
      return ok({
        valid: true,
        resolved_config_hash: "hash",
        warnings: [],
        errors: [],
      });
    });

    renderWorkbench();

    fireEvent.click(screen.getByRole("button", { name: "加载模板" }));
    await waitFor(() => expect(yamlTextarea().value).toContain("scenario:"));
    fireEvent.click(screen.getByRole("button", { name: "同步表单到 YAML" }));

    expect(
      await screen.findByText(/字段 experiment\.llm\.max_retries 需要整数/),
    ).toBeTruthy();
    expect(screen.getByText(/建议: 填写不带小数点和单位的数字/)).toBeTruthy();
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
