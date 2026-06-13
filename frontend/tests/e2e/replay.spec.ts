// Smoke e2e: the app boots, auto-loads the bundled demo episode, renders the 3D
// canvas, shows the crane panels, and the timeline/playback controls respond.
// Backend is NOT required (the demo loads from bundled fixtures).

import { test, expect } from "@playwright/test";

test.describe("offline replay smoke", () => {
  test("renders the scene and panels from the demo episode", async ({ page }) => {
    await page.goto("/");

    // 3D canvas mounts.
    await expect(page.getByTestId("scene-canvas")).toBeVisible();

    // Status panels show the demo cranes (>=3).
    const cranePanel = page.getByTestId("crane-status");
    await expect(cranePanel).toContainText("C1");
    await expect(cranePanel).toContainText("C2");
    await expect(cranePanel).toContainText("C3");

    // Risk panel is display-only.
    await expect(page.getByTestId("risk-status")).toContainText("display-only");

    // Timeline is present with frame counter.
    await expect(page.getByTestId("timeline")).toBeVisible();
    await expect(page.getByTestId("timeline")).toContainText(/帧/);

    // Event log has the deterministic risk snapshots.
    await expect(page.getByTestId("event-log")).toContainText("risk_snapshot");
  });

  test("playback advances the timeline", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByTestId("crane-status")).toContainText("C1");
    const before = await page.getByTestId("timeline").textContent();
    // Press play, let it run, then pause.
    await page.getByTestId("play-pause").click();
    await page.waitForTimeout(800);
    await page.getByTestId("play-pause").click();
    const after = await page.getByTestId("timeline").textContent();
    // The frame counter or time should have advanced (playhead moved forward).
    expect(after).not.toEqual(before);
  });

  test("selecting a crane highlights it and follow toggles", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByTestId("crane-list")).toContainText("C2");
    await page.getByTestId("crane-list").getByText("C2", { exact: true }).click();
    await expect(page.getByTestId("follow-toggle")).toBeVisible();
    await page.getByTestId("follow-toggle").click();
    await expect(page.getByTestId("crane-list")).toContainText("跟随");
  });
});
