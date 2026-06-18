# Multifloor Construction Semantics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade the crane simulation from flat pickup/dropoff points to backward-compatible construction-site vertical semantics for floors, platforms, hook targets, safe transport height, recording, and 3D display.

**Architecture:** Keep existing YAML and runtime contracts intact by adding optional fields rather than replacing old fields. Task generation resolves zone-level semantics into TaskPoint fields, the state machine consumes those resolved fields, Recorder exports them, and the frontend reads the same optional fields from config, manifest, and SimFrame task payloads.

**Tech Stack:** Python 3, Pydantic v2, pytest, TypeScript, React, Three.js, Vitest.

---

### Task 1: Backend Schema

**Files:**
- Modify: `backend/app/schemas/config.py`
- Modify: `backend/app/schemas/task.py`
- Test: `backend/app/tests/test_config_schema.py`
- Test: `backend/app/tests/test_task_schema.py`

- [x] Add optional semantic fields to `ZoneConfig` while keeping old zone geometry fields.
- [x] Add optional `BuildingConfig` and `SiteConfig.buildings`.
- [x] Add optional semantic fields to `TaskPoint`; keep `z` as the compatibility height used by older consumers.
- [x] Run: `.\.venv\Scripts\python.exe -m pytest backend/app/tests/test_config_schema.py backend/app/tests/test_task_schema.py -q`

### Task 2: Task Generation

**Files:**
- Modify: `backend/app/sim/task_generation.py`
- Test: `backend/app/tests/test_task_generation.py`

- [x] Add tests for ground pickup plus 20m floor dropoff semantic fields.
- [x] Add tests for hook target above surface and old `z_range_m` compatibility.
- [x] Add an unreachable-floor test that checks `point_height_unreachable` and readable details.
- [x] Implement `resolve_zone_vertical_semantics(zone, load_size_m, fallback_z, zone_type)`.
- [x] Keep radius checks XY-only and validate hook target against crane hook world min/max.
- [x] Run: `.\.venv\Scripts\python.exe -m pytest backend/app/tests/test_task_generation.py -q`

### Task 3: Task State Machine

**Files:**
- Modify: `backend/app/sim/task_state_machine.py`
- Test: `backend/app/tests/test_task_state_machine.py`

- [x] Add tests proving attach/release use `hook_target_z_m` rather than `load_center_z_m`.
- [x] Add tests proving lift requires max pickup approach, dropoff approach, and configured safe transport height.
- [x] Implement `point_hook_target_z`, `point_surface_z`, and `point_approach_z`.
- [x] Add release event semantic details.
- [x] Run: `.\.venv\Scripts\python.exe -m pytest backend/app/tests/test_task_state_machine.py -q`

### Task 4: Recorder

**Files:**
- Modify: `backend/app/schemas/recorder.py`
- Modify: `backend/app/sim/recorder.py`
- Test: `backend/app/tests/test_recorder.py`

- [x] Add nullable semantic task columns to `TaskParquetRow`.
- [x] Preserve SimFrame task queue payloads with new TaskPoint fields.
- [x] Verify manifest site includes buildings through existing site passthrough.
- [x] Run: `.\.venv\Scripts\python.exe -m pytest backend/app/tests/test_recorder.py -q`

### Task 5: Frontend Config UI

**Files:**
- Modify: `frontend/src/workbench/types.ts`
- Modify: `frontend/src/workbench/configModel.ts`
- Modify: `frontend/src/components/workbench/ConfigurationPage.tsx`
- Test: `frontend/tests/workbench/configModel.test.ts`
- Test: `frontend/tests/workbench/configuration.test.tsx`

- [x] Add zone semantic form fields and YAML round trip support.
- [x] Change defaults to ground material plus elevated floor work zone.
- [x] Add a multifloor construction preset action.
- [x] Run focused Vitest files for config model and configuration page.

### Task 6: Frontend 3D and Panels

**Files:**
- Modify: `frontend/src/types/config.ts`
- Modify: `frontend/src/types/sim.ts`
- Modify: `frontend/src/three/geometry/zones.ts`
- Add: `frontend/src/three/geometry/floors.ts`
- Modify: `frontend/src/three/ThreeSceneController.ts`
- Modify: `frontend/src/components/panels/TaskStatusPanel.tsx`
- Test: `frontend/tests/three/geometry.test.ts`
- Test: `frontend/tests/three/controller.test.ts`
- Test: `frontend/tests/panels.test.tsx`

- [x] Render zones at `surface_z_m` when present.
- [x] Render building floors from manifest/config and infer simple floor plates from zones when building data is missing.
- [x] Display task floor and height fields in the task status panel.
- [x] Run focused Vitest files for Three geometry/controller and panels.

### Task 7: Demo Config and Acceptance

**Files:**
- Add: `configs/multifloor_construction_demo.yaml`

- [x] Add a four-crane, six-floor demo with ground/truck pickup and floor/roof dropoff zones.
- [x] Validate the old `configs/deepseek_demo_4x2_manual.yaml`.
- [x] Validate the new `configs/multifloor_construction_demo.yaml`.
- [x] Run related backend and frontend tests.
- [x] Review diff and commit the completed work.

## Verification

- `.\.venv\Scripts\python.exe -m pytest -q` -> 1113 passed, 3 skipped.
- `npm test` -> 26 test files passed, 223 tests passed.
- `npm run typecheck` -> passed.
- `npm run build` -> passed.
- Old demo local run: `scripts\run_episode.py --config configs\deepseek_demo_4x2_manual.yaml --runner local --output-json`.
- New demo local run: `scripts\run_episode.py --config configs\multifloor_construction_demo.yaml --runner local --output-json`.
- Browser visual smoke: desktop and mobile screenshots rendered nonblank multi-floor scene; `floors`, `floor:tower_a:level_3`, `floor:tower_a:level_5`, `floor:tower_a:level_7`, ground material zone, and roof work zone were present.
