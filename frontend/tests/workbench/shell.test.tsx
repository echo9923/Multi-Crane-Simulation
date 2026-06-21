import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AppRoutes } from "@/App";
import { useRealtimeEpisode } from "@/hooks/useRealtimeEpisode";
import { useStore } from "@/state/store";
import { useWorkbenchStore } from "@/state/workbench";
import type { SimFrame } from "@/types/sim";

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
    for (const label of ["场景", "API Key", "运行", "3D 观察", "数据导出", "设置"]) {
      expect(within(nav).getByRole("link", { name: label })).toBeTruthy();
    }
  });

  it("shows the experiment page at the root route", () => {
    renderWorkbench("/");

    expect(screen.getByRole("heading", { name: "选择场景" })).toBeTruthy();
  });

  it("shows the run page on the run route", () => {
    renderWorkbench("/run");

    expect(screen.getByRole("heading", { name: "运行仿真" })).toBeTruthy();
  });

  it("embeds the existing 3D module layout on the visualization route", () => {
    renderWorkbench("/visualization");

    expect(screen.getByRole("heading", { name: "3D 观察" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "实时观察", pressed: true })).toBeTruthy();
    expect(screen.getByRole("button", { name: "离线回放", pressed: false })).toBeTruthy();
    expect(screen.getByText(/当前没有实时 Episode/)).toBeTruthy();
    expect(screen.queryByTestId("file-input")).toBeNull();
    expect(useRealtimeEpisode).toHaveBeenCalledWith(undefined);

    fireEvent.click(screen.getByRole("button", { name: "离线回放" }));

    expect(screen.getByText(/离线回放尚未加载数据/)).toBeTruthy();
    expect(screen.getByTestId("scene-canvas")).toBeTruthy();
    expect(screen.getByTestId("file-input")).toBeTruthy();
    expect(document.querySelector('[data-region="left"]')).toBeTruthy();
    expect(document.querySelector('[data-region="center"]')).toBeTruthy();
    expect(document.querySelector('[data-region="right"]')).toBeTruthy();
    expect(document.querySelector('[data-region="bottom"]')).toBeTruthy();
  });

  it("clears stale realtime frames when switching to offline replay mode", () => {
    useStore.getState().startLiveEpisode("E-live");
    useStore.getState().setConnection({ status: "open" });
    useStore.getState().pushRealtimeFrame({
      type: "sim_frame",
      schema_version: "1.0",
      episode_id: "E-live",
      scenario_id: "curated",
      frame: 7,
      time_s: 3.5,
      episode_status: "running",
      cranes: [],
      pairs: [],
      tasks: [],
      weather: {
        schema_version: "1.0",
        wind_speed_m_s: 0,
        wind_gust_m_s: null,
        wind_direction_deg: null,
        visibility: "good",
        rain_level: null,
        fog_level: null,
      },
      events: [],
      offline_labels: null,
    } as SimFrame);

    renderWorkbench("/visualization");

    expect(screen.getByText(/3.5s \/ 3.5s/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "离线回放" }));

    expect(useStore.getState().mode).toBe("replay");
    expect(useStore.getState().episodeId).toBeNull();
    expect(useStore.getState().latestFrame).toBeNull();
    expect(useStore.getState().frames).toHaveLength(0);
    expect(screen.getByText(/离线回放尚未加载数据/)).toBeTruthy();
  });

  it("keeps the legacy live route pointed at visualization with realtime episode id", () => {
    renderWorkbench("/live/E1");

    expect(screen.getByRole("heading", { name: "3D 观察" })).toBeTruthy();
    expect(screen.getByText(/实时 Episode：E1/)).toBeTruthy();
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
