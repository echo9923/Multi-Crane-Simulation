import { describe, expect, it } from "vitest";
import {
  UNSUPPORTED_CORE_PATCH_FIELDS,
  coreFormToPatches,
  defaultCoreForm,
  extractExperimentSummary,
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
      llmProvider: "openai_compatible",
    });

    expect(patches["experiment.experiment_id"]).toBe("exp2");
    expect(patches["scenario.layout.num_cranes"]).toBe(6);
    expect(patches["experiment.sim.duration_s"]).toBe(300);
    expect(patches["experiment.llm.provider"]).toBe("openai_compatible");
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
