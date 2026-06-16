# Desktop Workbench Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Phase 1 development desktop workbench: one desktop entry point starts the FastAPI backend, opens the React workbench, lets the user configure one experiment, run it, view it in 3D, and download/open run artifacts.

**Architecture:** Electron owns only desktop launch and native shell actions. FastAPI remains the authoritative backend and receives thin `/desktop/*` workbench APIs. The current React/Vite/Three frontend, including the light Tailwind redesign on `feat/frontend-light-redesign`, becomes a tabbed workbench around the existing Module M/N functionality.

**Tech Stack:** Python 3.13/Pydantic/FastAPI/PyYAML/pytest, React 18/Vite/TypeScript/Tailwind/Zustand/Vitest/Testing Library, Electron with Node ESM modules.

---

## Scope Check

This plan implements only Phase 1 from `docs/superpowers/specs/2026-06-15-desktop-workbench-design.md`.

Implemented here:

- development Electron shell;
- backend process launch diagnostics;
- backend desktop APIs for templates, YAML render/patch, drafts, run listing, run files, environment;
- frontend runtime API base injection;
- workbench navigation tabs;
- template/core form/YAML validation flow;
- episode start/pause/resume/stop/state controls;
- reuse of current 3D visualization;
- data/export and settings pages;
- tests and developer documentation.

Excluded from this plan:

- packaged Windows/macOS release builds;
- backend binary packaging;
- full K/O/P data research workflows;
- full experiment library/database;
- OS keychain storage.

## Current Repository Context

- Branch at plan time: `feat/frontend-light-redesign`.
- The branch contains a light professional Tailwind redesign. Do not revert it.
- There is an untracked `.claude/` directory in the working tree at plan time. Do not add, modify, remove, or stage it unless the user explicitly asks.
- The existing frontend calls REST through `/api` and WebSocket through `/ws`.
- Existing backend Module M routes already expose episode lifecycle and downloads.

## File Structure

### Backend

- Modify `backend/app/api/schemas.py`
  - Add desktop API schemas.
  - Add `EpisodeStartRequest` and control response exports already present where needed by frontend types.
- Create `backend/app/api/desktop_service.py`
  - Pure functions for listing templates, rendering/patching YAML, saving/listing drafts, listing runs, listing run files, and environment reports.
  - No FastAPI imports in this service.
- Create `backend/app/api/routes_desktop.py`
  - Thin FastAPI router over `desktop_service.py`.
- Modify `backend/app/main.py`
  - Include the desktop router.
- Create `backend/app/tests/test_desktop_service.py`
  - Unit tests for pure service behavior.
- Create `backend/app/tests/test_desktop_routes.py`
  - API tests using `TestClient`.

### Electron

- Modify `frontend/package.json`
  - Add Electron dependency and desktop scripts.
- Modify `frontend/package-lock.json`
  - Updated by `npm install --save-dev electron`.
- Create `frontend/electron/backend.mjs`
  - Backend port selection, Python discovery, launch command construction, health polling.
- Create `frontend/electron/main.mjs`
  - Electron app lifecycle, BrowserWindow creation, backend child cleanup, runtime config injection, native open-directory IPC.
- Create `frontend/electron/preload.mjs`
  - Safe renderer bridge for native desktop actions such as opening a run directory.
- Create `frontend/tests/electron/backend.test.ts`
  - Tests for port and command helpers.

### Frontend Runtime And API

- Create `frontend/src/runtime.ts`
  - Runtime config injection from `window.__MULTI_CRANE_DESKTOP__`.
- Modify `frontend/src/vite-env.d.ts`
  - Type the desktop runtime object.
- Modify `frontend/src/api/rest.ts`
  - Use runtime API base.
  - Add desktop API calls and episode control calls.
- Modify `frontend/src/api/ws.ts`
  - Use runtime WebSocket base when provided.
- Modify `frontend/src/api/config.ts`
  - Keep `api_key_env` visible while still scrubbing raw `api_key` and other true secrets.
- Modify `frontend/src/types/api.ts`
  - Add desktop and episode control TypeScript types.
- Create or modify tests:
  - `frontend/tests/runtime.test.ts`
  - `frontend/tests/config.test.ts`
  - `frontend/tests/rest.test.ts`
  - `frontend/tests/ws.test.ts`

### Frontend Workbench

- Create `frontend/src/workbench/types.ts`
  - Shared workbench form/state types.
- Create `frontend/src/workbench/configModel.ts`
  - Pure YAML/form mapping functions.
- Create `frontend/src/state/workbench.ts`
  - Zustand store for current experiment draft and run state.
- Create `frontend/src/components/workbench/WorkbenchShell.tsx`
  - Left navigation and top status bar.
- Create `frontend/src/components/workbench/ExperimentPage.tsx`
- Create `frontend/src/components/workbench/ConfigurationPage.tsx`
- Create `frontend/src/components/workbench/RunPage.tsx`
- Create `frontend/src/components/workbench/VisualizationPage.tsx`
- Create `frontend/src/components/workbench/DataExportPage.tsx`
- Create `frontend/src/components/workbench/SettingsPage.tsx`
- Modify `frontend/src/App.tsx`
  - Route the app through the workbench shell.
- Modify `frontend/src/styles.css`
  - Add workbench shell/layout styles using existing light design tokens.
- Create tests:
  - `frontend/tests/workbench/configModel.test.ts`
  - `frontend/tests/workbench/shell.test.tsx`
  - `frontend/tests/workbench/configuration.test.tsx`
  - `frontend/tests/workbench/run.test.tsx`
  - `frontend/tests/workbench/export-settings.test.tsx`

### Documentation

- Create `docs/desktop_workbench_phase1.md`
  - Developer startup instructions, test commands, and first-release limitations.

## Task 1: Backend Desktop Schemas And Pure Service

**Files:**
- Modify: `backend/app/api/schemas.py`
- Create: `backend/app/api/desktop_service.py`
- Test: `backend/app/tests/test_desktop_service.py`

- [ ] **Step 1: Write failing service tests**

Create `backend/app/tests/test_desktop_service.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

import yaml

from backend.app.api.desktop_service import (
    apply_config_patch,
    list_desktop_templates,
    list_run_files,
    list_runs,
    render_template_yaml,
    save_experiment_draft,
    scrub_secret_values,
)


def test_list_desktop_templates_reads_yaml_files(tmp_path: Path) -> None:
    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    (config_dir / "demo.yaml").write_text(
        "scenario:\n  scenario_id: demo\nexperiment:\n  experiment_id: demo_exp\n",
        encoding="utf-8",
    )

    templates = list_desktop_templates(project_root=tmp_path, template_dirs=[config_dir])

    assert len(templates) == 1
    assert templates[0].template_id == "demo"
    assert templates[0].name == "demo"
    assert templates[0].scenario_id == "demo"
    assert templates[0].experiment_id == "demo_exp"


def test_render_template_yaml_applies_core_overrides(tmp_path: Path) -> None:
    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    (config_dir / "demo.yaml").write_text(
        "\n".join(
            [
                "scenario:",
                "  scenario_id: demo",
                "  layout:",
                "    num_cranes: 4",
                "experiment:",
                "  experiment_id: demo_exp",
                "  sim:",
                "    duration_s: 100",
                "  llm:",
                "    provider: deepseek",
            ]
        ),
        encoding="utf-8",
    )

    text = render_template_yaml(
        project_root=tmp_path,
        template_id="demo",
        core_overrides={
            "scenario.layout.num_cranes": 6,
            "experiment.sim.duration_s": 240,
            "experiment.llm.provider": "openai_compatible",
        },
        template_dirs=[config_dir],
    )
    parsed = yaml.safe_load(text)

    assert parsed["scenario"]["layout"]["num_cranes"] == 6
    assert parsed["experiment"]["sim"]["duration_s"] == 240
    assert parsed["experiment"]["llm"]["provider"] == "openai_compatible"


def test_apply_config_patch_preserves_unmapped_yaml_fields() -> None:
    text = "scenario:\n  scenario_id: x\n  custom_field: keep\nexperiment:\n  sim:\n    duration_s: 10\n"

    patched = apply_config_patch(text, {"experiment.sim.duration_s": 20})
    parsed = yaml.safe_load(patched)

    assert parsed["scenario"]["custom_field"] == "keep"
    assert parsed["experiment"]["sim"]["duration_s"] == 20


def test_scrub_secret_values_masks_nested_api_keys() -> None:
    cleaned = scrub_secret_values(
        {
            "experiment": {
                "llm": {
                    "api_key": "sk-real",
                    "api_key_env": "DEEPSEEK_API_KEY",
                    "model": "m",
                }
            }
        }
    )

    llm = cleaned["experiment"]["llm"]
    assert llm["api_key"] == "***"
    assert llm["api_key_env"] == "DEEPSEEK_API_KEY"
    assert llm["model"] == "m"


def test_save_experiment_draft_never_writes_raw_secret(tmp_path: Path) -> None:
    draft_dir = tmp_path / ".desktop" / "experiments"
    result = save_experiment_draft(
        project_root=tmp_path,
        experiment_id="exp1",
        yaml_text="experiment:\n  llm:\n    api_key: sk-real\n    model: m\n",
        metadata={"template_id": "demo", "last_validation_hash": "abc"},
        draft_root=draft_dir,
    )

    yaml_text = Path(result.yaml_path).read_text(encoding="utf-8")
    meta = json.loads(Path(result.metadata_path).read_text(encoding="utf-8"))

    assert "sk-real" not in yaml_text
    assert "***" in yaml_text
    assert meta["experiment_id"] == "exp1"
    assert meta["template_id"] == "demo"


def test_list_runs_reads_episode_summaries(tmp_path: Path) -> None:
    run = tmp_path / "runs" / "exp" / "episode-1"
    (run / "metadata").mkdir(parents=True)
    (run / "metadata" / "episode_summary.json").write_text(
        json.dumps({"episode_id": "episode-1", "status": "completed", "duration_s": 12}),
        encoding="utf-8",
    )

    runs = list_runs(project_root=tmp_path, run_roots=[tmp_path / "runs"])

    assert len(runs) == 1
    assert runs[0].episode_id == "episode-1"
    assert runs[0].summary_available is True
    assert runs[0].path.endswith("episode-1")


def test_list_run_files_keeps_known_artifacts_only(tmp_path: Path) -> None:
    run = tmp_path / "runs" / "episode-1"
    for rel in [
        "metadata/episode_summary.json",
        "visual/frames.jsonl",
        "data/trajectories.parquet",
        "logs/commands.jsonl",
        "tmp/debug.tmp",
    ]:
        path = run / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x", encoding="utf-8")

    files = list_run_files(run)
    names = {item.relative_path for item in files}

    assert "metadata/episode_summary.json" in names
    assert "visual/frames.jsonl" in names
    assert "data/trajectories.parquet" in names
    assert "logs/commands.jsonl" in names
    assert "tmp/debug.tmp" not in names
```

- [ ] **Step 2: Run service tests and verify they fail**

Run:

```bash
.venv/bin/python -m pytest backend/app/tests/test_desktop_service.py -v
```

Expected result:

```text
ModuleNotFoundError: No module named 'backend.app.api.desktop_service'
```

- [ ] **Step 3: Add desktop API schemas**

Append these models to `backend/app/api/schemas.py` above `__all__`:

```python
class DesktopTemplate(ApiBaseModel):
    template_id: str
    name: str
    path: str
    scenario_id: Optional[str] = None
    experiment_id: Optional[str] = None
    description: Optional[str] = None


class DesktopTemplatesResponse(ApiBaseModel):
    items: list[DesktopTemplate]


class DesktopConfigRenderRequest(ApiBaseModel):
    template_id: str
    core_overrides: dict[str, Any] = Field(default_factory=dict)


class DesktopConfigPatchRequest(ApiBaseModel):
    yaml_text: str
    patches: dict[str, Any] = Field(default_factory=dict)


class DesktopConfigTextResponse(ApiBaseModel):
    yaml_text: str


class DesktopExperimentDraftRequest(ApiBaseModel):
    experiment_id: str
    yaml_text: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class DesktopExperimentDraftResponse(ApiBaseModel):
    experiment_id: str
    yaml_path: str
    metadata_path: str


class DesktopRecentExperiment(ApiBaseModel):
    experiment_id: str
    yaml_path: str
    metadata_path: str
    template_id: Optional[str] = None
    last_validation_hash: Optional[str] = None
    updated_at: Optional[str] = None


class DesktopRecentExperimentsResponse(ApiBaseModel):
    items: list[DesktopRecentExperiment]


class DesktopRunItem(ApiBaseModel):
    episode_id: str
    path: str
    status: Optional[str] = None
    created_at: Optional[str] = None
    summary_available: bool


class DesktopRunsResponse(ApiBaseModel):
    items: list[DesktopRunItem]


class DesktopRunFile(ApiBaseModel):
    relative_path: str
    path: str
    size_bytes: int = Field(ge=0)
    kind: str


class DesktopRunFilesResponse(ApiBaseModel):
    episode_id: str
    files: list[DesktopRunFile]


class DesktopEnvironmentResponse(ApiBaseModel):
    project_root: str
    python_path: Optional[str] = None
    python_version: Optional[str] = None
    run_roots: list[str] = Field(default_factory=list)
    backend_port: Optional[int] = None
```

Add these names to `__all__` in the same file:

```python
    "DesktopConfigPatchRequest",
    "DesktopConfigRenderRequest",
    "DesktopConfigTextResponse",
    "DesktopEnvironmentResponse",
    "DesktopExperimentDraftRequest",
    "DesktopExperimentDraftResponse",
    "DesktopRecentExperiment",
    "DesktopRecentExperimentsResponse",
    "DesktopRunFile",
    "DesktopRunFilesResponse",
    "DesktopRunItem",
    "DesktopRunsResponse",
    "DesktopTemplate",
    "DesktopTemplatesResponse",
```

- [ ] **Step 4: Implement `desktop_service.py`**

Create `backend/app/api/desktop_service.py`:

```python
from __future__ import annotations

import json
import os
import platform
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import yaml

from .schemas import (
    DesktopEnvironmentResponse,
    DesktopExperimentDraftResponse,
    DesktopRecentExperiment,
    DesktopRunFile,
    DesktopRunItem,
    DesktopTemplate,
)


SECRET_FIELD_RE = re.compile(
    r"(^|[_-])(api[-_]?key|apikey|token|secret|authorization|password)([_-]|$)",
    re.IGNORECASE,
)
SECRET_ALLOWLIST = {"api_key_env"}
DEFAULT_TEMPLATE_DIRS = (Path("configs"), Path("backend/app/tests/fixtures/configs"))
DEFAULT_DRAFT_ROOT = Path(".desktop/experiments")
KNOWN_RUN_PARTS = {"config", "metadata", "logs", "data", "visual", "replay"}


@dataclass(frozen=True)
class TemplateSource:
    template_id: str
    path: Path


def list_desktop_templates(
    *,
    project_root: Path,
    template_dirs: Iterable[Path] | None = None,
) -> list[DesktopTemplate]:
    sources = _template_sources(project_root, template_dirs)
    items: list[DesktopTemplate] = []
    for source in sources:
        payload = _read_yaml(source.path)
        scenario = payload.get("scenario") if isinstance(payload, dict) else None
        experiment = payload.get("experiment") if isinstance(payload, dict) else None
        items.append(
            DesktopTemplate(
                template_id=source.template_id,
                name=source.template_id.replace("_", " "),
                path=str(source.path),
                scenario_id=_str_or_none(scenario, "scenario_id"),
                experiment_id=_str_or_none(experiment, "experiment_id"),
                description=_str_or_none(payload, "description"),
            )
        )
    return sorted(items, key=lambda item: item.template_id)


def render_template_yaml(
    *,
    project_root: Path,
    template_id: str,
    core_overrides: dict[str, Any],
    template_dirs: Iterable[Path] | None = None,
) -> str:
    path = _find_template(project_root, template_id, template_dirs)
    payload = _read_yaml(path)
    if not isinstance(payload, dict):
        raise ValueError("template root must be an object")
    for dotted_path, value in core_overrides.items():
        _set_dotted_value(payload, dotted_path, value)
    return _dump_yaml(scrub_secret_values(payload))


def apply_config_patch(yaml_text: str, patches: dict[str, Any]) -> str:
    payload = yaml.safe_load(yaml_text)
    if not isinstance(payload, dict):
        raise ValueError("config root must be an object")
    for dotted_path, value in patches.items():
        _set_dotted_value(payload, dotted_path, value)
    return _dump_yaml(scrub_secret_values(payload))


def save_experiment_draft(
    *,
    project_root: Path,
    experiment_id: str,
    yaml_text: str,
    metadata: dict[str, Any],
    draft_root: Path | None = None,
) -> DesktopExperimentDraftResponse:
    safe_id = _safe_id(experiment_id)
    root = _resolve_under_project(project_root, draft_root or DEFAULT_DRAFT_ROOT)
    target = root / safe_id
    target.mkdir(parents=True, exist_ok=True)

    payload = yaml.safe_load(yaml_text)
    if not isinstance(payload, dict):
        raise ValueError("draft yaml root must be an object")
    clean_yaml = _dump_yaml(scrub_secret_values(payload))
    yaml_path = target / "draft.yaml"
    yaml_path.write_text(clean_yaml, encoding="utf-8")

    meta_payload = scrub_secret_values(
        {
            **metadata,
            "experiment_id": safe_id,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    metadata_path = target / "draft.meta.json"
    metadata_path.write_text(
        json.dumps(meta_payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return DesktopExperimentDraftResponse(
        experiment_id=safe_id,
        yaml_path=str(yaml_path),
        metadata_path=str(metadata_path),
    )


def list_recent_experiments(
    *,
    project_root: Path,
    draft_root: Path | None = None,
) -> list[DesktopRecentExperiment]:
    root = _resolve_under_project(project_root, draft_root or DEFAULT_DRAFT_ROOT)
    if not root.exists():
        return []
    items: list[DesktopRecentExperiment] = []
    for meta_path in sorted(root.glob("*/draft.meta.json")):
        try:
            metadata = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        experiment_id = str(metadata.get("experiment_id") or meta_path.parent.name)
        items.append(
            DesktopRecentExperiment(
                experiment_id=experiment_id,
                yaml_path=str(meta_path.parent / "draft.yaml"),
                metadata_path=str(meta_path),
                template_id=_optional_str(metadata.get("template_id")),
                last_validation_hash=_optional_str(metadata.get("last_validation_hash")),
                updated_at=_optional_str(metadata.get("updated_at")),
            )
        )
    return sorted(items, key=lambda item: item.updated_at or "", reverse=True)


def list_runs(*, project_root: Path, run_roots: Iterable[Path] | None = None) -> list[DesktopRunItem]:
    roots = list(run_roots or [Path("runs")])
    items: list[DesktopRunItem] = []
    for root_value in roots:
        root = _resolve_under_project(project_root, root_value)
        if not root.exists():
            continue
        for summary_path in sorted(root.rglob("metadata/episode_summary.json")):
            run_dir = summary_path.parent.parent
            summary = _read_json(summary_path)
            episode_id = str(summary.get("episode_id") or run_dir.name)
            items.append(
                DesktopRunItem(
                    episode_id=episode_id,
                    path=str(run_dir),
                    status=_optional_str(summary.get("status")),
                    created_at=_optional_str(summary.get("created_at")),
                    summary_available=True,
                )
            )
    return sorted(items, key=lambda item: item.path, reverse=True)


def list_run_files(run_dir: Path) -> list[DesktopRunFile]:
    if not run_dir.exists() or not run_dir.is_dir():
        raise FileNotFoundError(str(run_dir))
    files: list[DesktopRunFile] = []
    for path in sorted(item for item in run_dir.rglob("*") if item.is_file()):
        relative = path.relative_to(run_dir)
        if not relative.parts or relative.parts[0] not in KNOWN_RUN_PARTS:
            continue
        files.append(
            DesktopRunFile(
                relative_path=relative.as_posix(),
                path=str(path),
                size_bytes=path.stat().st_size,
                kind=relative.parts[0],
            )
        )
    return files


def environment_report(
    *,
    project_root: Path,
    backend_port: int | None = None,
    run_roots: Iterable[Path] | None = None,
) -> DesktopEnvironmentResponse:
    resolved_runs = [str(_resolve_under_project(project_root, root)) for root in (run_roots or [Path("runs")])]
    return DesktopEnvironmentResponse(
        project_root=str(project_root.resolve()),
        python_path=sys.executable,
        python_version=f"{platform.python_implementation()} {platform.python_version()}",
        run_roots=resolved_runs,
        backend_port=backend_port,
    )


def scrub_secret_values(value: Any) -> Any:
    if isinstance(value, list):
        return [scrub_secret_values(item) for item in value]
    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        for key, item in value.items():
            key_str = str(key)
            if key_str in SECRET_ALLOWLIST:
                cleaned[key_str] = item
            elif SECRET_FIELD_RE.search(key_str):
                cleaned[key_str] = "***" if item not in (None, "") else item
            else:
                cleaned[key_str] = scrub_secret_values(item)
        return cleaned
    return value


def _template_sources(project_root: Path, template_dirs: Iterable[Path] | None) -> list[TemplateSource]:
    sources: list[TemplateSource] = []
    for directory in template_dirs or DEFAULT_TEMPLATE_DIRS:
        root = _resolve_under_project(project_root, directory)
        if not root.exists():
            continue
        for path in sorted(root.glob("*.y*ml")):
            sources.append(TemplateSource(template_id=path.stem, path=path))
    return sources


def _find_template(project_root: Path, template_id: str, template_dirs: Iterable[Path] | None) -> Path:
    safe_id = _safe_id(template_id)
    for source in _template_sources(project_root, template_dirs):
        if source.template_id == safe_id:
            return source.path
    raise FileNotFoundError(f"template not found: {safe_id}")


def _read_yaml(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"YAML root must be an object: {path}")
    return payload


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _dump_yaml(payload: dict[str, Any]) -> str:
    return yaml.safe_dump(payload, allow_unicode=True, sort_keys=False)


def _set_dotted_value(payload: dict[str, Any], dotted_path: str, value: Any) -> None:
    parts = [part for part in dotted_path.split(".") if part]
    if not parts:
        raise ValueError("patch path cannot be empty")
    cursor: dict[str, Any] = payload
    for part in parts[:-1]:
        child = cursor.get(part)
        if child is None:
            child = {}
            cursor[part] = child
        if not isinstance(child, dict):
            raise ValueError(f"patch path crosses non-object field: {part}")
        cursor = child
    cursor[parts[-1]] = value


def _resolve_under_project(project_root: Path, path: Path) -> Path:
    candidate = path if path.is_absolute() else project_root / path
    resolved_project = project_root.resolve()
    resolved = candidate.resolve()
    if resolved != resolved_project and resolved_project not in resolved.parents:
        raise ValueError(f"path escapes project root: {path}")
    return resolved


def _safe_id(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip(".-")
    if cleaned in {"", ".", ".."}:
        raise ValueError("invalid identifier")
    return cleaned


def _optional_str(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _str_or_none(payload: Any, key: str) -> str | None:
    if not isinstance(payload, dict):
        return None
    return _optional_str(payload.get(key))
```

- [ ] **Step 5: Run service tests**

Run:

```bash
.venv/bin/python -m pytest backend/app/tests/test_desktop_service.py -v
```

Expected result:

```text
7 passed
```

- [ ] **Step 6: Commit backend service**

```bash
git add backend/app/api/schemas.py backend/app/api/desktop_service.py backend/app/tests/test_desktop_service.py
git commit -m "feat(desktop): add workbench service layer"
```

## Task 2: Backend Desktop Routes

**Files:**
- Create: `backend/app/api/routes_desktop.py`
- Modify: `backend/app/main.py`
- Test: `backend/app/tests/test_desktop_routes.py`

- [ ] **Step 1: Write failing route tests**

Create `backend/app/tests/test_desktop_routes.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.main import create_app


def _client(tmp_path: Path) -> TestClient:
    app = create_app()
    app.state.project_root = tmp_path
    app.state.backend_port = 8765
    return TestClient(app)


def test_templates_route_lists_config_templates(tmp_path: Path) -> None:
    configs = tmp_path / "configs"
    configs.mkdir()
    (configs / "demo.yaml").write_text(
        "scenario:\n  scenario_id: demo\nexperiment:\n  experiment_id: exp\n",
        encoding="utf-8",
    )

    res = _client(tmp_path).get("/desktop/templates")

    assert res.status_code == 200
    body = res.json()["data"]
    assert body["items"][0]["template_id"] == "demo"
    assert body["items"][0]["scenario_id"] == "demo"


def test_render_route_returns_yaml_text(tmp_path: Path) -> None:
    configs = tmp_path / "configs"
    configs.mkdir()
    (configs / "demo.yaml").write_text(
        "scenario:\n  layout:\n    num_cranes: 4\nexperiment:\n  sim:\n    duration_s: 10\n",
        encoding="utf-8",
    )

    res = _client(tmp_path).post(
        "/desktop/config/render",
        json={
            "template_id": "demo",
            "core_overrides": {"scenario.layout.num_cranes": 5},
        },
    )

    assert res.status_code == 200
    assert "num_cranes: 5" in res.json()["data"]["yaml_text"]


def test_draft_route_scrubs_secret_and_lists_recent(tmp_path: Path) -> None:
    client = _client(tmp_path)

    saved = client.post(
        "/desktop/experiments/draft",
        json={
            "experiment_id": "exp1",
            "yaml_text": "experiment:\n  llm:\n    api_key: sk-real\n",
            "metadata": {"template_id": "demo"},
        },
    )
    assert saved.status_code == 200
    yaml_path = Path(saved.json()["data"]["yaml_path"])
    assert "sk-real" not in yaml_path.read_text(encoding="utf-8")

    recent = client.get("/desktop/experiments/recent")
    assert recent.status_code == 200
    assert recent.json()["data"]["items"][0]["experiment_id"] == "exp1"


def test_runs_and_files_routes(tmp_path: Path) -> None:
    run = tmp_path / "runs" / "episode-1"
    (run / "metadata").mkdir(parents=True)
    (run / "metadata" / "episode_summary.json").write_text(
        json.dumps({"episode_id": "episode-1", "status": "completed"}),
        encoding="utf-8",
    )
    (run / "visual").mkdir()
    (run / "visual" / "frames.jsonl").write_text("{}", encoding="utf-8")
    client = _client(tmp_path)

    runs = client.get("/desktop/runs")
    files = client.get("/desktop/runs/episode-1/files")

    assert runs.status_code == 200
    assert runs.json()["data"]["items"][0]["episode_id"] == "episode-1"
    assert files.status_code == 200
    assert files.json()["data"]["files"][0]["relative_path"] == "metadata/episode_summary.json"


def test_environment_route_reports_project_root(tmp_path: Path) -> None:
    res = _client(tmp_path).get("/desktop/environment")

    assert res.status_code == 200
    data = res.json()["data"]
    assert data["project_root"] == str(tmp_path.resolve())
    assert data["backend_port"] == 8765
```

- [ ] **Step 2: Run route tests and verify they fail**

Run:

```bash
.venv/bin/python -m pytest backend/app/tests/test_desktop_routes.py -v
```

Expected result:

```text
assert 404 == 200
```

- [ ] **Step 3: Implement desktop routes**

Create `backend/app/api/routes_desktop.py`:

```python
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request

from .desktop_service import (
    apply_config_patch,
    environment_report,
    list_desktop_templates,
    list_recent_experiments,
    list_run_files,
    list_runs,
    render_template_yaml,
    save_experiment_draft,
)
from .errors import ApiException
from .schemas import (
    ApiResponse,
    DesktopConfigPatchRequest,
    DesktopConfigRenderRequest,
    DesktopConfigTextResponse,
    DesktopExperimentDraftRequest,
    DesktopRecentExperimentsResponse,
    DesktopRunFilesResponse,
    DesktopRunsResponse,
    DesktopTemplatesResponse,
)

router = APIRouter(prefix="/desktop")


@router.get("/templates", response_model=ApiResponse)
def get_templates(request: Request) -> ApiResponse:
    items = list_desktop_templates(project_root=_project_root(request))
    return ApiResponse(data=DesktopTemplatesResponse(items=items).model_dump(mode="json"))


@router.post("/config/render", response_model=ApiResponse)
def render_config(request: Request, payload: DesktopConfigRenderRequest) -> ApiResponse:
    text = render_template_yaml(
        project_root=_project_root(request),
        template_id=payload.template_id,
        core_overrides=payload.core_overrides,
    )
    return ApiResponse(data=DesktopConfigTextResponse(yaml_text=text).model_dump(mode="json"))


@router.post("/config/patch", response_model=ApiResponse)
def patch_config(payload: DesktopConfigPatchRequest) -> ApiResponse:
    text = apply_config_patch(payload.yaml_text, payload.patches)
    return ApiResponse(data=DesktopConfigTextResponse(yaml_text=text).model_dump(mode="json"))


@router.post("/experiments/draft", response_model=ApiResponse)
def save_draft(request: Request, payload: DesktopExperimentDraftRequest) -> ApiResponse:
    result = save_experiment_draft(
        project_root=_project_root(request),
        experiment_id=payload.experiment_id,
        yaml_text=payload.yaml_text,
        metadata=payload.metadata,
    )
    return ApiResponse(data=result.model_dump(mode="json"))


@router.get("/experiments/recent", response_model=ApiResponse)
def get_recent_experiments(request: Request) -> ApiResponse:
    items = list_recent_experiments(project_root=_project_root(request))
    return ApiResponse(data=DesktopRecentExperimentsResponse(items=items).model_dump(mode="json"))


@router.get("/runs", response_model=ApiResponse)
def get_runs(request: Request) -> ApiResponse:
    items = list_runs(project_root=_project_root(request))
    return ApiResponse(data=DesktopRunsResponse(items=items).model_dump(mode="json"))


@router.get("/runs/{episode_id}/files", response_model=ApiResponse)
def get_run_files(request: Request, episode_id: str) -> ApiResponse:
    run = _find_run_dir(_project_root(request), episode_id)
    files = list_run_files(run)
    return ApiResponse(data=DesktopRunFilesResponse(episode_id=episode_id, files=files).model_dump(mode="json"))


@router.get("/environment", response_model=ApiResponse)
def get_environment(request: Request) -> ApiResponse:
    port = getattr(request.app.state, "backend_port", None)
    result = environment_report(project_root=_project_root(request), backend_port=port)
    return ApiResponse(data=result.model_dump(mode="json"))


def _project_root(request: Request) -> Path:
    root = getattr(request.app.state, "project_root", None)
    if root is not None:
        return Path(root).resolve()
    return Path.cwd().resolve()


def _find_run_dir(project_root: Path, episode_id: str) -> Path:
    if "/" in episode_id or "\\" in episode_id or episode_id in {"", ".", ".."}:
        raise ApiException(status_code=404, code="M_E_EPISODE_NOT_FOUND", message="run not found", details={"episode_id": episode_id})
    for item in list_runs(project_root=project_root):
        if item.episode_id == episode_id:
            return Path(item.path)
    raise ApiException(status_code=404, code="M_E_EPISODE_NOT_FOUND", message="run not found", details={"episode_id": episode_id})


__all__ = ["router"]
```

- [ ] **Step 4: Register desktop router**

Modify `backend/app/main.py`:

```python
from backend.app.api.routes_desktop import router as desktop_router
```

Add this line in `create_app()` after the health router:

```python
    app.include_router(desktop_router)
```

- [ ] **Step 5: Run route tests**

Run:

```bash
.venv/bin/python -m pytest backend/app/tests/test_desktop_routes.py -v
```

Expected result:

```text
5 passed
```

- [ ] **Step 6: Run Module M and desktop API tests together**

Run:

```bash
.venv/bin/python -m pytest backend/app/tests/test_moduleM_*.py backend/app/tests/test_desktop_*.py -v
```

Expected result:

```text
passed
```

- [ ] **Step 7: Commit desktop routes**

```bash
git add backend/app/api/routes_desktop.py backend/app/main.py backend/app/tests/test_desktop_routes.py
git commit -m "feat(desktop): expose workbench API routes"
```

## Task 3: Frontend Runtime API Base

**Files:**
- Create: `frontend/src/runtime.ts`
- Modify: `frontend/src/vite-env.d.ts`
- Modify: `frontend/src/api/config.ts`
- Modify: `frontend/src/api/rest.ts`
- Modify: `frontend/src/api/ws.ts`
- Modify: `frontend/src/types/api.ts`
- Test: `frontend/tests/runtime.test.ts`
- Test: `frontend/tests/config.test.ts`
- Test: `frontend/tests/rest.test.ts`
- Test: `frontend/tests/ws.test.ts`

- [ ] **Step 1: Add failing runtime tests**

Create `frontend/tests/runtime.test.ts`:

```ts
import { describe, it, expect, beforeEach } from "vitest";
import { getApiBase, getWsBase, getRuntimeConfig } from "@/runtime";

declare global {
  interface Window {
    __MULTI_CRANE_DESKTOP__?: {
      apiBase?: string;
      wsBase?: string;
      backendPort?: number;
      mode?: "browser" | "desktop";
    };
  }
}

describe("runtime config", () => {
  beforeEach(() => {
    delete window.__MULTI_CRANE_DESKTOP__;
  });

  it("defaults to browser-relative api and ws bases", () => {
    expect(getApiBase()).toBe("/api");
    expect(getWsBase()).toBe("/ws");
    expect(getRuntimeConfig().mode).toBe("browser");
  });

  it("uses desktop-injected api and ws bases", () => {
    window.__MULTI_CRANE_DESKTOP__ = {
      apiBase: "http://127.0.0.1:8765",
      wsBase: "ws://127.0.0.1:8765/ws",
      backendPort: 8765,
      mode: "desktop",
    };

    expect(getApiBase()).toBe("http://127.0.0.1:8765");
    expect(getWsBase()).toBe("ws://127.0.0.1:8765/ws");
    expect(getRuntimeConfig().backendPort).toBe(8765);
  });

  it("uses Electron dev query parameters when preload script cannot edit Vite html", () => {
    window.history.replaceState(
      null,
      "",
      "/?desktopApiBase=http%3A%2F%2F127.0.0.1%3A8766&desktopWsBase=ws%3A%2F%2F127.0.0.1%3A8766%2Fws&desktopBackendPort=8766",
    );

    expect(getApiBase()).toBe("http://127.0.0.1:8766");
    expect(getWsBase()).toBe("ws://127.0.0.1:8766/ws");
    expect(getRuntimeConfig().mode).toBe("desktop");
    expect(getRuntimeConfig().backendPort).toBe(8766);

    window.history.replaceState(null, "", "/");
  });
});
```

- [ ] **Step 2: Run runtime test and verify it fails**

Run:

```bash
cd frontend && npm test -- runtime.test.ts
```

Expected result:

```text
Failed to resolve import "@/runtime"
```

- [ ] **Step 3: Implement runtime config**

Create `frontend/src/runtime.ts`:

```ts
export interface DesktopRuntimeConfig {
  apiBase?: string;
  wsBase?: string;
  backendPort?: number;
  mode?: "browser" | "desktop";
}

export function getRuntimeConfig(): Required<Pick<DesktopRuntimeConfig, "mode">> & DesktopRuntimeConfig {
  const injected = typeof window !== "undefined" ? window.__MULTI_CRANE_DESKTOP__ : undefined;
  const params = typeof window !== "undefined" ? new URLSearchParams(window.location.search) : new URLSearchParams();
  const queryApiBase = params.get("desktopApiBase") ?? undefined;
  const queryWsBase = params.get("desktopWsBase") ?? undefined;
  const queryPort = params.get("desktopBackendPort");
  return {
    mode: injected?.mode ?? (queryApiBase ? "desktop" : "browser"),
    apiBase: injected?.apiBase ?? queryApiBase,
    wsBase: injected?.wsBase ?? queryWsBase,
    backendPort: injected?.backendPort ?? (queryPort ? Number(queryPort) : undefined),
  };
}

export function getApiBase(): string {
  return getRuntimeConfig().apiBase ?? "/api";
}

export function getWsBase(): string {
  return getRuntimeConfig().wsBase ?? "/ws";
}
```

Modify `frontend/src/vite-env.d.ts`:

```ts
/// <reference types="vite/client" />

interface Window {
  __MULTI_CRANE_DESKTOP__?: {
    apiBase?: string;
    wsBase?: string;
    backendPort?: number;
    mode?: "browser" | "desktop";
  };
}
```

- [ ] **Step 4: Use runtime API base in REST client**

Modify `frontend/src/api/rest.ts`:

```ts
import { getApiBase } from "@/runtime";
```

Replace:

```ts
const API_BASE = "/api";
```

With:

```ts
function apiBase(): string {
  return getApiBase();
}
```

Replace every `fetch(`${API_BASE}${path}`` with:

```ts
fetch(`${apiBase()}${path}`
```

Replace the download fetch prefix with:

```ts
const base = apiBase();
res = await fetch(`${base}/episodes/${episodeId}/download${qs ? `?${qs}` : ""}`);
```

- [ ] **Step 5: Preserve `api_key_env` while scrubbing raw secrets**

Modify `frontend/src/api/config.ts`:

```ts
const SECRET_KEY = /(^|[_-])(api[-_]?key|apikey|token|secret|authorization|password)([_-]|$)/i;
const SECRET_ALLOWLIST = new Set(["api_key_env"]);
```

Update the object branch inside `scrubSecrets()`:

```ts
for (const [k, v] of Object.entries(obj as Record<string, unknown>)) {
  out[k] = SECRET_ALLOWLIST.has(k) ? scrubSecrets(v) : SECRET_KEY.test(k) ? "***" : scrubSecrets(v);
}
```

Append this test to `frontend/tests/config.test.ts`:

```ts
it("keeps api_key_env while masking raw api_key", () => {
  const out = scrubSecrets({
    llm: {
      api_key: "sk-real",
      api_key_env: "DEEPSEEK_API_KEY",
    },
  }) as Record<string, Record<string, unknown>>;
  expect(out.llm.api_key).toBe("***");
  expect(out.llm.api_key_env).toBe("DEEPSEEK_API_KEY");
});
```

- [ ] **Step 6: Add TypeScript API types and REST calls**

Append to `frontend/src/types/api.ts`:

```ts
export interface EpisodeControlResponse {
  episode_id: string;
  previous_status: string;
  status: string;
  accepted: boolean;
  reason: string | null;
}

export interface EpisodeStartRequest {
  config_path?: string | null;
  scenario?: Record<string, unknown> | null;
  experiment?: Record<string, unknown> | null;
  dataset?: Record<string, unknown> | null;
  overrides?: Record<string, unknown>;
  run_mode?: RunMode | null;
  runner?: "production" | "local" | null;
  episode_id?: string | null;
  autostart?: boolean;
}

export interface DesktopTemplate {
  template_id: string;
  name: string;
  path: string;
  scenario_id: string | null;
  experiment_id: string | null;
  description: string | null;
}

export interface DesktopTemplatesResponse {
  items: DesktopTemplate[];
}

export interface DesktopConfigTextResponse {
  yaml_text: string;
}

export interface DesktopRecentExperiment {
  experiment_id: string;
  yaml_path: string;
  metadata_path: string;
  template_id: string | null;
  last_validation_hash: string | null;
  updated_at: string | null;
}

export interface DesktopRecentExperimentsResponse {
  items: DesktopRecentExperiment[];
}

export interface DesktopRunItem {
  episode_id: string;
  path: string;
  status: string | null;
  created_at: string | null;
  summary_available: boolean;
}

export interface DesktopRunsResponse {
  items: DesktopRunItem[];
}

export interface DesktopRunFile {
  relative_path: string;
  path: string;
  size_bytes: number;
  kind: string;
}

export interface DesktopRunFilesResponse {
  episode_id: string;
  files: DesktopRunFile[];
}

export interface DesktopEnvironmentResponse {
  project_root: string;
  python_path: string | null;
  python_version: string | null;
  run_roots: string[];
  backend_port: number | null;
}
```

Update imports in `frontend/src/api/rest.ts` to include the new types, then append these functions:

```ts
export function startEpisode(req: EpisodeStartRequest, init?: { signal?: AbortSignal }) {
  return request<EpisodeStartResponse>("POST", "/episodes/start", req, init);
}

export function pauseEpisode(episodeId: string, init?: { signal?: AbortSignal }) {
  return request<EpisodeControlResponse>("POST", `/episodes/${episodeId}/pause`, undefined, init);
}

export function resumeEpisode(episodeId: string, init?: { signal?: AbortSignal }) {
  return request<EpisodeControlResponse>("POST", `/episodes/${episodeId}/resume`, undefined, init);
}

export function stopEpisode(episodeId: string, init?: { signal?: AbortSignal }) {
  return request<EpisodeControlResponse>("POST", `/episodes/${episodeId}/stop`, undefined, init);
}

export function listDesktopTemplates(init?: { signal?: AbortSignal }) {
  return request<DesktopTemplatesResponse>("GET", "/desktop/templates", undefined, init);
}

export function renderDesktopConfig(templateId: string, coreOverrides: Record<string, unknown>, init?: { signal?: AbortSignal }) {
  return request<DesktopConfigTextResponse>(
    "POST",
    "/desktop/config/render",
    { template_id: templateId, core_overrides: coreOverrides },
    init,
  );
}

export function patchDesktopConfig(yamlText: string, patches: Record<string, unknown>, init?: { signal?: AbortSignal }) {
  return request<DesktopConfigTextResponse>(
    "POST",
    "/desktop/config/patch",
    { yaml_text: yamlText, patches },
    init,
  );
}

export function saveDesktopDraft(experimentId: string, yamlText: string, metadata: Record<string, unknown>, init?: { signal?: AbortSignal }) {
  return request<{ experiment_id: string; yaml_path: string; metadata_path: string }>(
    "POST",
    "/desktop/experiments/draft",
    { experiment_id: experimentId, yaml_text: yamlText, metadata },
    init,
  );
}

export function listRecentExperiments(init?: { signal?: AbortSignal }) {
  return request<DesktopRecentExperimentsResponse>("GET", "/desktop/experiments/recent", undefined, init);
}

export function listDesktopRuns(init?: { signal?: AbortSignal }) {
  return request<DesktopRunsResponse>("GET", "/desktop/runs", undefined, init);
}

export function listDesktopRunFiles(episodeId: string, init?: { signal?: AbortSignal }) {
  return request<DesktopRunFilesResponse>("GET", `/desktop/runs/${episodeId}/files`, undefined, init);
}

export function getDesktopEnvironment(init?: { signal?: AbortSignal }) {
  return request<DesktopEnvironmentResponse>("GET", "/desktop/environment", undefined, init);
}
```

- [ ] **Step 7: Use runtime WebSocket base**

Modify `frontend/src/api/ws.ts`:

```ts
import { getWsBase } from "@/runtime";
```

Replace the constructor URL branch:

```ts
    this.url = opts.baseUrl
      ? `${opts.baseUrl}/episodes/${opts.episodeId}`
      : defaultUrl(opts.episodeId);
```

With:

```ts
    this.url = opts.baseUrl
      ? `${opts.baseUrl}/episodes/${opts.episodeId}`
      : `${getWsBase()}/episodes/${opts.episodeId}`;
```

Remove the old `defaultUrl()` helper after this change because runtime config now owns the default WebSocket base.

- [ ] **Step 8: Extend REST and WS tests**

Append to `frontend/tests/rest.test.ts`:

```ts
import {
  getDesktopEnvironment,
  listDesktopTemplates,
  pauseEpisode,
  renderDesktopConfig,
  startEpisode,
} from "@/api/rest";

describe("desktop REST calls", () => {
  it("uses the injected desktop api base", async () => {
    window.__MULTI_CRANE_DESKTOP__ = { apiBase: "http://127.0.0.1:8765", mode: "desktop" };
    const urls: string[] = [];
    setFetch(async (input) => {
      urls.push(String(input));
      return jsonRes({ code: 0, data: { project_root: "/p", python_path: null, python_version: null, run_roots: [], backend_port: 8765 }, message: "ok" });
    });

    await getDesktopEnvironment();

    expect(urls[0]).toBe("http://127.0.0.1:8765/desktop/environment");
    delete window.__MULTI_CRANE_DESKTOP__;
  });

  it("starts and pauses an episode", async () => {
    setFetch(async (input, init) => {
      if (String(input).includes("/episodes/start")) {
        expect(init?.method).toBe("POST");
        return jsonRes({ code: 0, data: { episode_id: "E1", run_id: null, run_dir: null, status: "running", resolved_config_hash: "h", websocket_url: null }, message: "ok" });
      }
      return jsonRes({ code: 0, data: { episode_id: "E1", previous_status: "running", status: "paused", accepted: true, reason: null }, message: "ok" });
    });

    const started = await startEpisode({ scenario: {}, experiment: {} });
    const paused = await pauseEpisode("E1");

    expect(started.episode_id).toBe("E1");
    expect(paused.status).toBe("paused");
  });

  it("loads templates and renders config", async () => {
    setFetch(async (input) => {
      if (String(input).includes("/desktop/templates")) {
        return jsonRes({ code: 0, data: { items: [{ template_id: "demo", name: "demo", path: "configs/demo.yaml", scenario_id: "s", experiment_id: "e", description: null }] }, message: "ok" });
      }
      return jsonRes({ code: 0, data: { yaml_text: "scenario:\n  layout:\n    num_cranes: 4\n" }, message: "ok" });
    });

    const templates = await listDesktopTemplates();
    const rendered = await renderDesktopConfig("demo", { "scenario.layout.num_cranes": 4 });

    expect(templates.items[0].template_id).toBe("demo");
    expect(rendered.yaml_text).toContain("num_cranes");
  });
});
```

Append to `frontend/tests/ws.test.ts`:

```ts
describe("EpisodeWebSocketClient runtime base", () => {
  it("uses desktop wsBase when no explicit baseUrl is passed", () => {
    window.__MULTI_CRANE_DESKTOP__ = { wsBase: "ws://127.0.0.1:8765/ws", mode: "desktop" };
    const { factory, sockets } = fakeFactory();
    const clock = fakeClock();
    const c = new EpisodeWebSocketClient({
      episodeId: "E1",
      socketFactory: factory,
      now: clock.now,
      schedule: clock.schedule,
      onFrame: () => {},
      onStatus: () => {},
    });

    c.connect();

    expect(sockets[0].url).toBe("ws://127.0.0.1:8765/ws/episodes/E1");
    c.stop();
    delete window.__MULTI_CRANE_DESKTOP__;
  });
});
```

- [ ] **Step 9: Run frontend API tests**

Run:

```bash
cd frontend && npm test -- runtime.test.ts config.test.ts rest.test.ts ws.test.ts
```

Expected result:

```text
PASS
```

- [ ] **Step 10: Commit runtime API changes**

```bash
git add frontend/src/runtime.ts frontend/src/vite-env.d.ts frontend/src/api/config.ts frontend/src/api/rest.ts frontend/src/api/ws.ts frontend/src/types/api.ts frontend/tests/runtime.test.ts frontend/tests/config.test.ts frontend/tests/rest.test.ts frontend/tests/ws.test.ts
git commit -m "feat(frontend): add desktop runtime API config"
```

## Task 4: Electron Development Shell

**Files:**
- Modify: `frontend/package.json`
- Modify: `frontend/package-lock.json`
- Create: `frontend/electron/backend.mjs`
- Create: `frontend/electron/main.mjs`
- Create: `frontend/electron/preload.mjs`
- Test: `frontend/tests/electron/backend.test.ts`

- [ ] **Step 1: Install Electron**

Run:

```bash
cd frontend && npm install --save-dev electron
```

Expected result:

```text
added
```

- [ ] **Step 2: Add failing Electron helper tests**

Create `frontend/tests/electron/backend.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { makeBackendLaunch, resolvePythonPath, runtimeScriptTag, withRuntimeScript } from "../../electron/backend.mjs";

describe("electron backend helpers", () => {
  it("resolves platform-specific venv python path", () => {
    expect(resolvePythonPath("/repo", "darwin")).toBe("/repo/.venv/bin/python");
    expect(resolvePythonPath("/repo", "linux")).toBe("/repo/.venv/bin/python");
    expect(resolvePythonPath("C:/repo", "win32")).toBe("C:/repo/.venv/Scripts/python.exe");
  });

  it("builds the uvicorn backend launch command", () => {
    const launch = makeBackendLaunch({
      projectRoot: "/repo",
      pythonPath: "/repo/.venv/bin/python",
      port: 8765,
    });

    expect(launch.command).toBe("/repo/.venv/bin/python");
    expect(launch.args).toEqual([
      "-m",
      "uvicorn",
      "backend.app.main:app",
      "--host",
      "127.0.0.1",
      "--port",
      "8765",
    ]);
    expect(launch.env.MULTI_CRANE_BACKEND_PORT).toBe("8765");
  });

  it("injects desktop runtime config into index html", () => {
    const html = "<html><head></head><body><div id=\"root\"></div></body></html>";
    const tag = runtimeScriptTag({ port: 8765 });
    const injected = withRuntimeScript(html, { port: 8765 });
    expect(tag).toContain("__MULTI_CRANE_DESKTOP__");
    expect(tag).toContain("8765");
    expect(injected).toContain("__MULTI_CRANE_DESKTOP__");
  });
});
```

- [ ] **Step 3: Run helper test and verify it fails**

Run:

```bash
cd frontend && npm test -- tests/electron/backend.test.ts
```

Expected result:

```text
Failed to load url ../../electron/backend.mjs
```

- [ ] **Step 4: Implement Electron backend helpers**

Create `frontend/electron/backend.mjs`:

```js
import { spawn } from "node:child_process";
import net from "node:net";
import path from "node:path";

export function resolvePythonPath(projectRoot, platform = process.platform) {
  if (platform === "win32") {
    return path.posix.join(projectRoot.replaceAll("\\", "/"), ".venv", "Scripts", "python.exe");
  }
  return path.join(projectRoot, ".venv", "bin", "python");
}

export function makeBackendLaunch({ projectRoot, pythonPath, port }) {
  return {
    command: pythonPath,
    args: [
      "-m",
      "uvicorn",
      "backend.app.main:app",
      "--host",
      "127.0.0.1",
      "--port",
      String(port),
    ],
    cwd: projectRoot,
    env: {
      ...process.env,
      MULTI_CRANE_BACKEND_PORT: String(port),
    },
  };
}

export function findAvailablePort(start = 8765, host = "127.0.0.1") {
  return new Promise((resolve, reject) => {
    const tryPort = (port) => {
      const server = net.createServer();
      server.once("error", (error) => {
        if (error && error.code === "EADDRINUSE") {
          tryPort(port + 1);
          return;
        }
        reject(error);
      });
      server.once("listening", () => {
        server.close(() => resolve(port));
      });
      server.listen(port, host);
    };
    tryPort(start);
  });
}

export async function waitForHealth({ port, timeoutMs = 15000, intervalMs = 250, fetchImpl = fetch }) {
  const deadline = Date.now() + timeoutMs;
  let lastError = null;
  while (Date.now() < deadline) {
    try {
      const res = await fetchImpl(`http://127.0.0.1:${port}/health`);
      if (res.ok) return true;
    } catch (error) {
      lastError = error;
    }
    await new Promise((resolve) => setTimeout(resolve, intervalMs));
  }
  throw new Error(`backend health check timed out on port ${port}: ${lastError ? String(lastError) : "no response"}`);
}

export function startBackend({ projectRoot, pythonPath, port, onLog }) {
  const launch = makeBackendLaunch({ projectRoot, pythonPath, port });
  const child = spawn(launch.command, launch.args, {
    cwd: launch.cwd,
    env: launch.env,
    stdio: ["ignore", "pipe", "pipe"],
  });
  child.stdout.on("data", (chunk) => onLog?.("stdout", chunk.toString()));
  child.stderr.on("data", (chunk) => onLog?.("stderr", chunk.toString()));
  return child;
}

export function runtimeScriptTag({ port }) {
  const config = {
    apiBase: `http://127.0.0.1:${port}`,
    wsBase: `ws://127.0.0.1:${port}/ws`,
    backendPort: port,
    mode: "desktop",
  };
  return `<script>window.__MULTI_CRANE_DESKTOP__=${JSON.stringify(config)}</script>`;
}

export function withRuntimeScript(html, { port }) {
  return html.replace("<head>", `<head>${runtimeScriptTag({ port })}`);
}
```

- [ ] **Step 5: Implement Electron main process**

Create `frontend/electron/main.mjs`:

```js
import { app, BrowserWindow, ipcMain, shell } from "electron";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import {
  findAvailablePort,
  resolvePythonPath,
  startBackend,
  waitForHealth,
  withRuntimeScript,
} from "./backend.mjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const frontendRoot = path.resolve(__dirname, "..");
const projectRoot = path.resolve(frontendRoot, "..");
let backendChild = null;
let backendLogs = "";

function appendLog(stream, text) {
  backendLogs += `[${stream}] ${text}`;
  if (backendLogs.length > 20000) backendLogs = backendLogs.slice(-20000);
}

async function startBackendOrThrow() {
  const port = await findAvailablePort(8765);
  const pythonPath = resolvePythonPath(projectRoot);
  backendChild = startBackend({
    projectRoot,
    pythonPath,
    port,
    onLog: appendLog,
  });
  await waitForHealth({ port });
  return port;
}

function createWindow(port) {
  const win = new BrowserWindow({
    width: 1440,
    height: 920,
    minWidth: 1180,
    minHeight: 760,
    title: "Multi Crane Workbench",
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      preload: path.join(__dirname, "preload.mjs"),
    },
  });

  if (process.env.VITE_DEV_SERVER_URL) {
    const devUrl = new URL(process.env.VITE_DEV_SERVER_URL);
    devUrl.searchParams.set("desktopApiBase", `http://127.0.0.1:${port}`);
    devUrl.searchParams.set("desktopWsBase", `ws://127.0.0.1:${port}/ws`);
    devUrl.searchParams.set("desktopBackendPort", String(port));
    win.loadURL(devUrl.toString());
    return win;
  }

  const distIndex = path.join(frontendRoot, "dist", "index.html");
  const html = withRuntimeScript(fs.readFileSync(distIndex, "utf8"), { port });
  const tempHtml = path.join(app.getPath("userData"), "desktop-index.html");
  fs.writeFileSync(tempHtml, html, "utf8");
  win.loadFile(tempHtml);
  return win;
}

function createFailureWindow(error) {
  const win = new BrowserWindow({
    width: 980,
    height: 700,
    title: "Multi Crane Workbench - backend failed",
  });
  const body = [
    "<h1>Backend failed to start</h1>",
    `<p>${String(error.message || error)}</p>`,
    "<pre>",
    backendLogs.replace(/[<>&]/g, (char) => ({ "<": "&lt;", ">": "&gt;", "&": "&amp;" })[char]),
    "</pre>",
  ].join("");
  win.loadURL(`data:text/html;charset=utf-8,${encodeURIComponent(body)}`);
}

app.whenReady().then(async () => {
  ipcMain.handle("desktop:openPath", async (_event, targetPath) => {
    if (typeof targetPath !== "string" || targetPath.length === 0) {
      return { ok: false, error: "invalid path" };
    }
    const result = await shell.openPath(targetPath);
    return result ? { ok: false, error: result } : { ok: true };
  });
  try {
    const port = await startBackendOrThrow();
    createWindow(port);
  } catch (error) {
    createFailureWindow(error);
  }
});

app.on("before-quit", () => {
  if (backendChild && !backendChild.killed) {
    backendChild.kill();
  }
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});
```

- [ ] **Step 6: Add Electron preload bridge**

Create `frontend/electron/preload.mjs`:

```js
import { contextBridge, ipcRenderer } from "electron";

contextBridge.exposeInMainWorld("multiCraneDesktop", {
  openPath: (path) => ipcRenderer.invoke("desktop:openPath", path),
});
```

Modify `frontend/src/vite-env.d.ts` to include the bridge:

```ts
interface Window {
  multiCraneDesktop?: {
    openPath(path: string): Promise<{ ok: boolean; error?: string }>;
  };
}
```

- [ ] **Step 7: Add package scripts**

Modify `frontend/package.json` scripts:

```json
{
  "desktop": "electron electron/main.mjs",
  "desktop:dev": "VITE_DEV_SERVER_URL=http://127.0.0.1:5173 electron electron/main.mjs"
}
```

Keep existing scripts unchanged.

- [ ] **Step 8: Run Electron helper tests**

Run:

```bash
cd frontend && npm test -- tests/electron/backend.test.ts
```

Expected result:

```text
PASS
```

- [ ] **Step 9: Run frontend typecheck**

Run:

```bash
cd frontend && npm run typecheck
```

Expected result:

```text
no TypeScript errors
```

- [ ] **Step 10: Commit Electron shell**

```bash
git add frontend/package.json frontend/package-lock.json frontend/electron/backend.mjs frontend/electron/main.mjs frontend/electron/preload.mjs frontend/src/vite-env.d.ts frontend/tests/electron/backend.test.ts
git commit -m "feat(desktop): add electron development shell"
```

## Task 5: Workbench State And Config Model

**Files:**
- Create: `frontend/src/workbench/types.ts`
- Create: `frontend/src/workbench/configModel.ts`
- Create: `frontend/src/state/workbench.ts`
- Test: `frontend/tests/workbench/configModel.test.ts`

- [ ] **Step 1: Write failing config model tests**

Create `frontend/tests/workbench/configModel.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import {
  coreFormToPatches,
  defaultCoreForm,
  extractExperimentSummary,
  yamlToCoreForm,
} from "@/workbench/configModel";

const yamlText = [
  "scenario:",
  "  scenario_id: demo",
  "  layout:",
  "    num_cranes: 4",
  "    mode: manual",
  "    overlap_level: medium",
  "  tasks:",
  "    num_tasks_per_crane: 2",
  "experiment:",
  "  experiment_id: exp",
  "  sim:",
  "    duration_s: 7200",
  "    dt: 0.2",
  "    stop_when_all_tasks_done: true",
  "  llm:",
  "    enabled: true",
  "    provider: deepseek",
  "    model: deepseek-v4-flash",
  "  safety_mode: S1",
].join("\n");

describe("workbench config model", () => {
  it("extracts core form values from YAML", () => {
    const form = yamlToCoreForm(yamlText);
    expect(form.experimentId).toBe("exp");
    expect(form.scenarioId).toBe("demo");
    expect(form.numCranes).toBe(4);
    expect(form.tasksPerCrane).toBe(2);
    expect(form.durationS).toBe(7200);
    expect(form.llmProvider).toBe("deepseek");
  });

  it("maps core form values to backend patch paths", () => {
    const patches = coreFormToPatches({
      ...defaultCoreForm(),
      experimentId: "exp2",
      numCranes: 6,
      durationS: 300,
      llmProvider: "openai_compatible",
    });

    expect(patches["experiment.experiment_id"]).toBe("exp2");
    expect(patches["scenario.layout.num_cranes"]).toBe(6);
    expect(patches["experiment.sim.duration_s"]).toBe(300);
    expect(patches["experiment.llm.provider"]).toBe("openai_compatible");
  });

  it("extracts an experiment summary for the top bar", () => {
    expect(extractExperimentSummary(yamlText)).toEqual({
      scenarioId: "demo",
      experimentId: "exp",
      numCranes: 4,
      durationS: 7200,
      llmProvider: "deepseek",
    });
  });
});
```

- [ ] **Step 2: Run config model tests and verify they fail**

Run:

```bash
cd frontend && npm test -- tests/workbench/configModel.test.ts
```

Expected result:

```text
Failed to resolve import "@/workbench/configModel"
```

- [ ] **Step 3: Add workbench types**

Create `frontend/src/workbench/types.ts`:

```ts
export interface CoreExperimentForm {
  scenarioId: string;
  experimentId: string;
  seed: number;
  durationS: number;
  dt: number;
  stopWhenAllTasksDone: boolean;
  numCranes: number;
  layoutMode: string;
  overlapLevel: string;
  heightStrategy: string;
  craneModelId: string;
  tasksPerCrane: number;
  taskGenerationMode: string;
  weatherMode: string;
  windSpeedMS: number;
  gustSpeedMS: number;
  windDirectionDeg: number;
  visibility: string;
  llmEnabled: boolean;
  llmProvider: string;
  llmModel: string;
  llmBaseUrl: string;
  llmApiKeyEnv: string;
  llmTemperature: number;
  llmFallbackPolicy: string;
  riskPromptMode: string;
  safetyMode: string;
  runRoot: string;
  saveVisualFrames: boolean;
  saveParquet: boolean;
  saveReplay: boolean;
}

export interface ExperimentSummary {
  scenarioId: string;
  experimentId: string;
  numCranes: number;
  durationS: number;
  llmProvider: string;
}
```

- [ ] **Step 4: Implement config model**

Create `frontend/src/workbench/configModel.ts`:

```ts
import yaml from "js-yaml";
import type { CoreExperimentForm, ExperimentSummary } from "./types";

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : {};
}

function readPath(root: unknown, path: string[]): unknown {
  let cursor: unknown = root;
  for (const part of path) {
    cursor = asRecord(cursor)[part];
  }
  return cursor;
}

function stringAt(root: unknown, path: string[], fallback: string): string {
  const value = readPath(root, path);
  return typeof value === "string" ? value : fallback;
}

function numberAt(root: unknown, path: string[], fallback: number): number {
  const value = readPath(root, path);
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

function booleanAt(root: unknown, path: string[], fallback: boolean): boolean {
  const value = readPath(root, path);
  return typeof value === "boolean" ? value : fallback;
}

export function defaultCoreForm(): CoreExperimentForm {
  return {
    scenarioId: "desktop_demo",
    experimentId: "desktop_demo",
    seed: 20260616,
    durationS: 7200,
    dt: 0.2,
    stopWhenAllTasksDone: true,
    numCranes: 4,
    layoutMode: "manual",
    overlapLevel: "medium",
    heightStrategy: "mixed",
    craneModelId: "demo_flat_top_45m",
    tasksPerCrane: 2,
    taskGenerationMode: "manual",
    weatherMode: "constant",
    windSpeedMS: 3,
    gustSpeedMS: 5,
    windDirectionDeg: 90,
    visibility: "good",
    llmEnabled: true,
    llmProvider: "deepseek",
    llmModel: "deepseek-v4-flash",
    llmBaseUrl: "https://api.deepseek.com",
    llmApiKeyEnv: "DEEPSEEK_API_KEY",
    llmTemperature: 0.2,
    llmFallbackPolicy: "neutral_stop",
    riskPromptMode: "R1",
    safetyMode: "S1",
    runRoot: "runs/desktop",
    saveVisualFrames: true,
    saveParquet: true,
    saveReplay: true,
  };
}

export function yamlToCoreForm(text: string): CoreExperimentForm {
  const parsed = yaml.load(text);
  const form = defaultCoreForm();
  return {
    ...form,
    scenarioId: stringAt(parsed, ["scenario", "scenario_id"], form.scenarioId),
    experimentId: stringAt(parsed, ["experiment", "experiment_id"], form.experimentId),
    seed: numberAt(parsed, ["scenario", "seed"], form.seed),
    durationS: numberAt(parsed, ["experiment", "sim", "duration_s"], form.durationS),
    dt: numberAt(parsed, ["experiment", "sim", "dt"], form.dt),
    stopWhenAllTasksDone: booleanAt(parsed, ["experiment", "sim", "stop_when_all_tasks_done"], form.stopWhenAllTasksDone),
    numCranes: numberAt(parsed, ["scenario", "layout", "num_cranes"], form.numCranes),
    layoutMode: stringAt(parsed, ["scenario", "layout", "mode"], form.layoutMode),
    overlapLevel: stringAt(parsed, ["scenario", "layout", "overlap_level"], form.overlapLevel),
    heightStrategy: stringAt(parsed, ["scenario", "layout", "height_strategy"], form.heightStrategy),
    tasksPerCrane: numberAt(parsed, ["scenario", "tasks", "num_tasks_per_crane"], form.tasksPerCrane),
    taskGenerationMode: stringAt(parsed, ["scenario", "tasks", "generation_mode"], form.taskGenerationMode),
    weatherMode: stringAt(parsed, ["scenario", "weather", "mode"], form.weatherMode),
    windSpeedMS: numberAt(parsed, ["scenario", "weather", "wind", "base_speed_m_s"], form.windSpeedMS),
    gustSpeedMS: numberAt(parsed, ["scenario", "weather", "wind", "gust_speed_m_s"], form.gustSpeedMS),
    windDirectionDeg: numberAt(parsed, ["scenario", "weather", "wind", "direction_deg"], form.windDirectionDeg),
    visibility: stringAt(parsed, ["scenario", "weather", "visibility", "base_level"], form.visibility),
    llmEnabled: booleanAt(parsed, ["experiment", "llm", "enabled"], form.llmEnabled),
    llmProvider: stringAt(parsed, ["experiment", "llm", "provider"], form.llmProvider),
    llmModel: stringAt(parsed, ["experiment", "llm", "model"], form.llmModel),
    llmBaseUrl: stringAt(parsed, ["experiment", "llm", "base_url"], form.llmBaseUrl),
    llmApiKeyEnv: stringAt(parsed, ["experiment", "llm", "api_key_env"], form.llmApiKeyEnv),
    llmTemperature: numberAt(parsed, ["experiment", "llm", "temperature"], form.llmTemperature),
    llmFallbackPolicy: stringAt(parsed, ["experiment", "llm", "fallback_policy"], form.llmFallbackPolicy),
    riskPromptMode: stringAt(parsed, ["experiment", "risk_prompt_mode"], form.riskPromptMode),
    safetyMode: stringAt(parsed, ["experiment", "safety_mode"], form.safetyMode),
    runRoot: stringAt(parsed, ["experiment", "output", "run_root"], form.runRoot),
    saveVisualFrames: booleanAt(parsed, ["experiment", "output", "save_visual_frames"], form.saveVisualFrames),
    saveParquet: booleanAt(parsed, ["experiment", "output", "save_parquet"], form.saveParquet),
    saveReplay: booleanAt(parsed, ["experiment", "output", "save_replay"], form.saveReplay),
  };
}

export function coreFormToPatches(form: CoreExperimentForm): Record<string, unknown> {
  return {
    "scenario.scenario_id": form.scenarioId,
    "scenario.seed": form.seed,
    "scenario.layout.num_cranes": form.numCranes,
    "scenario.layout.mode": form.layoutMode,
    "scenario.layout.overlap_level": form.overlapLevel,
    "scenario.layout.height_strategy": form.heightStrategy,
    "scenario.tasks.num_tasks_per_crane": form.tasksPerCrane,
    "scenario.tasks.generation_mode": form.taskGenerationMode,
    "scenario.weather.mode": form.weatherMode,
    "scenario.weather.wind.base_speed_m_s": form.windSpeedMS,
    "scenario.weather.wind.gust_speed_m_s": form.gustSpeedMS,
    "scenario.weather.wind.direction_deg": form.windDirectionDeg,
    "scenario.weather.visibility.base_level": form.visibility,
    "experiment.experiment_id": form.experimentId,
    "experiment.sim.duration_s": form.durationS,
    "experiment.sim.dt": form.dt,
    "experiment.sim.stop_when_all_tasks_done": form.stopWhenAllTasksDone,
    "experiment.llm.enabled": form.llmEnabled,
    "experiment.llm.provider": form.llmProvider,
    "experiment.llm.model": form.llmModel,
    "experiment.llm.base_url": form.llmBaseUrl,
    "experiment.llm.api_key_env": form.llmApiKeyEnv,
    "experiment.llm.temperature": form.llmTemperature,
    "experiment.llm.fallback_policy": form.llmFallbackPolicy,
    "experiment.risk_prompt_mode": form.riskPromptMode,
    "experiment.safety_mode": form.safetyMode,
    "experiment.output.run_root": form.runRoot,
    "experiment.output.save_visual_frames": form.saveVisualFrames,
    "experiment.output.save_parquet": form.saveParquet,
    "experiment.output.save_replay": form.saveReplay,
  };
}

export function extractExperimentSummary(text: string): ExperimentSummary {
  const form = yamlToCoreForm(text);
  return {
    scenarioId: form.scenarioId,
    experimentId: form.experimentId,
    numCranes: form.numCranes,
    durationS: form.durationS,
    llmProvider: form.llmProvider,
  };
}
```

- [ ] **Step 5: Add workbench store**

Create `frontend/src/state/workbench.ts`:

```ts
import { create } from "zustand";
import type { ScenarioValidateResult, DesktopTemplate, EpisodeStartResponse, EpisodeStateResponse } from "@/types/api";
import type { CoreExperimentForm, ExperimentSummary } from "@/workbench/types";
import { defaultCoreForm, extractExperimentSummary } from "@/workbench/configModel";

export interface WorkbenchState {
  templates: DesktopTemplate[];
  selectedTemplateId: string | null;
  yamlText: string;
  form: CoreExperimentForm;
  summary: ExperimentSummary | null;
  validation: ScenarioValidateResult | null;
  validationError: string | null;
  currentEpisode: EpisodeStartResponse | null;
  episodeState: EpisodeStateResponse | null;
  busy: boolean;
  setTemplates(items: DesktopTemplate[]): void;
  setTemplate(id: string | null): void;
  setYamlText(text: string): void;
  setFormPatch(patch: Partial<CoreExperimentForm>): void;
  setValidation(result: ScenarioValidateResult | null, error?: string | null): void;
  setCurrentEpisode(result: EpisodeStartResponse | null): void;
  setEpisodeState(result: EpisodeStateResponse | null): void;
  setBusy(busy: boolean): void;
  resetWorkbench(): void;
}

const initialForm = defaultCoreForm();

export const useWorkbenchStore = create<WorkbenchState>((set, get) => ({
  templates: [],
  selectedTemplateId: null,
  yamlText: "",
  form: initialForm,
  summary: null,
  validation: null,
  validationError: null,
  currentEpisode: null,
  episodeState: null,
  busy: false,
  setTemplates: (items) => set({ templates: items }),
  setTemplate: (id) => set({ selectedTemplateId: id }),
  setYamlText: (text) => {
    let summary: ExperimentSummary | null = null;
    try {
      summary = extractExperimentSummary(text);
    } catch {
      summary = get().summary;
    }
    set({ yamlText: text, summary });
  },
  setFormPatch: (patch) => set((state) => ({ form: { ...state.form, ...patch } })),
  setValidation: (result, error = null) => set({ validation: result, validationError: error }),
  setCurrentEpisode: (result) => set({ currentEpisode: result }),
  setEpisodeState: (result) => set({ episodeState: result }),
  setBusy: (busy) => set({ busy }),
  resetWorkbench: () =>
    set({
      templates: [],
      selectedTemplateId: null,
      yamlText: "",
      form: defaultCoreForm(),
      summary: null,
      validation: null,
      validationError: null,
      currentEpisode: null,
      episodeState: null,
      busy: false,
    }),
}));
```

- [ ] **Step 6: Run config model tests**

Run:

```bash
cd frontend && npm test -- tests/workbench/configModel.test.ts
```

Expected result:

```text
PASS
```

- [ ] **Step 7: Commit workbench state**

```bash
git add frontend/src/workbench/types.ts frontend/src/workbench/configModel.ts frontend/src/state/workbench.ts frontend/tests/workbench/configModel.test.ts
git commit -m "feat(frontend): add workbench config state"
```

## Task 6: Workbench Shell And Navigation

**Files:**
- Create: `frontend/src/components/workbench/WorkbenchShell.tsx`
- Create: `frontend/src/components/workbench/ExperimentPage.tsx`
- Create: `frontend/src/components/workbench/ConfigurationPage.tsx`
- Create: `frontend/src/components/workbench/RunPage.tsx`
- Create: `frontend/src/components/workbench/VisualizationPage.tsx`
- Create: `frontend/src/components/workbench/DataExportPage.tsx`
- Create: `frontend/src/components/workbench/SettingsPage.tsx`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/styles.css`
- Test: `frontend/tests/workbench/shell.test.tsx`

- [ ] **Step 1: Write failing shell test**

Create `frontend/tests/workbench/shell.test.tsx`:

```tsx
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { AppRoutes } from "@/App";

describe("WorkbenchShell", () => {
  it("renders the six workbench navigation entries", () => {
    render(
      <MemoryRouter initialEntries={["/"]}>
        <AppRoutes />
      </MemoryRouter>,
    );

    for (const label of ["实验", "配置", "运行", "3D 可视化", "数据/导出", "设置"]) {
      expect(screen.getByRole("link", { name: label })).toBeTruthy();
    }
  });

  it("opens the run page route", () => {
    render(
      <MemoryRouter initialEntries={["/run"]}>
        <AppRoutes />
      </MemoryRouter>,
    );

    expect(screen.getByRole("heading", { name: "运行" })).toBeTruthy();
  });
});
```

- [ ] **Step 2: Run shell test and verify it fails**

Run:

```bash
cd frontend && npm test -- tests/workbench/shell.test.tsx
```

Expected result:

```text
Unable to find role="link" and name "实验"
```

- [ ] **Step 3: Add workbench shell**

Create `frontend/src/components/workbench/WorkbenchShell.tsx`:

```tsx
import type { ReactNode } from "react";
import { NavLink } from "react-router-dom";
import { ConnectionBadge } from "@/components/ConnectionBadge";
import { useWorkbenchStore } from "@/state/workbench";

const nav = [
  { to: "/", label: "实验" },
  { to: "/config", label: "配置" },
  { to: "/run", label: "运行" },
  { to: "/visualization", label: "3D 可视化" },
  { to: "/data", label: "数据/导出" },
  { to: "/settings", label: "设置" },
];

export function WorkbenchShell({ children }: { children: ReactNode }) {
  const summary = useWorkbenchStore((s) => s.summary);
  const episode = useWorkbenchStore((s) => s.currentEpisode);
  return (
    <div className="workbench-shell">
      <aside className="workbench-nav" aria-label="工作台导航">
        <div className="workbench-brand">
          <span className="brand-badge" aria-hidden>塔</span>
          <span>群塔实验工作台</span>
        </div>
        <nav>
          {nav.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === "/"}
              className={({ isActive }) => `workbench-nav-link${isActive ? " active" : ""}`}
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
      </aside>
      <div className="workbench-content">
        <header className="workbench-topbar">
          <div>
            <div className="workbench-title">{summary?.experimentId ?? "未选择实验"}</div>
            <div className="muted">
              {summary ? `${summary.numCranes} 台塔吊 · ${summary.durationS}s · ${summary.llmProvider}` : "请选择模板或导入 YAML"}
            </div>
          </div>
          <span className="topbar-spacer" />
          {episode && <span className="chip">{episode.status} · {episode.episode_id}</span>}
          <ConnectionBadge />
        </header>
        <main className="workbench-page">{children}</main>
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Add initial page components**

Create `frontend/src/components/workbench/ExperimentPage.tsx`:

```tsx
export function ExperimentPage() {
  return (
    <section className="page-section">
      <h1>实验</h1>
      <p className="muted">从模板创建实验，或导入已有 YAML 配置。</p>
    </section>
  );
}
```

Create `frontend/src/components/workbench/ConfigurationPage.tsx`:

```tsx
export function ConfigurationPage() {
  return (
    <section className="page-section">
      <h1>配置</h1>
      <p className="muted">核心表单和高级 YAML 编辑器会在这里组织 Module A/B/D/E/G/H/J/L。</p>
    </section>
  );
}
```

Create `frontend/src/components/workbench/RunPage.tsx`:

```tsx
export function RunPage() {
  return (
    <section className="page-section">
      <h1>运行</h1>
      <p className="muted">启动、暂停、继续、停止 episode，并查看模块链路状态。</p>
    </section>
  );
}
```

Create `frontend/src/components/workbench/VisualizationPage.tsx`:

```tsx
import { useEffect } from "react";
import { Layout } from "@/components/Layout";
import { LeftControls } from "@/components/LeftControls";
import { Panels } from "@/components/panels/Panels";
import { SceneView } from "@/components/SceneView";
import { Timeline } from "@/components/Timeline";
import { ensureDemoLoaded } from "@/bootstrap";
import { useRealtimeEpisode } from "@/hooks/useRealtimeEpisode";
import { useWorkbenchStore } from "@/state/workbench";

export function VisualizationPage() {
  const episodeId = useWorkbenchStore((s) => s.currentEpisode?.episode_id ?? null);
  useRealtimeEpisode(episodeId ?? undefined);
  useEffect(() => {
    if (!episodeId) ensureDemoLoaded();
  }, [episodeId]);
  return (
    <div className="visualization-embed">
      <Layout left={<LeftControls />} center={<SceneView />} right={<Panels />} bottom={<Timeline />} />
    </div>
  );
}
```

Create `frontend/src/components/workbench/DataExportPage.tsx`:

```tsx
export function DataExportPage() {
  return (
    <section className="page-section">
      <h1>数据/导出</h1>
      <p className="muted">下载 episode zip、查看 run 文件清单，并保留 K/O/P 研究链路入口。</p>
    </section>
  );
}
```

Create `frontend/src/components/workbench/SettingsPage.tsx`:

```tsx
export function SettingsPage() {
  return (
    <section className="page-section">
      <h1>设置</h1>
      <p className="muted">查看后端、Python 环境、输出目录和 LLM 供应商设置。</p>
    </section>
  );
}
```

- [ ] **Step 5: Route App through workbench shell**

Replace `frontend/src/App.tsx` with:

```tsx
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { WorkbenchShell } from "@/components/workbench/WorkbenchShell";
import { ExperimentPage } from "@/components/workbench/ExperimentPage";
import { ConfigurationPage } from "@/components/workbench/ConfigurationPage";
import { RunPage } from "@/components/workbench/RunPage";
import { VisualizationPage } from "@/components/workbench/VisualizationPage";
import { DataExportPage } from "@/components/workbench/DataExportPage";
import { SettingsPage } from "@/components/workbench/SettingsPage";

export function AppRoutes() {
  return (
    <WorkbenchShell>
      <Routes>
        <Route path="/" element={<ExperimentPage />} />
        <Route path="/config" element={<ConfigurationPage />} />
        <Route path="/run" element={<RunPage />} />
        <Route path="/visualization" element={<VisualizationPage />} />
        <Route path="/data" element={<DataExportPage />} />
        <Route path="/settings" element={<SettingsPage />} />
        <Route path="*" element={<ExperimentPage />} />
      </Routes>
    </WorkbenchShell>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <AppRoutes />
    </BrowserRouter>
  );
}
```

- [ ] **Step 6: Add workbench styles**

Append to `frontend/src/styles.css`:

```css
@layer components {
  .workbench-shell {
    height: 100vh;
    display: grid;
    grid-template-columns: 224px 1fr;
    background: var(--bg);
    color: var(--text);
  }

  .workbench-nav {
    border-right: 1px solid var(--line);
    background: var(--panel);
    padding: 16px 12px;
    display: flex;
    flex-direction: column;
    gap: 16px;
  }

  .workbench-brand {
    display: flex;
    align-items: center;
    gap: 10px;
    font-weight: 700;
    font-size: 14px;
    padding: 4px 6px 12px;
    border-bottom: 1px solid var(--line);
  }

  .workbench-nav nav {
    display: flex;
    flex-direction: column;
    gap: 4px;
  }

  .workbench-nav-link {
    color: var(--muted);
    padding: 9px 10px;
    border-radius: var(--radius-md);
    font-size: 13px;
    font-weight: 500;
  }

  .workbench-nav-link:hover {
    background: var(--panel-2);
    color: var(--text);
  }

  .workbench-nav-link.active {
    background: var(--accent-soft);
    color: var(--accent);
  }

  .workbench-content {
    min-width: 0;
    min-height: 0;
    display: flex;
    flex-direction: column;
  }

  .workbench-topbar {
    height: 58px;
    border-bottom: 1px solid var(--line);
    background: var(--panel);
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 0 18px;
  }

  .workbench-title {
    font-size: 15px;
    font-weight: 700;
  }

  .topbar-spacer {
    flex: 1;
  }

  .workbench-page {
    min-height: 0;
    flex: 1;
    overflow: auto;
  }

  .page-section {
    padding: 20px;
    max-width: 1200px;
  }

  .visualization-embed {
    height: calc(100vh - 58px);
    min-height: 0;
  }
}
```

- [ ] **Step 7: Run shell test**

Run:

```bash
cd frontend && npm test -- tests/workbench/shell.test.tsx
```

Expected result:

```text
PASS
```

- [ ] **Step 8: Commit shell navigation**

```bash
git add frontend/src/App.tsx frontend/src/components/workbench frontend/src/styles.css frontend/tests/workbench/shell.test.tsx
git commit -m "feat(frontend): add desktop workbench shell"
```

## Task 7: Configuration Page Template/Form/YAML Flow

**Files:**
- Modify: `frontend/src/components/workbench/ConfigurationPage.tsx`
- Modify: `frontend/src/components/workbench/ExperimentPage.tsx`
- Test: `frontend/tests/workbench/configuration.test.tsx`

- [ ] **Step 1: Write failing configuration tests**

Create `frontend/tests/workbench/configuration.test.tsx`:

```tsx
import { describe, expect, it, beforeEach, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { WorkbenchShell } from "@/components/workbench/WorkbenchShell";
import { ConfigurationPage } from "@/components/workbench/ConfigurationPage";
import { ExperimentPage } from "@/components/workbench/ExperimentPage";
import { useWorkbenchStore } from "@/state/workbench";

function jsonRes(body: unknown) {
  return Promise.resolve({
    ok: true,
    status: 200,
    text: async () => JSON.stringify(body),
    json: async () => body,
  });
}

beforeEach(() => {
  useWorkbenchStore.getState().resetWorkbench();
  global.fetch = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.includes("/desktop/templates")) {
      return jsonRes({ code: 0, data: { items: [{ template_id: "demo", name: "demo", path: "configs/demo.yaml", scenario_id: "s", experiment_id: "e", description: null }] }, message: "ok" });
    }
    if (url.includes("/desktop/config/render")) {
      return jsonRes({ code: 0, data: { yaml_text: "scenario:\n  scenario_id: s\n  layout:\n    num_cranes: 4\nexperiment:\n  experiment_id: e\n  sim:\n    duration_s: 7200\n  llm:\n    provider: deepseek\n" }, message: "ok" });
    }
    if (url.includes("/desktop/config/patch")) {
      return jsonRes({ code: 0, data: { yaml_text: "scenario:\n  scenario_id: s\n  layout:\n    num_cranes: 6\nexperiment:\n  experiment_id: e\n  sim:\n    duration_s: 7200\n  llm:\n    provider: deepseek\n" }, message: "ok" });
    }
    return jsonRes({ code: 0, data: { valid: true, resolved_config_hash: "hash", warnings: [], errors: [] }, message: "ok" });
  }) as unknown as typeof fetch;
});

function renderConfig() {
  render(
    <MemoryRouter>
      <WorkbenchShell>
        <ConfigurationPage />
      </WorkbenchShell>
    </MemoryRouter>,
  );
}

describe("ConfigurationPage", () => {
  it("loads templates and renders YAML", async () => {
    renderConfig();

    fireEvent.click(screen.getByRole("button", { name: "加载模板" }));

    await waitFor(() => expect(screen.getByDisplayValue(/scenario:/)).toBeTruthy());
    expect(useWorkbenchStore.getState().selectedTemplateId).toBe("demo");
  });

  it("patches YAML when crane count changes", async () => {
    renderConfig();
    fireEvent.click(screen.getByRole("button", { name: "加载模板" }));
    await screen.findByDisplayValue(/scenario:/);

    fireEvent.change(screen.getByLabelText("塔吊数量"), { target: { value: "6" } });
    fireEvent.click(screen.getByRole("button", { name: "同步表单到 YAML" }));

    await waitFor(() => expect(screen.getByDisplayValue(/num_cranes: 6/)).toBeTruthy());
  });

  it("validates YAML through backend", async () => {
    renderConfig();
    fireEvent.click(screen.getByRole("button", { name: "加载模板" }));
    await screen.findByDisplayValue(/scenario:/);

    fireEvent.click(screen.getByRole("button", { name: "校验配置" }));

    await waitFor(() => expect(screen.getByText("校验通过")).toBeTruthy());
  });
});

describe("ExperimentPage", () => {
  it("shows current experiment summary", () => {
    useWorkbenchStore.getState().setYamlText(
      "scenario:\n  scenario_id: s\n  layout:\n    num_cranes: 4\nexperiment:\n  experiment_id: e\n  sim:\n    duration_s: 10\n  llm:\n    provider: deepseek\n",
    );
    render(
      <MemoryRouter>
        <WorkbenchShell>
          <ExperimentPage />
        </WorkbenchShell>
      </MemoryRouter>,
    );

    expect(screen.getByText("e")).toBeTruthy();
    expect(screen.getByText("4 台塔吊")).toBeTruthy();
  });
});
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
cd frontend && npm test -- tests/workbench/configuration.test.tsx
```

Expected result:

```text
Unable to find role="button" and name "加载模板"
```

- [ ] **Step 3: Implement ConfigurationPage**

Replace `frontend/src/components/workbench/ConfigurationPage.tsx` with:

```tsx
import { useState } from "react";
import { buildValidateRequest } from "@/api/config";
import {
  listDesktopTemplates,
  patchDesktopConfig,
  renderDesktopConfig,
  validateScenario,
} from "@/api/rest";
import { useWorkbenchStore } from "@/state/workbench";
import { coreFormToPatches } from "@/workbench/configModel";

export function ConfigurationPage() {
  const templates = useWorkbenchStore((s) => s.templates);
  const form = useWorkbenchStore((s) => s.form);
  const yamlText = useWorkbenchStore((s) => s.yamlText);
  const validation = useWorkbenchStore((s) => s.validation);
  const validationError = useWorkbenchStore((s) => s.validationError);
  const setTemplates = useWorkbenchStore((s) => s.setTemplates);
  const setTemplate = useWorkbenchStore((s) => s.setTemplate);
  const setYamlText = useWorkbenchStore((s) => s.setYamlText);
  const setFormPatch = useWorkbenchStore((s) => s.setFormPatch);
  const setValidation = useWorkbenchStore((s) => s.setValidation);
  const setBusy = useWorkbenchStore((s) => s.setBusy);
  const [error, setError] = useState<string | null>(null);

  async function loadTemplate() {
    setError(null);
    setBusy(true);
    try {
      const list = await listDesktopTemplates();
      setTemplates(list.items);
      const first = list.items[0];
      if (!first) throw new Error("没有可用模板");
      setTemplate(first.template_id);
      const rendered = await renderDesktopConfig(first.template_id, coreFormToPatches(form));
      setYamlText(rendered.yaml_text);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function syncForm() {
    setError(null);
    setBusy(true);
    try {
      const patched = await patchDesktopConfig(yamlText, coreFormToPatches(form));
      setYamlText(patched.yaml_text);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function validate() {
    setError(null);
    setBusy(true);
    try {
      const result = await validateScenario(buildValidateRequest(yamlText));
      setValidation(result, null);
    } catch (e) {
      setValidation(null, (e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="page-section config-workbench">
      <div className="page-header-row">
        <div>
          <h1>配置</h1>
          <p className="muted">核心表单 + 高级 YAML，由后端 Module A 权威校验。</p>
        </div>
        <button type="button" onClick={loadTemplate}>加载模板</button>
      </div>
      {error && <div className="notice error">{error}</div>}
      <div className="config-grid">
        <div className="panel">
          <h3>核心参数</h3>
          <div className="panel-body form-grid">
            <label>
              塔吊数量
              <input type="number" value={form.numCranes} onChange={(e) => setFormPatch({ numCranes: Number(e.target.value) })} />
            </label>
            <label>
              仿真时长
              <input type="number" value={form.durationS} onChange={(e) => setFormPatch({ durationS: Number(e.target.value) })} />
            </label>
            <label>
              LLM 供应商
              <select value={form.llmProvider} onChange={(e) => setFormPatch({ llmProvider: e.target.value })}>
                <option value="deepseek">DeepSeek</option>
                <option value="openai_compatible">OpenAI-compatible</option>
                <option value="custom">自定义</option>
                <option value="disabled">禁用 LLM</option>
              </select>
            </label>
            <label>
              模型
              <input value={form.llmModel} onChange={(e) => setFormPatch({ llmModel: e.target.value })} />
            </label>
            <label>
              API Key 环境变量
              <input value={form.llmApiKeyEnv} onChange={(e) => setFormPatch({ llmApiKeyEnv: e.target.value })} />
            </label>
            <label>
              安全模式
              <select value={form.safetyMode} onChange={(e) => setFormPatch({ safetyMode: e.target.value })}>
                <option value="S0">S0</option>
                <option value="S1">S1</option>
              </select>
            </label>
            <button type="button" onClick={syncForm}>同步表单到 YAML</button>
          </div>
        </div>
        <div className="panel yaml-panel">
          <h3>高级 YAML</h3>
          <div className="panel-body">
            <textarea
              aria-label="高级 YAML"
              value={yamlText}
              onChange={(e) => setYamlText(e.target.value)}
            />
            <div className="button-row">
              <button type="button" onClick={validate}>校验配置</button>
              {validation?.valid && <span className="chip success">校验通过</span>}
              {validationError && <span className="chip danger">{validationError}</span>}
            </div>
          </div>
        </div>
      </div>
      {templates.length > 0 && <div className="muted">已发现 {templates.length} 个模板。</div>}
    </section>
  );
}
```

- [ ] **Step 4: Implement ExperimentPage summary**

Replace `frontend/src/components/workbench/ExperimentPage.tsx` with:

```tsx
import { useWorkbenchStore } from "@/state/workbench";

export function ExperimentPage() {
  const summary = useWorkbenchStore((s) => s.summary);
  const validation = useWorkbenchStore((s) => s.validation);
  return (
    <section className="page-section">
      <h1>实验</h1>
      <p className="muted">从模板创建实验，或导入已有 YAML 配置。</p>
      <div className="panel">
        <h3>当前实验</h3>
        <div className="panel-body summary-grid">
          <div><span className="muted">实验</span><strong>{summary?.experimentId ?? "未选择"}</strong></div>
          <div><span className="muted">场景</span><strong>{summary?.scenarioId ?? "未选择"}</strong></div>
          <div><span className="muted">塔吊</span><strong>{summary ? `${summary.numCranes} 台塔吊` : "未选择"}</strong></div>
          <div><span className="muted">时长</span><strong>{summary ? `${summary.durationS}s` : "未选择"}</strong></div>
          <div><span className="muted">LLM</span><strong>{summary?.llmProvider ?? "未选择"}</strong></div>
          <div><span className="muted">校验</span><strong>{validation?.valid ? "通过" : "未校验"}</strong></div>
        </div>
      </div>
    </section>
  );
}
```

- [ ] **Step 5: Add configuration styles**

Append to `frontend/src/styles.css`:

```css
@layer components {
  .page-header-row {
    display: flex;
    align-items: center;
    gap: 16px;
    justify-content: space-between;
    margin-bottom: 14px;
  }

  .config-grid {
    display: grid;
    grid-template-columns: minmax(320px, 420px) minmax(420px, 1fr);
    gap: 14px;
    align-items: start;
  }

  .form-grid {
    display: grid;
    gap: 10px;
  }

  .form-grid label {
    display: grid;
    gap: 5px;
    color: var(--muted);
    font-size: 12px;
  }

  .yaml-panel textarea {
    width: 100%;
    min-height: 520px;
    resize: vertical;
    font-family: var(--font-mono);
    line-height: 1.45;
  }

  .button-row {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-top: 10px;
  }

  .summary-grid {
    display: grid;
    grid-template-columns: repeat(3, minmax(120px, 1fr));
    gap: 12px;
  }

  .summary-grid div {
    display: grid;
    gap: 4px;
  }

  .notice.error,
  .chip.danger {
    color: #b91c1c;
    border-color: #fecaca;
    background: #fef2f2;
  }

  .chip.success {
    color: #15803d;
    border-color: #bbf7d0;
    background: #f0fdf4;
  }
}
```

- [ ] **Step 6: Run configuration tests**

Run:

```bash
cd frontend && npm test -- tests/workbench/configuration.test.tsx
```

Expected result:

```text
PASS
```

- [ ] **Step 7: Commit configuration flow**

```bash
git add frontend/src/components/workbench/ConfigurationPage.tsx frontend/src/components/workbench/ExperimentPage.tsx frontend/src/styles.css frontend/tests/workbench/configuration.test.tsx
git commit -m "feat(frontend): add workbench configuration flow"
```

## Task 8: Run Controls And Episode State

**Files:**
- Modify: `frontend/src/components/workbench/RunPage.tsx`
- Test: `frontend/tests/workbench/run.test.tsx`

- [ ] **Step 1: Write failing run page tests**

Create `frontend/tests/workbench/run.test.tsx`:

```tsx
import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { WorkbenchShell } from "@/components/workbench/WorkbenchShell";
import { RunPage } from "@/components/workbench/RunPage";
import { useWorkbenchStore } from "@/state/workbench";

function jsonRes(body: unknown) {
  return Promise.resolve({
    ok: true,
    status: 200,
    text: async () => JSON.stringify(body),
    json: async () => body,
  });
}

beforeEach(() => {
  useWorkbenchStore.getState().resetWorkbench();
  useWorkbenchStore.getState().setYamlText(
    "scenario:\n  scenario_id: s\nexperiment:\n  experiment_id: e\n",
  );
  global.fetch = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.includes("/episodes/start")) {
      return jsonRes({ code: 0, data: { episode_id: "E1", run_id: "R1", run_dir: "runs/E1", status: "running", resolved_config_hash: "h", websocket_url: null }, message: "ok" });
    }
    if (url.includes("/pause")) {
      return jsonRes({ code: 0, data: { episode_id: "E1", previous_status: "running", status: "paused", accepted: true, reason: null }, message: "ok" });
    }
    if (url.includes("/resume")) {
      return jsonRes({ code: 0, data: { episode_id: "E1", previous_status: "paused", status: "running", accepted: true, reason: null }, message: "ok" });
    }
    if (url.includes("/stop")) {
      return jsonRes({ code: 0, data: { episode_id: "E1", previous_status: "running", status: "stopped", accepted: true, reason: null }, message: "ok" });
    }
    return jsonRes({ code: 0, data: { episode_id: "E1", status: "running", frame_index: 3, time_s: 1.5, run_dir: "runs/E1", last_frame: null, terminal_reason: null, metrics: { risk_events: 2 } }, message: "ok" });
  }) as unknown as typeof fetch;
});

function renderRun() {
  render(
    <MemoryRouter>
      <WorkbenchShell>
        <RunPage />
      </WorkbenchShell>
    </MemoryRouter>,
  );
}

describe("RunPage", () => {
  it("starts an episode and loads state", async () => {
    renderRun();
    fireEvent.click(screen.getByRole("button", { name: "启动" }));

    await waitFor(() => expect(screen.getByText("E1")).toBeTruthy());
    expect(screen.getByText("running")).toBeTruthy();
    expect(screen.getByText("frame 3")).toBeTruthy();
  });

  it("supports pause resume and stop", async () => {
    renderRun();
    fireEvent.click(screen.getByRole("button", { name: "启动" }));
    await waitFor(() => expect(screen.getByText("E1")).toBeTruthy());

    fireEvent.click(screen.getByRole("button", { name: "暂停" }));
    fireEvent.click(screen.getByRole("button", { name: "继续" }));
    fireEvent.click(screen.getByRole("button", { name: "停止" }));

    await waitFor(() => expect(global.fetch).toHaveBeenCalledWith(expect.stringContaining("/stop"), expect.anything()));
  });
});
```

- [ ] **Step 2: Run run tests and verify they fail**

Run:

```bash
cd frontend && npm test -- tests/workbench/run.test.tsx
```

Expected result:

```text
Unable to find role="button" and name "启动"
```

- [ ] **Step 3: Implement RunPage**

Replace `frontend/src/components/workbench/RunPage.tsx` with:

```tsx
import { buildValidateRequest } from "@/api/config";
import { getEpisodeState, pauseEpisode, resumeEpisode, startEpisode, stopEpisode, validateScenario } from "@/api/rest";
import { useStore } from "@/state/store";
import { useWorkbenchStore } from "@/state/workbench";

export function RunPage() {
  const yamlText = useWorkbenchStore((s) => s.yamlText);
  const currentEpisode = useWorkbenchStore((s) => s.currentEpisode);
  const episodeState = useWorkbenchStore((s) => s.episodeState);
  const setCurrentEpisode = useWorkbenchStore((s) => s.setCurrentEpisode);
  const setEpisodeState = useWorkbenchStore((s) => s.setEpisodeState);
  const setValidation = useWorkbenchStore((s) => s.setValidation);
  const setEpisodeId = useStore((s) => s.setEpisodeId);
  const setMode = useStore((s) => s.setMode);

  async function validate() {
    const result = await validateScenario(buildValidateRequest(yamlText));
    setValidation(result, null);
  }

  async function start() {
    const req = buildValidateRequest(yamlText);
    const started = await startEpisode({ ...req, run_mode: "interactive_server", runner: "production", autostart: true });
    setCurrentEpisode(started);
    setEpisodeId(started.episode_id);
    setMode("live");
    const state = await getEpisodeState(started.episode_id);
    setEpisodeState(state);
  }

  async function refresh() {
    if (!currentEpisode) return;
    setEpisodeState(await getEpisodeState(currentEpisode.episode_id));
  }

  async function pause() {
    if (!currentEpisode) return;
    await pauseEpisode(currentEpisode.episode_id);
    await refresh();
  }

  async function resume() {
    if (!currentEpisode) return;
    await resumeEpisode(currentEpisode.episode_id);
    await refresh();
  }

  async function stop() {
    if (!currentEpisode) return;
    await stopEpisode(currentEpisode.episode_id);
    await refresh();
  }

  return (
    <section className="page-section">
      <div className="page-header-row">
        <div>
          <h1>运行</h1>
          <p className="muted">通过 Module M/J 启动 episode，并查看模块链路状态。</p>
        </div>
        <div className="button-row">
          <button type="button" onClick={validate}>校验</button>
          <button type="button" onClick={start}>启动</button>
          <button type="button" onClick={pause} disabled={!currentEpisode}>暂停</button>
          <button type="button" onClick={resume} disabled={!currentEpisode}>继续</button>
          <button type="button" onClick={stop} disabled={!currentEpisode}>停止</button>
          <button type="button" onClick={refresh} disabled={!currentEpisode}>刷新状态</button>
        </div>
      </div>
      <div className="panel">
        <h3>Episode 状态</h3>
        <div className="panel-body summary-grid">
          <div><span className="muted">episode</span><strong>{currentEpisode?.episode_id ?? "未启动"}</strong></div>
          <div><span className="muted">状态</span><strong>{episodeState?.status ?? currentEpisode?.status ?? "idle"}</strong></div>
          <div><span className="muted">帧</span><strong>{episodeState ? `frame ${episodeState.frame_index}` : "-"}</strong></div>
          <div><span className="muted">时间</span><strong>{episodeState ? `${episodeState.time_s.toFixed(1)}s` : "-"}</strong></div>
          <div><span className="muted">run_dir</span><strong>{episodeState?.run_dir ?? currentEpisode?.run_dir ?? "-"}</strong></div>
          <div><span className="muted">terminal</span><strong>{episodeState?.terminal_reason ?? "-"}</strong></div>
        </div>
      </div>
      <div className="panel">
        <h3>模块链路摘要</h3>
        <div className="panel-body module-grid">
          {["C 物理", "D 任务", "E 天气", "F Observation", "G LLM", "H 安全", "I 控制器", "L 记录"].map((label) => (
            <div key={label} className="module-card">
              <strong>{label}</strong>
              <span className="muted">{episodeState ? "等待后端指标扩展" : "未运行"}</span>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
```

- [ ] **Step 4: Add module grid styles**

Append to `frontend/src/styles.css`:

```css
@layer components {
  .module-grid {
    display: grid;
    grid-template-columns: repeat(4, minmax(120px, 1fr));
    gap: 10px;
  }

  .module-card {
    border: 1px solid var(--line);
    border-radius: var(--radius-md);
    background: var(--panel-2);
    padding: 10px;
    display: grid;
    gap: 5px;
  }
}
```

- [ ] **Step 5: Run run tests**

Run:

```bash
cd frontend && npm test -- tests/workbench/run.test.tsx
```

Expected result:

```text
PASS
```

- [ ] **Step 6: Commit run controls**

```bash
git add frontend/src/components/workbench/RunPage.tsx frontend/src/styles.css frontend/tests/workbench/run.test.tsx
git commit -m "feat(frontend): add workbench run controls"
```

## Task 9: Data Export And Settings Pages

**Files:**
- Modify: `frontend/src/components/workbench/DataExportPage.tsx`
- Modify: `frontend/src/components/workbench/SettingsPage.tsx`
- Test: `frontend/tests/workbench/export-settings.test.tsx`

- [ ] **Step 1: Write failing export/settings tests**

Create `frontend/tests/workbench/export-settings.test.tsx`:

```tsx
import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { WorkbenchShell } from "@/components/workbench/WorkbenchShell";
import { DataExportPage } from "@/components/workbench/DataExportPage";
import { SettingsPage } from "@/components/workbench/SettingsPage";
import { useWorkbenchStore } from "@/state/workbench";

function jsonRes(body: unknown) {
  return Promise.resolve({
    ok: true,
    status: 200,
    text: async () => JSON.stringify(body),
    json: async () => body,
    blob: async () => new Blob(["zip"]),
  });
}

beforeEach(() => {
  useWorkbenchStore.getState().resetWorkbench();
  useWorkbenchStore.getState().setCurrentEpisode({ episode_id: "E1", run_id: null, run_dir: "runs/E1", status: "completed", resolved_config_hash: "h", websocket_url: null });
  global.fetch = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.includes("/desktop/runs/E1/files")) {
      return jsonRes({ code: 0, data: { episode_id: "E1", files: [{ relative_path: "visual/frames.jsonl", path: "/runs/E1/visual/frames.jsonl", size_bytes: 12, kind: "visual" }] }, message: "ok" });
    }
    if (url.includes("/desktop/runs")) {
      return jsonRes({ code: 0, data: { items: [{ episode_id: "E1", path: "runs/E1", status: "completed", created_at: null, summary_available: true }] }, message: "ok" });
    }
    if (url.includes("/desktop/environment")) {
      return jsonRes({ code: 0, data: { project_root: "/repo", python_path: "/repo/.venv/bin/python", python_version: "CPython 3.13", run_roots: ["/repo/runs"], backend_port: 8765 }, message: "ok" });
    }
    return jsonRes({});
  }) as unknown as typeof fetch;
});

describe("DataExportPage", () => {
  it("lists run files for current episode", async () => {
    render(
      <MemoryRouter>
        <WorkbenchShell>
          <DataExportPage />
        </WorkbenchShell>
      </MemoryRouter>,
    );

    fireEvent.click(screen.getByRole("button", { name: "刷新文件清单" }));

    await waitFor(() => expect(screen.getByText("visual/frames.jsonl")).toBeTruthy());
  });
});

describe("SettingsPage", () => {
  it("loads backend environment", async () => {
    render(
      <MemoryRouter>
        <WorkbenchShell>
          <SettingsPage />
        </WorkbenchShell>
      </MemoryRouter>,
    );

    fireEvent.click(screen.getByRole("button", { name: "刷新环境" }));

    await waitFor(() => expect(screen.getByText("/repo")).toBeTruthy());
    expect(screen.getByText("8765")).toBeTruthy();
  });
});
```

- [ ] **Step 2: Run export/settings tests and verify they fail**

Run:

```bash
cd frontend && npm test -- tests/workbench/export-settings.test.tsx
```

Expected result:

```text
Unable to find role="button" and name "刷新文件清单"
```

- [ ] **Step 3: Implement DataExportPage**

Replace `frontend/src/components/workbench/DataExportPage.tsx` with:

```tsx
import { useState } from "react";
import { downloadEpisode, listDesktopRunFiles, listDesktopRuns } from "@/api/rest";
import { useWorkbenchStore } from "@/state/workbench";
import type { DesktopRunFile, DesktopRunItem } from "@/types/api";

export function DataExportPage() {
  const episode = useWorkbenchStore((s) => s.currentEpisode);
  const [runs, setRuns] = useState<DesktopRunItem[]>([]);
  const [files, setFiles] = useState<DesktopRunFile[]>([]);
  const [message, setMessage] = useState<string | null>(null);

  async function refreshRuns() {
    const result = await listDesktopRuns();
    setRuns(result.items);
  }

  async function refreshFiles() {
    if (!episode) {
      setMessage("请先启动或选择 episode");
      return;
    }
    const result = await listDesktopRunFiles(episode.episode_id);
    setFiles(result.files);
  }

  async function download() {
    if (!episode) {
      setMessage("请先启动或选择 episode");
      return;
    }
    await downloadEpisode(episode.episode_id);
    setMessage("下载请求已完成");
  }

  async function openRunDir() {
    const target = episode?.run_dir;
    if (!target) {
      setMessage("当前 episode 没有 run_dir");
      return;
    }
    if (!window.multiCraneDesktop) {
      setMessage("当前浏览器环境不支持打开目录");
      return;
    }
    const result = await window.multiCraneDesktop.openPath(target);
    setMessage(result.ok ? "已请求打开 run 目录" : result.error ?? "打开目录失败");
  }

  return (
    <section className="page-section">
      <div className="page-header-row">
        <div>
          <h1>数据/导出</h1>
          <p className="muted">查看 Module L/M 产物，并保留 K/O/P 研究链路入口。</p>
        </div>
        <div className="button-row">
          <button type="button" onClick={refreshRuns}>刷新运行列表</button>
          <button type="button" onClick={refreshFiles}>刷新文件清单</button>
          <button type="button" onClick={download}>下载 zip</button>
          <button type="button" onClick={openRunDir}>打开 run 目录</button>
        </div>
      </div>
      {message && <div className="chip">{message}</div>}
      <div className="panel">
        <h3>运行列表</h3>
        <div className="panel-body">
          <table className="grid">
            <tbody>
              {runs.map((run) => (
                <tr key={run.episode_id}>
                  <td>{run.episode_id}</td>
                  <td>{run.status ?? "-"}</td>
                  <td>{run.path}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
      <div className="panel">
        <h3>文件清单</h3>
        <div className="panel-body">
          <table className="grid">
            <tbody>
              {files.map((file) => (
                <tr key={file.relative_path}>
                  <td>{file.relative_path}</td>
                  <td>{file.kind}</td>
                  <td>{file.size_bytes}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
      <div className="panel">
        <h3>研究链路入口</h3>
        <div className="panel-body module-grid">
          <div className="module-card"><strong>K 离线风险标签</strong><span className="muted">Phase 3 接入</span></div>
          <div className="module-card"><strong>O 数据集构建</strong><span className="muted">Phase 3 接入</span></div>
          <div className="module-card"><strong>P 训练样本转换</strong><span className="muted">Phase 3 接入</span></div>
        </div>
      </div>
    </section>
  );
}
```

- [ ] **Step 4: Implement SettingsPage**

Replace `frontend/src/components/workbench/SettingsPage.tsx` with:

```tsx
import { useState } from "react";
import { getDesktopEnvironment } from "@/api/rest";
import { getRuntimeConfig } from "@/runtime";
import type { DesktopEnvironmentResponse } from "@/types/api";

export function SettingsPage() {
  const [environment, setEnvironment] = useState<DesktopEnvironmentResponse | null>(null);
  const runtime = getRuntimeConfig();

  async function refresh() {
    setEnvironment(await getDesktopEnvironment());
  }

  return (
    <section className="page-section">
      <div className="page-header-row">
        <div>
          <h1>设置</h1>
          <p className="muted">后端、Python 环境、输出目录和模型供应商默认值。</p>
        </div>
        <button type="button" onClick={refresh}>刷新环境</button>
      </div>
      <div className="panel">
        <h3>桌面运行时</h3>
        <div className="panel-body summary-grid">
          <div><span className="muted">模式</span><strong>{runtime.mode}</strong></div>
          <div><span className="muted">端口</span><strong>{runtime.backendPort ?? environment?.backend_port ?? "-"}</strong></div>
          <div><span className="muted">API</span><strong>{runtime.apiBase ?? "/api"}</strong></div>
        </div>
      </div>
      <div className="panel">
        <h3>后端环境</h3>
        <div className="panel-body summary-grid">
          <div><span className="muted">项目</span><strong>{environment?.project_root ?? "-"}</strong></div>
          <div><span className="muted">Python</span><strong>{environment?.python_path ?? "-"}</strong></div>
          <div><span className="muted">版本</span><strong>{environment?.python_version ?? "-"}</strong></div>
        </div>
      </div>
      <div className="panel">
        <h3>LLM 供应商</h3>
        <div className="panel-body module-grid">
          <div className="module-card"><strong>DeepSeek</strong><span className="muted">使用 DEEPSEEK_API_KEY</span></div>
          <div className="module-card"><strong>OpenAI-compatible</strong><span className="muted">自定义 base_url + model</span></div>
          <div className="module-card"><strong>禁用 LLM</strong><span className="muted">规则或 fallback baseline</span></div>
        </div>
      </div>
    </section>
  );
}
```

- [ ] **Step 5: Run export/settings tests**

Run:

```bash
cd frontend && npm test -- tests/workbench/export-settings.test.tsx
```

Expected result:

```text
PASS
```

- [ ] **Step 6: Commit export/settings pages**

```bash
git add frontend/src/components/workbench/DataExportPage.tsx frontend/src/components/workbench/SettingsPage.tsx frontend/tests/workbench/export-settings.test.tsx
git commit -m "feat(frontend): add desktop export and settings pages"
```

## Task 10: Developer Documentation And Verification

**Files:**
- Create: `docs/desktop_workbench_phase1.md`
- Modify: `.gitignore`

- [ ] **Step 1: Add `.desktop/` to gitignore**

Modify root `.gitignore` and add:

```gitignore
.desktop/
```

Do not add `.claude/` unless the user asks. It is untracked at plan time and outside this feature.

- [ ] **Step 2: Write developer documentation**

Create `docs/desktop_workbench_phase1.md`:

```markdown
# Desktop Workbench Phase 1

## Scope

Phase 1 provides a development desktop workbench for a single experiment loop:

1. Electron starts the FastAPI backend.
2. React opens as a tabbed workbench.
3. A user loads a template, edits core fields and YAML, validates the config, starts one episode, watches 3D, and downloads run artifacts.

Phase 1 does not package a final Windows or macOS release build. It expects the local Python virtual environment and frontend dependencies to exist.

## Development Startup

From the repository root:

```bash
cd frontend
npm run dev
```

In another terminal:

```bash
cd frontend
npm run desktop:dev
```

The Electron app starts FastAPI from the repository `.venv` and loads the Vite dev server.

## Backend Verification

```bash
.venv/bin/python -m pytest backend/app/tests/test_desktop_service.py backend/app/tests/test_desktop_routes.py -v
```

## Frontend Verification

```bash
cd frontend
npm run typecheck
npm test -- runtime.test.ts rest.test.ts ws.test.ts tests/workbench
```

## Full Existing Regression

```bash
.venv/bin/python -m pytest
cd frontend
npm run typecheck
npm test
```

## Secret Rule

Raw API keys must not be written to draft YAML, git files, run summaries, logs, or downloaded archives. Use `api_key_env` such as `DEEPSEEK_API_KEY`.
```

- [ ] **Step 3: Run backend desktop tests**

Run:

```bash
.venv/bin/python -m pytest backend/app/tests/test_desktop_service.py backend/app/tests/test_desktop_routes.py -v
```

Expected result:

```text
passed
```

- [ ] **Step 4: Run full backend tests**

Run:

```bash
.venv/bin/python -m pytest
```

Expected result:

```text
passed
```

- [ ] **Step 5: Run frontend typecheck and tests**

Run:

```bash
cd frontend && npm run typecheck && npm test
```

Expected result:

```text
passed
```

- [ ] **Step 6: Run build smoke checks**

Run:

```bash
cd frontend && npm run build
```

Expected result:

```text
vite build
```

Then manually smoke check development desktop launch:

```bash
cd frontend
npm run dev
```

In another terminal:

```bash
cd frontend
npm run desktop:dev
```

Expected behavior:

- Electron window opens.
- Settings page can refresh environment.
- Backend health appears in the UI.
- Configuration page can load a template.
- Run page can start a local episode when a valid YAML config is present.

- [ ] **Step 7: Commit docs and verification updates**

```bash
git add .gitignore docs/desktop_workbench_phase1.md
git commit -m "docs(desktop): document phase one workbench"
```

## Final Verification Before Completion

Run these from repository root after all tasks are complete:

```bash
git status --short
.venv/bin/python -m pytest
cd frontend && npm run typecheck && npm test && npm run build
```

Expected:

- Git status shows only expected untracked user-owned files, such as `.claude/`, if still present.
- Backend pytest passes.
- Frontend typecheck passes.
- Frontend Vitest passes.
- Frontend build passes.

Do not claim completion until these commands have run and their outputs are checked.
