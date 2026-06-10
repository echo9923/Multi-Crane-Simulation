# Module B Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Implement module B end to end: crane model library, manual and auto layout resolution, resolved `CraneConfig[]`, layout diagnostics, reachability precheck, and acceptance tests.

**Architecture:** Add module B domain schemas in `backend/app/schemas/crane.py`, pure simulation/layout modules under `backend/app/sim/`, and call the module B resolver from `backend/app/core/config_resolver.py`. Keep `CraneConfig` immutable static configuration and keep all runtime state, task generation, physics, controller, risk, and recorder behavior out of module B.

**Tech Stack:** Python 3.9+, Pydantic v2, pytest, standard-library geometry/random/math only.

---

### Task 1: Crane Model Library

**Files:**
- Create: `backend/app/schemas/crane.py`
- Create: `backend/app/sim/crane_model.py`
- Test: `backend/app/tests/test_crane_model.py`
- Test: `backend/app/tests/test_layout_errors.py`

- [x] Write failing tests for builtin model loading, YAML override/new model, duplicate model IDs, radian conversion, capacity/moment helpers, invalid model validation, and `LAY_E_003` error mapping.
- [x] Run `python3 -m pytest backend/app/tests/test_crane_model.py backend/app/tests/test_layout_errors.py -v` and verify failures are for missing module B code.
- [x] Implement `CraneModelSpec`, `CraneModelLibraryError`, builtin `generic_flat_top_55m`, `build_crane_model_library()`, and `crane_model_error_to_config_error()`.
- [x] Re-run the two test files and keep them green.

### Task 2: Manual Layout Validation

**Files:**
- Modify: `backend/app/schemas/crane.py`
- Create: `backend/app/sim/layout_geometry.py`
- Create: `backend/app/sim/layout.py`
- Test: `backend/app/tests/test_manual_layout.py`
- Test: `backend/app/tests/test_layout_errors.py`

- [x] Write failing tests for valid manual layout, count mismatch, duplicate crane ID, unknown model, base out of boundary, box forbidden zone, mast height range, root z boundary, base distance, continuous slew success, limited slew failure, and arbitrary crane IDs.
- [x] Run `python3 -m pytest backend/app/tests/test_manual_layout.py backend/app/tests/test_layout_errors.py -v` and verify red.
- [x] Implement `LayoutResolutionError`, `ManualLayoutValidationResult`, `validate_manual_layout()`, box/polygon point checks as required, base distance diagnostics, and `layout_error_to_config_error()`.
- [x] Re-run manual layout and layout error tests.

### Task 3: CraneConfig Resolution And Resolved Layout

**Files:**
- Modify: `backend/app/schemas/crane.py`
- Modify: `backend/app/schemas/resolved_config.py`
- Modify: `backend/app/sim/layout.py`
- Modify: `backend/app/core/config_resolver.py`
- Test: `backend/app/tests/test_crane_config_resolution.py`
- Test: `backend/app/tests/test_resolved_config.py`

- [x] Write failing tests that manual `resolve_config()` produces `resolved.layout.resolved_cranes`, `layout_diagnostics`, and either `model_library_snapshot` or embedded model payload; root/hook/angle values are correct; pair diagnostics count is `N*(N-1)/2`; hash changes when base or mast height changes; secrets are not persisted.
- [x] Update old module A tests that intentionally asserted manual/auto did not generate cranes so they now describe current M0/M1 behavior.
- [x] Run targeted tests and verify red.
- [x] Implement `CraneConfig`, `CranePairLayoutDiagnostic`, `LayoutDiagnostics`, `create_crane_config()`, `build_layout_diagnostics()`, `resolve_layout_config()`, and resolver integration.
- [x] Re-run targeted tests.

### Task 4: Auto Layout Generator

**Files:**
- Create: `backend/app/sim/auto_layout.py`
- Modify: `backend/app/sim/layout.py`
- Modify: `backend/app/core/config_resolver.py`
- Test: `backend/app/tests/test_auto_layout.py`

- [x] Write failing tests for deterministic same seed, usually different different seed, quantity, boundary, forbidden zones, base distance, low versus high overlap, staggered height delta, mixed height semantics, coverage score differences, impossible site `LAY_E_001`, and `num_cranes=2/6`.
- [x] Run `python3 -m pytest backend/app/tests/test_auto_layout.py -v` and verify red.
- [x] Implement deterministic candidate generation using `seeds.layout`, model/mast sampling, constraint filtering, fixed overlap ratio `intersection_area / min(area_i, area_j)`, coverage score, height strategy score, quality score, failure counts, and Task 3 factory reuse.
- [x] Re-run auto layout tests.

### Task 5: Reachability Precheck

**Files:**
- Create: `backend/app/sim/layout_reachability.py`
- Modify: `backend/app/sim/auto_layout.py`
- Test: `backend/app/tests/test_layout_reachability.py`

- [x] Write failing tests for reachable material/work zones, unreachable radius, unreachable hook height, overweight load type, missing load type references, material/work load-type mismatch, multi-crane reports, manual warning-only behavior, and no `Task` runtime fields.
- [x] Run `python3 -m pytest backend/app/tests/test_layout_reachability.py -v` and verify red.
- [x] Implement `LayoutReachabilityReport`, representative point extraction for box/polygon zones, load capacity checks via `CraneModelSpec.capacity_at_radius_t`, and auto-layout penalty/failure hook.
- [x] Re-run reachability tests.

### Task 6: Acceptance And Documentation Gates

**Files:**
- Modify: `backend/app/tests/test_moduleA_acceptance.py`
- Create or modify: `backend/app/tests/test_moduleB_acceptance.py`
- Modify: docs only if implementation reveals contract drift.

- [x] Write/adjust acceptance tests covering module B docs, implementation boundary imports, M0/M1 exit criteria, `LAY_E_001/002/003`, and no runtime module coupling.
- [x] Run M0 tests:

```bash
python3 -m pytest backend/app/tests/test_crane_model.py -v
python3 -m pytest backend/app/tests/test_manual_layout.py -v
python3 -m pytest backend/app/tests/test_crane_config_resolution.py -v
python3 -m pytest backend/app/tests/test_layout_errors.py -v
python3 -m pytest backend/app/tests/test_resolved_config.py -v
```

- [x] Run M1 tests:

```bash
python3 -m pytest backend/app/tests/test_auto_layout.py -v
python3 -m pytest backend/app/tests/test_layout_reachability.py -v
```

- [x] Run full regression:

```bash
python3 -m pytest backend/app/tests -v
```

- [x] Run document checks:

```bash
find docs/moduleB -maxdepth 1 -name "*.md" -print | sort
rg -n "CraneModelSpec|CraneConfig|capacity_at_radius|LAY_E_001|LAY_E_002|LAY_E_003|resolved_cranes|layout_diagnostics|model_library_snapshot|hook_h_min_world_m|hook_h_max_world_m|overlap_ratio|quality_score" docs/moduleB
```

---

## Self-Review

This plan covers all six module B task documents: model library, manual validation, `CraneConfig` resolution, auto layout, reachability precheck, and acceptance. It preserves module boundaries by keeping runtime state, task generation, physics, controller, risk, recorder, and LLM out of module B.
