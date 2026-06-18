import { describe, expect, it } from "vitest";
import {
  UNSUPPORTED_CORE_PATCH_FIELDS,
  applyCoreFormToYaml,
  coreFormToPatches,
  defaultCoreForm,
  extractExperimentSummary,
  formatConfigError,
  yamlToCoreForm,
} from "@/workbench/configModel";

const yamlText = [
  "scenario:",
  "  scenario_id: demo",
  "  layout:",
  "    num_cranes: 4",
  "    mode: manual",
  "    overlap_level: medium",
  "  tasks:",
  "    num_tasks_per_crane: 2",
  "experiment:",
  "  experiment_id: exp",
  "  sim:",
  "    duration_s: 7200",
  "    dt: 0.2",
  "    stop_when_all_tasks_done: true",
  "  llm:",
  "    enabled: true",
  "    provider: deepseek",
  "    model: deepseek-v4-flash",
  "  safety_mode: S1",
].join("\n");

describe("workbench config model", () => {
  it("extracts core form values from YAML", () => {
    const form = yamlToCoreForm(yamlText);
    expect(form.experimentId).toBe("exp");
    expect(form.scenarioId).toBe("demo");
    expect(form.numCranes).toBe(4);
    expect(form.tasksPerCrane).toBe(2);
    expect(form.durationS).toBe(7200);
    expect(form.llmProvider).toBe("deepseek");
  });

  it("maps core form values to backend patch paths", () => {
    const patches = coreFormToPatches({
      ...defaultCoreForm(),
      experimentId: "exp2",
      numCranes: 6,
      durationS: 300,
      llmProvider: "mock",
    });

    expect(patches["experiment.experiment_id"]).toBe("exp2");
    expect(patches["scenario.layout.num_cranes"]).toBe(6);
    expect(patches["experiment.sim.duration_s"]).toBe(300);
    expect(patches["experiment.llm.provider"]).toBe("mock");
  });

  it("defaults DeepSeek base URL to the v1 chat API root", () => {
    expect(defaultCoreForm().llmBaseUrl).toBe("https://api.deepseek.com/v1");
  });

  it("defaults zones to a ground yard and elevated work floor", () => {
    const form = defaultCoreForm();

    expect(form.materialZones[0]).toMatchObject({
      zoneId: "ground_yard_1",
      surfaceZM: 0,
      zoneRole: "ground_yard",
    });
    expect(form.workZones[0]).toMatchObject({
      zoneId: "floor_03",
      surfaceZM: 12,
      floorId: "floor_03",
      buildingId: "tower_a",
      zoneRole: "floor_slab",
    });
    expect(form.workZones[0].zMin).toBe(12);
    expect(form.workZones[0].zMax).toBe(12.4);
  });

  it("default manual cranes have distinct safe base positions", () => {
    const form = defaultCoreForm();
    const bases = form.cranes.map((crane) => [crane.baseX, crane.baseY, crane.baseZ]);

    expect(new Set(bases.map((base) => base.join(","))).size).toBe(form.cranes.length);
    for (let left = 0; left < bases.length; left += 1) {
      for (let right = left + 1; right < bases.length; right += 1) {
        const dx = bases[left][0] - bases[right][0];
        const dy = bases[left][1] - bases[right][1];
        expect(Math.hypot(dx, dy)).toBeGreaterThanOrEqual(8);
      }
    }
  });

  it("extracts site, crane, zone, weather, risk, llm, and output fields", () => {
    const form = yamlToCoreForm([
      "scenario:",
      "  scenario_id: demo",
      "  seed: 20260614",
      "  site:",
      "    coordinate_system: ENU",
      "    boundary:",
      "      x_min: -80",
      "      x_max: 80",
      "      y_min: -70",
      "      y_max: 70",
      "      z_min: 0",
      "      z_max: 60",
      "    material_zones:",
      "      - zone_id: mat_c1",
      "        type: box",
      "        center: [-21.96, -21.96, 10]",
      "        size: [0.4, 0.4, 0.4]",
      "        z_range_m: [9.8, 10.2]",
      "        surface_z_m: 0",
      "        zone_role: ground_yard",
      "        hook_target_offset_m: 0.75",
      "        approach_clearance_m: 4",
      "        load_types: [rebar_bundle]",
      "    work_zones:",
      "      - zone_id: work_c1",
      "        type: box",
      "        center: [-26.485, -26.485, 11]",
      "        size: [0.6, 0.6, 0.5]",
      "        z_range_m: [10.8, 11.2]",
      "        surface_z_m: 10.8",
      "        floor_id: floor_03",
      "        building_id: tower_a",
      "        level_index: 3",
      "        zone_role: unloading_platform",
      "        accepted_load_types: [rebar_bundle]",
      "    forbidden_zones:",
      "      - zone_id: core",
      "        type: box",
      "        center: [0, 0, 10]",
      "        size: [4, 4, 20]",
      "  layout:",
      "    num_cranes: 1",
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
      "    queue_policy:",
      "      start_mode: simultaneous",
      "      initial_start_jitter_s: [0, 0]",
      "      inter_task_delay_s: [0, 1]",
      "    attach_delay_s: [0, 0]",
      "    release_delay_s: [0, 0]",
      "    state_machine:",
      "      attach_stage_timeout_s: 1200",
      "      release_stage_timeout_s: 1200",
      "      task_no_progress_timeout_s: 1200",
      "      recovery_release_timeout_s: 1200",
      "  weather:",
      "    mode: constant",
      "    wind:",
      "      base_speed_m_s: 3",
      "      gust_speed_m_s: 5",
      "      direction_deg: 90",
      "    visibility:",
      "      base_level: good",
      "  risk:",
      "    geometry_envelope:",
      "      jib_radius_m: 0.75",
      "      hook_radius_m: 0.5",
      "      load_radius_m: 1.0",
      "    thresholds_m:",
      "      low: 6",
      "      medium: 4",
      "      high: 2.5",
      "      near_miss: 1.5",
      "experiment:",
      "  experiment_id: exp",
      "  seed: 20260614",
      "  sim:",
      "    duration_s: 7200",
      "    dt: 0.2",
      "    min_duration_s: 0",
      "    stop_when_all_tasks_done: true",
      "    physics_hz: 5",
      "    controller_hz: 5",
      "    llm_decision_interval_s: 1.0",
      "  risk_prompt_mode: R1",
      "  safety_mode: S1",
      "  runtime:",
      "    mode: offline_batch",
      "    replay_mode: false",
      "    replay_file: null",
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
      "    structured_output:",
      "      mode: json_object",
      "    context:",
      "      history_mode: short",
      "      recent_decisions_full: 8",
      "      include_task_history_summary: true",
      "      include_completed_task_summary: true",
      "      include_failed_request_history: true",
      "      include_risk_event_history: true",
      "      summarizer:",
      "        mode: none",
      "        provider: same_as_operator",
      "        fallback: rule",
      "        trigger:",
      "          every_n_decisions: 20",
      "          context_over_tokens: 12000",
      "  output:",
      "    run_root: runs/deepseek-demo",
      "    save_visual_frames: true",
      "    save_parquet: true",
      "    save_replay: true",
    ].join("\n"));

    expect(form.coordinateSystem).toBe("ENU");
    expect(form.boundary.xMin).toBe(-80);
    expect(form.physicsHz).toBe(5);
    expect(form.controllerHz).toBe(5);
    expect(form.cranes[0]).toMatchObject({ craneId: "C1", mastHeightM: 30 });
    expect(form.materialZones[0]).toMatchObject({
      zoneId: "mat_c1",
      centerX: -21.96,
      surfaceZM: 0,
      zoneRole: "ground_yard",
      hookTargetOffsetM: 0.75,
      approachClearanceM: 4,
    });
    expect(form.workZones[0]).toMatchObject({
      zoneId: "work_c1",
      acceptedLoadTypes: "rebar_bundle",
      surfaceZM: 10.8,
      floorId: "floor_03",
      buildingId: "tower_a",
      levelIndex: 3,
      zoneRole: "unloading_platform",
    });
    expect(form.forbiddenZones[0]).toMatchObject({ zoneId: "core", sizeZ: 20 });
    expect(form.timeoutS).toBe(30);
    expect(form.maxRetries).toBe(1);
    expect(form.maxConcurrentRequests).toBe(4);
    expect(form.summarizerEveryNDecisions).toBe(20);
    expect(form.saveReplay).toBe(true);
  });

  it("generates typed patches for extended visual fields", () => {
    const patches = coreFormToPatches({
      ...defaultCoreForm(),
      coordinateSystem: "ENU",
      boundary: { xMin: -1, xMax: 2, yMin: -3, yMax: 4, zMin: 0, zMax: 50 },
      cranes: [
        {
          craneId: "C1",
          modelId: "demo_flat_top_45m",
          baseX: -18,
          baseY: -18,
          baseZ: 0,
          mastHeightM: 30,
          thetaInitDeg: -135,
          slewMode: "continuous",
        },
      ],
      materialZones: [],
      workZones: [],
      forbiddenZones: [],
      maxRetries: 2,
      maxConcurrentRequests: 4,
      summarizerEveryNDecisions: 20,
    });

    expect(patches["scenario.site.boundary.x_min"]).toBe(-1);
    expect(patches["scenario.cranes"]).toEqual([
      {
        crane_id: "C1",
        model_id: "demo_flat_top_45m",
        base: [-18, -18, 0],
        mast_height_m: 30,
        theta_init_deg: -135,
        slew: { mode: "continuous" },
      },
    ]);
    expect(patches["experiment.llm.max_retries"]).toBe(2);
    expect(typeof patches["experiment.llm.max_retries"]).toBe("number");
  });

  it("writes zone vertical semantics into YAML patches", () => {
    const patches = coreFormToPatches({
      ...defaultCoreForm(),
      materialZones: [
        {
          zoneId: "ground_yard_1",
          type: "box",
          centerX: -20,
          centerY: -10,
          centerZ: 0,
          sizeX: 12,
          sizeY: 10,
          sizeZ: 0.4,
          zMin: 0,
          zMax: 0.4,
          surfaceZM: 0,
          floorId: "",
          buildingId: "",
          levelIndex: null,
          zoneRole: "ground_yard",
          hookTargetOffsetM: 0.5,
          approachClearanceM: 3,
          loadTypes: "rebar_bundle",
          acceptedLoadTypes: "",
        },
      ],
      workZones: [
        {
          zoneId: "floor_05",
          type: "box",
          centerX: 15,
          centerY: 12,
          centerZ: 18,
          sizeX: 10,
          sizeY: 8,
          sizeZ: 0.4,
          zMin: 18,
          zMax: 18.4,
          surfaceZM: 18,
          floorId: "floor_05",
          buildingId: "tower_a",
          levelIndex: 5,
          zoneRole: "floor_slab",
          hookTargetOffsetM: 0.5,
          approachClearanceM: 3,
          loadTypes: "",
          acceptedLoadTypes: "rebar_bundle",
        },
      ],
    });

    expect(patches["scenario.site.material_zones"]).toEqual([
      {
        zone_id: "ground_yard_1",
        type: "box",
        center: [-20, -10, 0],
        size: [12, 10, 0.4],
        z_range_m: [0, 0.4],
        surface_z_m: 0,
        zone_role: "ground_yard",
        hook_target_offset_m: 0.5,
        approach_clearance_m: 3,
        load_types: ["rebar_bundle"],
      },
    ]);
    expect(patches["scenario.site.work_zones"]).toEqual([
      {
        zone_id: "floor_05",
        type: "box",
        center: [15, 12, 18],
        size: [10, 8, 0.4],
        z_range_m: [18, 18.4],
        surface_z_m: 18,
        floor_id: "floor_05",
        building_id: "tower_a",
        level_index: 5,
        zone_role: "floor_slab",
        hook_target_offset_m: 0.5,
        approach_clearance_m: 3,
        accepted_load_types: ["rebar_bundle"],
      },
    ]);
  });

  it("applies core form values to YAML for live preview", () => {
    const nextYaml = applyCoreFormToYaml(yamlText, {
      ...defaultCoreForm(),
      scenarioId: "demo",
      experimentId: "exp",
      numCranes: 5,
      maxRetries: 3,
      llmProvider: "mock",
    });

    expect(nextYaml).toContain("num_cranes: 5");
    expect(nextYaml).toContain("max_retries: 3");
    expect(nextYaml).toContain("provider: mock");
    expect(yamlToCoreForm(nextYaml).numCranes).toBe(5);
  });

  it("formats pydantic integer errors with a field path", () => {
    expect(
      formatConfigError({
        message: "Input should be a valid integer, unable to parse string as an integer",
        details: {
          field_path: "experiment.llm.max_retries",
          errors: [
            {
              loc: ["experiment", "llm", "max_retries"],
              msg: "Input should be a valid integer, unable to parse string as an integer",
              input: "1.0",
            },
          ],
        },
      }),
    ).toContain("字段 experiment.llm.max_retries 需要整数");
  });

  it("formats manual crane layout distance errors with actionable details", () => {
    const message = formatConfigError({
      message: "crane bases are too close",
      details: {
        reason: "root_distance_too_small",
        field_path: "cranes",
        crane_id_a: "C1",
        crane_id_b: "C2",
        distance_m: 0,
        min_base_distance_m: 8,
      },
    });

    expect(message).toContain("塔吊基座距离太近");
    expect(message).toContain("C1 与 C2");
    expect(message).toContain("至少需要 8.00m");
  });

  it("extracts craneModelId from the first concrete crane", () => {
    const form = yamlToCoreForm(
      [
        "scenario:",
        "  cranes:",
        "    - crane_id: C1",
        "      model_id: tower_63m",
      ].join("\n"),
    );

    expect(form.craneModelId).toBe("tower_63m");
  });

  it("falls back to the first crane model when cranes are missing", () => {
    const form = yamlToCoreForm(
      [
        "scenario:",
        "  crane_models:",
        "    - model_id: flat_top_45m",
      ].join("\n"),
    );

    expect(form.craneModelId).toBe("flat_top_45m");
  });

  it("makes unsupported core form patch fields explicit", () => {
    const patches = coreFormToPatches({
      ...defaultCoreForm(),
      craneModelId: "tower_63m",
    });

    expect(patches).not.toHaveProperty("craneModelId");
    expect(Object.values(patches)).not.toContain("tower_63m");
    expect(UNSUPPORTED_CORE_PATCH_FIELDS).toContain("craneModelId");
  });

  it("extracts an experiment summary for the top bar", () => {
    expect(extractExperimentSummary(yamlText)).toEqual({
      scenarioId: "demo",
      experimentId: "exp",
      numCranes: 4,
      durationS: 7200,
      llmProvider: "deepseek",
    });
  });

  it("throws on invalid YAML when extracting a summary", () => {
    expect(() => extractExperimentSummary("scenario:\n  - broken: [")).toThrow();
  });
});
