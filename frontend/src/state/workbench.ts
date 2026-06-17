import { create } from "zustand";
import type {
  ScenarioValidateResult,
  DesktopTemplate,
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
  busy: boolean;
  setTemplates(items: DesktopTemplate[]): void;
  setTemplate(id: string | null): void;
  setYamlText(text: string): void;
  setFormPatch(patch: Partial<CoreExperimentForm>): void;
  setValidation(result: ScenarioValidateResult | null, error?: string | null): void;
  setCurrentEpisode(result: EpisodeStartResponse | null): void;
  setEpisodeState(result: EpisodeStateResponse | null): void;
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
  busy: false,
  setTemplates: (items) => set({ templates: items }),
  setTemplate: (id) => set({ selectedTemplateId: id }),
  setYamlText: (text) => {
    let summary: ExperimentSummary | null = null;
    try {
      summary = extractExperimentSummary(text);
    } catch {
      summary = null;
    }
    set((state) => {
      const configRevision = state.configRevision + 1;
      return {
        yamlText: text,
        summary,
        configRevision,
        currentEpisodeStale: state.currentEpisode !== null,
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
      busy: false,
    }),
}));
