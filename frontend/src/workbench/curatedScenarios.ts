import type { ScenarioMetadata } from "@/workbench/types";

export const CURATED_SCENARIOS: ScenarioMetadata[] = [
  {
    scenarioId: "curated_dense_highrise_ground",
    name: "场景 1：地面塔吊服务密集高楼组",
    purpose: "验证纯地面塔吊、多楼栋、多楼层卸货的稳定链路。",
    buildingCount: 3,
    craneCount: 4,
    taskCount: 8,
    hasElevatedCrane: false,
    primaryCrossRisk: "楼间中庭和塔楼边缘存在多台地面塔吊吊臂重叠。",
  },
  {
    scenarioId: "curated_elevated_crane_transfer",
    name: "场景 2：地面塔吊 + 高位楼面塔吊协同",
    purpose: "验证裙楼屋面中转平台、高位取货面和高位塔吊任务。",
    buildingCount: 3,
    craneCount: 3,
    taskCount: 8,
    hasElevatedCrane: true,
    primaryCrossRisk: "裙楼中转平台附近同时存在地面塔吊卸货和高位塔吊取货。",
  },
  {
    scenarioId: "curated_complex_cross_lifting",
    name: "场景 3：密集高楼复杂交叉吊运",
    purpose: "验证复杂交叉吊运、共享平台、高位平台塔吊和优先级调度。",
    buildingCount: 5,
    craneCount: 5,
    taskCount: 12,
    hasElevatedCrane: true,
    primaryCrossRisk: "中庭、裙楼屋面和北塔中高层平台形成多条重叠吊运走廊。",
  },
];

export function findCuratedScenario(scenarioId: string | null | undefined) {
  return CURATED_SCENARIOS.find((scenario) => scenario.scenarioId === scenarioId) ?? null;
}

export function scenarioMetadataFallback(scenarioId: string | null | undefined) {
  return findCuratedScenario(scenarioId) ?? CURATED_SCENARIOS[0];
}
