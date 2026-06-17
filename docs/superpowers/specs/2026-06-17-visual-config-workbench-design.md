# Visual Configuration Workbench Design

## Goal

Turn the desktop configuration page from a YAML-first developer surface into a form-first visual configuration workflow. Ordinary users should be able to load a template, adjust common crane simulation fields, validate the result, and run without editing YAML.

## Scope

This phase improves the existing React desktop workbench configuration page. It keeps the backend YAML contracts and validation authority intact, but expands the frontend form model, makes fixed-value fields selectable, makes numeric fields type-safe, introduces structured list editors for high-risk YAML sections, and demotes YAML to an advanced preview/editor.

This phase does not build a full generic JSON-schema form generator, visual map editor, polygon drawing tool, final provider credential manager, or complete Windows packaging flow. It should produce a usable first version that reduces the common YAML indentation/type errors seen in the current app.

## User Experience

The page should have a clear operational shape:

- top toolbar: load template, validate config, reset from template, save draft if available, and toggle advanced YAML editing;
- structured tabs or sections for Basic, Site, Cranes, Zones, Tasks, Weather/Risk, LLM/Output, and Advanced YAML;
- YAML visible as generated preview by default;
- YAML editable only after the user explicitly enables advanced editing;
- validation feedback shown with field path, Chinese explanation, current value when available, and suggested fix when known.

The main workflow is:

1. User loads a template.
2. App extracts a `CoreExperimentForm` from YAML.
3. User edits form fields.
4. App regenerates YAML automatically or with a clearly named sync action.
5. User validates.
6. Backend remains the final authority for correctness.

If the user edits YAML in advanced mode:

1. App parses YAML.
2. App tries to extract form values.
3. If parsing/extraction succeeds, form state updates.
4. If parsing/extraction or backend validation fails, the YAML text remains, form state is not polluted with invalid values, and the user sees a field-specific error.

## Field Coverage

First-version visual fields should cover the common template fields:

- IDs and seeds: `scenario.scenario_id`, `experiment.experiment_id`, `scenario.seed`, `experiment.seed`.
- Simulation: `experiment.sim.duration_s`, `dt`, `min_duration_s`, `physics_hz`, `controller_hz`, `llm_decision_interval_s`, `stop_when_all_tasks_done`.
- Site boundary: `scenario.site.coordinate_system`, `x_min`, `x_max`, `y_min`, `y_max`, `z_min`, `z_max`.
- Layout: `scenario.layout.mode`, `num_cranes`, `overlap_level`, `height_strategy`, `coverage_target`, `slew_mode_default`, `max_sampling_attempts`.
- Cranes: `scenario.cranes[]` entries with `crane_id`, `model_id`, `base`, `mast_height_m`, `theta_init_deg`, `slew.mode`.
- Zones: `material_zones`, `work_zones`, and `forbidden_zones` with box-style fields first: `zone_id`, `type`, `center`, `size`, `z_range_m`, and load type lists.
- Tasks: `generation_mode`, `num_tasks_per_crane`, queue delays, attach/release delays, and task state-machine timeout fields.
- Weather/risk: wind speed, gust speed, direction, visibility, risk thresholds, and geometry envelope radii.
- LLM/output: `enabled`, `provider`, `model`, `base_url`, `api_key_env`, `temperature`, `timeout_s`, `max_retries`, `max_consecutive_failures`, fallback and structured output modes, context and summarizer fields, output run root and save flags.

Fixed-value fields should be rendered as select controls using values accepted by the backend. Provider values should not include unsupported labels unless the backend enum is extended in the same change. Numeric fields should use number inputs and should store numbers in form state, not strings.

## Structured Editors

Array-like YAML sections should become cards or compact tables:

- `scenario.cranes`: add, remove, duplicate, and edit each crane.
- `scenario.site.material_zones`: add/remove/edit box zones and supported load types.
- `scenario.site.work_zones`: add/remove/edit box zones and accepted load types.
- `scenario.site.forbidden_zones`: add/remove/edit box forbidden zones.

The first version can preserve polygon zones in YAML without a full point editor, but it must not silently delete or corrupt unsupported zone fields. Editing a supported field should patch only that field and preserve unknown siblings.

## Tooltips And Help Text

Every visible field should have concise help text available near the control. The help text should explain:

- what the field controls;
- unit, if any;
- default or typical value;
- valid type/range;
- common invalid examples for risky fields.

Use restrained help UI suitable for a dense operational workbench. Do not add long in-page tutorials.

## YAML Handling

YAML should remain visible because it is useful for experts and debugging, but it should not be the main path:

- default mode: generated YAML preview, read-only;
- advanced mode: editable textarea;
- manual YAML edits trigger parse/type extraction feedback;
- invalid YAML should not overwrite the current valid form state;
- backend validation errors should map to a readable field path and Chinese message.

## Error Handling

Replace generic messages such as `Input should be a valid integer, unable to parse string as an integer` with a readable summary:

```text
字段 experiment.llm.max_retries 需要整数
当前值: "1.0"
建议: 改为 1
```

If a backend error includes `details.field_path`, show that path. If it includes `details.errors`, use the first Pydantic error location. If neither exists, show the raw message as a fallback.

## Architecture

Keep the existing backend APIs:

- `GET /desktop/templates`
- `POST /desktop/config/render`
- `POST /desktop/config/patch`
- `POST /scenarios/validate`

Add frontend-only form utilities around the existing `frontend/src/workbench/configModel.ts`:

- extend `CoreExperimentForm` and nested item types;
- extract nested sections from YAML while preserving defaults;
- generate dotted-path patches for all supported fields;
- format API validation errors for display;
- keep unsupported YAML siblings intact through backend patching.

The existing backend remains the final config authority. Add backend changes only if required to improve error details without changing the public config schema.

## Testing

Tests should cover:

- form extraction from `configs/deepseek_demo_4x2_manual.yaml`-like YAML;
- generated patches contain numbers as numbers, booleans as booleans, and fixed values as backend-supported enum values;
- invalid API error details format into field-specific Chinese messages;
- configuration page renders multiple visual sections/tabs;
- editing numeric/select fields sends typed patches;
- advanced YAML can be toggled and defaults to preview/read-only;
- existing validation, run, and Electron helper tests remain passing.

## Acceptance Criteria

- A normal user can configure the common demo without editing YAML.
- Numeric fields cannot accidentally send string values from the visual form.
- Fixed-value fields use selects or toggles, not free text.
- Cranes and common box zones can be edited without touching YAML.
- YAML remains available as advanced preview/editor.
- Validation errors identify the field path whenever backend details allow it.
- Backend validation remains authoritative.
- The app builds, frontend tests pass, focused backend desktop tests pass, and `git diff --check` passes.
