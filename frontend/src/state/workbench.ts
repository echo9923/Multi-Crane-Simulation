import { create } from "zustand";
import type {
  ScenarioValidateResult,
  DesktopTemplate,
  DesktopLLMProviderSummary,
  EpisodeStartResponse,
  EpisodeStateResponse,
} from "@/types/api";
import type { CoreExperimentForm, ExperimentSummary } from "@/workbench/types";
import { defaultCoreForm, extractExperimentSummary } from "@/workbench/configModel";

export interface WorkbenchState {
  templates: DesktopTemplate[];
  selectedTemplateId: string | null;
  yamlText: string;
  form: CoreExperimentForm;
  summary: ExperimentSummary | null;
  validation: ScenarioValidateResult | null;
  validationError: string | null;
  currentEpisode: EpisodeStartResponse | null;
  episodeState: EpisodeStateResponse | null;
  configRevision: number;
  currentEpisodeConfigRevision: number | null;
  currentEpisodeStale: boolean;
  providerSummaries: DesktopLLMProviderSummary[];
  busy: boolean;
  setTemplates(items: DesktopTemplate[]): void;
  setTemplate(id: string | null): void;
  setYamlText(text: string, opts?: { markEpisodeStale?: boolean }): void;
  setFormPatch(patch: Partial<CoreExperimentForm>): void;
  setValidation(result: ScenarioValidateResult | null, error?: string | null): void;
  setCurrentEpisode(result: EpisodeStartResponse | null): void;
  setEpisodeState(result: EpisodeStateResponse | null): void;
  setProviderSummaries(items: DesktopLLMProviderSummary[]): void;
  clearCurrentEpisode(): void;
  setBusy(busy: boolean): void;
  resetWorkbench(): void;
}

const initialForm = defaultCoreForm();

export const useWorkbenchStore = create<WorkbenchState>((set) => ({
  templates: [],
  selectedTemplateId: null,
  yamlText: "",
  form: initialForm,
  summary: null,
  validation: null,
  validationError: null,
  currentEpisode: null,
  episodeState: null,
  configRevision: 0,
  currentEpisodeConfigRevision: null,
  currentEpisodeStale: false,
  providerSummaries: [],
  busy: false,
  setTemplates: (items) => set({ templates: items }),
  setTemplate: (id) => set({ selectedTemplateId: id }),
  setYamlText: (text, opts = {}) => {
    let summary: ExperimentSummary | null = null;
    try {
      summary = extractExperimentSummary(text);
    } catch {
      summary = null;
    }
    set((state) => {
      const configRevision = state.configRevision + 1;
      const markEpisodeStale = opts.markEpisodeStale ?? true;
      return {
        yamlText: text,
        summary,
        configRevision,
        currentEpisodeStale: state.currentEpisode !== null && markEpisodeStale,
      };
    });
  },
  setFormPatch: (patch) => set((state) => ({ form: { ...state.form, ...patch } })),
  setValidation: (result, error = null) =>
    set({ validation: result, validationError: error }),
  setCurrentEpisode: (result) =>
    set((state) => ({
      currentEpisode: result,
      currentEpisodeConfigRevision: result ? state.configRevision : null,
      currentEpisodeStale: false,
    })),
  setEpisodeState: (result) => set({ episodeState: result }),
  setProviderSummaries: (items) => set({ providerSummaries: items }),
  clearCurrentEpisode: () =>
    set({
      currentEpisode: null,
      episodeState: null,
      currentEpisodeConfigRevision: null,
      currentEpisodeStale: false,
    }),
  setBusy: (busy) => set({ busy }),
  resetWorkbench: () =>
    set({
      templates: [],
      selectedTemplateId: null,
      yamlText: "",
      form: defaultCoreForm(),
      summary: null,
      validation: null,
      validationError: null,
      currentEpisode: null,
      episodeState: null,
      configRevision: 0,
      currentEpisodeConfigRevision: null,
      currentEpisodeStale: false,
      providerSummaries: [],
      busy: false,
    }),
}));
