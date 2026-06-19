# Desktop Packaging

This document records the current Windows desktop packaging workflow for the Phase 1 workbench. It is a repeatable local Windows `win-unpacked` package path, not the final cross-platform installer plan.

## Commands

Run packaging commands from the repository root:

```powershell
cd frontend
npm run desktop:pack
```

`desktop:pack` runs the production renderer build and then:

```powershell
electron-builder --win --config.win.signAndEditExecutable=false --config.win.signExecutable=false --dir
```

The `--dir` target creates an unsigned unpacked Windows app and avoids Windows executable signing/editing requirements during local verification.

For the current distributable-script contract, run:

```powershell
cd frontend
npm run desktop:dist
```

`desktop:dist` runs the same production renderer build and then:

```powershell
electron-builder --win --config.win.signAndEditExecutable=false --config.win.signExecutable=false
```

The current `package.json` requests the Windows `dir` target, so `desktop:dist` also produces an unpacked Windows directory unless installer targets are added later. Use `desktop:pack` for the standard repeatable unsigned local package check.

If the Electron runtime download from GitHub times out, rerun the same package script with an Electron mirror:

```powershell
cd frontend
$env:ELECTRON_MIRROR = "https://npmmirror.com/mirrors/electron/"
npm run desktop:pack
```

If `frontend/release/win-unpacked` cannot be overwritten, close any running `Multi Crane Workbench.exe` processes and rerun the package command.

## Output Location

Electron Builder writes package artifacts under:

```text
frontend/release/
```

The current repeatable Windows artifact is:

```text
frontend/release/win-unpacked/Multi Crane Workbench.exe
```

Inside the unpacked app, Electron resources live under:

```text
frontend/release/win-unpacked/resources/
```

The current resource layout is expected to include:

```text
resources/.venv/Scripts/python.exe
resources/project/backend/app/core/secret_resolver.py
resources/project/configs/deepseek_demo_4x2_manual.yaml
resources/project/pyproject.toml
```

## Packaged Contents

The package includes the frontend production build, Electron main/preload code, backend source, configs, `pyproject.toml`, and the local `.venv` copied into Electron resources. Because `.venv` is copied as-is, rebuild from a clean dependency-synchronized Windows environment before sharing a package internally.

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

`certifi/cacert.pem` remains included from `.venv` so packaged HTTPS clients keep their certificate bundle.

## Python Runtime

The project declares `requires-python = ">=3.9"` in `pyproject.toml`. The current Windows package is not a Python-free application: it launches FastAPI with a Python interpreter and backend source code.

Electron resolves Python in this order:

1. `MULTI_CRANE_PYTHON`, when set to a non-empty executable path.
2. `resources/.venv/Scripts/python.exe` in a packaged Windows app.
3. `MULTI_CRANE_DEV_PROJECT_ROOT/.venv/Scripts/python.exe`, when that optional development checkout root is set for packaged-app troubleshooting.
4. The repository `.venv/Scripts/python.exe` during development checkout runs.

If the packaged `.venv` is missing or incompatible, set `MULTI_CRANE_PYTHON` before launching the app so Electron can start the backend with another interpreter:

```powershell
$env:MULTI_CRANE_PYTHON = "D:\path\to\python.exe"
& ".\frontend\release\win-unpacked\Multi Crane Workbench.exe"
```

When testing a packaged app on the same development machine, `MULTI_CRANE_DEV_PROJECT_ROOT` can point to the repository checkout as a fallback if the copied `.venv` is missing:

```powershell
$env:MULTI_CRANE_DEV_PROJECT_ROOT = "D:\codeproject\python\Multi-Crane-Simulation"
& ".\frontend\release\win-unpacked\Multi Crane Workbench.exe"
```

Because `.venv` contains platform-specific Python packages and absolute-environment assumptions from the build machine, rebuild the package on the target Windows environment. Do not treat the copied `.venv` as a portable runtime or as the final distribution architecture.

## Secret Handling

Raw API keys must stay out of YAML files, git files, package resources, run summaries, logs, and downloaded archives. Config files should reference the name of an environment variable:

```yaml
llm:
  provider: deepseek
  api_key_env: DEEPSEEK_API_KEY
```

The actual value should be supplied by the shell or approved local secret store. `.env.local` and other `.env*` files are excluded from package resources, so the app should not depend on those files being copied into `resources`.

The backend resolves secrets through environment-variable references such as `api_key_env`. If a package run needs provider credentials, set the relevant provider environment variable before launching the app.

## Current Limits

The current package is useful for local Windows verification, but it is not a final release artifact:

- The app is unsigned and unpacked when built with `desktop:pack`.
- `desktop:dist` currently uses the Windows `dir` target, not an installer target.
- The backend is still Python source launched by a Python interpreter.
- The copied `.venv` is local-machine and platform specific.
- macOS packaging config remains in `package.json`, but the npm script contract is the Windows `win-unpacked` path.
- There is no installer auto-update, code-signing workflow, notarization workflow, or bundled backend binary yet.

## Next Phase

The next packaging phase should replace the source-plus-venv backend runtime with a backend binary, such as a PyInstaller or Nuitka build, and add signed installer targets where needed. That phase should also revisit installer signing, notarization for macOS, auto-update, and platform-specific secret storage.

## Verification

After packaging, inspect the unpacked app resources and run the regression checks:

```powershell
cd frontend
npm run desktop:pack
Test-Path ".\release\win-unpacked\Multi Crane Workbench.exe"
Test-Path .\release\win-unpacked\resources\.venv\Scripts\python.exe
Test-Path .\release\win-unpacked\resources\project\backend\app\main.py
npm run typecheck
npm test -- tests/electron/backend.test.ts
npm run build
cd ..
.\.venv\Scripts\python.exe -m pytest backend/app/tests/test_desktop_routes.py backend/app/tests/test_desktop_service.py -v
git diff --check
```
