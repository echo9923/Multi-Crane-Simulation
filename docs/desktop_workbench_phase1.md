# Desktop Workbench Phase 1

This document records the Phase 1 developer workflow for the desktop workbench. Phase 1 is a local development workbench, not a final Windows or macOS packaged release. It expects the repository Python virtualenv and frontend dependencies to already exist.

## Scope

Phase 1 connects the existing simulation stack into a desktop-oriented workbench:

- Electron starts the FastAPI backend from the repository `.venv`.
- React opens as a tabbed workbench served by the Vite dev server.
- A user can load a template, edit core experiment fields and advanced YAML, validate the config, start one episode, watch the 3D view, inspect run state, and download run artifacts.
- The backend and frontend still run as development services. Packaging, installer signing, auto-update, and final platform release behavior are outside Phase 1.

## Development Startup

Start the Vite dev server from the repository root:

```bash
cd frontend && npm run dev
```

In another terminal, start Electron:

```bash
cd frontend && npm run desktop:dev
```

`desktop:dev` launches `electron/dev.mjs`, which sets `VITE_DEV_SERVER_URL=http://127.0.0.1:5173` in Node before importing the main Electron process. This keeps the command cross-platform for Unix and Windows npm shells.

Electron resolves the project root, chooses an available backend port, starts FastAPI with `.venv/bin/python -m uvicorn backend.app.main:app`, passes the selected port through `MULTI_CRANE_BACKEND_PORT`, waits for `/health`, then loads the Vite dev server with desktop API and WebSocket runtime parameters. FastAPI enables narrowly scoped CORS for local renderer origins such as `http://127.0.0.1:5173` and `http://localhost:5173`; arbitrary remote origins are not allowed.

For non-dev `npm run desktop`, build the frontend first with `npm run build`. Electron reads `frontend/dist/index.html`, injects the desktop runtime config into `frontend/dist/desktop-index.html`, rewrites Vite root-relative asset URLs to `file://` URLs under `frontend/dist/assets`, and loads that generated file. The build output must remain available while the desktop shell is running.

## Workbench Tabs And Module Mapping

The Phase 1 shell keeps the current modules organized instead of bypassing them. The tab mapping is intentionally compact:

| Tab | Current responsibility | Module references |
| --- | --- | --- |
| Experiment | Experiment summary, selected scenario, validation status, current episode context. | A/B plus top-level run context. |
| Configuration | Template loading, core form patches, advanced YAML editing, config validation, LLM provider settings. | A/B/D/E/G/H plus config contracts used by downstream modules. |
| Run | Validate, start, pause, resume, stop, and refresh one interactive episode. Shows the active execution pipeline. | C/D/E/F/G/H/I/L are shown as the Phase 1 run pipeline. |
| 3D Visualization | Live or replay 3D scene, status panels, timeline, WebSocket-driven updates. | M/N plus runtime data from C through L. |
| Data/Export | Run list, episode file list, zip download, run directory opening, research data entry points. | K/O/P are preserved as research data and training pipeline entry points; L/M provide recorded artifacts and APIs. |
| Settings | Desktop runtime addresses, backend environment, run roots, supported LLM providers. | Development and operations surface for all modules. |

Modules A-P remain useful in the desktop workflow. Phase 1 exposes only the first developer-facing path through them; later phases can deepen each tab rather than replacing the module structure.

## Secret Rule

Raw API keys must not be written to draft YAML, git files, run summaries, logs, or downloaded archives. Config should reference an environment variable name with `api_key_env`, for example:

```yaml
llm:
  provider: deepseek
  api_key_env: DEEPSEEK_API_KEY
```

Keep the actual key in the local shell environment or another approved secret store.

## Verification Commands

Backend desktop service and route checks:

```bash
.venv/bin/python -m pytest backend/app/tests/test_desktop_service.py backend/app/tests/test_desktop_routes.py -v
```

Frontend typecheck:

```bash
cd frontend && npm run typecheck
```

Focused frontend workbench tests:

```bash
cd frontend && npm test -- tests/workbench/export-settings.test.tsx tests/workbench/run.test.tsx tests/workbench/configuration.test.tsx tests/workbench/shell.test.tsx tests/workbench/configModel.test.ts tests/state/workbench.test.ts tests/electron/backend.test.ts
```

Frontend build:

```bash
cd frontend && npm run build
```

Whitespace check:

```bash
git diff --check
```

Broader regression commands:

```bash
.venv/bin/python -m pytest
cd frontend && npm run typecheck && npm test
```

If a broader regression fails because an external API key or environment dependency is not present, record the failing test name and treat it as environmental until reproduced with the required secret or dependency configured.

## Task 10 Verification Log

Commands run for Task 10:

- `.venv/bin/python -m pytest backend/app/tests/test_desktop_service.py backend/app/tests/test_desktop_routes.py -v` - passed, 20 tests.
- `cd frontend && npm run typecheck` - passed.
- `cd frontend && npm test -- tests/workbench/export-settings.test.tsx tests/workbench/run.test.tsx tests/workbench/configuration.test.tsx tests/workbench/shell.test.tsx tests/workbench/configModel.test.ts tests/state/workbench.test.ts` - passed, 6 files and 35 tests.
- `cd frontend && npm run build` - passed.
- `git diff --check` - passed.

Additional regression commands run:

- `.venv/bin/python -m pytest` - 1063 passed, 2 skipped, 1 failed. The failing test was `backend/app/tests/test_external_deepseek_production.py::test_external_deepseek_v4_flash_production_generates_motion` because `DEEPSEEK_API_KEY` was not configured in `.env.local` or the environment.
- `cd frontend && npm test` - passed, 26 files and 175 tests.
