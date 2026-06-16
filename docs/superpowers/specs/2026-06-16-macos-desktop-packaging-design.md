# macOS Desktop Packaging Design

## Goal

Produce a macOS desktop package for the Phase 1 workbench that can be opened by double-clicking the Electron app on this development machine.

## Scope

This packaging pass creates a macOS Electron package around the existing Phase 1 desktop workbench. It includes the React build output, Electron main/preload code, project backend source, configs, and docs needed by the desktop shell.

This pass does not create a fully standalone Python-free Windows EXE. The packaged app still expects a usable Python environment to exist, preferring an explicit `MULTI_CRANE_PYTHON` path, then the repository `.venv`, then a bundled/adjacent `.venv` if present. A later packaging phase can replace that with a PyInstaller or Nuitka backend binary.

## Architecture

Electron Builder packages the frontend app from `frontend/`. The Electron main process resolves a project root in both development and packaged modes, starts FastAPI on a loopback port, serves the built renderer from a loopback static server, and injects runtime API/WebSocket settings.

The packaged app keeps the same security model as Phase 1:

- backend binds to `127.0.0.1`;
- renderer is loaded from a local loopback HTTP origin;
- FastAPI CORS allows only local renderer origins;
- desktop native file opening is constrained to allowed roots;
- API keys stay outside YAML/package artifacts and are referenced by `api_key_env`.

## Package Shape

The first deliverable is a macOS `.app` packaged by Electron Builder. A `.dmg` or zip may also be generated if the local toolchain supports it without signing/notarization.

The package should include:

- `frontend/dist/**`;
- `frontend/electron/**`;
- `backend/**`;
- `configs/**`;
- `pyproject.toml`;
- relevant docs for startup and limitations.

The package should not include:

- `.claude/`;
- `.env.local`;
- `runs/`;
- `.worktrees/`;
- raw API keys;
- frontend test artifacts.

## Backend Runtime Resolution

Packaged Electron must resolve Python predictably:

1. `MULTI_CRANE_PYTHON`, if set.
2. A packaged resource `.venv` if one exists beside app resources.
3. The repository `.venv` when running from a development checkout.
4. A platform fallback error message that explains how to set `MULTI_CRANE_PYTHON`.

This keeps the app usable on the current machine while making the next PyInstaller/backend-binary phase straightforward.

## Validation

Implementation must add tests for packaged path/resource resolution and package helper behavior. Verification must run:

- frontend Electron helper tests;
- frontend typecheck and unit tests;
- frontend production build;
- Electron Builder package command for macOS;
- backend desktop route/service tests.

Full backend regression can exclude the existing external DeepSeek production test when `DEEPSEEK_API_KEY` is not configured.

