import { render, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SceneView } from "@/components/SceneView";
import { useStore } from "@/state/store";
import type { SimFrame } from "@/types/sim";

const buildStaticMock = vi.fn();
const applyFrameMock = vi.fn();
const setShowRiskMock = vi.fn();
const setShowZonesMock = vi.fn();
const setShowPathsMock = vi.fn();

vi.mock("@/three/ThreeSceneController", () => ({
  ThreeSceneController: vi.fn().mockImplementation(() => ({
    buildStatic: buildStaticMock,
    applyFrame: applyFrameMock,
    resize: vi.fn(),
    pickCrane: vi.fn(),
    hasStatic: vi.fn(() => buildStaticMock.mock.calls.length > 0),
    setShowRisk: setShowRiskMock,
    setShowZones: setShowZonesMock,
    setShowPaths: setShowPathsMock,
    followCrane: vi.fn(),
    dispose: vi.fn(),
  })),
}));

class TestResizeObserver {
  observe() {}
  disconnect() {}
}

function frame(
  site?: SimFrame["site"],
  cranePatch: Partial<SimFrame["cranes"][number]> = {},
): SimFrame {
  return {
    type: "sim_frame",
    schema_version: "1.0",
    episode_id: "E-live",
    scenario_id: "scenario-live",
    frame: site ? 2 : 1,
    time_s: site ? 0.2 : 0.1,
    episode_status: "running",
    cranes: [
      {
        schema_version: "1.0",
        crane_id: "C1",
        base: [0, 0, 0],
        root: [0, 0, 40],
        tip: [50, 0, 40],
        hook: [20, 0, 10],
        theta_rad: 0,
        trolley_r_m: 20,
        hook_h_m: 10,
        load_attached: false,
        load_type: null,
        load_size_m: null,
        task_id: null,
        task_stage: "idle",
        pickup_zone_id: null,
        dropoff_zone_id: null,
        operator_profile: null,
        current_command: null,
        ...cranePatch,
      },
    ],
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
    site,
  };
}

function siteWithMaterialCenter(center: [number, number, number]): SimFrame["site"] {
  return {
    boundary: { x_min: -80, x_max: 80, y_min: -80, y_max: 80, z_min: 0, z_max: 60 },
    buildings: [
      {
        building_id: "tower_a",
        name: "Tower A",
        footprint: [[0, 0], [20, 0], [20, 20], [0, 20]],
        floors: 3,
        floor_height_m: 3.6,
        base_z_m: 0,
      },
    ],
    material_zones: [
      { zone_id: "mat_live", type: "box", center, size: [4, 4, 0.4] },
    ],
    work_zones: [],
    forbidden_zones: [],
  };
}

describe("SceneView live static scene lifecycle", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useStore.getState().reset();
    globalThis.ResizeObserver = TestResizeObserver as unknown as typeof ResizeObserver;
  });

  it("rebuilds static live geometry when a later frame adds site data", async () => {
    render(<SceneView />);
    await waitFor(() => expect(buildStaticMock).toHaveBeenCalledTimes(1));

    useStore.getState().pushRealtimeFrame(frame());
    await waitFor(() => expect(buildStaticMock).toHaveBeenCalledTimes(2));

    useStore.getState().pushRealtimeFrame(frame(siteWithMaterialCenter([10, 0, 0])));

    await waitFor(() => expect(buildStaticMock).toHaveBeenCalledTimes(3));
  });

  it("rebuilds static live geometry when site coordinates change without id or count changes", async () => {
    render(<SceneView />);
    await waitFor(() => expect(buildStaticMock).toHaveBeenCalledTimes(1));

    useStore.getState().pushRealtimeFrame(frame(siteWithMaterialCenter([10, 0, 0])));
    await waitFor(() => expect(buildStaticMock).toHaveBeenCalledTimes(2));

    useStore.getState().pushRealtimeFrame(frame(siteWithMaterialCenter([40, 15, 0])));
    await waitFor(() => expect(buildStaticMock).toHaveBeenCalledTimes(3));
  });

  it("rebuilds static live crane geometry when frame crane dimensions change", async () => {
    render(<SceneView />);
    await waitFor(() => expect(buildStaticMock).toHaveBeenCalledTimes(1));

    useStore.getState().pushRealtimeFrame(frame(siteWithMaterialCenter([10, 0, 0])));
    await waitFor(() => expect(buildStaticMock).toHaveBeenCalledTimes(2));

    useStore
      .getState()
      .pushRealtimeFrame(
        frame(siteWithMaterialCenter([10, 0, 0]), { tip: [65, 0, 40] }),
      );

    await waitFor(() => expect(buildStaticMock).toHaveBeenCalledTimes(3));
  });
});
