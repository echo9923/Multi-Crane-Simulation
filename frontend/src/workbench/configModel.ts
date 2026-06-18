import yaml from "js-yaml";
import type {
  BoundaryForm,
  BoxZoneFormItem,
  CoreExperimentForm,
  CraneFormItem,
  ExperimentSummary,
} from "./types";

export const UNSUPPORTED_CORE_PATCH_FIELDS = ["craneModelId"] as const;

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function readPath(root: unknown, path: string[]): unknown {
  let cursor: unknown = root;
  for (const part of path) {
    cursor = asRecord(cursor)[part];
  }
  return cursor;
}

function stringAt(root: unknown, path: string[], fallback: string): string {
  const value = readPath(root, path);
  return typeof value === "string" ? value : fallback;
}

function firstStringAt(root: unknown, path: string[], fallback: string): string {
  for (const value of asArray(readPath(root, path.slice(0, -1)))) {
    const candidate = asRecord(value)[path[path.length - 1]];
    if (typeof candidate === "string") return candidate;
  }
  return fallback;
}

function numberAt(root: unknown, path: string[], fallback: number): number {
  const value = readPath(root, path);
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

function booleanAt(root: unknown, path: string[], fallback: boolean): boolean {
  const value = readPath(root, path);
  return typeof value === "boolean" ? value : fallback;
}

function numberArrayAt(root: unknown, path: string[], fallback: number[]): number[] {
  const value = asArray(readPath(root, path));
  if (value.length === 0) return fallback;
  const numbers = value.map((item) => (typeof item === "number" && Number.isFinite(item) ? item : null));
  return numbers.every((item): item is number => item !== null) ? numbers : fallback;
}

function stringList(value: unknown): string {
  return asArray(value)
    .filter((item): item is string => typeof item === "string")
    .join(", ");
}

function splitStringList(value: string): string[] {
  return value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

function firstNumberAt(root: unknown, path: string[], index: number, fallback: number): number {
  return numberArrayAt(root, path, [])[index] ?? fallback;
}

function defaultBoundary(): BoundaryForm {
  return { xMin: -80, xMax: 80, yMin: -80, yMax: 80, zMin: 0, zMax: 60 };
}

export function createDefaultCrane(
  index = 0,
  opts: {
    boundary?: BoundaryForm;
    modelId?: string;
    slewMode?: string;
  } = {},
): CraneFormItem {
  const boundary = opts.boundary ?? defaultBoundary();
  const id = `C${index + 1}`;
  const spanX = Math.max(16, boundary.xMax - boundary.xMin);
  const spanY = Math.max(16, boundary.yMax - boundary.yMin);
  const insetX = Math.min(spanX * 0.25, 18);
  const insetY = Math.min(spanY * 0.25, 18);
  const positions = [
    [boundary.xMin + insetX, boundary.yMin + insetY],
    [boundary.xMax - insetX, boundary.yMin + insetY],
    [boundary.xMin + insetX, boundary.yMax - insetY],
    [boundary.xMax - insetX, boundary.yMax - insetY],
  ];
  const [baseX, baseY] = positions[index % positions.length];
  const row = Math.floor(index / positions.length);
  return {
    craneId: id,
    modelId: opts.modelId || "demo_flat_top_45m",
    baseX: baseX + row * 10,
    baseY,
    baseZ: 0,
    mastHeightM: 30 + (index % 4) * 2,
    thetaInitDeg: [-135, -45, 135, 45][index % 4],
    slewMode: opts.slewMode || "continuous",
  };
}

function defaultBoxZone(prefix: string, index = 0): BoxZoneFormItem {
  if (prefix === "mat") {
    return {
      zoneId: `ground_yard_${index + 1}`,
      type: "box",
      centerX: -20,
      centerY: -12 + index * 8,
      centerZ: 0,
      sizeX: 14,
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
    };
  }
  if (prefix === "work") {
    return {
      zoneId: index === 0 ? "floor_03" : `floor_${String(index + 3).padStart(2, "0")}`,
      type: "box",
      centerX: 18,
      centerY: 12 + index * 8,
      centerZ: 12,
      sizeX: 12,
      sizeY: 10,
      sizeZ: 0.4,
      zMin: 12,
      zMax: 12.4,
      surfaceZM: 12,
      floorId: index === 0 ? "floor_03" : `floor_${String(index + 3).padStart(2, "0")}`,
      buildingId: "tower_a",
      levelIndex: index + 3,
      zoneRole: "floor_slab",
      hookTargetOffsetM: 0.5,
      approachClearanceM: 3,
      loadTypes: "",
      acceptedLoadTypes: "rebar_bundle",
    };
  }
  return {
    zoneId: `${prefix}_${index + 1}`,
    type: "box",
    centerX: 0,
    centerY: 0,
    centerZ: 0,
    sizeX: 1,
    sizeY: 1,
    sizeZ: 1,
    zMin: 0,
    zMax: 1,
    surfaceZM: 0,
    floorId: "",
    buildingId: "",
    levelIndex: null,
    zoneRole: "",
    hookTargetOffsetM: 0.5,
    approachClearanceM: 3,
    loadTypes: "rebar_bundle",
    acceptedLoadTypes: "rebar_bundle",
  };
}

function cranesAt(root: unknown, fallback: CraneFormItem[]): CraneFormItem[] {
  const cranes = asArray(readPath(root, ["scenario", "cranes"]));
  if (cranes.length === 0) return fallback;
  return cranes.map((item, index) => {
    const crane = asRecord(item);
    const base = numberArrayAt(crane, ["base"], [0, 0, 0]);
    return {
      craneId: typeof crane.crane_id === "string" ? crane.crane_id : `C${index + 1}`,
      modelId: typeof crane.model_id === "string" ? crane.model_id : "demo_flat_top_45m",
      baseX: base[0] ?? 0,
      baseY: base[1] ?? 0,
      baseZ: base[2] ?? 0,
      mastHeightM: typeof crane.mast_height_m === "number" ? crane.mast_height_m : 30,
      thetaInitDeg: typeof crane.theta_init_deg === "number" ? crane.theta_init_deg : 0,
      slewMode: stringAt(crane, ["slew", "mode"], "continuous"),
    };
  });
}

function zonesAt(root: unknown, path: string[], prefix: string): BoxZoneFormItem[] {
  const zones = asArray(readPath(root, path));
  return zones.map((item, index) => {
    const zone = asRecord(item);
    const center = numberArrayAt(zone, ["center"], [0, 0, 0]);
    const size = numberArrayAt(zone, ["size"], [1, 1, 1]);
    const zRange = numberArrayAt(zone, ["z_range_m"], [center[2] ?? 0, center[2] ?? 0]);
    const surfaceZM = numberAt(zone, ["surface_z_m"], zRange[0] ?? center[2] ?? 0);
    const levelValue = zone.level_index;
    return {
      zoneId: typeof zone.zone_id === "string" ? zone.zone_id : `${prefix}_${index + 1}`,
      type: typeof zone.type === "string" ? zone.type : "box",
      centerX: center[0] ?? 0,
      centerY: center[1] ?? 0,
      centerZ: center[2] ?? 0,
      sizeX: size[0] ?? 1,
      sizeY: size[1] ?? 1,
      sizeZ: size[2] ?? 1,
      zMin: zRange[0] ?? 0,
      zMax: zRange[1] ?? 0,
      surfaceZM,
      floorId: typeof zone.floor_id === "string" ? zone.floor_id : "",
      buildingId: typeof zone.building_id === "string" ? zone.building_id : "",
      levelIndex: typeof levelValue === "number" && Number.isFinite(levelValue) ? levelValue : null,
      zoneRole: typeof zone.zone_role === "string" ? zone.zone_role : "",
      hookTargetOffsetM: numberAt(zone, ["hook_target_offset_m"], 0.5),
      approachClearanceM: numberAt(zone, ["approach_clearance_m"], 3),
      loadTypes: stringList(zone.load_types),
      acceptedLoadTypes: stringList(zone.accepted_load_types),
    };
  });
}

function craneToYaml(item: CraneFormItem): Record<string, unknown> {
  return {
    crane_id: item.craneId,
    model_id: item.modelId,
    base: [item.baseX, item.baseY, item.baseZ],
    mast_height_m: item.mastHeightM,
    theta_init_deg: item.thetaInitDeg,
    slew: { mode: item.slewMode },
  };
}

function zoneToYaml(item: BoxZoneFormItem, listKey: "load_types" | "accepted_load_types"): Record<string, unknown> {
  const payload: Record<string, unknown> = {
    zone_id: item.zoneId,
    type: item.type,
    center: [item.centerX, item.centerY, item.centerZ],
    size: [item.sizeX, item.sizeY, item.sizeZ],
    z_range_m: [item.zMin, item.zMax],
    surface_z_m: item.surfaceZM,
    hook_target_offset_m: item.hookTargetOffsetM,
    approach_clearance_m: item.approachClearanceM,
  };
  if (item.floorId.trim()) payload.floor_id = item.floorId.trim();
  if (item.buildingId.trim()) payload.building_id = item.buildingId.trim();
  if (item.levelIndex !== null) payload.level_index = item.levelIndex;
  if (item.zoneRole.trim()) payload.zone_role = item.zoneRole.trim();
  const values = splitStringList(listKey === "load_types" ? item.loadTypes : item.acceptedLoadTypes);
  if (values.length > 0) payload[listKey] = values;
  return payload;
}

function setPatchPath(
  root: Record<string, unknown>,
  path: string,
  value: unknown,
): void {
  const parts = path.split(".");
  let cursor = root;
  for (const [index, part] of parts.entries()) {
    if (index === parts.length - 1) {
      cursor[part] = value;
      return;
    }
    const existing = cursor[part];
    if (!existing || typeof existing !== "object" || Array.isArray(existing)) {
      const next: Record<string, unknown> = {};
      cursor[part] = next;
      cursor = next;
    } else {
      cursor = existing as Record<string, unknown>;
    }
  }
}

export function defaultCoreForm(): CoreExperimentForm {
  const boundary = defaultBoundary();
  return {
    scenarioId: "desktop_demo",
    experimentId: "desktop_demo",
    seed: 20260616,
    experimentSeed: 20260616,
    durationS: 7200,
    dt: 0.2,
    minDurationS: 0,
    physicsHz: 5,
    controllerHz: 5,
    llmDecisionIntervalS: 1,
    stopWhenAllTasksDone: true,
    coordinateSystem: "ENU",
    boundary,
    numCranes: 4,
    layoutMode: "manual",
    overlapLevel: "medium",
    heightStrategy: "mixed",
    coverageTarget: "balanced",
    slewModeDefault: "continuous",
    maxSamplingAttempts: 500,
    craneModelId: "demo_flat_top_45m",
    cranes: [
      createDefaultCrane(0, { boundary }),
      createDefaultCrane(1, { boundary }),
      createDefaultCrane(2, { boundary }),
      createDefaultCrane(3, { boundary }),
    ],
    materialZones: [defaultBoxZone("mat", 0)],
    workZones: [defaultBoxZone("work", 0)],
    forbiddenZones: [],
    tasksPerCrane: 2,
    taskGenerationMode: "manual",
    queueStartMode: "simultaneous",
    initialStartJitterMinS: 0,
    initialStartJitterMaxS: 0,
    interTaskDelayMinS: 0,
    interTaskDelayMaxS: 1,
    attachDelayMinS: 0,
    attachDelayMaxS: 0,
    releaseDelayMinS: 0,
    releaseDelayMaxS: 0,
    attachStageTimeoutS: 1200,
    releaseStageTimeoutS: 1200,
    taskNoProgressTimeoutS: 1200,
    recoveryReleaseTimeoutS: 1200,
    weatherMode: "constant",
    windSpeedMS: 3,
    gustSpeedMS: 5,
    windDirectionDeg: 90,
    visibility: "good",
    riskJibRadiusM: 0.75,
    riskHookRadiusM: 0.5,
    riskLoadRadiusM: 1,
    riskLowThresholdM: 6,
    riskMediumThresholdM: 4,
    riskHighThresholdM: 2.5,
    riskNearMissThresholdM: 1.5,
    llmEnabled: true,
    llmProvider: "deepseek",
    llmModel: "deepseek-v4-flash",
    llmBaseUrl: "https://api.deepseek.com/v1",
    llmApiKeyEnv: "DEEPSEEK_API_KEY",
    llmTemperature: 0.2,
    timeoutS: 30,
    maxRetries: 1,
    maxConsecutiveFailures: 10,
    maxConcurrentRequests: 4,
    llmFallbackPolicy: "neutral_stop",
    structuredOutputMode: "json_object",
    historyMode: "short",
    recentDecisionsFull: 8,
    includeTaskHistorySummary: true,
    includeCompletedTaskSummary: true,
    includeFailedRequestHistory: true,
    includeRiskEventHistory: true,
    summarizerMode: "none",
    summarizerProvider: "same_as_operator",
    summarizerFallback: "rule",
    summarizerEveryNDecisions: 20,
    summarizerContextOverTokens: 12000,
    riskPromptMode: "R1",
    safetyMode: "S1",
    runtimeMode: "offline_batch",
    replayMode: false,
    llmCacheEnabled: true,
    runRoot: "runs/desktop",
    saveVisualFrames: true,
    saveParquet: true,
    saveReplay: true,
  };
}

export function yamlToCoreForm(text: string): CoreExperimentForm {
  const parsed = yaml.load(text);
  const form = defaultCoreForm();
  const boundary = {
    xMin: numberAt(parsed, ["scenario", "site", "boundary", "x_min"], form.boundary.xMin),
    xMax: numberAt(parsed, ["scenario", "site", "boundary", "x_max"], form.boundary.xMax),
    yMin: numberAt(parsed, ["scenario", "site", "boundary", "y_min"], form.boundary.yMin),
    yMax: numberAt(parsed, ["scenario", "site", "boundary", "y_max"], form.boundary.yMax),
    zMin: numberAt(parsed, ["scenario", "site", "boundary", "z_min"], form.boundary.zMin),
    zMax: numberAt(parsed, ["scenario", "site", "boundary", "z_max"], form.boundary.zMax),
  };
  return {
    ...form,
    scenarioId: stringAt(parsed, ["scenario", "scenario_id"], form.scenarioId),
    experimentId: stringAt(parsed, ["experiment", "experiment_id"], form.experimentId),
    seed: numberAt(parsed, ["scenario", "seed"], form.seed),
    experimentSeed: numberAt(parsed, ["experiment", "seed"], form.experimentSeed),
    durationS: numberAt(parsed, ["experiment", "sim", "duration_s"], form.durationS),
    dt: numberAt(parsed, ["experiment", "sim", "dt"], form.dt),
    minDurationS: numberAt(parsed, ["experiment", "sim", "min_duration_s"], form.minDurationS),
    physicsHz: numberAt(parsed, ["experiment", "sim", "physics_hz"], form.physicsHz),
    controllerHz: numberAt(parsed, ["experiment", "sim", "controller_hz"], form.controllerHz),
    llmDecisionIntervalS: numberAt(parsed, ["experiment", "sim", "llm_decision_interval_s"], form.llmDecisionIntervalS),
    stopWhenAllTasksDone: booleanAt(
      parsed,
      ["experiment", "sim", "stop_when_all_tasks_done"],
      form.stopWhenAllTasksDone,
    ),
    coordinateSystem: stringAt(parsed, ["scenario", "site", "coordinate_system"], form.coordinateSystem),
    boundary,
    numCranes: numberAt(parsed, ["scenario", "layout", "num_cranes"], form.numCranes),
    layoutMode: stringAt(parsed, ["scenario", "layout", "mode"], form.layoutMode),
    overlapLevel: stringAt(
      parsed,
      ["scenario", "layout", "overlap_level"],
      form.overlapLevel,
    ),
    heightStrategy: stringAt(
      parsed,
      ["scenario", "layout", "height_strategy"],
      form.heightStrategy,
    ),
    coverageTarget: stringAt(parsed, ["scenario", "layout", "coverage_target"], form.coverageTarget),
    slewModeDefault: stringAt(parsed, ["scenario", "layout", "slew_mode_default"], form.slewModeDefault),
    maxSamplingAttempts: numberAt(
      parsed,
      ["scenario", "layout", "max_sampling_attempts"],
      form.maxSamplingAttempts,
    ),
    craneModelId: firstStringAt(
      parsed,
      ["scenario", "cranes", "model_id"],
      firstStringAt(
        parsed,
        ["scenario", "crane_models", "model_id"],
        form.craneModelId,
      ),
    ),
    cranes: cranesAt(parsed, form.cranes),
    materialZones: zonesAt(parsed, ["scenario", "site", "material_zones"], "mat"),
    workZones: zonesAt(parsed, ["scenario", "site", "work_zones"], "work"),
    forbiddenZones: zonesAt(parsed, ["scenario", "site", "forbidden_zones"], "forbidden"),
    tasksPerCrane: numberAt(
      parsed,
      ["scenario", "tasks", "num_tasks_per_crane"],
      form.tasksPerCrane,
    ),
    taskGenerationMode: stringAt(
      parsed,
      ["scenario", "tasks", "generation_mode"],
      form.taskGenerationMode,
    ),
    queueStartMode: stringAt(parsed, ["scenario", "tasks", "queue_policy", "start_mode"], form.queueStartMode),
    initialStartJitterMinS: firstNumberAt(
      parsed,
      ["scenario", "tasks", "queue_policy", "initial_start_jitter_s"],
      0,
      form.initialStartJitterMinS,
    ),
    initialStartJitterMaxS: firstNumberAt(
      parsed,
      ["scenario", "tasks", "queue_policy", "initial_start_jitter_s"],
      1,
      form.initialStartJitterMaxS,
    ),
    interTaskDelayMinS: firstNumberAt(
      parsed,
      ["scenario", "tasks", "queue_policy", "inter_task_delay_s"],
      0,
      form.interTaskDelayMinS,
    ),
    interTaskDelayMaxS: firstNumberAt(
      parsed,
      ["scenario", "tasks", "queue_policy", "inter_task_delay_s"],
      1,
      form.interTaskDelayMaxS,
    ),
    attachDelayMinS: firstNumberAt(parsed, ["scenario", "tasks", "attach_delay_s"], 0, form.attachDelayMinS),
    attachDelayMaxS: firstNumberAt(parsed, ["scenario", "tasks", "attach_delay_s"], 1, form.attachDelayMaxS),
    releaseDelayMinS: firstNumberAt(parsed, ["scenario", "tasks", "release_delay_s"], 0, form.releaseDelayMinS),
    releaseDelayMaxS: firstNumberAt(parsed, ["scenario", "tasks", "release_delay_s"], 1, form.releaseDelayMaxS),
    attachStageTimeoutS: numberAt(
      parsed,
      ["scenario", "tasks", "state_machine", "attach_stage_timeout_s"],
      form.attachStageTimeoutS,
    ),
    releaseStageTimeoutS: numberAt(
      parsed,
      ["scenario", "tasks", "state_machine", "release_stage_timeout_s"],
      form.releaseStageTimeoutS,
    ),
    taskNoProgressTimeoutS: numberAt(
      parsed,
      ["scenario", "tasks", "state_machine", "task_no_progress_timeout_s"],
      form.taskNoProgressTimeoutS,
    ),
    recoveryReleaseTimeoutS: numberAt(
      parsed,
      ["scenario", "tasks", "state_machine", "recovery_release_timeout_s"],
      form.recoveryReleaseTimeoutS,
    ),
    weatherMode: stringAt(parsed, ["scenario", "weather", "mode"], form.weatherMode),
    windSpeedMS: numberAt(
      parsed,
      ["scenario", "weather", "wind", "base_speed_m_s"],
      form.windSpeedMS,
    ),
    gustSpeedMS: numberAt(
      parsed,
      ["scenario", "weather", "wind", "gust_speed_m_s"],
      form.gustSpeedMS,
    ),
    windDirectionDeg: numberAt(
      parsed,
      ["scenario", "weather", "wind", "direction_deg"],
      form.windDirectionDeg,
    ),
    visibility: stringAt(
      parsed,
      ["scenario", "weather", "visibility", "base_level"],
      form.visibility,
    ),
    riskJibRadiusM: numberAt(
      parsed,
      ["scenario", "risk", "geometry_envelope", "jib_radius_m"],
      form.riskJibRadiusM,
    ),
    riskHookRadiusM: numberAt(
      parsed,
      ["scenario", "risk", "geometry_envelope", "hook_radius_m"],
      form.riskHookRadiusM,
    ),
    riskLoadRadiusM: numberAt(
      parsed,
      ["scenario", "risk", "geometry_envelope", "load_radius_m"],
      form.riskLoadRadiusM,
    ),
    riskLowThresholdM: numberAt(parsed, ["scenario", "risk", "thresholds_m", "low"], form.riskLowThresholdM),
    riskMediumThresholdM: numberAt(
      parsed,
      ["scenario", "risk", "thresholds_m", "medium"],
      form.riskMediumThresholdM,
    ),
    riskHighThresholdM: numberAt(parsed, ["scenario", "risk", "thresholds_m", "high"], form.riskHighThresholdM),
    riskNearMissThresholdM: numberAt(
      parsed,
      ["scenario", "risk", "thresholds_m", "near_miss"],
      form.riskNearMissThresholdM,
    ),
    llmEnabled: booleanAt(parsed, ["experiment", "llm", "enabled"], form.llmEnabled),
    llmProvider: stringAt(parsed, ["experiment", "llm", "provider"], form.llmProvider),
    llmModel: stringAt(parsed, ["experiment", "llm", "model"], form.llmModel),
    llmBaseUrl: stringAt(parsed, ["experiment", "llm", "base_url"], form.llmBaseUrl),
    llmApiKeyEnv: stringAt(
      parsed,
      ["experiment", "llm", "api_key_env"],
      form.llmApiKeyEnv,
    ),
    llmTemperature: numberAt(
      parsed,
      ["experiment", "llm", "temperature"],
      form.llmTemperature,
    ),
    timeoutS: numberAt(parsed, ["experiment", "llm", "timeout_s"], form.timeoutS),
    maxRetries: numberAt(parsed, ["experiment", "llm", "max_retries"], form.maxRetries),
    maxConsecutiveFailures: numberAt(
      parsed,
      ["experiment", "llm", "max_consecutive_failures"],
      form.maxConsecutiveFailures,
    ),
    maxConcurrentRequests: numberAt(
      parsed,
      ["experiment", "llm", "scheduling", "max_concurrent_requests"],
      form.maxConcurrentRequests,
    ),
    llmFallbackPolicy: stringAt(
      parsed,
      ["experiment", "llm", "fallback_policy"],
      form.llmFallbackPolicy,
    ),
    structuredOutputMode: stringAt(
      parsed,
      ["experiment", "llm", "structured_output", "mode"],
      form.structuredOutputMode,
    ),
    historyMode: stringAt(parsed, ["experiment", "llm", "context", "history_mode"], form.historyMode),
    recentDecisionsFull: numberAt(
      parsed,
      ["experiment", "llm", "context", "recent_decisions_full"],
      form.recentDecisionsFull,
    ),
    includeTaskHistorySummary: booleanAt(
      parsed,
      ["experiment", "llm", "context", "include_task_history_summary"],
      form.includeTaskHistorySummary,
    ),
    includeCompletedTaskSummary: booleanAt(
      parsed,
      ["experiment", "llm", "context", "include_completed_task_summary"],
      form.includeCompletedTaskSummary,
    ),
    includeFailedRequestHistory: booleanAt(
      parsed,
      ["experiment", "llm", "context", "include_failed_request_history"],
      form.includeFailedRequestHistory,
    ),
    includeRiskEventHistory: booleanAt(
      parsed,
      ["experiment", "llm", "context", "include_risk_event_history"],
      form.includeRiskEventHistory,
    ),
    summarizerMode: stringAt(
      parsed,
      ["experiment", "llm", "context", "summarizer", "mode"],
      form.summarizerMode,
    ),
    summarizerProvider: stringAt(
      parsed,
      ["experiment", "llm", "context", "summarizer", "provider"],
      form.summarizerProvider,
    ),
    summarizerFallback: stringAt(
      parsed,
      ["experiment", "llm", "context", "summarizer", "fallback"],
      form.summarizerFallback,
    ),
    summarizerEveryNDecisions: numberAt(
      parsed,
      ["experiment", "llm", "context", "summarizer", "trigger", "every_n_decisions"],
      form.summarizerEveryNDecisions,
    ),
    summarizerContextOverTokens: numberAt(
      parsed,
      ["experiment", "llm", "context", "summarizer", "trigger", "context_over_tokens"],
      form.summarizerContextOverTokens,
    ),
    riskPromptMode: stringAt(
      parsed,
      ["experiment", "risk_prompt_mode"],
      form.riskPromptMode,
    ),
    safetyMode: stringAt(parsed, ["experiment", "safety_mode"], form.safetyMode),
    runtimeMode: stringAt(parsed, ["experiment", "runtime", "mode"], form.runtimeMode),
    replayMode: booleanAt(parsed, ["experiment", "runtime", "replay_mode"], form.replayMode),
    llmCacheEnabled: booleanAt(parsed, ["experiment", "runtime", "llm_cache_enabled"], form.llmCacheEnabled),
    runRoot: stringAt(parsed, ["experiment", "output", "run_root"], form.runRoot),
    saveVisualFrames: booleanAt(
      parsed,
      ["experiment", "output", "save_visual_frames"],
      form.saveVisualFrames,
    ),
    saveParquet: booleanAt(
      parsed,
      ["experiment", "output", "save_parquet"],
      form.saveParquet,
    ),
    saveReplay: booleanAt(
      parsed,
      ["experiment", "output", "save_replay"],
      form.saveReplay,
    ),
  };
}

export function coreFormToPatches(form: CoreExperimentForm): Record<string, unknown> {
  return {
    "scenario.scenario_id": form.scenarioId,
    "scenario.seed": form.seed,
    "scenario.site.coordinate_system": form.coordinateSystem,
    "scenario.site.boundary.x_min": form.boundary.xMin,
    "scenario.site.boundary.x_max": form.boundary.xMax,
    "scenario.site.boundary.y_min": form.boundary.yMin,
    "scenario.site.boundary.y_max": form.boundary.yMax,
    "scenario.site.boundary.z_min": form.boundary.zMin,
    "scenario.site.boundary.z_max": form.boundary.zMax,
    "scenario.layout.num_cranes": form.numCranes,
    "scenario.layout.mode": form.layoutMode,
    "scenario.layout.overlap_level": form.overlapLevel,
    "scenario.layout.height_strategy": form.heightStrategy,
    "scenario.layout.coverage_target": form.coverageTarget,
    "scenario.layout.slew_mode_default": form.slewModeDefault,
    "scenario.layout.max_sampling_attempts": form.maxSamplingAttempts,
    "scenario.cranes": form.cranes.map(craneToYaml),
    "scenario.site.material_zones": form.materialZones.map((item) => zoneToYaml(item, "load_types")),
    "scenario.site.work_zones": form.workZones.map((item) => zoneToYaml(item, "accepted_load_types")),
    "scenario.site.forbidden_zones": form.forbiddenZones.map((item) => zoneToYaml(item, "load_types")),
    "scenario.tasks.num_tasks_per_crane": form.tasksPerCrane,
    "scenario.tasks.generation_mode": form.taskGenerationMode,
    "scenario.tasks.queue_policy.start_mode": form.queueStartMode,
    "scenario.tasks.queue_policy.initial_start_jitter_s": [
      form.initialStartJitterMinS,
      form.initialStartJitterMaxS,
    ],
    "scenario.tasks.queue_policy.inter_task_delay_s": [
      form.interTaskDelayMinS,
      form.interTaskDelayMaxS,
    ],
    "scenario.tasks.attach_delay_s": [form.attachDelayMinS, form.attachDelayMaxS],
    "scenario.tasks.release_delay_s": [form.releaseDelayMinS, form.releaseDelayMaxS],
    "scenario.tasks.state_machine.attach_stage_timeout_s": form.attachStageTimeoutS,
    "scenario.tasks.state_machine.release_stage_timeout_s": form.releaseStageTimeoutS,
    "scenario.tasks.state_machine.task_no_progress_timeout_s": form.taskNoProgressTimeoutS,
    "scenario.tasks.state_machine.recovery_release_timeout_s": form.recoveryReleaseTimeoutS,
    "scenario.weather.mode": form.weatherMode,
    "scenario.weather.wind.base_speed_m_s": form.windSpeedMS,
    "scenario.weather.wind.gust_speed_m_s": form.gustSpeedMS,
    "scenario.weather.wind.direction_deg": form.windDirectionDeg,
    "scenario.weather.visibility.base_level": form.visibility,
    "scenario.risk.geometry_envelope.jib_radius_m": form.riskJibRadiusM,
    "scenario.risk.geometry_envelope.hook_radius_m": form.riskHookRadiusM,
    "scenario.risk.geometry_envelope.load_radius_m": form.riskLoadRadiusM,
    "scenario.risk.thresholds_m.low": form.riskLowThresholdM,
    "scenario.risk.thresholds_m.medium": form.riskMediumThresholdM,
    "scenario.risk.thresholds_m.high": form.riskHighThresholdM,
    "scenario.risk.thresholds_m.near_miss": form.riskNearMissThresholdM,
    "experiment.experiment_id": form.experimentId,
    "experiment.seed": form.experimentSeed,
    "experiment.sim.duration_s": form.durationS,
    "experiment.sim.dt": form.dt,
    "experiment.sim.min_duration_s": form.minDurationS,
    "experiment.sim.physics_hz": form.physicsHz,
    "experiment.sim.controller_hz": form.controllerHz,
    "experiment.sim.llm_decision_interval_s": form.llmDecisionIntervalS,
    "experiment.sim.stop_when_all_tasks_done": form.stopWhenAllTasksDone,
    "experiment.runtime.mode": form.runtimeMode,
    "experiment.runtime.replay_mode": form.replayMode,
    "experiment.runtime.llm_cache_enabled": form.llmCacheEnabled,
    "experiment.llm.enabled": form.llmEnabled,
    "experiment.llm.provider": form.llmProvider,
    "experiment.llm.model": form.llmModel,
    "experiment.llm.base_url": form.llmBaseUrl,
    "experiment.llm.api_key_env": form.llmApiKeyEnv,
    "experiment.llm.temperature": form.llmTemperature,
    "experiment.llm.timeout_s": form.timeoutS,
    "experiment.llm.max_retries": form.maxRetries,
    "experiment.llm.max_consecutive_failures": form.maxConsecutiveFailures,
    "experiment.llm.scheduling.max_concurrent_requests": form.maxConcurrentRequests,
    "experiment.llm.fallback_policy": form.llmFallbackPolicy,
    "experiment.llm.structured_output.mode": form.structuredOutputMode,
    "experiment.llm.context.history_mode": form.historyMode,
    "experiment.llm.context.recent_decisions_full": form.recentDecisionsFull,
    "experiment.llm.context.include_task_history_summary": form.includeTaskHistorySummary,
    "experiment.llm.context.include_completed_task_summary": form.includeCompletedTaskSummary,
    "experiment.llm.context.include_failed_request_history": form.includeFailedRequestHistory,
    "experiment.llm.context.include_risk_event_history": form.includeRiskEventHistory,
    "experiment.llm.context.summarizer.mode": form.summarizerMode,
    "experiment.llm.context.summarizer.provider": form.summarizerProvider,
    "experiment.llm.context.summarizer.fallback": form.summarizerFallback,
    "experiment.llm.context.summarizer.trigger.every_n_decisions": form.summarizerEveryNDecisions,
    "experiment.llm.context.summarizer.trigger.context_over_tokens": form.summarizerContextOverTokens,
    "experiment.risk_prompt_mode": form.riskPromptMode,
    "experiment.safety_mode": form.safetyMode,
    "experiment.output.run_root": form.runRoot,
    "experiment.output.save_visual_frames": form.saveVisualFrames,
    "experiment.output.save_parquet": form.saveParquet,
    "experiment.output.save_replay": form.saveReplay,
  };
}

export function applyCoreFormToYaml(
  text: string,
  form: CoreExperimentForm,
  extraPatches: Record<string, unknown> = {},
): string {
  const parsed = yaml.load(text);
  const root = asRecord(parsed);
  const patches = { ...coreFormToPatches(form), ...extraPatches };
  for (const [path, value] of Object.entries(patches)) {
    setPatchPath(root, path, value);
  }
  return yaml.dump(root, {
    lineWidth: -1,
    noRefs: true,
    sortKeys: false,
  });
}

export function formatConfigError(error: unknown): string {
  const candidate = asRecord(error);
  const details = asRecord(candidate.details);
  const errors = asArray(details.errors);
  const first = asRecord(errors[0]);
  const loc = asArray(first.loc)
    .map((part) => String(part))
    .filter(Boolean);
  const fieldPath = typeof details.field_path === "string" && details.field_path
    ? details.field_path
    : loc.join(".");
  const message = typeof candidate.message === "string"
    ? candidate.message
    : error instanceof Error
      ? error.message
      : String(error);
  const input = first.input;
  const inputLine = input !== undefined ? `\n当前值: ${JSON.stringify(input)}` : "";
  const reason = typeof details.reason === "string" ? details.reason : "";
  if (reason === "root_distance_too_small") {
    const craneA = typeof details.crane_id_a === "string" ? details.crane_id_a : "一台塔吊";
    const craneB = typeof details.crane_id_b === "string" ? details.crane_id_b : "另一台塔吊";
    const distance = typeof details.distance_m === "number" ? details.distance_m.toFixed(2) : "未知";
    const minDistance = typeof details.min_base_distance_m === "number"
      ? details.min_base_distance_m.toFixed(2)
      : "规定";
    return `塔吊基座距离太近: ${craneA} 与 ${craneB} 当前距离 ${distance}m，至少需要 ${minDistance}m。\n建议: 在配置页的“塔吊列表”里调整基座 X/Y，或切换为自动布局。`;
  }
  if (reason === "manual_count_mismatch") {
    const expected = typeof details.expected === "number" ? details.expected : "配置的";
    const actual = typeof details.actual === "number" ? details.actual : "当前";
    return `塔吊数量不一致: 塔吊数量设置为 ${expected}，但塔吊列表里有 ${actual} 项。\n建议: 修改塔吊数量，或增删塔吊列表项，让两者一致。`;
  }
  if (reason === "base_out_of_boundary") {
    const craneId = typeof details.crane_id === "string" ? details.crane_id : "该塔吊";
    return `塔吊基座超出场地边界: ${craneId} 的 base 不在 site.boundary 范围内。\n建议: 调整该塔吊的基座 X/Y/Z，或扩大场地边界。`;
  }
  if (reason === "base_inside_forbidden_zone") {
    const craneId = typeof details.crane_id === "string" ? details.crane_id : "该塔吊";
    const zoneId = typeof details.zone_id === "string" ? details.zone_id : "禁入区";
    return `塔吊基座落入禁入区: ${craneId} 位于 ${zoneId} 内。\n建议: 移动塔吊基座，或调整 forbidden_zones。`;
  }
  const integerError = /valid integer|parse string as an integer/i.test(message);
  if (integerError && fieldPath) {
    return `字段 ${fieldPath} 需要整数${inputLine}\n建议: 填写不带小数点和单位的数字，例如 1`;
  }
  if (fieldPath) {
    return `字段 ${fieldPath} 校验失败: ${message}${inputLine}`;
  }
  return message;
}

export function extractExperimentSummary(text: string): ExperimentSummary {
  const form = yamlToCoreForm(text);
  return {
    scenarioId: form.scenarioId,
    experimentId: form.experimentId,
    numCranes: form.numCranes,
    durationS: form.durationS,
    llmProvider: form.llmProvider,
  };
}
