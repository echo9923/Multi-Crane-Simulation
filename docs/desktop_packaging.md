# Desktop Packaging

This document records the current macOS desktop packaging workflow for the Phase 1 workbench. It is a local developer package path, not the final cross-platform installer plan.

## Commands

Run packaging commands from the repository root:

```bash
cd frontend && npm run desktop:pack
```

`desktop:pack` runs the production renderer build and then `electron-builder --mac --dir`. The `--dir` target creates an unsigned unpacked macOS app and should avoid signing and notarization requirements.

For a distributable macOS target, run:

```bash
cd frontend && npm run desktop:dist
```

`desktop:dist` runs the same production renderer build and then `electron-builder --mac`. The current `package.json` requests `dir` and `dmg` macOS targets. DMG creation may depend on the local macOS signing/notarization setup; use `desktop:pack` for the repeatable unsigned local package check.

## Output Location

Electron Builder writes package artifacts under:

```text
frontend/release/
```

The unpacked app path is architecture-dependent. On Apple Silicon it is normally:

```text
frontend/release/mac-arm64/Multi Crane Workbench.app
```

On Intel macOS it is normally:

```text
frontend/release/mac/Multi Crane Workbench.app
```

Inside the app, Electron resources live under:

```text
Multi Crane Workbench.app/Contents/Resources/
```

The current resource layout is expected to include:

```text
Contents/Resources/.venv/bin/python
Contents/Resources/project/backend/app/core/secret_resolver.py
Contents/Resources/project/configs/deepseek_demo_4x2_manual.yaml
Contents/Resources/project/pyproject.toml
```

## Packaged Contents

The package includes the frontend production build, Electron main/preload code, backend source, configs, `pyproject.toml`, and the local `.venv` copied into Electron resources.

The package intentionally excludes local secrets and generated output. The Electron Builder `extraResources` filters exclude:

```text
.env*
.claude/
.worktrees/
runs/
__pycache__/
*.pyc
.pytest_cache/
*.pem
*.p12
*.key
*token*.json
*credentials*.json
```

## Python Runtime

The project declares `requires-python = ">=3.9"` in `pyproject.toml`. The current macOS package is not a Python-free application: it launches FastAPI with a Python interpreter and backend source code.

Electron resolves Python in this order:

1. `MULTI_CRANE_PYTHON`, when set to a non-empty executable path.
2. `Contents/Resources/.venv/bin/python` in a packaged macOS app.
3. The repository `.venv/bin/python` during development checkout runs.

If the packaged `.venv` is missing or incompatible, set `MULTI_CRANE_PYTHON` before launching the app so Electron can start the backend with another interpreter:

```bash
MULTI_CRANE_PYTHON=/absolute/path/to/python open "frontend/release/mac-arm64/Multi Crane Workbench.app"
```

For double-click launches on macOS, environment variables may need to be exported into the GUI launch environment, for example with `launchctl setenv MULTI_CRANE_PYTHON /absolute/path/to/python`, before opening the app from Finder.

Because `.venv` contains platform-specific Python packages, rebuild the package on the target macOS architecture. Do not treat the copied `.venv` as a portable Windows or Linux runtime.

## Secret Handling

Raw API keys must stay out of YAML files, git files, package resources, run summaries, logs, and downloaded archives. Config files should reference the name of an environment variable:

```yaml
llm:
  provider: deepseek
  api_key_env: DEEPSEEK_API_KEY
```

The actual value should be supplied by the shell or approved local secret store. `.env.local` and other `.env*` files are excluded from package resources, so the app should not depend on those files being copied into `Contents/Resources`.

The backend resolves secrets through environment-variable references such as `api_key_env`. If a package run needs provider credentials, set the relevant provider environment variable before launching the app.

## Current Limits

The current package is useful for local macOS verification, but it is not a final release artifact:

- The app is unsigned and unpacked when built with `desktop:pack`.
- `desktop:dist` may produce a DMG only when the local macOS packaging toolchain allows it.
- The backend is still Python source launched by a Python interpreter.
- The copied `.venv` is local-machine and architecture specific.
- There is no Windows EXE in this phase.
- There is no installer auto-update, notarization workflow, or bundled backend binary yet.

## Next Phase

The next packaging phase should replace the source-plus-venv backend runtime with a backend binary, such as a PyInstaller or Nuitka build, and add a Windows packaging path that produces a Windows EXE. That phase should also revisit installer signing, notarization, and platform-specific secret storage.

## Verification

After packaging, inspect the unpacked app resources and run the regression checks:

```bash
cd frontend && npm run desktop:pack
cd frontend && npm run typecheck && npm test && npm run build
.venv/bin/python -m pytest backend/app/tests/test_desktop_routes.py backend/app/tests/test_desktop_service.py -v
git diff --check
```
