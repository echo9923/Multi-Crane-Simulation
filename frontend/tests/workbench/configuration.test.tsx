import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AppRoutes } from "@/App";
import { useStore } from "@/state/store";
import { useWorkbenchStore } from "@/state/workbench";
import { yamlToCoreForm } from "@/workbench/configModel";

function ok(data: unknown) {
  return Promise.resolve(
    new Response(JSON.stringify({ code: 0, data, message: "ok" }), {
      headers: { "content-type": "application/json" },
    }),
  );
}

const curatedYaml = [
  'description: "Dense high-rise tower crane lifting scenario."',
  "scenario:",
  "  scenario_id: curated_dense_highrise_ground",
  "  seed: 20260619",
  "  site:",
  "    coordinate_system: ENU",
  "    boundary:",
  "      x_min: -110",
  "      x_max: 110",
  "      y_min: -90",
  "      y_max: 100",
  "      z_min: 0",
  "      z_max: 90",
  "    buildings:",
  "      - building_id: tower_a",
  "        name: Tower A",
  "        floors: 18",
  "        floor_height_m: 3.6",
  "        base_z_m: 0",
  "    material_zones:",
  "      - zone_id: ground_yard_west",
  "        type: box",
  "        center: [-82, 10, 0]",
  "        size: [18, 14, 0.4]",
  "        z_range_m: [0, 0.4]",
  "        surface_z_m: 0",
  "        load_types: [rebar_bundle]",
  "    work_zones:",
  "      - zone_id: tower_a_floor_10",
  "        type: box",
  "        center: [-28, 18, 36]",
  "        size: [16, 12, 0.4]",
  "        z_range_m: [36, 36.4]",
  "        surface_z_m: 36",
  "        building_id: tower_a",
  "        level_index: 10",
  "        zone_role: floor_slab",
  "        hook_target_offset_m: 0.5",
  "        accepted_load_types: [rebar_bundle]",
  "  layout:",
  "    num_cranes: 4",
  "    mode: manual",
  "  cranes:",
  "    - crane_id: C1",
  "      model_id: demo_flat_top_75m",
  "      base: [-76, -12, 0]",
  "      mast_height_m: 72",
  "      theta_init_deg: 0",
  "      slew:",
  "        mode: continuous",
  "  load_types:",
  "    rebar_bundle:",
  "      weight_range_t: [1.0, 1.4]",
  "      size_m: [4.0, 0.8, 0.8]",
  "  tasks:",
  "    generation_mode: manual",
  "    num_tasks_per_crane: 1",
  "    manual_tasks:",
  "      - task_id: T1_C1_rebar_to_A10",
  "        crane_id: C1",
  "        pickup_zone_id: ground_yard_west",
  "        dropoff_zone_id: tower_a_floor_10",
  "        load_type: rebar_bundle",
  "        priority: high",
  "experiment:",
  "  experiment_id: curated_dense_highrise_ground",
  "  sim:",
  "    duration_s: 7200",
  "    dt: 0.2",
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
  "  runtime:",
  "    mode: offline_batch",
  "  output:",
  "    run_root: runs/curated",
].join("\n");

function installFetchMock() {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url.includes("/desktop/templates")) {
      return ok({
        items: [
          {
            template_id: "curated_dense_highrise_ground",
            name: "Dense high-rise ground cranes",
            path: "configs/curated_dense_highrise_ground.yaml",
            scenario_id: "curated_dense_highrise_ground",
            experiment_id: "curated_dense_highrise_ground",
            description: "Dense high-rise tower crane lifting scenario.",
          },
          {
            template_id: "curated_elevated_crane_transfer",
            name: "Elevated crane transfer",
            path: "configs/curated_elevated_crane_transfer.yaml",
            scenario_id: "curated_elevated_crane_transfer",
            experiment_id: "curated_elevated_crane_transfer",
            description: "Ground cranes feed an elevated tower crane.",
          },
          {
            template_id: "curated_complex_cross_lifting",
            name: "Complex cross lifting",
            path: "configs/curated_complex_cross_lifting.yaml",
            scenario_id: "curated_complex_cross_lifting",
            experiment_id: "curated_complex_cross_lifting",
            description: "Dense overlapping lift zones with cross-risk.",
          },
        ],
      });
    }
    if (url.includes("/desktop/config/render")) {
      return ok({ yaml_text: curatedYaml });
    }
    if (url.includes("/desktop/experiments/draft")) {
      return ok({
        experiment_id: "curated_dense_highrise_ground",
        yaml_path: "/tmp/draft.yaml",
        metadata_path: "/tmp/draft.meta.json",
      });
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
        updated_at: "2026-06-20T00:00:00Z",
      });
    }
    if (url.includes("/desktop/llm/providers/deepseek/secret")) {
      return ok({
        provider: "deepseek",
        display_name: "DeepSeek",
        default_base_url: "https://api.deepseek.com/v1",
        default_model: "deepseek-chat",
        api_key_env: "DEEPSEEK_API_KEY",
        has_saved_key: true,
        key_masked: "ds-n****9999",
        updated_at: "2026-06-20T00:00:00Z",
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
            has_saved_key: true,
            key_masked: "ds-****1234",
            updated_at: "2026-06-20T00:00:00Z",
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
        manual_task_validation: {
          valid: true,
          task_count: 1,
          expected_task_count: 1,
          task_reports: [
            {
              task_id: "T1_C1_rebar_to_A10",
              crane_id: "C1",
              pickup_zone_id: "ground_yard_west",
              dropoff_zone_id: "tower_a_floor_10",
              load_type: "rebar_bundle",
              priority: "high",
              pickup_reachable: true,
              dropoff_reachable: true,
              pickup_height_m: 1.3,
              dropoff_height_m: 37.3,
              blocking_reasons: [],
            },
          ],
          warnings: [],
          blocking_reasons: [],
        },
      });
    }
    if (url.includes("/episodes/start")) {
      return ok({
        episode_id: "E-curated",
        run_id: "R-curated",
        run_dir: "runs/curated/E-curated",
        status: "running",
        resolved_config_hash: "hash",
        websocket_url: "/ws/episodes/E-curated",
      });
    }
    if (url.includes("/episodes/E-curated/state")) {
      return ok({
        episode_id: "E-curated",
        status: "running",
        frame_index: 4,
        time_s: 0.8,
        run_dir: "runs/curated/E-curated",
        last_frame: null,
        terminal_reason: null,
        metrics: {},
      });
    }
    throw new Error(`unexpected URL ${url}`);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function renderWorkbench(initialPath = "/") {
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
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

function selectLoadedScenario() {
  useWorkbenchStore.getState().setYamlText(curatedYaml, { markEpisodeStale: false });
  useWorkbenchStore.getState().setFormPatch(yamlToCoreForm(curatedYaml));
}

const runningEpisode = {
  episode_id: "E-old",
  run_id: "R-old",
  run_dir: "runs/curated/E-old",
  status: "running",
  resolved_config_hash: "old-hash",
  websocket_url: "/ws/episodes/E-old",
};

describe("curated workbench flow", () => {
  beforeEach(() => {
    useStore.getState().reset();
    useWorkbenchStore.getState().resetWorkbench();
    vi.restoreAllMocks();
    installFetchMock();
  });

  it("uses the experiment page as the three-scenario entry point", async () => {
    const fetchMock = vi.mocked(fetch);
    renderWorkbench("/");

    expect(screen.getByRole("heading", { name: "选择场景" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "场景" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "API Key" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "加载模板" })).toBeNull();
    expect(screen.queryByRole("button", { name: "同步模板" })).toBeNull();
    expect(screen.queryByText("自动生成多楼层施工示例")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: /选择 场景 1/ }));

    await waitFor(() =>
      expect(useWorkbenchStore.getState().summary?.scenarioId).toBe(
        "curated_dense_highrise_ground",
      ),
    );
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("/desktop/config/render"),
      expect.anything(),
    );
    expect(screen.getByText("当前选择：curated_dense_highrise_ground")).toBeTruthy();

    fireEvent.click(screen.getByRole("link", { name: "下一步：配置 API Key" }));
    expect(await screen.findByRole("heading", { name: "配置 API Key" })).toBeTruthy();
  });

  it("keeps configuration focused on provider key setup and scenario validation", async () => {
    const fetchMock = vi.mocked(fetch);
    selectLoadedScenario();
    renderWorkbench("/config");

    await waitFor(() => expect(screen.getByText("已保存：ds-****1234")).toBeTruthy());
    expect(screen.getByRole("heading", { name: "配置 API Key" })).toBeTruthy();
    expect(screen.queryByText(/mock/i)).toBeNull();
    expect(screen.queryByText(/replay/i)).toBeNull();
    expect(screen.queryByRole("button", { name: "加载模板" })).toBeNull();
    expect(screen.queryByRole("button", { name: "同步模板" })).toBeNull();
    expect(screen.queryByRole("button", { name: "运行仿真" })).toBeNull();
    expect(screen.queryByRole("heading", { name: "塔吊" })).toBeNull();
    expect(screen.queryByRole("heading", { name: "场地" })).toBeNull();

    fireEvent.change(screen.getByLabelText("Provider"), {
      target: { value: "siliconflow" },
    });
    fireEvent.change(screen.getByLabelText("API Key"), {
      target: { value: "sf-temp-secret-123456" },
    });
    fireEvent.click(screen.getByRole("button", { name: "保存 Key" }));

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining("/desktop/llm/providers/siliconflow/secret"),
        expect.anything(),
      ),
    );
    expect((screen.getByLabelText("API Key") as HTMLInputElement).value).toBe("");
    expect(screen.getByText("已保存：sf-t****3456")).toBeTruthy();
    expect(useWorkbenchStore.getState().yamlText).toContain(
      "model: deepseek-ai/DeepSeek-V4-Flash",
    );
    expect(useWorkbenchStore.getState().yamlText).toContain(
      "base_url: https://api.siliconflow.cn/v1",
    );

    fireEvent.click(screen.getByRole("button", { name: "测试连接" }));
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining("/desktop/llm/providers/siliconflow/test"),
        expect.anything(),
      ),
    );
    expect(screen.getByText(/连接成功/)).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "校验场景" }));
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining("/scenarios/validate"),
        expect.anything(),
      ),
    );
    expect(screen.getByText("配置校验：通过")).toBeTruthy();
    expect(screen.getByText("手工任务校验：1/1 可达")).toBeTruthy();
    expect(screen.getByText("T1_C1_rebar_to_A10")).toBeTruthy();
    expect(screen.getByText("37.3 m")).toBeTruthy();

    const yamlPreview = screen.getByLabelText("高级：查看 YAML") as HTMLTextAreaElement;
    expect(yamlPreview.readOnly).toBe(true);
    expect(yamlPreview.value).toContain("scenario_id: curated_dense_highrise_ground");
  });

  it("saving the current provider key does not rewrite scenario model settings", async () => {
    selectLoadedScenario();
    renderWorkbench("/config");

    await waitFor(() => expect(screen.getByText("已保存：ds-****1234")).toBeTruthy());
    fireEvent.change(screen.getByLabelText("API Key"), {
      target: { value: "sk-new-deepseek-key-123456" },
    });
    fireEvent.click(screen.getByRole("button", { name: "保存 Key" }));

    await waitFor(() => expect(screen.getByText("已保存：ds-n****9999")).toBeTruthy());
    const yamlText = useWorkbenchStore.getState().yamlText;
    expect(yamlText).toContain("model: deepseek-v4-flash");
    expect(yamlText).not.toContain("model: deepseek-chat");
    expect(yamlText).not.toContain("api_key_env:");
  });

  it("uses the run page as the only startup surface", async () => {
    const fetchMock = vi.mocked(fetch);
    selectLoadedScenario();
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

    renderWorkbench("/run");

    await waitFor(() => expect(screen.getByText("API Key 已配置")).toBeTruthy());
    expect(screen.getByText("场景已选择")).toBeTruthy();
    expect(screen.getByText("校验通过")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "开始运行" }));

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining("/episodes/start"),
        expect.anything(),
      ),
    );
    const startBody = requestBodyFor(fetchMock, "/episodes/start");
    expect(startBody.run_mode).toBe("interactive_server");
    expect(startBody.runner).toBe("production");
    expect(startBody.autostart).toBe(true);
    expect(startBody.scenario).toMatchObject({
      scenario_id: "curated_dense_highrise_ground",
    });
    expect(await screen.findByText("E-curated")).toBeTruthy();
    expect(screen.getByRole("link", { name: "打开 3D 观察" })).toBeTruthy();

    cleanup();
    renderWorkbench("/config");
    expect(screen.queryByRole("button", { name: "开始运行" })).toBeNull();
  });

  it("keeps startup disabled until scene, key, and validation are ready", async () => {
    renderWorkbench("/run");

    expect(screen.getByText("场景未选择")).toBeTruthy();
    expect(screen.getByText("校验未通过")).toBeTruthy();
    expect((screen.getByRole("button", { name: "开始运行" }) as HTMLButtonElement).disabled).toBe(
      true,
    );

    cleanup();
    selectLoadedScenario();
    useWorkbenchStore.getState().setValidation({
      valid: true,
      resolved_config_hash: "hash",
      manual_task_validation: {
        valid: false,
        task_count: 1,
        expected_task_count: 1,
        task_reports: [],
        warnings: [],
        blocking_reasons: ["dropoff_out_of_radius"],
      },
    });
    renderWorkbench("/run");

    await waitFor(() => expect(screen.getByText("API Key 已配置")).toBeTruthy());
    expect(screen.getByText("校验未通过")).toBeTruthy();
    expect((screen.getByRole("button", { name: "开始运行" }) as HTMLButtonElement).disabled).toBe(
      true,
    );
  });

  it("clears old episode and live state when selecting a different curated scenario", async () => {
    const fetchMock = vi.mocked(fetch);
    useWorkbenchStore.getState().setCurrentEpisode(runningEpisode);
    useWorkbenchStore.getState().setEpisodeState({
      episode_id: "E-old",
      status: "running",
      frame_index: 12,
      time_s: 6,
      run_dir: "runs/curated/E-old",
      last_frame: null,
      terminal_reason: null,
      metrics: {},
    });
    useStore.getState().startLiveEpisode("E-old");

    renderWorkbench("/");

    fireEvent.click(screen.getByRole("button", { name: "选择 场景 2" }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining("/desktop/config/render"),
        expect.anything(),
      );
    });
    expect(useWorkbenchStore.getState().currentEpisode).toBeNull();
    expect(useWorkbenchStore.getState().episodeState).toBeNull();
    expect(useStore.getState().mode).toBe("idle");
    expect(useStore.getState().episodeId).toBeNull();
  });

  it("keeps the current episode when reselecting the same curated scenario", async () => {
    selectLoadedScenario();
    useWorkbenchStore.getState().setCurrentEpisode(runningEpisode);
    useWorkbenchStore.getState().setEpisodeState({
      episode_id: "E-old",
      status: "running",
      frame_index: 12,
      time_s: 6,
      run_dir: "runs/curated/E-old",
      last_frame: null,
      terminal_reason: null,
      metrics: {},
    });
    useStore.getState().startLiveEpisode("E-old");

    renderWorkbench("/");

    fireEvent.click(screen.getByRole("button", { name: "选择 场景 1" }));

    await waitFor(() =>
      expect(useWorkbenchStore.getState().summary?.scenarioId).toBe(
        "curated_dense_highrise_ground",
      ),
    );
    expect(useWorkbenchStore.getState().currentEpisode?.episode_id).toBe("E-old");
    expect(useWorkbenchStore.getState().episodeState?.episode_id).toBe("E-old");
    expect(useStore.getState().mode).toBe("live");
    expect(useStore.getState().episodeId).toBe("E-old");
  });
});
