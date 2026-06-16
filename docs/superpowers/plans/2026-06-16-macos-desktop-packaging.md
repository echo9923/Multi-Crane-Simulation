# macOS Desktop Packaging Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a macOS Electron packaging path for the Phase 1 desktop workbench.

**Architecture:** Use Electron Builder from `frontend/` to produce a local macOS `.app` package. Keep FastAPI as the backend runtime, but make Electron path/Python resolution work in both development and packaged app layouts.

**Tech Stack:** Electron 42, Electron Builder, Node ESM, React/Vite, FastAPI/Python, Vitest, pytest.

---

## Task 1: Packaging Config And Resource Resolution

**Files:**
- Modify: `frontend/package.json`
- Modify: `frontend/package-lock.json`
- Modify: `frontend/electron/backend.mjs`
- Modify: `frontend/electron/backend.d.mts`
- Modify: `frontend/electron/main.mjs`
- Test: `frontend/tests/electron/backend.test.ts`

- [ ] **Step 1: Write failing Electron packaging tests**

Add tests that describe:

- packaged app resource roots resolve from `process.resourcesPath`;
- `resolvePythonPath()` prefers `MULTI_CRANE_PYTHON`;
- packaged resource `.venv` paths are supported;
- app resource inclusion excludes `.env.local`, `runs`, `.worktrees`, and `.claude`.

Run:

```bash
cd frontend && npm test -- tests/electron/backend.test.ts
```

Expected: tests fail because helpers/config do not exist yet.

- [ ] **Step 2: Implement path and Python helpers**

Update Electron helpers so:

- dev mode keeps current repo-root behavior;
- packaged mode can resolve backend resources under Electron Builder resources;
- Python path priority is explicit env, packaged `.venv`, then repo `.venv`.

Keep helper functions pure enough to test without launching Electron.

- [ ] **Step 3: Add Electron Builder configuration**

Add scripts:

```json
"desktop:pack": "npm run build && electron-builder --mac --dir",
"desktop:dist": "npm run build && electron-builder --mac"
```

Add build config that packages required files/resources and excludes secrets/output directories.

- [ ] **Step 4: Verify and commit**

Run:

```bash
cd frontend && npm test -- tests/electron/backend.test.ts
cd frontend && npm run typecheck
git diff --check
```

Commit:

```bash
git add frontend/package.json frontend/package-lock.json frontend/electron/backend.mjs frontend/electron/backend.d.mts frontend/electron/main.mjs frontend/tests/electron/backend.test.ts
git commit -m "feat(desktop): add mac packaging configuration"
```

## Task 2: Packaging Docs And Local Package Build

**Files:**
- Modify: `docs/desktop_workbench_phase1.md`
- Create or Modify: `docs/desktop_packaging.md`

- [ ] **Step 1: Document packaging commands and limits**

Document:

- `cd frontend && npm run desktop:pack`;
- `cd frontend && npm run desktop:dist`;
- package output location;
- current Python runtime requirement;
- `MULTI_CRANE_PYTHON`;
- secret handling;
- next phase: backend binary / Windows EXE.

- [ ] **Step 2: Run package build**

Run:

```bash
cd frontend && npm run desktop:pack
```

Expected: Electron Builder creates an unpacked macOS app under `frontend/release` or `frontend/dist-*` depending on config.

- [ ] **Step 3: Run regression checks**

Run:

```bash
cd frontend && npm run typecheck && npm test && npm run build
.venv/bin/python -m pytest backend/app/tests/test_desktop_routes.py backend/app/tests/test_desktop_service.py -v
git diff --check
```

- [ ] **Step 4: Commit docs**

```bash
git add docs/desktop_workbench_phase1.md docs/desktop_packaging.md
git commit -m "docs(desktop): document mac packaging workflow"
```

