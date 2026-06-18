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

  it("marks an active episode stale only for user-authored config edits", () => {
    const store = useWorkbenchStore.getState();
    store.setYamlText(validYaml);
    store.setCurrentEpisode({
      episode_id: "E1",
      run_id: "R1",
      run_dir: "runs/E1",
      status: "running",
      resolved_config_hash: "hash",
      websocket_url: "/ws/episodes/E1",
    });

    useWorkbenchStore.getState().setYamlText(
      validYaml.replace("duration_s: 7200", "duration_s: 3600"),
      { markEpisodeStale: false },
    );

    expect(useWorkbenchStore.getState().currentEpisodeStale).toBe(false);

    useWorkbenchStore.getState().setYamlText(
      validYaml.replace("duration_s: 7200", "duration_s: 1800"),
    );

    expect(useWorkbenchStore.getState().currentEpisodeStale).toBe(true);
  });
});
