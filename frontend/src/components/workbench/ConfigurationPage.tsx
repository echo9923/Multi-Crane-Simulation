import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";

import {
  getLatestDesktopDraft,
  listDesktopTemplates,
  patchDesktopConfig,
  renderDesktopConfig,
  saveDesktopDraft,
  saveDesktopLLMProviderSecret,
  testDesktopLLMProvider,
  validateScenario,
} from "@/api/rest";
import { buildValidateRequest } from "@/api/config";
import { useWorkbenchStore } from "@/state/workbench";
import {
  applyCoreFormToYaml,
  coreFormToPatches,
  createDefaultCrane,
  formatConfigError,
  yamlToCoreForm,
} from "@/workbench/configModel";
import type {
  BoundaryForm,
  BoxZoneFormItem,
  CoreExperimentForm,
  CraneFormItem,
} from "@/workbench/types";

type NumericCoreField = {
  [K in keyof CoreExperimentForm]: CoreExperimentForm[K] extends number ? K : never;
}[keyof CoreExperimentForm];

type StringCoreField = {
  [K in keyof CoreExperimentForm]: CoreExperimentForm[K] extends string ? K : never;
}[keyof CoreExperimentForm];

type BooleanCoreField = {
  [K in keyof CoreExperimentForm]: CoreExperimentForm[K] extends boolean ? K : never;
}[keyof CoreExperimentForm];

type ZoneListKey = "materialZones" | "workZones" | "forbiddenZones";

const LLM_PROVIDER_OPTIONS = ["deepseek", "minimax", "siliconflow", "mock", "replay"];
const LLM_PROVIDER_DEFAULTS: Record<string, Partial<CoreExperimentForm>> = {
  deepseek: {
    llmModel: "deepseek-chat",
    llmBaseUrl: "https://api.deepseek.com/v1",
    llmApiKeyEnv: "DEEPSEEK_API_KEY",
  },
  minimax: {
    llmModel: "abab6.5s-chat",
    llmBaseUrl: "https://api.minimax.chat/v1",
    llmApiKeyEnv: "MINIMAX_API_KEY",
  },
  siliconflow: {
    llmModel: "deepseek-ai/DeepSeek-V4-Flash",
    llmBaseUrl: "https://api.siliconflow.cn/v1",
    llmApiKeyEnv: "SILICONFLOW_API_KEY",
  },
};
const COORDINATE_OPTIONS = ["ENU", "NED"];
const LAYOUT_OPTIONS = ["manual", "auto"];
const OVERLAP_OPTIONS = ["low", "medium", "high"];
const HEIGHT_OPTIONS = ["mixed", "staggered", "same_level"];
const COVERAGE_OPTIONS = ["balanced", "wide_coverage", "dense_overlap"];
const SLEW_OPTIONS = ["continuous", "limited"];
const TASK_GENERATION_OPTIONS = ["manual", "auto"];
const QUEUE_START_OPTIONS = ["simultaneous", "staggered", "scheduled"];
const WEATHER_OPTIONS = ["constant", "schedule", "random"];
const VISIBILITY_OPTIONS = ["good", "medium", "poor"];
const RISK_PROMPT_OPTIONS = ["R0", "R1"];
const SAFETY_OPTIONS = ["S0", "S1", "S2", "S3"];
const RUNTIME_OPTIONS = ["offline_batch", "offline_replay", "interactive_server"];
const STRUCTURED_OUTPUT_OPTIONS = ["json_object", "json_schema"];
const HISTORY_OPTIONS = ["none", "short", "long"];
const SUMMARIZER_OPTIONS = ["none", "rule", "llm"];
const SUMMARIZER_PROVIDER_OPTIONS = ["same_as_operator", "explicit"];
const FALLBACK_POLICY_OPTIONS = ["neutral_stop"];
const ZONE_ROLE_OPTIONS = [
  "",
  "ground_yard",
  "truck_bed",
  "floor_slab",
  "roof",
  "podium",
  "temporary_platform",
  "unloading_platform",
  "recovery",
];
const REAL_LLM_PROVIDERS = new Set(["deepseek", "minimax", "siliconflow"]);
const AUTOSAVE_DELAY_MS = 800;

function parseNumber(
  value: string,
  opts: { integer?: boolean; min?: number; max?: number } = {},
): number | null {
  if (value.trim() === "") return null;
  const next = Number(value);
  if (!Number.isFinite(next)) return null;
  if (opts.integer && !Number.isInteger(next)) return null;
  if (opts.min !== undefined && next < opts.min) return null;
  if (opts.max !== undefined && next > opts.max) return null;
  return next;
}

function valueOption(value: string) {
  return (
    <option value={value} key={value}>
      {value}
    </option>
  );
}

function Field(props: {
  id: string;
  label: string;
  help: string;
  children: ReactNode;
}) {
  return (
    <div className="workbench-field">
      <div className="workbench-field-heading">
        <label htmlFor={props.id}>{props.label}</label>
        <span className="workbench-field-tooltip" title={props.help}>
          ?
        </span>
      </div>
      {props.children}
      <p className="workbench-help">{props.help}</p>
    </div>
  );
}

function ToggleField(props: {
  label: string;
  help: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
}) {
  return (
    <div className="workbench-field">
      <label className="workbench-toggle-field">
        <input
          type="checkbox"
          checked={props.checked}
          onChange={(event) => props.onChange(event.target.checked)}
        />
        <span>{props.label}</span>
      </label>
      <p className="workbench-help">{props.help}</p>
    </div>
  );
}

function makeCrane(index: number, form: CoreExperimentForm): CraneFormItem {
  return createDefaultCrane(index, {
    boundary: form.boundary,
    modelId: form.craneModelId,
    slewMode: form.slewModeDefault,
  });
}

function makeZone(prefix: string, index: number): BoxZoneFormItem {
  if (prefix === "mat") {
    return {
      zoneId: `ground_yard_${index + 1}`,
      type: "box",
      centerX: -20,
      centerY: -12 + index * 8,
      centerZ: 0,
      sizeX: 14,
      sizeY: 10,
      sizeZ: 0.4,
      zMin: 0,
      zMax: 0.4,
      surfaceZM: 0,
      floorId: "",
      buildingId: "",
      levelIndex: null,
      zoneRole: "ground_yard",
      hookTargetOffsetM: 0.5,
      approachClearanceM: 3,
      loadTypes: "rebar_bundle",
      acceptedLoadTypes: "",
    };
  }
  if (prefix === "work") {
    const level = index + 3;
    const surface = level * 3.6;
    const floorId = `floor_${String(level).padStart(2, "0")}`;
    return {
      zoneId: floorId,
      type: "box",
      centerX: 18,
      centerY: 12 + index * 8,
      centerZ: surface,
      sizeX: 12,
      sizeY: 10,
      sizeZ: 0.4,
      zMin: surface,
      zMax: surface + 0.4,
      surfaceZM: surface,
      floorId,
      buildingId: "tower_a",
      levelIndex: level,
      zoneRole: "floor_slab",
      hookTargetOffsetM: 0.5,
      approachClearanceM: 3,
      loadTypes: "",
      acceptedLoadTypes: "rebar_bundle",
    };
  }
  return {
    zoneId: `${prefix}_${index + 1}`,
    type: "box",
    centerX: 0,
    centerY: 0,
    centerZ: 0,
    sizeX: 1,
    sizeY: 1,
    sizeZ: 1,
    zMin: 0,
    zMax: 1,
    surfaceZM: 0,
    floorId: "",
    buildingId: "",
    levelIndex: null,
    zoneRole: "",
    hookTargetOffsetM: 0.5,
    approachClearanceM: 3,
    loadTypes: "rebar_bundle",
    acceptedLoadTypes: "rebar_bundle",
  };
}

function resizeCranes(
  cranes: CraneFormItem[],
  count: number,
  form: CoreExperimentForm,
): CraneFormItem[] {
  if (count <= cranes.length) return cranes.slice(0, count);
  const next = [...cranes];
  while (next.length < count) {
    next.push(makeCrane(next.length, form));
  }
  return next;
}

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function safeDraftId(value: string): string {
  const cleaned = value.trim().replace(/[^A-Za-z0-9_.-]/g, "_");
  return cleaned || "desktop_autosave";
}

export function ConfigurationPage() {
  const [advancedYamlEnabled, setAdvancedYamlEnabled] = useState(false);
  const [localApiKey, setLocalApiKey] = useState("");
  const [llmSecretBusy, setLlmSecretBusy] = useState(false);
  const [llmSecretStatus, setLlmSecretStatus] = useState(
    "真实 API Key 只保存到本机设置，不写入 YAML。",
  );
  const [draftStatus, setDraftStatus] = useState("正在检查本机草稿。");
  const [draftReady, setDraftReady] = useState(false);
  const skipNextAutosaveRef = useRef(true);
  const savingDraftRef = useRef(false);

  const templates = useWorkbenchStore((s) => s.templates);
  const selectedTemplateId = useWorkbenchStore((s) => s.selectedTemplateId);
  const yamlText = useWorkbenchStore((s) => s.yamlText);
  const form = useWorkbenchStore((s) => s.form);
  const validation = useWorkbenchStore((s) => s.validation);
  const validationError = useWorkbenchStore((s) => s.validationError);
  const busy = useWorkbenchStore((s) => s.busy);
  const setTemplates = useWorkbenchStore((s) => s.setTemplates);
  const setTemplate = useWorkbenchStore((s) => s.setTemplate);
  const setYamlText = useWorkbenchStore((s) => s.setYamlText);
  const setFormPatch = useWorkbenchStore((s) => s.setFormPatch);
  const setValidation = useWorkbenchStore((s) => s.setValidation);
  const setBusy = useWorkbenchStore((s) => s.setBusy);

  const applyYamlToWorkbench = (
    text: string,
    opts: { markEpisodeStale?: boolean } = {},
  ) => {
    setYamlText(text, opts);
    setFormPatch(yamlToCoreForm(text));
  };

  const saveDraft = async (
    text = useWorkbenchStore.getState().yamlText,
    opts: { automatic?: boolean } = {},
  ) => {
    if (!text.trim() || savingDraftRef.current) return;
    savingDraftRef.current = true;
    setDraftStatus(opts.automatic ? "保存中。" : "正在保存草稿。");
    try {
      const state = useWorkbenchStore.getState();
      const draftForm = state.form;
      await saveDesktopDraft(
        safeDraftId(draftForm.experimentId),
        text,
        {
          template_id: state.selectedTemplateId,
          last_validation_hash: state.validation?.resolved_config_hash ?? null,
          autosaved: Boolean(opts.automatic),
        },
      );
      setDraftStatus(opts.automatic ? "已自动保存。" : "草稿已保存。");
    } catch (error) {
      setDraftStatus(`保存失败：${errorText(error)}`);
    } finally {
      savingDraftRef.current = false;
    }
  };

  const updateForm = (patch: Partial<CoreExperimentForm>) => {
    const nextForm = { ...form, ...patch };
    setFormPatch(patch);
    if (!yamlText) return;
    try {
      setYamlText(applyCoreFormToYaml(yamlText, nextForm));
      setValidation(null);
    } catch (error) {
      setValidation(null, `YAML 预览更新失败: ${formatConfigError(error)}`);
    }
  };

  const updateFormAndYaml = (
    patch: Partial<CoreExperimentForm>,
    extraPatches: Record<string, unknown>,
  ) => {
    const nextForm = { ...form, ...patch };
    setFormPatch(patch);
    if (!yamlText) return;
    try {
      setYamlText(applyCoreFormToYaml(yamlText, nextForm, extraPatches));
      setValidation(null);
    } catch (error) {
      setValidation(null, `YAML 棰勮鏇存柊澶辫触: ${formatConfigError(error)}`);
    }
  };

  const handleAdvancedYamlChange = (text: string) => {
    setYamlText(text);
    try {
      setFormPatch(yamlToCoreForm(text));
      setValidation(null);
    } catch (error) {
      setValidation(null, `YAML 解析失败: ${formatConfigError(error)}`);
    }
  };

  useEffect(() => {
    let cancelled = false;
    const restoreLatestDraft = async () => {
      try {
        const latest = await getLatestDesktopDraft();
        if (cancelled) return;
        if (latest.yaml_text) {
          skipNextAutosaveRef.current = true;
          applyYamlToWorkbench(latest.yaml_text, { markEpisodeStale: false });
          setDraftStatus(
            latest.updated_at ? `已恢复上次草稿：${latest.updated_at}` : "已恢复上次草稿。",
          );
        } else {
          setDraftStatus("暂无本机草稿。");
        }
      } catch (error) {
        if (!cancelled) {
          setDraftStatus(`草稿恢复失败：${errorText(error)}`);
        }
      } finally {
        if (!cancelled) setDraftReady(true);
      }
    };
    void restoreLatestDraft();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!draftReady || !yamlText.trim()) return;
    if (skipNextAutosaveRef.current) {
      skipNextAutosaveRef.current = false;
      return;
    }
    const timer = window.setTimeout(() => {
      void saveDraft(yamlText, { automatic: true });
    }, AUTOSAVE_DELAY_MS);
    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [draftReady, yamlText]);

  const loadTemplate = async () => {
    setBusy(true);
    setValidation(null);
    try {
      const result = await listDesktopTemplates();
      setTemplates(result.items);
      const first = result.items[0];
      if (!first) {
        setTemplate(null);
        throw new Error("没有可用模板");
      }
      setTemplate(first.template_id);
      const rendered = await renderDesktopConfig(
        first.template_id,
        {},
      );
      applyYamlToWorkbench(rendered.yaml_text);
      setDraftStatus("模板已加载，后续修改会自动保存。");
    } catch (error) {
      setValidation(null, formatConfigError(error));
    } finally {
      setBusy(false);
    }
  };

  const syncYaml = async () => {
    setBusy(true);
    setValidation(null);
    try {
      const patched = await patchDesktopConfig(yamlText, coreFormToPatches(form));
      applyYamlToWorkbench(patched.yaml_text);
    } catch (error) {
      setValidation(null, formatConfigError(error));
    } finally {
      setBusy(false);
    }
  };

  const validateYaml = async () => {
    setBusy(true);
    try {
      const result = await validateScenario(buildValidateRequest(yamlText));
      setValidation(result);
    } catch (error) {
      setValidation(null, formatConfigError(error));
    } finally {
      setBusy(false);
    }
  };

  const setTextField = (field: StringCoreField, value: string) => {
    updateForm({ [field]: value } as Partial<CoreExperimentForm>);
  };

  const setLLMProvider = (value: string) => {
    updateForm({
      llmProvider: value,
      ...(LLM_PROVIDER_DEFAULTS[value] ?? {}),
    });
    setLocalApiKey("");
    setLlmSecretStatus(
      REAL_LLM_PROVIDERS.has(value)
        ? "真实 API Key 只保存到本机设置，不写入 YAML。"
        : "mock/replay 不需要 API Key。",
    );
  };

  const saveLocalApiKey = async () => {
    if (!REAL_LLM_PROVIDERS.has(form.llmProvider)) {
      setLlmSecretStatus("当前 provider 不需要 API Key。");
      return;
    }
    if (!localApiKey.trim()) {
      setLlmSecretStatus("请输入 API Key 后再保存。");
      return;
    }
    setLlmSecretBusy(true);
    try {
      const result = await saveDesktopLLMProviderSecret(form.llmProvider, {
        api_key: localApiKey,
        base_url: form.llmBaseUrl || null,
        model: form.llmModel || null,
      });
      setLocalApiKey("");
      setLlmSecretStatus(`已保存到本机设置：${result.key_masked ?? "已脱敏"}`);
      await saveDraft(useWorkbenchStore.getState().yamlText, { automatic: true });
    } catch (error) {
      setLlmSecretStatus(`保存失败：${errorText(error)}`);
    } finally {
      setLlmSecretBusy(false);
    }
  };

  const testLocalApiKey = async () => {
    if (!REAL_LLM_PROVIDERS.has(form.llmProvider)) {
      setLlmSecretStatus("当前 provider 不需要真实连通性测试。");
      return;
    }
    setLlmSecretBusy(true);
    try {
      const result = await testDesktopLLMProvider(form.llmProvider, {
        api_key: localApiKey || null,
        base_url: form.llmBaseUrl || null,
        model: form.llmModel || null,
      });
      const models = result.sample_models?.length
        ? `，模型示例：${result.sample_models.join(", ")}`
        : "";
      const httpStatus = result.status_code !== null ? `，HTTP ${result.status_code}` : "";
      setLlmSecretStatus(
        `${result.ok ? "连通性测试成功" : "连通性测试失败"}：${
          result.message ?? "无返回消息"
        }${httpStatus}，${result.latency_ms.toFixed(0)} ms${models}`,
      );
    } catch (error) {
      setLlmSecretStatus(`测试失败：${errorText(error)}`);
    } finally {
      setLlmSecretBusy(false);
    }
  };

  const setNumberField = (
    field: NumericCoreField,
    value: string,
    opts: { integer?: boolean; min?: number; max?: number } = {},
  ) => {
    const next = parseNumber(value, opts);
    if (next === null) return;
    updateForm({ [field]: next } as Partial<CoreExperimentForm>);
  };

  const setBooleanField = (field: BooleanCoreField, value: boolean) => {
    updateForm({ [field]: value } as Partial<CoreExperimentForm>);
  };

  const setBoundaryNumber = (
    field: keyof BoundaryForm,
    value: string,
    opts: { min?: number; max?: number } = {},
  ) => {
    const next = parseNumber(value, opts);
    if (next === null) return;
    updateForm({ boundary: { ...form.boundary, [field]: next } });
  };

  const setCraneCount = (value: string) => {
    const next = parseNumber(value, { integer: true, min: 1 });
    if (next === null) return;
    updateForm({
      numCranes: next,
      cranes: resizeCranes(form.cranes, next, form),
    });
  };

  const updateCrane = (index: number, patch: Partial<CraneFormItem>) => {
    updateForm({
      cranes: form.cranes.map((item, itemIndex) =>
        itemIndex === index ? { ...item, ...patch } : item,
      ),
    });
  };

  const updateCraneNumber = (
    index: number,
    field: keyof Pick<
      CraneFormItem,
      "baseX" | "baseY" | "baseZ" | "mastHeightM" | "thetaInitDeg"
    >,
    value: string,
    opts: { min?: number; max?: number } = {},
  ) => {
    const next = parseNumber(value, opts);
    if (next === null) return;
    updateCrane(index, { [field]: next });
  };

  const addCrane = () => {
    const cranes = [...form.cranes, makeCrane(form.cranes.length, form)];
    updateForm({ cranes, numCranes: cranes.length });
  };

  const removeCrane = (index: number) => {
    const cranes = form.cranes.filter((_, itemIndex) => itemIndex !== index);
    const nextCranes = cranes.length > 0 ? cranes : [makeCrane(0, form)];
    updateForm({ cranes: nextCranes, numCranes: nextCranes.length });
  };

  const updateZone = (
    listKey: ZoneListKey,
    index: number,
    patch: Partial<BoxZoneFormItem>,
  ) => {
    updateForm({
      [listKey]: form[listKey].map((item, itemIndex) =>
        itemIndex === index ? { ...item, ...patch } : item,
      ),
    } as Partial<CoreExperimentForm>);
  };

  const updateZoneNumber = (
    listKey: ZoneListKey,
    index: number,
    field: keyof Pick<
      BoxZoneFormItem,
      | "centerX"
      | "centerY"
      | "centerZ"
      | "sizeX"
      | "sizeY"
      | "sizeZ"
      | "zMin"
      | "zMax"
      | "surfaceZM"
      | "hookTargetOffsetM"
      | "approachClearanceM"
    >,
    value: string,
    opts: { min?: number; max?: number } = {},
  ) => {
    const next = parseNumber(value, opts);
    if (next === null) return;
    updateZone(listKey, index, { [field]: next });
  };

  const updateZoneLevelIndex = (
    listKey: ZoneListKey,
    index: number,
    value: string,
  ) => {
    if (value.trim() === "") {
      updateZone(listKey, index, { levelIndex: null });
      return;
    }
    const next = parseNumber(value, { integer: true, min: 0 });
    if (next === null) return;
    updateZone(listKey, index, { levelIndex: next });
  };

  const addZone = (listKey: ZoneListKey, prefix: string) => {
    updateForm({
      [listKey]: [...form[listKey], makeZone(prefix, form[listKey].length)],
    } as Partial<CoreExperimentForm>);
  };

  const removeZone = (listKey: ZoneListKey, index: number) => {
    updateForm({
      [listKey]: form[listKey].filter((_, itemIndex) => itemIndex !== index),
    } as Partial<CoreExperimentForm>);
  };

  const applyMultifloorPreset = () => {
    const craneModelId = "demo_flat_top_75m";
    const craneModels = [
      {
        model_id: craneModelId,
        jib_length_m: 75,
        counter_jib_length_m: 12,
        mast_height_range_m: [40, 50],
        max_load_t: 6,
        max_load_radius_m: 15,
        tip_load_t: 1.5,
        rated_moment_t_m: 110,
        slew_speed_max_deg_s: 2,
        slew_acc_max_deg_s2: 0.8,
        trolley_r_min_m: 5,
        trolley_r_max_m: 72,
        trolley_speed_max_m_s: 0.9,
        trolley_acc_max_m_s2: 0.7,
        cable_length_min_m: 2,
        cable_length_max_m: 60,
        hoist_speed_max_m_s: 1.2,
        hoist_acc_max_m_s2: 0.8,
        min_clearance_below_jib_m: 2,
      },
    ];
    const cranePositions = [
      [-24, -24],
      [24, -24],
      [-24, 30],
      [24, 30],
    ] as const;
    const craneMastHeights = [40, 44, 46, 48];
    const cranes = cranePositions.map(([baseX, baseY], index) => {
      return {
        craneId: `C${index + 1}`,
        modelId: craneModelId,
        baseX,
        baseY,
        baseZ: 0,
        mastHeightM: craneMastHeights[index],
        thetaInitDeg: [-135, -45, 135, 45][index],
        slewMode: "continuous",
      };
    });
    const materialZones: BoxZoneFormItem[] = [
      {
        ...makeZone("mat", 0),
        zoneId: "ground_yard_1",
        centerX: -24,
        centerY: -18,
        surfaceZM: 0,
        zMin: 0,
        zMax: 0.4,
        zoneRole: "ground_yard",
      },
      {
        ...makeZone("mat", 1),
        zoneId: "truck_bed_1",
        centerX: -8,
        centerY: -24,
        centerZ: 1.2,
        surfaceZM: 1.2,
        zMin: 1.2,
        zMax: 1.6,
        zoneRole: "truck_bed",
      },
    ];
    const workZones: BoxZoneFormItem[] = [3, 5, 7].map((level, index) => {
      const surface = level * 3.6;
      const floorId = level === 7 ? "roof" : `floor_${String(level).padStart(2, "0")}`;
      return {
        ...makeZone("work", index),
        zoneId: `${floorId}_dropoff`,
        centerX: 18 + index * 8,
        centerY: 10 + index * 6,
        centerZ: surface,
        zMin: surface,
        zMax: surface + 0.4,
        surfaceZM: surface,
        floorId,
        buildingId: "tower_a",
        levelIndex: level,
        zoneRole: level === 7 ? "roof" : "floor_slab",
      };
    });
    const buildings = [
      {
        building_id: "tower_a",
        name: "Tower A",
        footprint: [
          [-32, -20],
          [40, -20],
          [40, 34],
          [-32, 34],
        ],
        floors: 7,
        floor_height_m: 3.6,
        base_z_m: 0,
      },
    ];
    const loadTypes = {
      rebar_bundle: {
        display_name: "Rebar bundle",
        weight_range_t: [1.0, 1.4],
        size_m: [4.0, 0.8, 0.8],
        shape: "box_long",
      },
    };
    const firstDropoffByCrane = [
      "floor_03_dropoff",
      "floor_05_dropoff",
      "roof_dropoff",
      "floor_05_dropoff",
    ];
    const secondDropoffByCrane = [
      "floor_05_dropoff",
      "roof_dropoff",
      "floor_03_dropoff",
      "roof_dropoff",
    ];
    const manualTasks = cranes.flatMap((crane, index) => [
      {
        task_id: `T_${crane.craneId}_001`,
        crane_id: crane.craneId,
        task_type: "easy_task",
        pickup_zone_id: index % 2 === 0 ? "ground_yard_1" : "truck_bed_1",
        dropoff_zone_id: firstDropoffByCrane[index],
        load_type: "rebar_bundle",
        priority: "medium",
      },
      {
        task_id: `T_${crane.craneId}_002`,
        crane_id: crane.craneId,
        task_type: "easy_task",
        pickup_zone_id: index % 2 === 0 ? "truck_bed_1" : "ground_yard_1",
        dropoff_zone_id: secondDropoffByCrane[index],
        load_type: "rebar_bundle",
        priority: index % 2 === 0 ? "medium" : "high",
      },
    ]);
    updateFormAndYaml({
      scenarioId: "multifloor_construction_demo",
      experimentId: "multifloor_construction_demo",
      boundary: { xMin: -90, xMax: 90, yMin: -90, yMax: 90, zMin: 0, zMax: 70 },
      craneModelId,
      cranes,
      materialZones,
      workZones,
      numCranes: 4,
      tasksPerCrane: 2,
      taskGenerationMode: "manual",
    }, {
      "scenario.crane_models": craneModels,
      "scenario.load_types": loadTypes,
      "scenario.site.buildings": buildings,
      "scenario.tasks.manual_tasks": manualTasks,
      "scenario.tasks.state_machine.safe_transport_height_m": 28,
    });
  };

  const selectedTemplate = templates.find(
    (item) => item.template_id === selectedTemplateId,
  );

  const renderZoneList = (
    listKey: ZoneListKey,
    title: string,
    prefix: string,
    listHelp: string,
  ) => (
    <div className="workbench-array-group">
      <div className="workbench-array-header">
        <div>
          <h3>{title}</h3>
          <p className="workbench-help">{listHelp}</p>
        </div>
        <button type="button" onClick={() => addZone(listKey, prefix)}>
          添加一项
        </button>
      </div>
      <div className="workbench-card-list">
        {form[listKey].length === 0 ? (
          <p className="muted">暂无条目。</p>
        ) : null}
        {form[listKey].map((zone, index) => (
          <div className="workbench-zone-card" key={`${listKey}-${zone.zoneId}-${index}`}>
            <div className="workbench-card-titlebar">
              <strong>{zone.zoneId || `${title} ${index + 1}`}</strong>
              <button type="button" onClick={() => removeZone(listKey, index)}>
                删除
              </button>
            </div>
            <div className="workbench-field-grid compact">
              <Field
                id={`${listKey}-${index}-id`}
                label="区域 ID"
                help="区域唯一标识，会被任务的 pickup/dropoff 或禁入区策略引用。"
              >
                <input
                  id={`${listKey}-${index}-id`}
                  type="text"
                  value={zone.zoneId}
                  onChange={(event) =>
                    updateZone(listKey, index, { zoneId: event.target.value })
                  }
                />
              </Field>
              <Field
                id={`${listKey}-${index}-type`}
                label="类型"
                help="当前可视化表单按 box 长方体区域编辑，YAML 高级模式可保留更多形状。"
              >
                <select
                  id={`${listKey}-${index}-type`}
                  value={zone.type}
                  onChange={(event) =>
                    updateZone(listKey, index, { type: event.target.value })
                  }
                >
                  {["box"].map(valueOption)}
                </select>
              </Field>
              <Field
                id={`${listKey}-${index}-center-x`}
                label="中心 X"
                help="区域中心点 X 坐标，单位为米。"
              >
                <input
                  id={`${listKey}-${index}-center-x`}
                  type="number"
                  value={zone.centerX}
                  onChange={(event) =>
                    updateZoneNumber(listKey, index, "centerX", event.target.value)
                  }
                />
              </Field>
              <Field
                id={`${listKey}-${index}-center-y`}
                label="中心 Y"
                help="区域中心点 Y 坐标，单位为米。"
              >
                <input
                  id={`${listKey}-${index}-center-y`}
                  type="number"
                  value={zone.centerY}
                  onChange={(event) =>
                    updateZoneNumber(listKey, index, "centerY", event.target.value)
                  }
                />
              </Field>
              <Field
                id={`${listKey}-${index}-center-z`}
                label="中心 Z"
                help="区域中心点 Z 坐标，单位为米。"
              >
                <input
                  id={`${listKey}-${index}-center-z`}
                  type="number"
                  min={0}
                  value={zone.centerZ}
                  onChange={(event) =>
                    updateZoneNumber(listKey, index, "centerZ", event.target.value, {
                      min: 0,
                    })
                  }
                />
              </Field>
              <Field
                id={`${listKey}-${index}-size-x`}
                label="尺寸 X"
                help="长方体在 X 方向的长度，单位为米，必须为正数。"
              >
                <input
                  id={`${listKey}-${index}-size-x`}
                  type="number"
                  min={0.01}
                  step={0.1}
                  value={zone.sizeX}
                  onChange={(event) =>
                    updateZoneNumber(listKey, index, "sizeX", event.target.value, {
                      min: 0.01,
                    })
                  }
                />
              </Field>
              <Field
                id={`${listKey}-${index}-size-y`}
                label="尺寸 Y"
                help="长方体在 Y 方向的长度，单位为米，必须为正数。"
              >
                <input
                  id={`${listKey}-${index}-size-y`}
                  type="number"
                  min={0.01}
                  step={0.1}
                  value={zone.sizeY}
                  onChange={(event) =>
                    updateZoneNumber(listKey, index, "sizeY", event.target.value, {
                      min: 0.01,
                    })
                  }
                />
              </Field>
              <Field
                id={`${listKey}-${index}-size-z`}
                label="尺寸 Z"
                help="长方体在 Z 方向的高度，单位为米，必须为正数。"
              >
                <input
                  id={`${listKey}-${index}-size-z`}
                  type="number"
                  min={0.01}
                  step={0.1}
                  value={zone.sizeZ}
                  onChange={(event) =>
                    updateZoneNumber(listKey, index, "sizeZ", event.target.value, {
                      min: 0.01,
                    })
                  }
                />
              </Field>
              <Field
                id={`${listKey}-${index}-z-min`}
                label="Z 下限"
                help="区域有效高度下限，单位为米。"
              >
                <input
                  id={`${listKey}-${index}-z-min`}
                  type="number"
                  min={0}
                  value={zone.zMin}
                  onChange={(event) =>
                    updateZoneNumber(listKey, index, "zMin", event.target.value, {
                      min: 0,
                    })
                  }
                />
              </Field>
              <Field
                id={`${listKey}-${index}-z-max`}
                label="Z 上限"
                help="区域有效高度上限，单位为米，应大于 Z 下限。"
              >
                <input
                  id={`${listKey}-${index}-z-max`}
                  type="number"
                  min={0}
                  value={zone.zMax}
                  onChange={(event) =>
                    updateZoneNumber(listKey, index, "zMax", event.target.value, {
                      min: 0,
                    })
                  }
                />
              </Field>
              <Field
                id={`${listKey}-${index}-surface-z`}
                label="surface_z_m"
                help="装卸表面标高，物料区通常是地面堆场/车辆平台；工作区通常是楼层、屋面或卸料平台。"
              >
                <input
                  id={`${listKey}-${index}-surface-z`}
                  type="number"
                  min={0}
                  step={0.1}
                  value={zone.surfaceZM}
                  onChange={(event) =>
                    updateZoneNumber(listKey, index, "surfaceZM", event.target.value, {
                      min: 0,
                    })
                  }
                />
              </Field>
              <Field
                id={`${listKey}-${index}-floor-id`}
                label="floor_id"
                help="楼层或平台标识，例如 floor_03、roof；地面堆场可留空。"
              >
                <input
                  id={`${listKey}-${index}-floor-id`}
                  type="text"
                  value={zone.floorId}
                  onChange={(event) =>
                    updateZone(listKey, index, { floorId: event.target.value })
                  }
                />
              </Field>
              <Field
                id={`${listKey}-${index}-building-id`}
                label="building_id"
                help="建筑标识，用于 3D 楼层板和任务面板串联显示。"
              >
                <input
                  id={`${listKey}-${index}-building-id`}
                  type="text"
                  value={zone.buildingId}
                  onChange={(event) =>
                    updateZone(listKey, index, { buildingId: event.target.value })
                  }
                />
              </Field>
              <Field
                id={`${listKey}-${index}-level-index`}
                label="level_index"
                help="楼层序号，可留空；例如 3 表示第三层。"
              >
                <input
                  id={`${listKey}-${index}-level-index`}
                  type="number"
                  min={0}
                  step={1}
                  value={zone.levelIndex ?? ""}
                  onChange={(event) =>
                    updateZoneLevelIndex(listKey, index, event.target.value)
                  }
                />
              </Field>
              <Field
                id={`${listKey}-${index}-zone-role`}
                label="zone_role"
                help="区域语义，影响任务高度解释和 3D 视觉样式。"
              >
                <select
                  id={`${listKey}-${index}-zone-role`}
                  value={zone.zoneRole}
                  onChange={(event) =>
                    updateZone(listKey, index, { zoneRole: event.target.value })
                  }
                >
                  {ZONE_ROLE_OPTIONS.map(valueOption)}
                </select>
              </Field>
              <Field
                id={`${listKey}-${index}-hook-offset`}
                label="hook_target_offset_m"
                help="吊钩目标比载荷顶部额外高出的距离，单位米。"
              >
                <input
                  id={`${listKey}-${index}-hook-offset`}
                  type="number"
                  min={0}
                  step={0.1}
                  value={zone.hookTargetOffsetM}
                  onChange={(event) =>
                    updateZoneNumber(listKey, index, "hookTargetOffsetM", event.target.value, {
                      min: 0,
                    })
                  }
                />
              </Field>
              <Field
                id={`${listKey}-${index}-approach-clearance`}
                label="approach_clearance_m"
                help="接近/越障高度相对吊钩目标的净空，单位米。"
              >
                <input
                  id={`${listKey}-${index}-approach-clearance`}
                  type="number"
                  min={0}
                  step={0.1}
                  value={zone.approachClearanceM}
                  onChange={(event) =>
                    updateZoneNumber(listKey, index, "approachClearanceM", event.target.value, {
                      min: 0,
                    })
                  }
                />
              </Field>
              <Field
                id={`${listKey}-${index}-loads`}
                label={listKey === "workZones" ? "接收载荷类型" : "载荷类型"}
                help="多个类型用英文逗号分隔，系统会写成 YAML 数组。"
              >
                <input
                  id={`${listKey}-${index}-loads`}
                  type="text"
                  value={
                    listKey === "workZones"
                      ? zone.acceptedLoadTypes
                      : zone.loadTypes
                  }
                  onChange={(event) =>
                    updateZone(
                      listKey,
                      index,
                      listKey === "workZones"
                        ? { acceptedLoadTypes: event.target.value }
                        : { loadTypes: event.target.value },
                    )
                  }
                />
              </Field>
            </div>
          </div>
        ))}
      </div>
    </div>
  );

  return (
    <section className="workbench-page">
      <header className="workbench-page-header">
        <h1>配置</h1>
        <p className="muted">
          通过表单维护场景、塔吊、任务、天气和 LLM 参数；YAML 作为高级预览保留。
        </p>
      </header>

      <div className="workbench-config-toolbar">
        <button type="button" onClick={loadTemplate} disabled={busy}>
          加载模板
        </button>
        <button type="button" onClick={syncYaml} disabled={busy || !yamlText}>
          同步表单到 YAML
        </button>
        <button type="button" onClick={validateYaml} disabled={busy || !yamlText}>
          校验配置
        </button>
        <button type="button" onClick={applyMultifloorPreset} disabled={busy}>
          生成多楼层施工示例
        </button>
        <button type="button" onClick={() => void saveDraft()} disabled={busy || !yamlText}>
          保存草稿
        </button>
        {selectedTemplate ? (
          <span className="chip">模板 {selectedTemplate.name}</span>
        ) : null}
        <span className="chip">{draftStatus}</span>
        {validation?.valid ? <span className="chip chip-ok">校验通过</span> : null}
      </div>

      {validationError ? (
        <div className="workbench-notice" role="alert">
          {validationError}
        </div>
      ) : null}

      <div className="workbench-config-grid">
        <div className="workbench-config-sections">
          <section className="workbench-panel workbench-config-section">
            <div className="workbench-config-section-header">
              <h2>基础</h2>
              <p className="workbench-help">
                定义实验身份、随机性和仿真步进，是每次运行最常改的入口。
              </p>
            </div>
            <div className="workbench-field-grid">
              <Field
                id="config-scenario-id"
                label="场景 ID"
                help="场景的唯一名称，会写入运行记录和导出数据。"
              >
                <input
                  id="config-scenario-id"
                  type="text"
                  value={form.scenarioId}
                  onChange={(event) => setTextField("scenarioId", event.target.value)}
                />
              </Field>
              <Field
                id="config-experiment-id"
                label="实验 ID"
                help="本次实验的唯一名称，建议能体现模型、塔吊数或数据集版本。"
              >
                <input
                  id="config-experiment-id"
                  type="text"
                  value={form.experimentId}
                  onChange={(event) =>
                    setTextField("experimentId", event.target.value)
                  }
                />
              </Field>
              <Field
                id="config-seed"
                label="随机种子"
                help="控制场景生成的随机性；保持相同数值可复现实验。默认 20260616。"
              >
                <input
                  id="config-seed"
                  type="number"
                  step={1}
                  value={form.seed}
                  onChange={(event) =>
                    setNumberField("seed", event.target.value, { integer: true })
                  }
                />
              </Field>
              <Field
                id="config-experiment-seed"
                label="实验种子"
                help="控制实验运行侧的随机性；通常与随机种子保持一致。"
              >
                <input
                  id="config-experiment-seed"
                  type="number"
                  step={1}
                  value={form.experimentSeed}
                  onChange={(event) =>
                    setNumberField("experimentSeed", event.target.value, {
                      integer: true,
                    })
                  }
                />
              </Field>
              <Field
                id="config-duration"
                label="仿真时长"
                help="单次仿真最长运行时间，单位为秒，必须大于 0。"
              >
                <input
                  id="config-duration"
                  type="number"
                  min={1}
                  value={form.durationS}
                  onChange={(event) =>
                    setNumberField("durationS", event.target.value, { min: 1 })
                  }
                />
              </Field>
              <Field
                id="config-dt"
                label="仿真步长"
                help="物理仿真的时间步长，单位为秒；越小越精细但运行更慢。"
              >
                <input
                  id="config-dt"
                  type="number"
                  min={0.01}
                  step={0.01}
                  value={form.dt}
                  onChange={(event) =>
                    setNumberField("dt", event.target.value, { min: 0.01 })
                  }
                />
              </Field>
              <Field
                id="config-min-duration"
                label="最短运行时长"
                help="即使任务提前完成，也至少运行到该时长，单位为秒。"
              >
                <input
                  id="config-min-duration"
                  type="number"
                  min={0}
                  value={form.minDurationS}
                  onChange={(event) =>
                    setNumberField("minDurationS", event.target.value, { min: 0 })
                  }
                />
              </Field>
              <Field
                id="config-physics-hz"
                label="物理频率"
                help="每秒物理更新次数，必须大于 0。默认 5。"
              >
                <input
                  id="config-physics-hz"
                  type="number"
                  min={1}
                  value={form.physicsHz}
                  onChange={(event) =>
                    setNumberField("physicsHz", event.target.value, { min: 1 })
                  }
                />
              </Field>
              <Field
                id="config-controller-hz"
                label="控制频率"
                help="控制器每秒更新次数，必须大于 0。默认 5。"
              >
                <input
                  id="config-controller-hz"
                  type="number"
                  min={1}
                  value={form.controllerHz}
                  onChange={(event) =>
                    setNumberField("controllerHz", event.target.value, { min: 1 })
                  }
                />
              </Field>
              <Field
                id="config-llm-interval"
                label="LLM 决策间隔"
                help="每台塔吊向模型请求决策的间隔，单位为秒。"
              >
                <input
                  id="config-llm-interval"
                  type="number"
                  min={0.1}
                  step={0.1}
                  value={form.llmDecisionIntervalS}
                  onChange={(event) =>
                    setNumberField("llmDecisionIntervalS", event.target.value, {
                      min: 0.1,
                    })
                  }
                />
              </Field>
              <ToggleField
                label="全部任务完成后停止"
                help="开启后所有任务完成即可结束，关闭后会跑满仿真时长。"
                checked={form.stopWhenAllTasksDone}
                onChange={(checked) =>
                  setBooleanField("stopWhenAllTasksDone", checked)
                }
              />
            </div>
          </section>

          <section className="workbench-panel workbench-config-section">
            <div className="workbench-config-section-header">
              <h2>场地</h2>
              <p className="workbench-help">
                管理坐标系和施工区域边界，边界过小会让塔吊或任务点落在场外。
              </p>
            </div>
            <div className="workbench-field-grid">
              <Field
                id="config-coordinate-system"
                label="坐标系"
                help="坐标轴定义。ENU 表示东-北-上；NED 表示北-东-下。默认 ENU。"
              >
                <select
                  id="config-coordinate-system"
                  value={form.coordinateSystem}
                  onChange={(event) =>
                    setTextField("coordinateSystem", event.target.value)
                  }
                >
                  {COORDINATE_OPTIONS.map(valueOption)}
                </select>
              </Field>
              <Field
                id="config-x-min"
                label="X 最小值"
                help="场地 X 方向下界，单位为米。"
              >
                <input
                  id="config-x-min"
                  type="number"
                  value={form.boundary.xMin}
                  onChange={(event) =>
                    setBoundaryNumber("xMin", event.target.value)
                  }
                />
              </Field>
              <Field
                id="config-x-max"
                label="X 最大值"
                help="场地 X 方向上界，单位为米，应大于 X 最小值。"
              >
                <input
                  id="config-x-max"
                  type="number"
                  value={form.boundary.xMax}
                  onChange={(event) =>
                    setBoundaryNumber("xMax", event.target.value)
                  }
                />
              </Field>
              <Field
                id="config-y-min"
                label="Y 最小值"
                help="场地 Y 方向下界，单位为米。"
              >
                <input
                  id="config-y-min"
                  type="number"
                  value={form.boundary.yMin}
                  onChange={(event) =>
                    setBoundaryNumber("yMin", event.target.value)
                  }
                />
              </Field>
              <Field
                id="config-y-max"
                label="Y 最大值"
                help="场地 Y 方向上界，单位为米，应大于 Y 最小值。"
              >
                <input
                  id="config-y-max"
                  type="number"
                  value={form.boundary.yMax}
                  onChange={(event) =>
                    setBoundaryNumber("yMax", event.target.value)
                  }
                />
              </Field>
              <Field
                id="config-z-min"
                label="Z 最小值"
                help="场地高度下界，单位为米，通常为 0。"
              >
                <input
                  id="config-z-min"
                  type="number"
                  min={0}
                  value={form.boundary.zMin}
                  onChange={(event) =>
                    setBoundaryNumber("zMin", event.target.value, { min: 0 })
                  }
                />
              </Field>
              <Field
                id="config-z-max"
                label="Z 最大值"
                help="场地高度上界，单位为米，应覆盖塔吊吊臂和吊钩活动范围。"
              >
                <input
                  id="config-z-max"
                  type="number"
                  min={0}
                  value={form.boundary.zMax}
                  onChange={(event) =>
                    setBoundaryNumber("zMax", event.target.value, { min: 0 })
                  }
                />
              </Field>
            </div>
          </section>

          <section className="workbench-panel workbench-config-section">
            <div className="workbench-config-section-header">
              <h2>塔吊</h2>
              <p className="workbench-help">
                配置塔吊数量、布局策略和每台塔吊的位置高度；修改数量会同步增删列表。
              </p>
            </div>
            <div className="workbench-field-grid">
              <Field
                id="config-crane-count"
                label="塔吊数量"
                help="参与仿真的塔吊数量，必须是大于 0 的整数。"
              >
                <input
                  id="config-crane-count"
                  type="number"
                  min={1}
                  step={1}
                  value={form.numCranes}
                  onChange={(event) => setCraneCount(event.target.value)}
                />
              </Field>
              <Field
                id="config-layout-mode"
                label="布局模式"
                help="manual 使用下方塔吊列表；auto 让系统按策略采样布局。"
              >
                <select
                  id="config-layout-mode"
                  value={form.layoutMode}
                  onChange={(event) => setTextField("layoutMode", event.target.value)}
                >
                  {LAYOUT_OPTIONS.map(valueOption)}
                </select>
              </Field>
              <Field
                id="config-overlap-level"
                label="重叠程度"
                help="控制塔吊覆盖区域的交叠目标，影响碰撞风险和协作密度。"
              >
                <select
                  id="config-overlap-level"
                  value={form.overlapLevel}
                  onChange={(event) =>
                    setTextField("overlapLevel", event.target.value)
                  }
                >
                  {OVERLAP_OPTIONS.map(valueOption)}
                </select>
              </Field>
              <Field
                id="config-height-strategy"
                label="高度策略"
                help="控制不同塔吊之间的高度关系，错层通常能降低吊臂冲突。"
              >
                <select
                  id="config-height-strategy"
                  value={form.heightStrategy}
                  onChange={(event) =>
                    setTextField("heightStrategy", event.target.value)
                  }
                >
                  {HEIGHT_OPTIONS.map(valueOption)}
                </select>
              </Field>
              <Field
                id="config-coverage-target"
                label="覆盖目标"
                help="balanced 兼顾覆盖和风险；wide_coverage 更重覆盖；dense_overlap 更重交叠压力。"
              >
                <select
                  id="config-coverage-target"
                  value={form.coverageTarget}
                  onChange={(event) =>
                    setTextField("coverageTarget", event.target.value)
                  }
                >
                  {COVERAGE_OPTIONS.map(valueOption)}
                </select>
              </Field>
              <Field
                id="config-slew-default"
                label="默认回转模式"
                help="continuous 允许连续回转；limited 会按机械角度限制回转。"
              >
                <select
                  id="config-slew-default"
                  value={form.slewModeDefault}
                  onChange={(event) =>
                    setTextField("slewModeDefault", event.target.value)
                  }
                >
                  {SLEW_OPTIONS.map(valueOption)}
                </select>
              </Field>
              <Field
                id="config-max-sampling"
                label="最大采样次数"
                help="自动布局时最多尝试的采样次数，必须是正整数。"
              >
                <input
                  id="config-max-sampling"
                  type="number"
                  min={1}
                  step={1}
                  value={form.maxSamplingAttempts}
                  onChange={(event) =>
                    setNumberField("maxSamplingAttempts", event.target.value, {
                      integer: true,
                      min: 1,
                    })
                  }
                />
              </Field>
            </div>

            <div className="workbench-array-group">
              <div className="workbench-array-header">
                <div>
                  <h3>塔吊列表</h3>
                  <p className="workbench-help">
                    每项会写入 scenario.cranes，坐标单位为米，角度单位为度。
                  </p>
                </div>
                <button type="button" onClick={addCrane}>
                  添加塔吊
                </button>
              </div>
              <div className="workbench-card-list">
                {form.cranes.map((crane, index) => (
                  <div className="workbench-zone-card" key={`${crane.craneId}-${index}`}>
                    <div className="workbench-card-titlebar">
                      <strong>{crane.craneId || `塔吊 ${index + 1}`}</strong>
                      <button type="button" onClick={() => removeCrane(index)}>
                        删除
                      </button>
                    </div>
                    <div className="workbench-field-grid compact">
                      <Field
                        id={`crane-${index}-id`}
                        label="塔吊 ID"
                        help="塔吊唯一编号，会出现在任务、日志和可视化中。"
                      >
                        <input
                          id={`crane-${index}-id`}
                          type="text"
                          value={crane.craneId}
                          onChange={(event) =>
                            updateCrane(index, { craneId: event.target.value })
                          }
                        />
                      </Field>
                      <Field
                        id={`crane-${index}-model`}
                        label="塔吊模型"
                        help="引用 crane_models 或内置塔吊模型的 model_id。"
                      >
                        <input
                          id={`crane-${index}-model`}
                          type="text"
                          value={crane.modelId}
                          onChange={(event) =>
                            updateCrane(index, { modelId: event.target.value })
                          }
                        />
                      </Field>
                      <Field
                        id={`crane-${index}-base-x`}
                        label="基座 X"
                        help="塔吊基座 X 坐标，单位为米。"
                      >
                        <input
                          id={`crane-${index}-base-x`}
                          type="number"
                          value={crane.baseX}
                          onChange={(event) =>
                            updateCraneNumber(index, "baseX", event.target.value)
                          }
                        />
                      </Field>
                      <Field
                        id={`crane-${index}-base-y`}
                        label="基座 Y"
                        help="塔吊基座 Y 坐标，单位为米。"
                      >
                        <input
                          id={`crane-${index}-base-y`}
                          type="number"
                          value={crane.baseY}
                          onChange={(event) =>
                            updateCraneNumber(index, "baseY", event.target.value)
                          }
                        />
                      </Field>
                      <Field
                        id={`crane-${index}-base-z`}
                        label="基座 Z"
                        help="塔吊基座高度，单位为米，通常为 0。"
                      >
                        <input
                          id={`crane-${index}-base-z`}
                          type="number"
                          min={0}
                          value={crane.baseZ}
                          onChange={(event) =>
                            updateCraneNumber(index, "baseZ", event.target.value, {
                              min: 0,
                            })
                          }
                        />
                      </Field>
                      <Field
                        id={`crane-${index}-mast-height`}
                        label="塔身高度"
                        help="塔吊塔身高度，单位为米，必须大于 0。"
                      >
                        <input
                          id={`crane-${index}-mast-height`}
                          type="number"
                          min={1}
                          value={crane.mastHeightM}
                          onChange={(event) =>
                            updateCraneNumber(
                              index,
                              "mastHeightM",
                              event.target.value,
                              { min: 1 },
                            )
                          }
                        />
                      </Field>
                      <Field
                        id={`crane-${index}-theta`}
                        label="初始角度"
                        help="塔吊吊臂初始方位角，单位为度。"
                      >
                        <input
                          id={`crane-${index}-theta`}
                          type="number"
                          value={crane.thetaInitDeg}
                          onChange={(event) =>
                            updateCraneNumber(
                              index,
                              "thetaInitDeg",
                              event.target.value,
                            )
                          }
                        />
                      </Field>
                      <Field
                        id={`crane-${index}-slew`}
                        label="回转模式"
                        help="单台塔吊的回转限制，覆盖默认回转模式。"
                      >
                        <select
                          id={`crane-${index}-slew`}
                          value={crane.slewMode}
                          onChange={(event) =>
                            updateCrane(index, { slewMode: event.target.value })
                          }
                        >
                          {SLEW_OPTIONS.map(valueOption)}
                        </select>
                      </Field>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </section>

          <section className="workbench-panel workbench-config-section">
            <div className="workbench-config-section-header">
              <h2>区域</h2>
              <p className="workbench-help">
                用结构化条目维护物料区、作业区和禁入区，避免手写 YAML 数组和缩进。
              </p>
            </div>
            {renderZoneList(
              "materialZones",
              "物料区",
              "mat",
              "吊装任务的取货区域，load_types 会限制可生成的载荷类型。",
            )}
            {renderZoneList(
              "workZones",
              "作业区",
              "work",
              "吊装任务的落货区域，accepted_load_types 会限制可接收载荷。",
            )}
            {renderZoneList(
              "forbiddenZones",
              "禁入区",
              "forbidden",
              "安全系统会根据禁入区阻止或记录吊钩、载荷进入危险空间。",
            )}
          </section>

          <section className="workbench-panel workbench-config-section">
            <div className="workbench-config-section-header">
              <h2>任务 / 天气 / 风险</h2>
              <p className="workbench-help">
                控制任务生成、排队节奏、天气条件和风险阈值，直接影响场景难度。
              </p>
            </div>
            <div className="workbench-field-grid">
              <Field
                id="config-tasks-per-crane"
                label="每台任务数"
                help="每台塔吊生成的任务数量，必须是正整数。"
              >
                <input
                  id="config-tasks-per-crane"
                  type="number"
                  min={1}
                  step={1}
                  value={form.tasksPerCrane}
                  onChange={(event) =>
                    setNumberField("tasksPerCrane", event.target.value, {
                      integer: true,
                      min: 1,
                    })
                  }
                />
              </Field>
              <Field
                id="config-task-mode"
                label="任务生成模式"
                help="manual 使用配置中的任务；auto 按区域和分布自动生成。"
              >
                <select
                  id="config-task-mode"
                  value={form.taskGenerationMode}
                  onChange={(event) =>
                    setTextField("taskGenerationMode", event.target.value)
                  }
                >
                  {TASK_GENERATION_OPTIONS.map(valueOption)}
                </select>
              </Field>
              <Field
                id="config-queue-start"
                label="队列启动方式"
                help="控制各塔吊任务队列是同时启动、错峰启动还是按计划启动。"
              >
                <select
                  id="config-queue-start"
                  value={form.queueStartMode}
                  onChange={(event) =>
                    setTextField("queueStartMode", event.target.value)
                  }
                >
                  {QUEUE_START_OPTIONS.map(valueOption)}
                </select>
              </Field>
              <Field
                id="config-initial-jitter-min"
                label="初始抖动最小值"
                help="任务启动延迟范围下限，单位为秒，不能为负。"
              >
                <input
                  id="config-initial-jitter-min"
                  type="number"
                  min={0}
                  value={form.initialStartJitterMinS}
                  onChange={(event) =>
                    setNumberField("initialStartJitterMinS", event.target.value, {
                      min: 0,
                    })
                  }
                />
              </Field>
              <Field
                id="config-initial-jitter-max"
                label="初始抖动最大值"
                help="任务启动延迟范围上限，单位为秒，应不小于最小值。"
              >
                <input
                  id="config-initial-jitter-max"
                  type="number"
                  min={0}
                  value={form.initialStartJitterMaxS}
                  onChange={(event) =>
                    setNumberField("initialStartJitterMaxS", event.target.value, {
                      min: 0,
                    })
                  }
                />
              </Field>
              <Field
                id="config-inter-delay-min"
                label="任务间隔最小值"
                help="同一塔吊两个任务之间的间隔下限，单位为秒。"
              >
                <input
                  id="config-inter-delay-min"
                  type="number"
                  min={0}
                  value={form.interTaskDelayMinS}
                  onChange={(event) =>
                    setNumberField("interTaskDelayMinS", event.target.value, {
                      min: 0,
                    })
                  }
                />
              </Field>
              <Field
                id="config-inter-delay-max"
                label="任务间隔最大值"
                help="同一塔吊两个任务之间的间隔上限，单位为秒。"
              >
                <input
                  id="config-inter-delay-max"
                  type="number"
                  min={0}
                  value={form.interTaskDelayMaxS}
                  onChange={(event) =>
                    setNumberField("interTaskDelayMaxS", event.target.value, {
                      min: 0,
                    })
                  }
                />
              </Field>
              <Field
                id="config-attach-timeout"
                label="挂载超时"
                help="挂载阶段最长等待时间，单位为秒，超出会触发失败策略。"
              >
                <input
                  id="config-attach-timeout"
                  type="number"
                  min={1}
                  value={form.attachStageTimeoutS}
                  onChange={(event) =>
                    setNumberField("attachStageTimeoutS", event.target.value, {
                      min: 1,
                    })
                  }
                />
              </Field>
              <Field
                id="config-release-timeout"
                label="释放超时"
                help="释放阶段最长等待时间，单位为秒。"
              >
                <input
                  id="config-release-timeout"
                  type="number"
                  min={1}
                  value={form.releaseStageTimeoutS}
                  onChange={(event) =>
                    setNumberField("releaseStageTimeoutS", event.target.value, {
                      min: 1,
                    })
                  }
                />
              </Field>
              <Field
                id="config-no-progress-timeout"
                label="无进展超时"
                help="任务长时间无进展时的判定窗口，单位为秒。"
              >
                <input
                  id="config-no-progress-timeout"
                  type="number"
                  min={1}
                  value={form.taskNoProgressTimeoutS}
                  onChange={(event) =>
                    setNumberField("taskNoProgressTimeoutS", event.target.value, {
                      min: 1,
                    })
                  }
                />
              </Field>
              <Field
                id="config-weather-mode"
                label="天气模式"
                help="constant 固定天气；schedule 按时段变化；random 随机采样。"
              >
                <select
                  id="config-weather-mode"
                  value={form.weatherMode}
                  onChange={(event) => setTextField("weatherMode", event.target.value)}
                >
                  {WEATHER_OPTIONS.map(valueOption)}
                </select>
              </Field>
              <Field
                id="config-wind-speed"
                label="基础风速"
                help="基础风速，单位 m/s，不能为负。"
              >
                <input
                  id="config-wind-speed"
                  type="number"
                  min={0}
                  step={0.1}
                  value={form.windSpeedMS}
                  onChange={(event) =>
                    setNumberField("windSpeedMS", event.target.value, { min: 0 })
                  }
                />
              </Field>
              <Field
                id="config-gust-speed"
                label="阵风风速"
                help="阵风风速，单位 m/s，通常不小于基础风速。"
              >
                <input
                  id="config-gust-speed"
                  type="number"
                  min={0}
                  step={0.1}
                  value={form.gustSpeedMS}
                  onChange={(event) =>
                    setNumberField("gustSpeedMS", event.target.value, { min: 0 })
                  }
                />
              </Field>
              <Field
                id="config-wind-direction"
                label="风向"
                help="风向角，单位为度。"
              >
                <input
                  id="config-wind-direction"
                  type="number"
                  value={form.windDirectionDeg}
                  onChange={(event) =>
                    setNumberField("windDirectionDeg", event.target.value)
                  }
                />
              </Field>
              <Field
                id="config-visibility"
                label="能见度"
                help="影响观察噪声和遮挡；poor 会显著增加操作难度。"
              >
                <select
                  id="config-visibility"
                  value={form.visibility}
                  onChange={(event) => setTextField("visibility", event.target.value)}
                >
                  {VISIBILITY_OPTIONS.map(valueOption)}
                </select>
              </Field>
              <Field
                id="config-risk-low"
                label="低风险阈值"
                help="塔吊对象距离低于该值时进入低风险提示，单位为米。"
              >
                <input
                  id="config-risk-low"
                  type="number"
                  min={0}
                  value={form.riskLowThresholdM}
                  onChange={(event) =>
                    setNumberField("riskLowThresholdM", event.target.value, {
                      min: 0,
                    })
                  }
                />
              </Field>
              <Field
                id="config-risk-medium"
                label="中风险阈值"
                help="塔吊对象距离低于该值时进入中风险提示，单位为米。"
              >
                <input
                  id="config-risk-medium"
                  type="number"
                  min={0}
                  value={form.riskMediumThresholdM}
                  onChange={(event) =>
                    setNumberField("riskMediumThresholdM", event.target.value, {
                      min: 0,
                    })
                  }
                />
              </Field>
              <Field
                id="config-risk-high"
                label="高风险阈值"
                help="塔吊对象距离低于该值时进入高风险提示，单位为米。"
              >
                <input
                  id="config-risk-high"
                  type="number"
                  min={0}
                  value={form.riskHighThresholdM}
                  onChange={(event) =>
                    setNumberField("riskHighThresholdM", event.target.value, {
                      min: 0,
                    })
                  }
                />
              </Field>
              <Field
                id="config-risk-near-miss"
                label="近失阈值"
                help="距离低于该值会记录 near_miss 风险事件，单位为米。"
              >
                <input
                  id="config-risk-near-miss"
                  type="number"
                  min={0}
                  value={form.riskNearMissThresholdM}
                  onChange={(event) =>
                    setNumberField("riskNearMissThresholdM", event.target.value, {
                      min: 0,
                    })
                  }
                />
              </Field>
            </div>
          </section>

          <section className="workbench-panel workbench-config-section">
            <div className="workbench-config-section-header">
              <h2>LLM 与输出</h2>
              <p className="workbench-help">
                选择模型供应商、运行安全策略和导出内容；数值字段会以数字写入 YAML。
              </p>
            </div>
            <div className="workbench-field-grid">
              <ToggleField
                label="启用 LLM"
                help="关闭后不会请求真实模型，适合只验证物理、任务和数据导出。"
                checked={form.llmEnabled}
                onChange={(checked) => setBooleanField("llmEnabled", checked)}
              />
              <Field
                id="config-llm-provider"
                label="LLM Provider"
                help="当前后端已接入的供应商；mock/replay 不需要 API Key。"
              >
                <select
                  id="config-llm-provider"
                  value={form.llmProvider}
                  onChange={(event) => setLLMProvider(event.target.value)}
                >
                  {LLM_PROVIDER_OPTIONS.map(valueOption)}
                </select>
              </Field>
              <Field
                id="config-llm-model"
                label="模型"
                help="传给供应商的模型名称，例如 deepseek-v4-flash。"
              >
                <input
                  id="config-llm-model"
                  type="text"
                  value={form.llmModel}
                  onChange={(event) => setTextField("llmModel", event.target.value)}
                />
              </Field>
              <Field
                id="config-llm-base-url"
                label="Base URL"
                help="兼容 OpenAI Chat Completions 的服务地址，留空则使用供应商默认地址。"
              >
                <input
                  id="config-llm-base-url"
                  type="url"
                  value={form.llmBaseUrl}
                  onChange={(event) =>
                    setTextField("llmBaseUrl", event.target.value)
                  }
                />
              </Field>
              <Field
                id="config-llm-api-key-env"
                label="API Key Env"
                help="可选环境变量名；真实密钥可在下方保存到本机设置，不写入 YAML。"
              >
                <input
                  id="config-llm-api-key-env"
                  type="text"
                  value={form.llmApiKeyEnv}
                  onChange={(event) =>
                    setTextField("llmApiKeyEnv", event.target.value)
                  }
                />
              </Field>
              <div className="workbench-field workbench-field-wide">
                <div className="workbench-field-heading">
                  <label htmlFor="config-llm-local-api-key">本机 API Key</label>
                  <span
                    className="workbench-field-tooltip"
                    title="保存到 .desktop/secrets/llm_providers.json，只返回脱敏状态，不写入 YAML。"
                  >
                    ?
                  </span>
                </div>
                <div className="workbench-inline-secret">
                  <input
                    id="config-llm-local-api-key"
                    type="password"
                    value={localApiKey}
                    onChange={(event) => setLocalApiKey(event.target.value)}
                    disabled={!REAL_LLM_PROVIDERS.has(form.llmProvider)}
                    placeholder={
                      REAL_LLM_PROVIDERS.has(form.llmProvider)
                        ? "输入 API Key，可直接测试或保存到本机"
                        : "mock/replay 无需 API Key"
                    }
                  />
                  <button
                    type="button"
                    onClick={saveLocalApiKey}
                    disabled={llmSecretBusy || !REAL_LLM_PROVIDERS.has(form.llmProvider)}
                  >
                    保存 Key
                  </button>
                  <button
                    type="button"
                    onClick={testLocalApiKey}
                    disabled={llmSecretBusy || !REAL_LLM_PROVIDERS.has(form.llmProvider)}
                  >
                    测试连通性
                  </button>
                </div>
                <p className="workbench-help">{llmSecretStatus}</p>
              </div>
              <Field
                id="config-llm-temperature"
                label="Temperature"
                help="模型采样温度，不能为负；越高输出越发散。"
              >
                <input
                  id="config-llm-temperature"
                  type="number"
                  min={0}
                  step={0.1}
                  value={form.llmTemperature}
                  onChange={(event) =>
                    setNumberField("llmTemperature", event.target.value, { min: 0 })
                  }
                />
              </Field>
              <Field
                id="config-llm-timeout"
                label="请求超时"
                help="单次模型请求超时时间，单位为秒，必须大于 0。"
              >
                <input
                  id="config-llm-timeout"
                  type="number"
                  min={1}
                  value={form.timeoutS}
                  onChange={(event) =>
                    setNumberField("timeoutS", event.target.value, { min: 1 })
                  }
                />
              </Field>
              <Field
                id="config-llm-max-retries"
                label="最大重试次数"
                help="模型请求失败后的重试次数，必须是整数，默认 1。"
              >
                <input
                  id="config-llm-max-retries"
                  type="number"
                  min={0}
                  step={1}
                  value={form.maxRetries}
                  onChange={(event) =>
                    setNumberField("maxRetries", event.target.value, {
                      integer: true,
                      min: 0,
                    })
                  }
                />
              </Field>
              <Field
                id="config-llm-max-failures"
                label="连续失败上限"
                help="连续请求失败超过该值后触发运行失败或降级策略。"
              >
                <input
                  id="config-llm-max-failures"
                  type="number"
                  min={1}
                  step={1}
                  value={form.maxConsecutiveFailures}
                  onChange={(event) =>
                    setNumberField("maxConsecutiveFailures", event.target.value, {
                      integer: true,
                      min: 1,
                    })
                  }
                />
              </Field>
              <Field
                id="config-llm-concurrent"
                label="最大并发请求"
                help="同时向模型发送的最大请求数，必须是正整数。"
              >
                <input
                  id="config-llm-concurrent"
                  type="number"
                  min={1}
                  step={1}
                  value={form.maxConcurrentRequests}
                  onChange={(event) =>
                    setNumberField("maxConcurrentRequests", event.target.value, {
                      integer: true,
                      min: 1,
                    })
                  }
                />
              </Field>
              <Field
                id="config-llm-fallback"
                label="失败回退策略"
                help="模型不可用时的指令回退策略，neutral_stop 会输出中性停止。"
              >
                <select
                  id="config-llm-fallback"
                  value={form.llmFallbackPolicy}
                  onChange={(event) =>
                    setTextField("llmFallbackPolicy", event.target.value)
                  }
                >
                  {FALLBACK_POLICY_OPTIONS.map(valueOption)}
                </select>
              </Field>
              <Field
                id="config-structured-output"
                label="结构化输出"
                help="控制模型响应格式约束，json_object 更通用，json_schema 更严格。"
              >
                <select
                  id="config-structured-output"
                  value={form.structuredOutputMode}
                  onChange={(event) =>
                    setTextField("structuredOutputMode", event.target.value)
                  }
                >
                  {STRUCTURED_OUTPUT_OPTIONS.map(valueOption)}
                </select>
              </Field>
              <Field
                id="config-history-mode"
                label="历史上下文"
                help="控制提示词中携带多少历史决策，越长 token 消耗越高。"
              >
                <select
                  id="config-history-mode"
                  value={form.historyMode}
                  onChange={(event) => setTextField("historyMode", event.target.value)}
                >
                  {HISTORY_OPTIONS.map(valueOption)}
                </select>
              </Field>
              <Field
                id="config-recent-decisions"
                label="完整历史条数"
                help="保留完整近期决策的条数，必须是非负整数。"
              >
                <input
                  id="config-recent-decisions"
                  type="number"
                  min={0}
                  step={1}
                  value={form.recentDecisionsFull}
                  onChange={(event) =>
                    setNumberField("recentDecisionsFull", event.target.value, {
                      integer: true,
                      min: 0,
                    })
                  }
                />
              </Field>
              <Field
                id="config-summarizer-mode"
                label="摘要模式"
                help="控制长上下文摘要生成方式；none 表示不生成摘要。"
              >
                <select
                  id="config-summarizer-mode"
                  value={form.summarizerMode}
                  onChange={(event) =>
                    setTextField("summarizerMode", event.target.value)
                  }
                >
                  {SUMMARIZER_OPTIONS.map(valueOption)}
                </select>
              </Field>
              <Field
                id="config-summarizer-provider"
                label="摘要供应商"
                help="same_as_operator 使用同一个模型；explicit 使用摘要专用配置。"
              >
                <select
                  id="config-summarizer-provider"
                  value={form.summarizerProvider}
                  onChange={(event) =>
                    setTextField("summarizerProvider", event.target.value)
                  }
                >
                  {SUMMARIZER_PROVIDER_OPTIONS.map(valueOption)}
                </select>
              </Field>
              <Field
                id="config-summarizer-fallback"
                label="摘要回退"
                help="摘要失败时使用的备选方式。"
              >
                <select
                  id="config-summarizer-fallback"
                  value={form.summarizerFallback}
                  onChange={(event) =>
                    setTextField("summarizerFallback", event.target.value)
                  }
                >
                  {SUMMARIZER_OPTIONS.map(valueOption)}
                </select>
              </Field>
              <Field
                id="config-summarizer-every"
                label="每 N 次摘要"
                help="每多少次决策触发一次摘要，必须是正整数。"
              >
                <input
                  id="config-summarizer-every"
                  type="number"
                  min={1}
                  step={1}
                  value={form.summarizerEveryNDecisions}
                  onChange={(event) =>
                    setNumberField("summarizerEveryNDecisions", event.target.value, {
                      integer: true,
                      min: 1,
                    })
                  }
                />
              </Field>
              <Field
                id="config-summarizer-tokens"
                label="摘要 token 阈值"
                help="上下文超过该 token 数后触发摘要，必须是正整数。"
              >
                <input
                  id="config-summarizer-tokens"
                  type="number"
                  min={1}
                  step={1}
                  value={form.summarizerContextOverTokens}
                  onChange={(event) =>
                    setNumberField(
                      "summarizerContextOverTokens",
                      event.target.value,
                      { integer: true, min: 1 },
                    )
                  }
                />
              </Field>
              <Field
                id="config-risk-prompt-mode"
                label="风险提示模式"
                help="R0 不注入安全提示；R1 会注入在线风险摘要。"
              >
                <select
                  id="config-risk-prompt-mode"
                  value={form.riskPromptMode}
                  onChange={(event) =>
                    setTextField("riskPromptMode", event.target.value)
                  }
                >
                  {RISK_PROMPT_OPTIONS.map(valueOption)}
                </select>
              </Field>
              <Field
                id="config-safety-mode"
                label="安全模式"
                help="S0 最宽松，S3 最严格；等级越高越倾向于安全干预。"
              >
                <select
                  id="config-safety-mode"
                  value={form.safetyMode}
                  onChange={(event) => setTextField("safetyMode", event.target.value)}
                >
                  {SAFETY_OPTIONS.map(valueOption)}
                </select>
              </Field>
              <Field
                id="config-runtime-mode"
                label="运行模式"
                help="offline_batch 用于批处理运行；offline_replay 用于回放；interactive_server 用于交互服务。"
              >
                <select
                  id="config-runtime-mode"
                  value={form.runtimeMode}
                  onChange={(event) => setTextField("runtimeMode", event.target.value)}
                >
                  {RUNTIME_OPTIONS.map(valueOption)}
                </select>
              </Field>
              <Field
                id="config-run-root"
                label="输出目录"
                help="运行产物保存目录，默认 runs/desktop。"
              >
                <input
                  id="config-run-root"
                  type="text"
                  value={form.runRoot}
                  onChange={(event) => setTextField("runRoot", event.target.value)}
                />
              </Field>
              <ToggleField
                label="回放模式"
                help="开启后按回放配置读取历史指令，通常配合 offline_replay。"
                checked={form.replayMode}
                onChange={(checked) => setBooleanField("replayMode", checked)}
              />
              <ToggleField
                label="启用 LLM 缓存"
                help="相同请求可复用缓存响应，降低重复实验成本。"
                checked={form.llmCacheEnabled}
                onChange={(checked) => setBooleanField("llmCacheEnabled", checked)}
              />
              <ToggleField
                label="保存可视化帧"
                help="保存前端回放或可视化所需的帧数据。"
                checked={form.saveVisualFrames}
                onChange={(checked) => setBooleanField("saveVisualFrames", checked)}
              />
              <ToggleField
                label="保存 Parquet"
                help="保存训练和分析常用的 Parquet 表。"
                checked={form.saveParquet}
                onChange={(checked) => setBooleanField("saveParquet", checked)}
              />
              <ToggleField
                label="保存回放"
                help="保存 command_replay 等回放数据。"
                checked={form.saveReplay}
                onChange={(checked) => setBooleanField("saveReplay", checked)}
              />
            </div>
          </section>
        </div>

        <div className="workbench-panel workbench-yaml-panel">
          <div className="workbench-yaml-actions">
            <label className="workbench-yaml-label" htmlFor="workbench-yaml">
              高级 YAML
            </label>
            <label className="workbench-yaml-edit-toggle">
              <input
                type="checkbox"
                checked={advancedYamlEnabled}
                onChange={(event) => setAdvancedYamlEnabled(event.target.checked)}
              />
              <span>高级 YAML 编辑</span>
            </label>
          </div>
          <p className="workbench-help">
            默认作为只读预览。需要直接修改 YAML 时先开启高级编辑；语法正确后会同步回左侧表单。
          </p>
          <textarea
            id="workbench-yaml"
            value={yamlText}
            readOnly={!advancedYamlEnabled}
            onChange={(event) => handleAdvancedYamlChange(event.target.value)}
            spellCheck={false}
          />
        </div>
      </div>
    </section>
  );
}
