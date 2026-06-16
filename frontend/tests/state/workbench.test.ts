import { beforeEach, describe, expect, it } from "vitest";
import { useWorkbenchStore } from "@/state/workbench";

const validYaml = [
  "scenario:",
  "  scenario_id: demo",
  "  layout:",
  "    num_cranes: 4",
  "experiment:",
  "  experiment_id: exp",
  "  sim:",
  "    duration_s: 7200",
  "  llm:",
  "    provider: deepseek",
].join("\n");

describe("workbench store", () => {
  beforeEach(() => {
    useWorkbenchStore.getState().resetWorkbench();
  });

  it("clears the summary when YAML parsing fails", () => {
    useWorkbenchStore.getState().setYamlText(validYaml);
    expect(useWorkbenchStore.getState().summary).toEqual({
      scenarioId: "demo",
      experimentId: "exp",
      numCranes: 4,
      durationS: 7200,
      llmProvider: "deepseek",
    });

    useWorkbenchStore.getState().setYamlText("scenario:\n  - broken: [");

    expect(useWorkbenchStore.getState().summary).toBeNull();
  });
});
