import { describe, it, expect, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { useStore } from "@/state/store";
import { parseFramesJsonl, parseManifest, parseCommandLog } from "@/api/loader";
import type { EventRow } from "@/types/logs";
import { CraneStatusPanel } from "@/components/panels/CraneStatusPanel";
import { TaskStatusPanel } from "@/components/panels/TaskStatusPanel";
import { RiskStatusPanel } from "@/components/panels/RiskStatusPanel";
import { LLMCommandLog } from "@/components/panels/LLMCommandLog";
import { EventLog } from "@/components/panels/EventLog";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const frames = parseFramesJsonl(readFileSync(join(here, "fixtures", "frames.jsonl"), "utf8")).frames;
const manifest = parseManifest(readFileSync(join(here, "fixtures", "episode_manifest.json"), "utf8"))!;
const commands = parseCommandLog(
  readFileSync(join(here, "fixtures", "logs", "commands.jsonl"), "utf8"),
).rows;

function loadStore() {
  useStore.getState().reset();
  useStore.getState().loadEpisode(frames, manifest, null, null, commands);
}

function loadSingleFrame(frame: typeof frames[number]) {
  useStore.getState().reset();
  useStore.getState().loadEpisode([frame], manifest, null, null, commands);
}

describe("CraneStatusPanel", () => {
  beforeEach(loadStore);

  it("renders one row per crane with display-converted fields", () => {
    render(<CraneStatusPanel />);
    const panel = screen.getByTestId("crane-status");
    const rows = panel.querySelectorAll("tbody tr");
    expect(rows.length).toBe(frames[0].cranes.length);
    const c1 = frames[0].cranes.find((c) => c.crane_id === "C1")!;
    expect(panel.textContent).toContain("C1");
    expect(panel.textContent).toContain(((c1.theta_rad * 180) / Math.PI).toFixed(1));
  });

  it("selects a crane on row click", () => {
    render(<CraneStatusPanel />);
    const panel = screen.getByTestId("crane-status");
    const rows = panel.querySelectorAll("tbody tr");
    fireEvent.click(rows[1]);
    expect(useStore.getState().ui.selectedCraneId).toBe(frames[0].cranes[1].crane_id);
  });
});

describe("TaskStatusPanel", () => {
  beforeEach(loadStore);

  it("derives task rows from crane task state when frame tasks are missing", () => {
    loadSingleFrame({ ...frames[0], tasks: [] });

    render(<TaskStatusPanel />);

    const panel = screen.getByTestId("task-status");
    expect(panel.textContent).toContain("T-C1");
    expect(panel.textContent).toContain("lift_load");
    expect(panel.textContent).toContain("T-C3");
    expect(panel.textContent).toContain("move_to_dropoff");
    expect(panel.textContent).not.toContain("无任务");
    expect(panel.querySelectorAll("tbody tr").length).toBe(2);
  });

  it("expands task queue payloads from backend frames", () => {
    loadSingleFrame({
      ...frames[0],
      tasks: [
        {
          crane_id: "C1",
          active_task_id: "T_C1_001",
          tasks: [
            {
              task_id: "T_C1_001",
              crane_id: "C1",
              task_type: "easy_task",
              status: "active",
              priority: "high",
              deadline_s: 120,
            },
          ],
        },
      ],
    });

    render(<TaskStatusPanel />);

    const panel = screen.getByTestId("task-status");
    expect(panel.textContent).toContain("T_C1_001");
    expect(panel.textContent).toContain("C1");
    expect(panel.textContent).toContain("easy_task");
    expect(panel.textContent).toContain("active");
    expect(panel.textContent).toContain("high");
    expect(panel.textContent).toContain("120");
    expect(panel.querySelectorAll("tbody tr").length).toBe(1);
  });

  it("shows the empty hint only when the frame has no task rows", () => {
    loadSingleFrame({
      ...frames[0],
      tasks: [],
      cranes: frames[0].cranes.map((crane) => ({
        ...crane,
        task_id: null,
        task_stage: "idle",
        load_type: null,
        pickup_zone_id: null,
        dropoff_zone_id: null,
      })),
    });

    render(<TaskStatusPanel />);

    expect(screen.getByTestId("task-status").textContent).toContain("无任务");
  });
});

describe("RiskStatusPanel", () => {
  beforeEach(loadStore);

  it("renders a row per pair and marks data display-only", () => {
    render(<RiskStatusPanel />);
    const panel = screen.getByTestId("risk-status");
    const rows = panel.querySelectorAll("tbody tr");
    expect(rows.length).toBe(frames[0].pairs.length);
    expect(panel.textContent).toContain("display-only");
  });
});

describe("LLMCommandLog", () => {
  beforeEach(loadStore);

  it("expands a row to show all six sections", () => {
    render(<LLMCommandLog />);
    const rows = screen.getAllByTestId("cmd-row");
    expect(rows.length).toBe(commands.length);
    // before expand, sections hidden
    expect(screen.queryByText("observation")).toBeNull();
    fireEvent.click(rows[0].querySelector(".cmd-summary")!);
    for (const label of ["observation", "messages", "raw_response", "parsed_command", "executed_command", "validation_errors"]) {
      expect(screen.getByText(label)).toBeTruthy();
    }
  });

  it("flags rows that have validation errors", () => {
    render(<LLMCommandLog />);
    // The second command row (idx===1) was generated with a validation error.
    expect(screen.getByText(/validation error/)).toBeTruthy();
  });

  it("degrades to current_command when no command log is loaded", () => {
    useStore.getState().reset();
    useStore.getState().loadEpisode(frames, manifest, null, null, []);
    render(<LLMCommandLog />);
    // C1/C3 carry a current_command, C2 does not -> 2 rows.
    const rows = screen.getAllByTestId("cmd-row");
    expect(rows.length).toBe(frames[0].cranes.filter((c) => c.current_command).length);
  });

  it("masks secret-like content in rendered blobs", () => {
    useStore.getState().reset();
    useStore.getState().loadEpisode(frames, manifest, null, null, [
      {
        crane_id: "C1",
        time_s: 1,
        parsed_command: { note: "api_key=sk-1234567890abcdef please" },
      },
    ]);
    render(<LLMCommandLog />);
    const row = screen.getAllByTestId("cmd-row")[0];
    fireEvent.click(row.querySelector(".cmd-summary")!);
    expect(screen.getByText("parsed_command").nextElementSibling?.textContent).toContain("***");
    expect(screen.getByText("parsed_command").nextElementSibling?.textContent).not.toContain("sk-1234567890abcdef");
  });
});

describe("EventLog", () => {
  beforeEach(loadStore);

  it("lists events collected across frames and seeks on click", () => {
    render(<EventLog />);
    const panel = screen.getByTestId("event-log");
    const rows = panel.querySelectorAll("tbody tr");
    expect(rows.length).toBeGreaterThan(1);
    // Click the last event (a non-zero risk snapshot) and assert the timeline
    // jumps to the matching frame and selects the related crane.
    const lastRow = rows[rows.length - 1];
    fireEvent.click(lastRow);
    const allEvents = frames.flatMap((f) => f.events) as EventRow[];
    const evt = allEvents[allEvents.length - 1];
    const expectedIdx = frames.findIndex((f) => f.time_s === evt.time_s);
    expect(useStore.getState().currentIndex).toBe(Math.max(0, expectedIdx));
    expect(useStore.getState().currentIndex).toBeGreaterThan(0);
    const ids = evt.crane_ids ?? [];
    if (ids.length > 0) {
      expect(useStore.getState().ui.selectedCraneId).toBe(ids[0]);
    }
  });
});
