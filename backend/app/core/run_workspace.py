from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from importlib import metadata as importlib_metadata
from pathlib import Path
from typing import Iterable, List, Optional, Union

import yaml

from backend.app.core.path_utils import PathLike, PathSecurityError, normalize_path_under_root
from backend.app.schemas.resolved_config import ResolvedConfig
from backend.app.schemas.run_metadata import RunMetadata


class RunWorkspaceError(RuntimeError):
    pass


@dataclass(frozen=True)
class RunWorkspace:
    path: Path
    run_id: str
    created_files: List[Path]


def create_run_workspace(
    resolved_config: ResolvedConfig,
    *,
    run_root: Optional[PathLike] = None,
    allowed_root: Optional[PathLike] = None,
    run_id: Optional[str] = None,
    forbidden_secret_values: Optional[Iterable[str]] = None,
) -> RunWorkspace:
    root = _resolve_run_root(
        run_root or resolved_config.output.run_root,
        allowed_root=allowed_root,
    )
    experiment_id = resolved_config.experiment["experiment_id"]
    scenario_id = resolved_config.scenario["scenario_id"]
    final_run_id = run_id or _generate_run_id(resolved_config.resolved_config_hash)
    workspace_path, final_run_id = _unique_workspace_path(root, experiment_id, final_run_id)

    try:
        for relative_dir in ["config", "metadata", "logs", "data", "visual", "replay"]:
            (workspace_path / relative_dir).mkdir(parents=True, exist_ok=False)
    except OSError as exc:
        raise RunWorkspaceError(f"failed to create run workspace: {workspace_path}") from exc

    resolved_payload = resolved_config.model_dump(mode="json")
    metadata = _build_run_metadata(
        resolved_config,
        experiment_id=experiment_id,
        scenario_id=scenario_id,
        run_id=final_run_id,
    )
    metadata_payload = metadata.model_dump(mode="json")

    _assert_no_secret_values(
        [resolved_payload, metadata_payload],
        forbidden_secret_values=forbidden_secret_values,
    )

    resolved_path = workspace_path / "config" / "resolved_config.yaml"
    metadata_path = workspace_path / "metadata" / "run_metadata.json"
    try:
        resolved_path.write_text(
            yaml.safe_dump(resolved_payload, sort_keys=True, allow_unicode=True),
            encoding="utf-8",
        )
        metadata_path.write_text(
            json.dumps(metadata_payload, ensure_ascii=False, sort_keys=True, indent=2),
            encoding="utf-8",
        )
    except OSError as exc:
        raise RunWorkspaceError(f"failed to write run workspace files: {workspace_path}") from exc

    return RunWorkspace(
        path=workspace_path,
        run_id=final_run_id,
        created_files=[resolved_path, metadata_path],
    )


def _resolve_run_root(path: PathLike, *, allowed_root: Optional[PathLike]) -> Path:
    if allowed_root is None:
        return Path(path).expanduser().resolve()
    try:
        return normalize_path_under_root(path, root=allowed_root)
    except PathSecurityError as exc:
        raise RunWorkspaceError(str(exc)) from exc


def _unique_workspace_path(root: Path, experiment_id: str, run_id: str) -> tuple[Path, str]:
    base = root / experiment_id
    candidate_run_id = run_id
    candidate = base / candidate_run_id
    index = 1
    while candidate.exists():
        candidate_run_id = f"{run_id}_{index:02d}"
        candidate = base / candidate_run_id
        index += 1
    return candidate, candidate_run_id


def _generate_run_id(resolved_config_hash: str) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"run_{timestamp}_{resolved_config_hash[:8]}"


def _build_run_metadata(
    resolved_config: ResolvedConfig,
    *,
    experiment_id: str,
    scenario_id: str,
    run_id: str,
) -> RunMetadata:
    return RunMetadata(
        schema_version=resolved_config.schema_version,
        experiment_id=experiment_id,
        scenario_id=scenario_id,
        run_id=run_id,
        created_at=datetime.now(timezone.utc).isoformat(),
        git_commit=_git_commit(),
        git_dirty=_git_dirty(),
        python_version=sys.version,
        package_summary=_package_summary(),
        resolved_config_hash=resolved_config.resolved_config_hash,
        provider=resolved_config.provider.provider,
        model=resolved_config.provider.model,
        temperature=resolved_config.provider.temperature,
        key_source=resolved_config.provider.key_source,
        key_masked=resolved_config.provider.key_masked,
    )


def _git_commit() -> Optional[str]:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            text=True,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip() or None


def _git_dirty() -> Optional[bool]:
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            check=True,
            text=True,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return bool(result.stdout.strip())


def _package_summary() -> dict:
    packages = {}
    for name in ["pydantic", "PyYAML", "pytest"]:
        try:
            packages[name] = importlib_metadata.version(name)
        except importlib_metadata.PackageNotFoundError:
            packages[name] = None
    return {"packages": packages}


def _assert_no_secret_values(
    payloads: Iterable[object],
    *,
    forbidden_secret_values: Optional[Iterable[str]],
) -> None:
    forbidden = [secret for secret in (forbidden_secret_values or []) if secret]
    if not forbidden:
        return
    serialized = "\n".join(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
        for payload in payloads
    )
    for secret in forbidden:
        if secret in serialized:
            raise RunWorkspaceError("refusing to persist content containing a full secret")
