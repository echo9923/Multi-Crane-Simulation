# Visual Configuration Workbench Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the desktop configuration page form-first so users can configure common crane simulation settings without hand-editing YAML.

**Architecture:** Extend the existing frontend workbench form model and keep the backend YAML/validation APIs as the source of truth. The React configuration page will render grouped form sections, generate typed dotted-path patches, keep YAML as advanced preview/editing, and format backend validation errors with field paths.

**Tech Stack:** React, Zustand, TypeScript, js-yaml, Vitest, Testing Library, FastAPI/Pydantic validation APIs.

---

## File Structure

- Modify `frontend/src/workbench/types.ts`: add nested form item types for boundaries, cranes, zones, tasks, weather/risk, LLM, and output fields.
- Modify `frontend/src/workbench/configModel.ts`: extract extended fields from YAML, generate typed patch maps, format validation errors, provide field metadata/options.
- Modify `frontend/src/components/workbench/ConfigurationPage.tsx`: replace the single core form with grouped visual sections and YAML preview/advanced editing behavior.
- Modify `frontend/src/styles.css`: add dense operational layout styles for config sections, cards, inline fields, help text, and advanced YAML controls.
- Modify tests in `frontend/tests/workbench/configModel.test.ts` and `frontend/tests/workbench/configuration.test.tsx`.
- Optionally modify `frontend/src/types/api.ts` only if existing error detail typing blocks useful formatting.

## Task 1: Extend Config Model And Error Formatting

**Files:**
- Modify: `frontend/src/workbench/types.ts`
- Modify: `frontend/src/workbench/configModel.ts`
- Test: `frontend/tests/workbench/configModel.test.ts`

- [ ] **Step 1: Write failing tests for extended extraction and typed patches**

Add tests to `frontend/tests/workbench/configModel.test.ts`:

```ts
it("extracts site, crane, zone, weather, risk, llm, and output fields", () => {
  const form = yamlToCoreForm([
    "scenario:",
    "  scenario_id: demo",
    "  seed: 20260614",
    "  site:",
    "    coordinate_system: ENU",
    "    boundary:",
    "      x_min: -80",
    "      x_max: 80",
    "      y_min: -70",
    "      y_max: 70",
    "      z_min: 0",
    "      z_max: 60",
    "    material_zones:",
    "      - zone_id: mat_c1",
    "        type: box",
    "        center: [-21.96, -21.96, 10]",
    "        size: [0.4, 0.4, 0.4]",
    "        z_range_m: [9.8, 10.2]",
    "        load_types: [rebar_bundle]",
    "    work_zones:",
    "      - zone_id: work_c1",
    "        type: box",
    "        center: [-26.485, -26.485, 11]",
    "        size: [0.6, 0.6, 0.5]",
    "        z_range_m: [10.8, 11.2]",
    "        accepted_load_types: [rebar_bundle]",
    "    forbidden_zones:",
    "      - zone_id: core",
    "        type: box",
    "        center: [0, 0, 10]",
    "        size: [4, 4, 20]",
    "  layout:",
    "    num_cranes: 1",
    "    mode: manual",
    "    overlap_level: medium",
    "    height_strategy: mixed",
    "    coverage_target: balanced",
    "    slew_mode_default: continuous",
    "    max_sampling_attempts: 500",
    "  cranes:",
    "    - crane_id: C1",
    "      model_id: demo_flat_top_45m",
    "      base: [-18, -18, 0]",
    "      mast_height_m: 30",
    "      theta_init_deg: -135",
    "      slew:",
    "        mode: continuous",
    "  tasks:",
    "    generation_mode: manual",
    "    num_tasks_per_crane: 2",
    "    queue_policy:",
    "      start_mode: simultaneous",
    "      initial_start_jitter_s: [0, 0]",
    "      inter_task_delay_s: [0, 1]",
    "    attach_delay_s: [0, 0]",
    "    release_delay_s: [0, 0]",
    "    state_machine:",
    "      attach_stage_timeout_s: 1200",
    "      release_stage_timeout_s: 1200",
    "      task_no_progress_timeout_s: 1200",
    "      recovery_release_timeout_s: 1200",
    "  weather:",
    "    mode: constant",
    "    wind:",
    "      base_speed_m_s: 3",
    "      gust_speed_m_s: 5",
    "      direction_deg: 90",
    "    visibility:",
    "      base_level: good",
    "  risk:",
    "    geometry_envelope:",
    "      jib_radius_m: 0.75",
    "      hook_radius_m: 0.5",
    "      load_radius_m: 1.0",
    "    thresholds_m:",
    "      low: 6",
    "      medium: 4",
    "      high: 2.5",
    "      near_miss: 1.5",
    "experiment:",
    "  experiment_id: exp",
    "  seed: 20260614",
    "  sim:",
    "    duration_s: 7200",
    "    dt: 0.2",
    "    min_duration_s: 0",
    "    stop_when_all_tasks_done: true",
    "    physics_hz: 5",
    "    controller_hz: 5",
    "    llm_decision_interval_s: 1.0",
    "  risk_prompt_mode: R1",
    "  safety_mode: S1",
    "  runtime:",
    "    mode: offline_batch",
    "    replay_mode: false",
    "    replay_file: null",
    "    llm_cache_enabled: true",
    "  llm:",
    "    enabled: true",
    "    provider: deepseek",
    "    model: deepseek-v4-flash",
    "    base_url: https://api.deepseek.com",
    "    api_key_env: DEEPSEEK_API_KEY",
    "    temperature: 0.2",
    "    timeout_s: 30",
    "    max_retries: 1",
    "    max_consecutive_failures: 10",
    "    fallback_policy: neutral_stop",
    "    structured_output:",
    "      mode: json_object",
    "    context:",
    "      history_mode: short",
    "      recent_decisions_full: 8",
    "      include_task_history_summary: true",
    "      include_completed_task_summary: true",
    "      include_failed_request_history: true",
    "      include_risk_event_history: true",
    "      summarizer:",
    "        mode: none",
    "        provider: same_as_operator",
    "        fallback: rule",
    "        trigger:",
    "          every_n_decisions: 20",
    "          context_over_tokens: 12000",
    "  output:",
    "    run_root: runs/deepseek-demo",
    "    save_visual_frames: true",
    "    save_parquet: true",
    "    save_replay: true",
  ].join(\"\\n\"));

  expect(form.coordinateSystem).toBe("ENU");
  expect(form.boundary.xMin).toBe(-80);
  expect(form.physicsHz).toBe(5);
  expect(form.cranes[0]).toMatchObject({ craneId: "C1", mastHeightM: 30 });
  expect(form.materialZones[0]).toMatchObject({ zoneId: "mat_c1", centerX: -21.96 });
  expect(form.workZones[0]).toMatchObject({ zoneId: "work_c1", acceptedLoadTypes: "rebar_bundle" });
  expect(form.forbiddenZones[0]).toMatchObject({ zoneId: "core", sizeZ: 20 });
  expect(form.timeoutS).toBe(30);
  expect(form.maxRetries).toBe(1);
  expect(form.summarizerEveryNDecisions).toBe(20);
  expect(form.saveReplay).toBe(true);
});

it("generates typed patches for extended visual fields", () => {
  const patches = coreFormToPatches({
    ...defaultCoreForm(),
    coordinateSystem: "ENU",
    boundary: { xMin: -1, xMax: 2, yMin: -3, yMax: 4, zMin: 0, zMax: 50 },
    cranes: [
      {
        craneId: "C1",
        modelId: "demo_flat_top_45m",
        baseX: -18,
        baseY: -18,
        baseZ: 0,
        mastHeightM: 30,
        thetaInitDeg: -135,
        slewMode: "continuous",
      },
    ],
    materialZones: [],
    workZones: [],
    forbiddenZones: [],
    maxRetries: 2,
    maxConcurrentRequests: 4,
    summarizerEveryNDecisions: 20,
  });

  expect(patches["scenario.site.boundary.x_min"]).toBe(-1);
  expect(patches["scenario.cranes"]).toEqual([
    {
      crane_id: "C1",
      model_id: "demo_flat_top_45m",
      base: [-18, -18, 0],
      mast_height_m: 30,
      theta_init_deg: -135,
      slew: { mode: "continuous" },
    },
  ]);
  expect(patches["experiment.llm.max_retries"]).toBe(2);
  expect(typeof patches["experiment.llm.max_retries"]).toBe("number");
});
```

- [ ] **Step 2: Write failing tests for validation error formatting**

Add tests to `frontend/tests/workbench/configModel.test.ts`:

```ts
it("formats pydantic integer errors with a field path", () => {
  expect(
    formatConfigError({
      message: "Input should be a valid integer, unable to parse string as an integer",
      details: {
        field_path: "experiment.llm.max_retries",
        errors: [
          {
            loc: ["experiment", "llm", "max_retries"],
            msg: "Input should be a valid integer, unable to parse string as an integer",
            input: "1.0",
          },
        ],
      },
    }),
  ).toContain("字段 experiment.llm.max_retries 需要整数");
});
```

- [ ] **Step 3: Run tests and verify they fail**

Run:

```bash
cd frontend && npm test -- tests/workbench/configModel.test.ts
```

Expected: fail because extended fields and `formatConfigError` do not exist yet.

- [ ] **Step 4: Implement types and config model helpers**

Update `frontend/src/workbench/types.ts` with explicit item interfaces:

```ts
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
  loadTypes: string;
  acceptedLoadTypes: string;
}
```

Extend `CoreExperimentForm` with fields from the spec. Keep camelCase names and number values.

Update `frontend/src/workbench/configModel.ts`:

- add helpers `numberArrayAt`, `recordArrayAt`, `cranesAt`, `zonesAt`;
- extend `defaultCoreForm`;
- extend `yamlToCoreForm`;
- extend `coreFormToPatches`;
- export `formatConfigError(error: unknown): string`.

Use backend-supported provider options first: `deepseek`, `minimax`, `mock`, `replay`. Do not add unsupported provider enum values in this task.

- [ ] **Step 5: Run tests and verify they pass**

Run:

```bash
cd frontend && npm test -- tests/workbench/configModel.test.ts
```

Expected: pass.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/workbench/types.ts frontend/src/workbench/configModel.ts frontend/tests/workbench/configModel.test.ts
git commit -m "feat(desktop): expand visual config model"
```

## Task 2: Build Form-First Configuration Page

**Files:**
- Modify: `frontend/src/components/workbench/ConfigurationPage.tsx`
- Modify: `frontend/src/styles.css`
- Test: `frontend/tests/workbench/configuration.test.tsx`

- [ ] **Step 1: Write failing UI tests**

Add tests to `frontend/tests/workbench/configuration.test.tsx`:

```ts
it("renders visual configuration sections and keeps YAML preview read-only by default", async () => {
  renderWorkbench();

  fireEvent.click(screen.getByRole("button", { name: "加载模板" }));
  await waitFor(() => expect(yamlTextarea().value).toContain("scenario:"));

  expect(screen.getByRole("heading", { name: "基础" })).toBeTruthy();
  expect(screen.getByRole("heading", { name: "场地" })).toBeTruthy();
  expect(screen.getByRole("heading", { name: "塔吊" })).toBeTruthy();
  expect(screen.getByRole("heading", { name: "区域" })).toBeTruthy();
  expect(screen.getByRole("heading", { name: "LLM 与输出" })).toBeTruthy();
  expect(yamlTextarea().readOnly).toBe(true);
});

it("toggles advanced YAML editing", async () => {
  renderWorkbench();

  fireEvent.click(screen.getByRole("button", { name: "加载模板" }));
  await waitFor(() => expect(yamlTextarea().value).toContain("scenario:"));

  fireEvent.click(screen.getByRole("checkbox", { name: "高级 YAML 编辑" }));

  expect(yamlTextarea().readOnly).toBe(false);
});

it("sends typed numeric and select patches from visual fields", async () => {
  const fetchMock = vi.mocked(fetch);
  renderWorkbench();

  fireEvent.click(screen.getByRole("button", { name: "加载模板" }));
  await waitFor(() => expect(yamlTextarea().value).toContain("scenario:"));

  fireEvent.change(screen.getByLabelText("随机种子"), { target: { value: "20260618" } });
  fireEvent.change(screen.getByLabelText("坐标系"), { target: { value: "ENU" } });
  fireEvent.change(screen.getByLabelText("最大重试次数"), { target: { value: "2" } });
  fireEvent.click(screen.getByRole("button", { name: "同步表单到 YAML" }));

  await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining("/desktop/config/patch"), expect.anything()));
  const body = requestBodyFor(fetchMock, "/desktop/config/patch");
  const patches = body.patches as Record<string, unknown>;
  expect(patches["scenario.seed"]).toBe(20260618);
  expect(patches["scenario.site.coordinate_system"]).toBe("ENU");
  expect(patches["experiment.llm.max_retries"]).toBe(2);
});
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
cd frontend && npm test -- tests/workbench/configuration.test.tsx
```

Expected: fail because visual sections, advanced YAML toggle, and fields do not exist.

- [ ] **Step 3: Implement grouped form layout**

Update `ConfigurationPage.tsx`:

- keep toolbar at top;
- render panels with headings `基础`, `场地`, `塔吊`, `区域`, `任务 / 天气 / 风险`, `LLM 与输出`, `高级 YAML`;
- replace free-text fixed-value fields with selects;
- add number inputs for all numeric fields in the tests;
- add reusable local helpers `numberChange`, `textChange`, `selectChange`;
- render YAML textarea read-only unless `advancedYamlEnabled` state is true;
- on YAML textarea change in advanced mode, update YAML text and attempt `yamlToCoreForm` sync inside a try/catch.

Keep the UI dense and operational. Do not add landing-page or marketing-style explanation blocks.

- [ ] **Step 4: Add card editors for cranes and zones**

In `ConfigurationPage.tsx`, render:

- crane cards from `form.cranes`;
- material zone cards from `form.materialZones`;
- work zone cards from `form.workZones`;
- forbidden zone cards from `form.forbiddenZones`;
- Add/remove buttons for each list;
- inputs for ids, coordinates, sizes, z ranges, load type strings.

Use stable button labels such as `添加塔吊`, `删除塔吊 C1`, `添加物料区`, `添加作业区`, `添加禁区`.

- [ ] **Step 5: Add styles**

Update `frontend/src/styles.css`:

- make config layout a single scrollable work area with a responsive two-column grid;
- add `.workbench-config-sections`, `.workbench-config-section`, `.workbench-field-grid`, `.workbench-inline-fields`, `.workbench-card-list`, `.workbench-zone-card`, `.workbench-help`;
- ensure labels and buttons do not overflow at desktop widths;
- keep cards at 8px border radius or less.

- [ ] **Step 6: Run tests and verify they pass**

Run:

```bash
cd frontend && npm test -- tests/workbench/configuration.test.tsx
```

Expected: pass.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/workbench/ConfigurationPage.tsx frontend/src/styles.css frontend/tests/workbench/configuration.test.tsx
git commit -m "feat(desktop): make config page form first"
```

## Task 3: Improve API Error Display

**Files:**
- Modify: `frontend/src/api/rest.ts`
- Modify: `frontend/src/components/workbench/ConfigurationPage.tsx`
- Test: `frontend/tests/rest.test.ts`
- Test: `frontend/tests/workbench/configuration.test.tsx`

- [ ] **Step 1: Write failing tests for detailed error display**

Add to `frontend/tests/workbench/configuration.test.tsx`:

```ts
it("shows field-specific validation errors in Chinese", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/desktop/templates")) {
        return ok({ items: [{ template_id: "demo", name: "Demo", path: "configs/demo.yaml" }] });
      }
      if (url.includes("/desktop/config/render")) return ok({ yaml_text: renderYaml });
      if (url.includes("/scenarios/validate")) {
        return new Response(
          JSON.stringify({
            code: "M_E_CONFIG_INVALID",
            data: null,
            message: "Input should be a valid integer, unable to parse string as an integer",
            details: {
              field_path: "experiment.llm.max_retries",
              errors: [
                {
                  loc: ["experiment", "llm", "max_retries"],
                  msg: "Input should be a valid integer, unable to parse string as an integer",
                  input: "1.0",
                },
              ],
            },
          }),
          { status: 422, headers: { "content-type": "application/json" } },
        );
      }
      throw new Error(`unexpected URL ${url}`);
    }),
  );

  renderWorkbench();
  fireEvent.click(screen.getByRole("button", { name: "加载模板" }));
  await waitFor(() => expect(yamlTextarea().value).toContain("scenario:"));
  fireEvent.click(screen.getByRole("button", { name: "校验配置" }));

  await screen.findByText(/字段 experiment\\.llm\\.max_retries 需要整数/);
});
```

- [ ] **Step 2: Run test and verify it fails**

Run:

```bash
cd frontend && npm test -- tests/workbench/configuration.test.tsx
```

Expected: fail because `ConfigurationPage` still uses raw `error.message`.

- [ ] **Step 3: Use formatted errors in configuration actions**

Update `ConfigurationPage.tsx`:

- import `formatConfigError`;
- replace `errorMessage(error)` calls for validation, render, and patch failures with `formatConfigError(error)`;
- keep network errors readable.

If `ApiClientError` details are already stored in the error object, use them. If not, update `frontend/src/api/rest.ts` or `frontend/src/types/api.ts` so `formatConfigError` can read `code`, `message`, `details`, and `status`.

- [ ] **Step 4: Run tests and verify they pass**

Run:

```bash
cd frontend && npm test -- tests/workbench/configuration.test.tsx tests/rest.test.ts
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api/rest.ts frontend/src/types/api.ts frontend/src/components/workbench/ConfigurationPage.tsx frontend/tests/rest.test.ts frontend/tests/workbench/configuration.test.tsx
git commit -m "fix(desktop): show field specific config errors"
```

## Task 4: Verification, Package Refresh, And Push

**Files:**
- Modify: docs only if implementation discoveries require small usage notes.

- [ ] **Step 1: Run focused frontend tests**

Run:

```bash
cd frontend && npm test -- tests/workbench/configModel.test.ts tests/workbench/configuration.test.tsx tests/workbench/run.test.tsx tests/state/workbench.test.ts
```

Expected: pass.

- [ ] **Step 2: Run broader frontend checks**

Run:

```bash
cd frontend && npm run typecheck && npm test && npm run build
```

Expected: pass.

- [ ] **Step 3: Run backend desktop checks**

Run:

```bash
.venv/bin/python -m pytest backend/app/tests/test_desktop_routes.py backend/app/tests/test_desktop_service.py backend/app/tests/test_desktop_runtime_dependencies.py -q
```

Expected: pass.

- [ ] **Step 4: Run package build**

Run:

```bash
cd frontend && ELECTRON_MIRROR=https://npmmirror.com/mirrors/electron/ npm run desktop:pack
```

Expected: pass and refresh `frontend/release/mac-arm64/Multi Crane Workbench.app`.

- [ ] **Step 5: Inspect package smoke resources**

Run:

```bash
"frontend/release/mac-arm64/Multi Crane Workbench.app/Contents/Resources/.venv/bin/python" -m uvicorn --version
test -f "frontend/release/mac-arm64/Multi Crane Workbench.app/Contents/Resources/.venv/lib/python3.13/site-packages/certifi/cacert.pem"
find "frontend/release/mac-arm64/Multi Crane Workbench.app/Contents/Resources" \( -name ".env.local" -o -name ".claude" -o -name ".worktrees" -o -name "runs" \) -print
```

Expected: uvicorn version prints, certifi file exists, find prints nothing.

- [ ] **Step 6: Whitespace and final status**

Run:

```bash
git diff --check
git status --short --branch
```

Expected: only `.claude/` and `frontend/release/` remain untracked; no unstaged tracked changes after commits.

- [ ] **Step 7: Push main**

Run:

```bash
git push origin main
```

Expected: remote `main` receives all commits.
