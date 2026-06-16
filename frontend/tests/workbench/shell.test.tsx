import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AppRoutes } from "@/App";
import { useRealtimeEpisode } from "@/hooks/useRealtimeEpisode";
import { useStore } from "@/state/store";
import { useWorkbenchStore } from "@/state/workbench";

vi.mock("@/components/SceneView", () => ({
  SceneView: () => <canvas data-testid="scene-canvas" />,
}));

vi.mock("@/hooks/useRealtimeEpisode", () => ({
  useRealtimeEpisode: vi.fn(),
}));

function renderWorkbench(initialPath = "/") {
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <AppRoutes />
    </MemoryRouter>,
  );
}

describe("workbench shell", () => {
  beforeEach(() => {
    vi.mocked(useRealtimeEpisode).mockClear();
    useStore.getState().reset();
    useWorkbenchStore.getState().resetWorkbench();
  });

  it("renders the six primary navigation links", () => {
    renderWorkbench();

    const nav = screen.getByRole("navigation", { name: "工作台导航" });
    for (const label of ["实验", "配置", "运行", "3D 可视化", "数据/导出", "设置"]) {
      expect(within(nav).getByRole("link", { name: label })).toBeTruthy();
    }
  });

  it("shows the experiment page at the root route", () => {
    renderWorkbench("/");

    expect(screen.getByRole("heading", { name: "实验" })).toBeTruthy();
  });

  it("shows the run page on the run route", () => {
    renderWorkbench("/run");

    expect(screen.getByRole("heading", { name: "运行" })).toBeTruthy();
  });

  it("embeds the existing 3D module layout on the visualization route", () => {
    renderWorkbench("/visualization");

    expect(screen.getByRole("heading", { name: "3D 可视化" })).toBeTruthy();
    expect(screen.getByTestId("scene-canvas")).toBeTruthy();
    expect(screen.getByTestId("file-input")).toBeTruthy();
    expect(document.querySelector('[data-region="left"]')).toBeTruthy();
    expect(document.querySelector('[data-region="center"]')).toBeTruthy();
    expect(document.querySelector('[data-region="right"]')).toBeTruthy();
    expect(document.querySelector('[data-region="bottom"]')).toBeTruthy();
  });

  it("keeps the legacy live route pointed at visualization with realtime episode id", () => {
    renderWorkbench("/live/E1");

    expect(screen.getByRole("heading", { name: "3D 可视化" })).toBeTruthy();
    expect(useRealtimeEpisode).toHaveBeenCalledWith("E1");
  });

  it("shows legacy visualization runtime state when no workbench episode exists", () => {
    useStore.getState().setMode("replay");
    useStore.getState().setEpisodeId("demo-episode");

    renderWorkbench("/run");

    expect(screen.getByText(/replay · demo-episode/)).toBeTruthy();
    expect(screen.queryByText(/Episode 未运行/)).toBeNull();
  });
});
