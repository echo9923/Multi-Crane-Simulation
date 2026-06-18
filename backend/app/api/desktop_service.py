from __future__ import annotations

import copy
import json
import platform
import re
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from backend.app.api.schemas import (
    DesktopEnvironmentResponse,
    DesktopExperimentDraftResponse,
    DesktopRecentExperiment,
    DesktopRunFile,
    DesktopRunItem,
    DesktopTemplate,
)

DEFAULT_TEMPLATE_DIRS = ("configs",)
DEFAULT_DRAFT_ROOT = ".desktop/experiments"
EXPERIMENT_DRAFT_METADATA_FILENAME = "draft.meta.json"
DEFAULT_RUN_ROOTS = ("runs",)
KNOWN_ARTIFACT_DIRS = frozenset({"config", "metadata", "logs", "data", "visual", "replay"})
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_SECRET_KEY_RE = re.compile(
    r"(^|[_-])(api[_-]?key|apikey|token|secret|authorization|password)([_-]|$)",
    re.IGNORECASE,
)
_VISIBLE_SECRET_REF_KEYS = frozenset({"api_key_env"})


@dataclass(frozen=True)
class DesktopExperimentDraft:
    experiment_id: str
    yaml_text: str
    metadata: dict[str, Any]
    updated_at: str | None = None


def list_desktop_templates(
    project_root: Path | str,
    template_dirs: list[Path | str] | None = None,
) -> list[DesktopTemplate]:
    """Read available YAML templates from configured template directories."""
    templates: list[DesktopTemplate] = []
    for directory in _template_dirs(project_root, template_dirs):
        if not directory.is_dir():
            continue
        for path in sorted(_yaml_files(directory)):
            data = _read_yaml_mapping(path)
            scenario = _mapping_at(data, "scenario")
            experiment = _mapping_at(data, "experiment")
            templates.append(
                DesktopTemplate(
                    template_id=path.stem,
                    name=path.stem.replace("_", " "),
                    path=str(path),
                    scenario_id=_string_or_none(scenario.get("scenario_id")),
                    experiment_id=_string_or_none(experiment.get("experiment_id")),
                    description=_template_description(data),
                )
            )
    return sorted(templates, key=lambda item: item.template_id)


def render_template_yaml(
    project_root: Path | str,
    template_id: str,
    core_overrides: Mapping[str, Any],
    template_dirs: list[Path | str] | None = None,
) -> str:
    """Render a template by id after applying dotted-path overrides."""
    path = _find_template_path(project_root, template_id, template_dirs)
    data = _read_yaml_mapping(path)
    patched = _apply_dotted_patches(data, core_overrides)
    return _dump_yaml(scrub_secret_values(patched))


def apply_config_patch(yaml_text: str, patches: Mapping[str, Any]) -> str:
    """Patch an existing YAML object while preserving fields outside the patch."""
    data = yaml.safe_load(yaml_text) if yaml_text.strip() else {}
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ValueError("yaml_text must contain a YAML mapping")
    patched = _apply_dotted_patches(data, patches)
    return _dump_yaml(scrub_secret_values(patched))


def save_experiment_draft(
    project_root: Path | str,
    experiment_id: str,
    yaml_text: str,
    metadata: Mapping[str, Any],
    draft_root: Path | str | None = None,
) -> DesktopExperimentDraftResponse:
    """Persist a scrubbed desktop draft and metadata under a safe experiment id."""
    safe_id = _safe_id(experiment_id, field_name="experiment_id")
    root = _draft_root(project_root, draft_root)
    target = (root / safe_id).resolve()
    _ensure_relative_to(target, root.resolve())
    target.mkdir(parents=True, exist_ok=True)

    data = yaml.safe_load(yaml_text) if yaml_text.strip() else {}
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ValueError("yaml_text must contain a YAML mapping")
    scrubbed_yaml = _dump_yaml(scrub_secret_values(data))

    yaml_path = target / "draft.yaml"
    metadata_path = target / EXPERIMENT_DRAFT_METADATA_FILENAME
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    metadata_payload = scrub_secret_values(dict(metadata))
    if not isinstance(metadata_payload, dict):
        metadata_payload = {}
    metadata_payload.update(
        {
            "experiment_id": safe_id,
            "yaml_path": str(yaml_path),
            "metadata_path": str(metadata_path),
            "updated_at": now,
        }
    )

    yaml_path.write_text(scrubbed_yaml, encoding="utf-8")
    metadata_path.write_text(
        json.dumps(metadata_payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return DesktopExperimentDraftResponse(
        experiment_id=safe_id,
        yaml_path=str(yaml_path),
        metadata_path=str(metadata_path),
    )


def list_recent_experiments(
    project_root: Path | str,
    draft_root: Path | str | None = None,
) -> list[DesktopRecentExperiment]:
    """List desktop draft metadata sorted by most recently updated."""
    root = _draft_root(project_root, draft_root)
    if not root.is_dir():
        return []

    items: list[DesktopRecentExperiment] = []
    for path in sorted(root.glob(f"*/{EXPERIMENT_DRAFT_METADATA_FILENAME}")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        experiment_id = _safe_metadata_experiment_id(data.get("experiment_id"), fallback=path.parent.name)
        items.append(
            DesktopRecentExperiment(
                experiment_id=experiment_id,
                yaml_path=str(path.parent / "draft.yaml"),
                metadata_path=str(path),
                template_id=_string_or_none(data.get("template_id")),
                last_validation_hash=_string_or_none(data.get("last_validation_hash")),
                updated_at=_string_or_none(data.get("updated_at")),
            )
        )
    return sorted(items, key=lambda item: item.updated_at or "", reverse=True)


def load_latest_experiment_draft(
    project_root: Path | str,
    draft_root: Path | str | None = None,
) -> DesktopExperimentDraft | None:
    """Load the most recently updated desktop draft, returning scrubbed YAML."""
    recent = list_recent_experiments(project_root=project_root, draft_root=draft_root)
    if not recent:
        return None
    item = recent[0]
    root = _draft_root(project_root, draft_root).resolve()
    yaml_path = Path(item.yaml_path).expanduser().resolve()
    metadata_path = Path(item.metadata_path).expanduser().resolve()
    _ensure_relative_to(yaml_path, root)
    _ensure_relative_to(metadata_path, root)
    if not yaml_path.is_file():
        return None

    data = _read_yaml_mapping(yaml_path)
    metadata = _read_json_mapping(metadata_path)
    scrubbed_yaml = _dump_yaml(scrub_secret_values(data))
    scrubbed_metadata = scrub_secret_values(metadata)
    if not isinstance(scrubbed_metadata, dict):
        scrubbed_metadata = {}
    return DesktopExperimentDraft(
        experiment_id=item.experiment_id,
        yaml_text=scrubbed_yaml,
        metadata=scrubbed_metadata,
        updated_at=item.updated_at,
    )


def list_runs(
    project_root: Path | str,
    run_roots: list[Path | str] | None = None,
) -> list[DesktopRunItem]:
    """Find episode run directories from metadata, including active runs."""
    run_dirs: dict[Path, dict[str, Any]] = {}
    for root in _run_roots(project_root, run_roots):
        if not root.is_dir():
            continue
        for metadata_path in sorted(root.rglob("metadata/episode_metadata.json")):
            run_dir = metadata_path.parent.parent
            run_dirs.setdefault(run_dir, {})["metadata"] = _read_json_mapping(metadata_path)
        for summary_path in sorted(root.rglob("metadata/episode_summary.json")):
            run_dir = summary_path.parent.parent
            run_dirs.setdefault(run_dir, {})["summary"] = _read_json_mapping(summary_path)
    items: list[DesktopRunItem] = []
    for run_dir, payloads in run_dirs.items():
        metadata = payloads.get("metadata") or {}
        summary = payloads.get("summary") or {}
        episode_id = (
            _string_or_none(summary.get("episode_id"))
            or _string_or_none(metadata.get("episode_id"))
            or run_dir.name
        )
        status = (
            _string_or_none(summary.get("status"))
            or _string_or_none(summary.get("episode_status"))
            or _string_or_none(metadata.get("status"))
            or _string_or_none(metadata.get("episode_status"))
        )
        created_at = (
            _string_or_none(summary.get("created_at"))
            or _string_or_none(summary.get("started_at"))
            or _string_or_none(metadata.get("created_at"))
            or _string_or_none(metadata.get("started_at"))
        )
        items.append(
            DesktopRunItem(
                episode_id=episode_id,
                path=str(run_dir),
                status=status,
                created_at=created_at,
                summary_available=bool(summary),
            )
        )
    return sorted(items, key=lambda item: item.path)


def list_run_files(
    run_dir: Path | str,
    *,
    project_root: Path | str | None = None,
    run_roots: list[Path | str] | None = None,
) -> list[DesktopRunFile]:
    """List known desktop artifacts below a run directory."""
    if project_root is None:
        root = Path(run_dir).expanduser().resolve()
    else:
        project = Path(project_root).expanduser().resolve()
        run_path = Path(run_dir).expanduser()
        root = run_path.resolve() if run_path.is_absolute() else (project / run_path).resolve()
        allowed_roots = _run_roots(project, run_roots)
        if not any(_is_relative_to(root, allowed_root) for allowed_root in allowed_roots):
            raise ValueError("run_dir must stay under a configured run root")
    if not root.is_dir():
        return []

    files: list[DesktopRunFile] = []
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        relative = path.relative_to(root)
        if not relative.parts or relative.parts[0] not in KNOWN_ARTIFACT_DIRS:
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
    project_root: Path | str,
    data_root: Path | str | None = None,
    backend_port: int | None = None,
    run_roots: list[Path | str] | None = None,
) -> DesktopEnvironmentResponse:
    """Return local backend environment details for the desktop workbench."""
    root = Path(project_root).expanduser().resolve()
    writable_root = Path(data_root).expanduser().resolve() if data_root is not None else root
    roots = _run_roots(writable_root, run_roots)
    return DesktopEnvironmentResponse(
        project_root=str(root),
        data_root=str(writable_root),
        python_path=sys.executable,
        python_version=f"{platform.python_implementation()} {platform.python_version()}",
        run_roots=[str(path) for path in roots],
        backend_port=backend_port,
    )


def scrub_secret_values(value: Any) -> Any:
    """Recursively mask secret-looking keys while keeping env-var references visible."""
    if isinstance(value, Mapping):
        cleaned: dict[Any, Any] = {}
        for key, item in value.items():
            if isinstance(key, str) and _is_secret_key(key):
                cleaned[key] = "***" if item not in (None, "") else item
            else:
                cleaned[key] = scrub_secret_values(item)
        return cleaned
    if isinstance(value, list):
        return [scrub_secret_values(item) for item in value]
    if isinstance(value, tuple):
        return tuple(scrub_secret_values(item) for item in value)
    return copy.deepcopy(value)


def _template_dirs(
    project_root: Path | str,
    template_dirs: list[Path | str] | None,
) -> list[Path]:
    root = Path(project_root).expanduser().resolve()
    values = template_dirs if template_dirs is not None else list(DEFAULT_TEMPLATE_DIRS)
    return [_resolve_under_project(root, value) for value in values]


def _run_roots(project_root: Path | str, run_roots: list[Path | str] | None) -> list[Path]:
    root = Path(project_root).expanduser().resolve()
    values = run_roots if run_roots is not None else list(DEFAULT_RUN_ROOTS)
    return [_resolve_under_project(root, value) for value in values]


def _draft_root(project_root: Path | str, draft_root: Path | str | None) -> Path:
    root = Path(project_root).expanduser().resolve()
    value = draft_root if draft_root is not None else DEFAULT_DRAFT_ROOT
    return _resolve_under_project(root, value)


def _resolve_under_project(project_root: Path, value: Path | str) -> Path:
    path = Path(value).expanduser()
    resolved = path.resolve() if path.is_absolute() else (project_root / path).resolve()
    _ensure_relative_to(resolved, project_root)
    return resolved


def _ensure_relative_to(path: Path, parent: Path) -> None:
    if not _is_relative_to(path, parent):
        raise ValueError(f"path must stay under {parent}")


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _yaml_files(directory: Path) -> list[Path]:
    files: list[Path] = []
    for pattern in ("*.yaml", "*.yml"):
        files.extend(path for path in directory.glob(pattern) if path.is_file())
    return files


def _read_yaml_mapping(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError(f"YAML file must contain a mapping: {path}")
    return data


def _read_json_mapping(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _mapping_at(data: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = data.get(key)
    return value if isinstance(value, Mapping) else {}


def _template_description(data: Mapping[str, Any]) -> str | None:
    for key in ("description", "name"):
        value = _string_or_none(data.get(key))
        if value:
            return value
    for section_name in ("experiment", "scenario"):
        section = _mapping_at(data, section_name)
        value = _string_or_none(section.get("description"))
        if value:
            return value
    return None


def _find_template_path(
    project_root: Path | str,
    template_id: str,
    template_dirs: list[Path | str] | None,
) -> Path:
    safe_id = _safe_id(template_id, field_name="template_id")
    for directory in _template_dirs(project_root, template_dirs):
        for suffix in (".yaml", ".yml"):
            path = (directory / f"{safe_id}{suffix}").resolve()
            _ensure_relative_to(path, directory.resolve())
            if path.is_file():
                return path
    raise FileNotFoundError(f"template not found: {safe_id}")


def _safe_id(value: str, *, field_name: str) -> str:
    if not _SAFE_ID_RE.fullmatch(value):
        raise ValueError(f"{field_name} contains unsafe characters")
    return value


def _safe_metadata_experiment_id(value: Any, *, fallback: str) -> str:
    if isinstance(value, str) and _SAFE_ID_RE.fullmatch(value):
        return value
    return fallback


def _apply_dotted_patches(data: Mapping[str, Any], patches: Mapping[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(dict(data))
    for dotted_key, value in patches.items():
        if not isinstance(dotted_key, str) or not dotted_key:
            raise ValueError("patch keys must be non-empty dotted strings")
        _set_dotted_value(result, dotted_key, value)
    return result


def _set_dotted_value(data: dict[str, Any], dotted_key: str, value: Any) -> None:
    parts = dotted_key.split(".")
    if any(part == "" for part in parts):
        raise ValueError(f"invalid patch key: {dotted_key}")
    cursor = data
    for part in parts[:-1]:
        next_value = cursor.get(part)
        if not isinstance(next_value, dict):
            next_value = {}
            cursor[part] = next_value
        cursor = next_value
    cursor[parts[-1]] = copy.deepcopy(value)


def _dump_yaml(value: Any) -> str:
    return yaml.safe_dump(value, sort_keys=False, allow_unicode=True)


def _is_secret_key(key: str) -> bool:
    normalized = key.lower()
    if normalized in _VISIBLE_SECRET_REF_KEYS:
        return False
    return bool(_SECRET_KEY_RE.search(normalized))


def _string_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) else None


__all__ = [
    "EXPERIMENT_DRAFT_METADATA_FILENAME",
    "KNOWN_ARTIFACT_DIRS",
    "apply_config_patch",
    "environment_report",
    "list_desktop_templates",
    "list_recent_experiments",
    "list_run_files",
    "list_runs",
    "render_template_yaml",
    "save_experiment_draft",
    "scrub_secret_values",
]
