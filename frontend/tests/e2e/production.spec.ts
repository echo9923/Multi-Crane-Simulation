import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { test, expect } from "@playwright/test";

interface ProductionE2EState {
  run_dirs: string[];
  dataset_dir: string;
  stgnn_output_root: string;
  stgnn_sample_count: number;
  frontend_replay_files: {
    frames_jsonl: string;
    episode_manifest: string;
  };
}

function productionState(): ProductionE2EState {
  const statePath =
    process.env.PRODUCTION_E2E_STATE ??
    resolve(__dirname, "../../test-results/production-e2e-state.json");
  return JSON.parse(readFileSync(statePath, "utf8")) as ProductionE2EState;
}

test.describe("production runner frontend integration", () => {
  test("loads production frames.jsonl and manifest into replay panels", async ({ page }) => {
    const state = productionState();
    await page.goto("/");

    await page.getByTestId("file-input").setInputFiles([
      state.frontend_replay_files.frames_jsonl,
      state.frontend_replay_files.episode_manifest,
      resolve(state.run_dirs[0], "logs", "commands.jsonl"),
    ]);

    await expect(page.getByTestId("scene-canvas")).toBeVisible();
    await expect(page.getByTestId("crane-status")).toContainText("C1");
    await expect(page.getByTestId("crane-status")).toContainText("C2");
    await expect(page.getByTestId("llm-command-log")).toContainText(/LLM 指令日志（[1-9]/);
    await expect(page.getByTestId("timeline")).toContainText(/帧 1\/[1-9]/);
    await expect(page.getByText(/replay · full-pipeline-0000/)).toBeVisible();
  });

  test("live page receives a websocket sim_frame and renders cranes", async ({ page }) => {
    const state = productionState();
    const firstFrame = JSON.parse(
      readFileSync(state.frontend_replay_files.frames_jsonl, "utf8")
        .trim()
        .split("\n")[0],
    );

    await page.addInitScript((frame) => {
      class MockWebSocket {
        static CONNECTING = 0;
        static OPEN = 1;
        static CLOSING = 2;
        static CLOSED = 3;
        readyState = MockWebSocket.CONNECTING;
        onopen: (() => void) | null = null;
        onmessage: ((event: { data: string }) => void) | null = null;
        onclose: (() => void) | null = null;
        onerror: ((event: unknown) => void) | null = null;

        constructor(public readonly url: string) {
          setTimeout(() => {
            this.readyState = MockWebSocket.OPEN;
            this.onopen?.();
            this.onmessage?.({
              data: JSON.stringify({ type: "sim_frame", data: frame }),
            });
          }, 25);
        }

        close() {
          this.readyState = MockWebSocket.CLOSED;
          this.onclose?.();
        }

        send() {}
      }
      window.WebSocket = MockWebSocket as unknown as typeof WebSocket;
    }, firstFrame);

    await page.goto("/live/full-pipeline-0000");

    await expect(page.getByTestId("connection-badge")).toContainText("已连接");
    await expect(page.getByTestId("scene-canvas")).toBeVisible();
    await expect(page.getByTestId("crane-status")).toContainText("C1");
    await expect(page.getByTestId("crane-status")).toContainText("C2");
    await expect(page.getByTestId("crane-list")).toContainText("C1");
    await expect(page.getByText(/live · full-pipeline-0000/)).toBeVisible();
  });
});
