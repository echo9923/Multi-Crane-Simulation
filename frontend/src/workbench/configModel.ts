import yaml from "js-yaml";
import type { CoreExperimentForm, ExperimentSummary } from "./types";

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

export function defaultCoreForm(): CoreExperimentForm {
  return {
    scenarioId: "desktop_demo",
    experimentId: "desktop_demo",
    seed: 20260616,
    durationS: 7200,
    dt: 0.2,
    stopWhenAllTasksDone: true,
    numCranes: 4,
    layoutMode: "manual",
    overlapLevel: "medium",
    heightStrategy: "mixed",
    craneModelId: "demo_flat_top_45m",
    tasksPerCrane: 2,
    taskGenerationMode: "manual",
    weatherMode: "constant",
    windSpeedMS: 3,
    gustSpeedMS: 5,
    windDirectionDeg: 90,
    visibility: "good",
    llmEnabled: true,
    llmProvider: "deepseek",
    llmModel: "deepseek-v4-flash",
    llmBaseUrl: "https://api.deepseek.com",
    llmApiKeyEnv: "DEEPSEEK_API_KEY",
    llmTemperature: 0.2,
    llmFallbackPolicy: "neutral_stop",
    riskPromptMode: "R1",
    safetyMode: "S1",
    runRoot: "runs/desktop",
    saveVisualFrames: true,
    saveParquet: true,
    saveReplay: true,
  };
}

export function yamlToCoreForm(text: string): CoreExperimentForm {
  const parsed = yaml.load(text);
  const form = defaultCoreForm();
  return {
    ...form,
    scenarioId: stringAt(parsed, ["scenario", "scenario_id"], form.scenarioId),
    experimentId: stringAt(parsed, ["experiment", "experiment_id"], form.experimentId),
    seed: numberAt(parsed, ["scenario", "seed"], form.seed),
    durationS: numberAt(parsed, ["experiment", "sim", "duration_s"], form.durationS),
    dt: numberAt(parsed, ["experiment", "sim", "dt"], form.dt),
    stopWhenAllTasksDone: booleanAt(
      parsed,
      ["experiment", "sim", "stop_when_all_tasks_done"],
      form.stopWhenAllTasksDone,
    ),
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
    craneModelId: firstStringAt(
      parsed,
      ["scenario", "cranes", "model_id"],
      firstStringAt(
        parsed,
        ["scenario", "crane_models", "model_id"],
        form.craneModelId,
      ),
    ),
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
    llmFallbackPolicy: stringAt(
      parsed,
      ["experiment", "llm", "fallback_policy"],
      form.llmFallbackPolicy,
    ),
    riskPromptMode: stringAt(
      parsed,
      ["experiment", "risk_prompt_mode"],
      form.riskPromptMode,
    ),
    safetyMode: stringAt(parsed, ["experiment", "safety_mode"], form.safetyMode),
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
    "scenario.layout.num_cranes": form.numCranes,
    "scenario.layout.mode": form.layoutMode,
    "scenario.layout.overlap_level": form.overlapLevel,
    "scenario.layout.height_strategy": form.heightStrategy,
    "scenario.tasks.num_tasks_per_crane": form.tasksPerCrane,
    "scenario.tasks.generation_mode": form.taskGenerationMode,
    "scenario.weather.mode": form.weatherMode,
    "scenario.weather.wind.base_speed_m_s": form.windSpeedMS,
    "scenario.weather.wind.gust_speed_m_s": form.gustSpeedMS,
    "scenario.weather.wind.direction_deg": form.windDirectionDeg,
    "scenario.weather.visibility.base_level": form.visibility,
    "experiment.experiment_id": form.experimentId,
    "experiment.sim.duration_s": form.durationS,
    "experiment.sim.dt": form.dt,
    "experiment.sim.stop_when_all_tasks_done": form.stopWhenAllTasksDone,
    "experiment.llm.enabled": form.llmEnabled,
    "experiment.llm.provider": form.llmProvider,
    "experiment.llm.model": form.llmModel,
    "experiment.llm.base_url": form.llmBaseUrl,
    "experiment.llm.api_key_env": form.llmApiKeyEnv,
    "experiment.llm.temperature": form.llmTemperature,
    "experiment.llm.fallback_policy": form.llmFallbackPolicy,
    "experiment.risk_prompt_mode": form.riskPromptMode,
    "experiment.safety_mode": form.safetyMode,
    "experiment.output.run_root": form.runRoot,
    "experiment.output.save_visual_frames": form.saveVisualFrames,
    "experiment.output.save_parquet": form.saveParquet,
    "experiment.output.save_replay": form.saveReplay,
  };
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
