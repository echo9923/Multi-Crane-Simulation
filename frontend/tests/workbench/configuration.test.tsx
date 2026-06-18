import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import yaml from "js-yaml";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

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
  "    material_zones:",
  "      - zone_id: mat_c1",
  "        type: box",
  "        center: [-20, -20, 0]",
  "        size: [12, 10, 0.4]",
  "        z_range_m: [0, 0.4]",
  "        surface_z_m: 0",
  "        zone_role: ground_yard",
  "        load_types: [rebar_bundle]",
  "    work_zones:",
  "      - zone_id: work_c1",
  "        type: box",
  "        center: [20, 20, 12]",
  "        size: [12, 10, 0.4]",
  "        z_range_m: [12, 12.4]",
  "        surface_z_m: 12",
  "        floor_id: floor_03",
  "        building_id: tower_a",
  "        level_index: 3",
  "        zone_role: floor_slab",
  "        accepted_load_types: [rebar_bundle]",
  "    forbidden_zones: []",
  "  load_types:",
  "    rebar_bundle:",
  "      display_name: Rebar bundle",
  "      weight_range_t: [1.0, 1.4]",
  "      size_m: [4.0, 0.8, 0.8]",
  "      shape: box_long",
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
  "    manual_tasks:",
  "      - task_id: T_C1_001",
  "        task_type: easy_task",
  "        pickup_zone_id: mat_c1",
  "        dropoff_zone_id: work_c1",
  "        load_type: rebar_bundle",
  "        priority: medium",
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
  "    base_url: https://api.deepseek.com/v1",
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
const latestDraftYaml = renderYaml
  .replace("provider: deepseek", "provider: siliconflow")
  .replace("model: deepseek-v4-flash", "model: deepseek-ai/DeepSeek-V4-Flash")
  .replace("base_url: https://api.deepseek.com/v1", "base_url: https://api.siliconflow.cn/v1")
  .replace("api_key_env: DEEPSEEK_API_KEY", "api_key_env: SILICONFLOW_API_KEY");

function installFetchMock(opts: { latestDraftYaml?: string | null; renderYamlText?: string } = {}) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.includes("/desktop/experiments/draft/latest")) {
      return ok(
        opts.latestDraftYaml
          ? {
              experiment_id: "draft_exp",
              yaml_text: opts.latestDraftYaml,
              metadata: { template_id: "demo" },
              updated_at: "2026-06-17T00:00:00Z",
            }
          : {
              experiment_id: null,
              yaml_text: null,
              metadata: null,
              updated_at: null,
            },
      );
    }
    if (url.includes("/desktop/experiments/draft")) {
      return ok({
        experiment_id: "demo_experiment",
        yaml_path: "/tmp/.desktop/experiments/demo_experiment/draft.yaml",
        metadata_path: "/tmp/.desktop/experiments/demo_experiment/draft.meta.json",
      });
    }
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
      return ok({ yaml_text: opts.renderYamlText ?? renderYaml });
    }
    if (url.includes("/desktop/config/patch")) {
      return ok({ yaml_text: patchedYaml });
    }
    if (url.includes("/desktop/llm/providers/siliconflow/secret")) {
      return ok({
        provider: "siliconflow",
        display_name: "SiliconFlow",
        default_base_url: "https://api.siliconflow.cn/v1",
        default_model: "deepseek-ai/DeepSeek-V4-Flash",
        api_key_env: "SILICONFLOW_API_KEY",
        has_saved_key: true,
        key_masked: "sf-t****3456",
        updated_at: "2026-06-17T00:00:00Z",
      });
    }
    if (url.includes("/desktop/llm/providers/siliconflow/test")) {
      return ok({
        ok: true,
        provider: "siliconflow",
        base_url: "https://api.siliconflow.cn/v1",
        latency_ms: 12,
        status_code: 200,
        model_count: 1,
        sample_models: ["deepseek-ai/DeepSeek-V4-Flash"],
        message: "connected",
      });
    }
    if (url.includes("/desktop/llm/providers")) {
      return ok({
        items: [
          {
            provider: "deepseek",
            display_name: "DeepSeek",
            default_base_url: "https://api.deepseek.com/v1",
            default_model: "deepseek-chat",
            api_key_env: "DEEPSEEK_API_KEY",
            has_saved_key: false,
            key_masked: null,
            updated_at: null,
          },
          {
            provider: "minimax",
            display_name: "MiniMax",
            default_base_url: "https://api.minimax.chat/v1",
            default_model: "abab6.5s-chat",
            api_key_env: "MINIMAX_API_KEY",
            has_saved_key: false,
            key_masked: null,
            updated_at: null,
          },
          {
            provider: "siliconflow",
            display_name: "SiliconFlow",
            default_base_url: "https://api.siliconflow.cn/v1",
            default_model: "deepseek-ai/DeepSeek-V4-Flash",
            api_key_env: "SILICONFLOW_API_KEY",
            has_saved_key: false,
            key_masked: null,
            updated_at: null,
          },
          {
            provider: "mock",
            display_name: "Mock",
            default_base_url: null,
            default_model: "mock-production",
            api_key_env: null,
            has_saved_key: false,
            key_masked: null,
            updated_at: null,
          },
          {
            provider: "replay",
            display_name: "Replay",
            default_base_url: null,
            default_model: "replay",
            api_key_env: null,
            has_saved_key: false,
            key_masked: null,
            updated_at: null,
          },
        ],
      });
    }
    if (url.includes("/scenarios/validate")) {
      return ok({
        valid: true,
        resolved_config_hash: "hash",
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

function toolbarButtons() {
  return Array.from(
    document.querySelectorAll<HTMLButtonElement>(".workbench-config-toolbar button"),
  );
}

function parsedYamlText() {
  return yaml.load(yamlTextarea().value) as {
    scenario?: {
      load_types?: Record<string, unknown>;
      crane_models?: Array<{
        model_id?: string;
        jib_length_m?: number;
        trolley_r_min_m?: number;
        trolley_r_max_m?: number;
        cable_length_min_m?: number;
      }>;
      layout?: {
        num_cranes?: number;
      };
      cranes?: Array<{
        crane_id?: string;
        model_id?: string;
        base?: number[];
        mast_height_m?: number;
      }>;
      site?: {
        material_zones?: Array<{
          zone_id?: string;
          center?: number[];
          load_types?: string[];
        }>;
        work_zones?: Array<{
          zone_id?: string;
          center?: number[];
          accepted_load_types?: string[];
          surface_z_m?: number;
          hook_target_offset_m?: number;
        }>;
      };
      tasks?: {
        manual_tasks?: Array<{
          pickup_zone_id?: string;
          dropoff_zone_id?: string;
          crane_id?: string;
          load_type?: string;
        }>;
      };
    };
  };
}

function requestBodyFor(fetchMock: ReturnType<typeof vi.mocked<typeof fetch>>, path: string) {
  const call = fetchMock.mock.calls.find(([url]) => String(url).includes(path));
  expect(call).toBeTruthy();
  const init = call?.[1] as RequestInit;
  expect(typeof init.body).toBe("string");
  return JSON.parse(init.body as string) as Record<string, unknown>;
}

function hasPostedDraft(fetchMock: ReturnType<typeof vi.mocked<typeof fetch>>) {
  return fetchMock.mock.calls.some(([url, init]) => {
    const request = init as RequestInit | undefined;
    return (
      String(url).includes("/desktop/experiments/draft") &&
      !String(url).includes("/latest") &&
      request?.method === "POST"
    );
  });
}

describe("workbench configuration flow", () => {
  beforeEach(() => {
    useStore.getState().reset();
    useWorkbenchStore.getState().resetWorkbench();
    vi.restoreAllMocks();
    installFetchMock();
  });

  afterEach(() => {
    vi.useRealTimers();
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
    const body = requestBodyFor(fetchMock, "/desktop/config/render");
    expect(body.core_overrides).toEqual({});
  });

  it("keeps manual task zone references valid after applying the multifloor preset", async () => {
    renderWorkbench();

    fireEvent.click(toolbarButtons()[0]);
    await waitFor(() => expect(yamlTextarea().value).toContain("pickup_zone_id: mat_c1"));

    fireEvent.click(toolbarButtons()[3]);

    const parsed = parsedYamlText();
    const materialZones = new Map(
      parsed.scenario?.site?.material_zones
        ?.filter((zone) => zone.zone_id)
        .map((zone) => [zone.zone_id, zone]) ?? [],
    );
    const workZones = new Map(
      parsed.scenario?.site?.work_zones
        ?.filter((zone) => zone.zone_id)
        .map((zone) => [zone.zone_id, zone]) ?? [],
    );
    const loadTypeIds = new Set(Object.keys(parsed.scenario?.load_types ?? {}));
    const manualTasks = parsed.scenario?.tasks?.manual_tasks ?? [];
    const craneModels = new Map(
      parsed.scenario?.crane_models
        ?.filter((model) => model.model_id)
        .map((model) => [model.model_id, model]) ?? [],
    );
    const cranes = new Map(
      parsed.scenario?.cranes
        ?.filter((crane) => crane.crane_id)
        .map((crane) => [crane.crane_id, crane]) ?? [],
    );

    expect(parsed.scenario?.layout?.num_cranes).toBe(4);
    expect(parsed.scenario?.cranes ?? []).toHaveLength(4);
    expect(manualTasks).toHaveLength(8);
    expect(craneModels.get("demo_flat_top_75m")?.jib_length_m).toBe(75);
    expect(craneModels.get("demo_flat_top_75m")?.trolley_r_max_m).toBe(72);
    for (const task of manualTasks) {
      const materialZone = materialZones.get(task.pickup_zone_id);
      const workZone = workZones.get(task.dropoff_zone_id);
      expect(materialZone).toBeTruthy();
      expect(workZone).toBeTruthy();
      expect(loadTypeIds.has(task.load_type ?? "")).toBe(true);
      expect(materialZone?.load_types ?? []).toContain(task.load_type);
      expect(workZone?.accepted_load_types ?? []).toContain(task.load_type);
      const crane = cranes.get(task.crane_id);
      const model = craneModels.get(crane?.model_id);
      expect(crane).toBeTruthy();
      expect(model).toBeTruthy();
      const base = crane?.base ?? [];
      const pickupCenter = materialZone?.center ?? [];
      const dropoffCenter = workZone?.center ?? [];
      for (const center of [pickupCenter, dropoffCenter]) {
        const radius = Math.hypot((center[0] ?? 0) - (base[0] ?? 0), (center[1] ?? 0) - (base[1] ?? 0));
        expect(radius).toBeGreaterThanOrEqual(model?.trolley_r_min_m ?? 0);
        expect(radius).toBeLessThanOrEqual(model?.trolley_r_max_m ?? 0);
      }
      const pickupAngle = Math.atan2(
        (pickupCenter[1] ?? 0) - (base[1] ?? 0),
        (pickupCenter[0] ?? 0) - (base[0] ?? 0),
      );
      const dropoffAngle = Math.atan2(
        (dropoffCenter[1] ?? 0) - (base[1] ?? 0),
        (dropoffCenter[0] ?? 0) - (base[0] ?? 0),
      );
      const deltaDeg =
        Math.abs((((dropoffAngle - pickupAngle) * 180) / Math.PI + 540) % 360 - 180);
      expect(deltaDeg).toBeGreaterThanOrEqual(35);
    }
    for (const crane of parsed.scenario?.cranes ?? []) {
      const model = craneModels.get(crane.model_id);
      expect(model).toBeTruthy();
      const hookMax =
        (crane.mast_height_m ?? 0) - (model?.cable_length_min_m ?? Number.POSITIVE_INFINITY);
      for (const workZone of workZones.values()) {
        const hookTarget =
          (workZone.surface_z_m ?? 0) + 0.8 + (workZone.hook_target_offset_m ?? 0.5);
        expect(hookMax).toBeGreaterThanOrEqual(hookTarget);
      }
    }
  }, 10000);

  it("restores the latest draft when the configuration page opens", async () => {
    installFetchMock({ latestDraftYaml });
    renderWorkbench();

    await waitFor(() => expect(yamlTextarea().value).toContain("provider: siliconflow"));

    expect(screen.getByText(/已恢复上次草稿/)).toBeTruthy();
    expect((screen.getByLabelText("LLM Provider") as HTMLSelectElement).value).toBe(
      "siliconflow",
    );
    expect((screen.getByLabelText("Base URL") as HTMLInputElement).value).toBe(
      "https://api.siliconflow.cn/v1",
    );
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

  it("auto-saves configuration edits and supports manual draft save", async () => {
    const fetchMock = vi.mocked(fetch);
    renderWorkbench();

    fireEvent.click(screen.getByRole("button", { name: "加载模板" }));
    await waitFor(() => expect(yamlTextarea().value).toContain("scenario:"));

    fireEvent.change(screen.getByLabelText("模型"), {
      target: { value: "deepseek-ai/DeepSeek-V4-Flash" },
    });
    await waitFor(
      () => expect(hasPostedDraft(fetchMock)).toBe(true),
      { timeout: 1800 },
    );
    expect(screen.getByText(/已自动保存/)).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "保存草稿" }));
    await waitFor(() => expect(screen.getByText(/草稿已保存/)).toBeTruthy());
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("/desktop/experiments/draft"),
      expect.anything(),
    );
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
      "siliconflow",
      "mock",
      "replay",
    ]);

    fireEvent.change(providerSelect, { target: { value: "siliconflow" } });
    fireEvent.click(screen.getByRole("button", { name: "同步表单到 YAML" }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining("/desktop/config/patch"),
        expect.anything(),
      );
    });
    const body = requestBodyFor(fetchMock, "/desktop/config/patch");
    const patches = body.patches as Record<string, unknown>;
    expect(patches["experiment.llm.provider"]).toBe("siliconflow");
    expect(patches["experiment.llm.base_url"]).toBe("https://api.siliconflow.cn/v1");
    expect(patches["experiment.llm.api_key_env"]).toBe("SILICONFLOW_API_KEY");
  });

  it("saves and tests local API keys directly from the configuration page", async () => {
    const fetchMock = vi.mocked(fetch);
    renderWorkbench();

    fireEvent.click(screen.getByRole("button", { name: "加载模板" }));
    await waitFor(() => expect(yamlTextarea().value).toContain("scenario:"));

    fireEvent.change(screen.getByLabelText("LLM Provider"), {
      target: { value: "siliconflow" },
    });
    fireEvent.change(screen.getByLabelText("本机 API Key"), {
      target: { value: "sf-temp-secret-123456" },
    });
    fireEvent.click(screen.getByRole("button", { name: "保存 Key" }));

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining("/desktop/llm/providers/siliconflow/secret"),
        expect.anything(),
      ),
    );
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining("/desktop/experiments/draft"),
        expect.anything(),
      ),
    );
    expect((screen.getByLabelText("本机 API Key") as HTMLInputElement).value).toBe("");
    expect(screen.getByText(/已保存到本机设置：sf-t\*\*\*\*3456/)).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "测试连通性" }));

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining("/desktop/llm/providers/siliconflow/test"),
        expect.anything(),
      ),
    );
    expect(screen.getByText(/连通性测试成功/)).toBeTruthy();
  }, 10000);

  it("saves and tests LLM provider secrets from settings", async () => {
    const fetchMock = vi.mocked(fetch);
    renderWorkbench("/settings");

    await waitFor(() => expect(screen.getByLabelText("Provider")).toBeTruthy());
    fireEvent.change(screen.getByLabelText("Provider"), {
      target: { value: "siliconflow" },
    });
    fireEvent.change(screen.getByLabelText("API Key"), {
      target: { value: "sf-temp-secret-123456" },
    });
    fireEvent.click(screen.getByRole("button", { name: "保存 API Key" }));

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining("/desktop/llm/providers/siliconflow/secret"),
        expect.anything(),
      ),
    );
    expect((screen.getByLabelText("API Key") as HTMLInputElement).value).toBe("");
    expect(screen.getByText(/已保存 sf-t\*\*\*\*3456/)).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "测试连通性" }));

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining("/desktop/llm/providers/siliconflow/test"),
        expect.anything(),
      ),
    );
    expect(screen.getByText(/连接成功/)).toBeTruthy();
    expect(screen.getByText(/模型示例: deepseek-ai\/DeepSeek-V4-Flash/)).toBeTruthy();
  });

  it("does not show API key controls for mock provider settings", async () => {
    renderWorkbench("/settings");

    await waitFor(() => expect(screen.getByLabelText("Provider")).toBeTruthy());
    fireEvent.change(screen.getByLabelText("Provider"), {
      target: { value: "mock" },
    });

    expect(screen.queryByLabelText("API Key")).toBeNull();
    expect(screen.getAllByText(/不需要 API Key/).length).toBeGreaterThan(0);
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

  it("adds non-overlapping default cranes when crane count increases", async () => {
    renderWorkbench();

    fireEvent.click(screen.getByRole("button", { name: "加载模板" }));
    await waitFor(() => expect(yamlTextarea().value).toContain("base: [-18, -18, 0]"));

    fireEvent.change(screen.getByLabelText("塔吊数量"), {
      target: { value: "5" },
    });

    expect(yamlTextarea().value).toContain("crane_id: C5");
    expect(yamlTextarea().value).not.toContain("base:\n    - 0\n    - 0\n    - 0");
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

  it("keeps template crane bases when validating loaded YAML", async () => {
    const fetchMock = vi.mocked(fetch);
    renderWorkbench();

    fireEvent.click(screen.getByRole("button", { name: "加载模板" }));
    await waitFor(() => expect(yamlTextarea().value).toContain("base: [-18, -18, 0]"));
    fireEvent.click(screen.getByRole("button", { name: "校验配置" }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining("/scenarios/validate"),
        expect.anything(),
      );
    });
    const body = requestBodyFor(fetchMock, "/scenarios/validate");
    const scenario = body.scenario as Record<string, unknown>;
    const cranes = scenario.cranes as Array<Record<string, unknown>>;
    expect(cranes.map((crane) => crane.base)).toEqual([[-18, -18, 0]]);
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
