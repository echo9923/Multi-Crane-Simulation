export interface CoreExperimentForm {
  scenarioId: string;
  experimentId: string;
  seed: number;
  durationS: number;
  dt: number;
  stopWhenAllTasksDone: boolean;
  numCranes: number;
  layoutMode: string;
  overlapLevel: string;
  heightStrategy: string;
  craneModelId: string;
  tasksPerCrane: number;
  taskGenerationMode: string;
  weatherMode: string;
  windSpeedMS: number;
  gustSpeedMS: number;
  windDirectionDeg: number;
  visibility: string;
  llmEnabled: boolean;
  llmProvider: string;
  llmModel: string;
  llmBaseUrl: string;
  llmApiKeyEnv: string;
  llmTemperature: number;
  llmFallbackPolicy: string;
  riskPromptMode: string;
  safetyMode: string;
  runRoot: string;
  saveVisualFrames: boolean;
  saveParquet: boolean;
  saveReplay: boolean;
}

export interface ExperimentSummary {
  scenarioId: string;
  experimentId: string;
  numCranes: number;
  durationS: number;
  llmProvider: string;
}
