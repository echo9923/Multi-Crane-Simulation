export interface BoundaryForm {
  xMin: number;
  xMax: number;
  yMin: number;
  yMax: number;
  zMin: number;
  zMax: number;
}

export interface CraneFormItem {
  craneId: string;
  modelId: string;
  baseX: number;
  baseY: number;
  baseZ: number;
  mastHeightM: number;
  thetaInitDeg: number;
  slewMode: string;
}

export interface BoxZoneFormItem {
  zoneId: string;
  type: string;
  centerX: number;
  centerY: number;
  centerZ: number;
  sizeX: number;
  sizeY: number;
  sizeZ: number;
  zMin: number;
  zMax: number;
  surfaceZM: number;
  floorId: string;
  buildingId: string;
  levelIndex: number | null;
  zoneRole: string;
  hookTargetOffsetM: number;
  approachClearanceM: number;
  loadTypes: string;
  acceptedLoadTypes: string;
}

export interface CoreExperimentForm {
  scenarioId: string;
  experimentId: string;
  seed: number;
  experimentSeed: number;
  durationS: number;
  dt: number;
  minDurationS: number;
  physicsHz: number;
  controllerHz: number;
  llmDecisionIntervalS: number;
  stopWhenAllTasksDone: boolean;
  coordinateSystem: string;
  boundary: BoundaryForm;
  numCranes: number;
  layoutMode: string;
  overlapLevel: string;
  heightStrategy: string;
  coverageTarget: string;
  slewModeDefault: string;
  maxSamplingAttempts: number;
  craneModelId: string;
  cranes: CraneFormItem[];
  materialZones: BoxZoneFormItem[];
  workZones: BoxZoneFormItem[];
  forbiddenZones: BoxZoneFormItem[];
  tasksPerCrane: number;
  taskGenerationMode: string;
  queueStartMode: string;
  initialStartJitterMinS: number;
  initialStartJitterMaxS: number;
  interTaskDelayMinS: number;
  interTaskDelayMaxS: number;
  attachDelayMinS: number;
  attachDelayMaxS: number;
  releaseDelayMinS: number;
  releaseDelayMaxS: number;
  attachStageTimeoutS: number;
  releaseStageTimeoutS: number;
  taskNoProgressTimeoutS: number;
  recoveryReleaseTimeoutS: number;
  weatherMode: string;
  windSpeedMS: number;
  gustSpeedMS: number;
  windDirectionDeg: number;
  visibility: string;
  riskJibRadiusM: number;
  riskHookRadiusM: number;
  riskLoadRadiusM: number;
  riskLowThresholdM: number;
  riskMediumThresholdM: number;
  riskHighThresholdM: number;
  riskNearMissThresholdM: number;
  llmEnabled: boolean;
  llmProvider: string;
  llmModel: string;
  llmBaseUrl: string;
  llmApiKeyEnv: string;
  llmTemperature: number;
  timeoutS: number;
  maxRetries: number;
  maxConsecutiveFailures: number;
  maxConcurrentRequests: number;
  llmFallbackPolicy: string;
  structuredOutputMode: string;
  historyMode: string;
  recentDecisionsFull: number;
  includeTaskHistorySummary: boolean;
  includeCompletedTaskSummary: boolean;
  includeFailedRequestHistory: boolean;
  includeRiskEventHistory: boolean;
  summarizerMode: string;
  summarizerProvider: string;
  summarizerFallback: string;
  summarizerEveryNDecisions: number;
  summarizerContextOverTokens: number;
  riskPromptMode: string;
  safetyMode: string;
  runtimeMode: string;
  replayMode: boolean;
  llmCacheEnabled: boolean;
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
