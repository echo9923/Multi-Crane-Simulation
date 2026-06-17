from __future__ import annotations

from typing import Iterable, List, Optional

from pydantic import ValidationError

from backend.app.core.config_hash import ConfigHashError
from backend.app.core.config_loader import ConfigLoadError
from backend.app.core.path_utils import PathSecurityError
from backend.app.core.secret_resolver import SecretGovernanceError
from backend.app.schemas.errors import ConfigError, StartupFailureResult
from backend.app.sim.auto_layout import AutoLayoutError, auto_layout_error_to_config_error
from backend.app.sim.layout import LayoutResolutionError, layout_error_to_config_error


CONFIG_KIND_ERROR_CODES = {
    "scenario": "CFG_E_001",
    "experiment": "CFG_E_002",
    "dataset": "CFG_E_DATASET",
}


def pydantic_errors_to_config_errors(
    validation_error: ValidationError,
    *,
    config_kind: str,
    source_file: Optional[str],
    forbidden_secret_values: Optional[Iterable[str]] = None,
) -> List[ConfigError]:
    errors = []
    for raw_error in validation_error.errors():
        field_path = _format_field_path(raw_error.get("loc", ()))
        message = _scrub_secrets(raw_error.get("msg", "配置校验失败"), forbidden_secret_values)
        errors.append(
            ConfigError(
                error_code=_error_code_for_kind(config_kind),
                message=message,
                field_path=field_path,
                source_file=source_file,
                hint=_hint_for_kind(config_kind, field_path),
                details=_scrub_details(
                    {
                        "config_kind": config_kind,
                        "pydantic_error": raw_error,
                    },
                    forbidden_secret_values,
                ),
            )
        )
    return errors


def config_error_from_exception(
    exc: Exception,
    *,
    config_kind: str,
    source_file: Optional[str],
    field_path: Optional[str] = None,
    forbidden_secret_values: Optional[Iterable[str]] = None,
) -> ConfigError:
    if isinstance(exc, ConfigHashError):
        return ConfigError(
            error_code="CFG_E_003",
            message=_scrub_secrets(str(exc), forbidden_secret_values),
            field_path="resolved_config_hash",
            source_file=source_file,
            hint="Ensure resolved config contains only deterministic serializable fields.",
            details={"config_kind": config_kind},
        )

    if isinstance(exc, SecretGovernanceError):
        return ConfigError(
            error_code=_error_code_for_kind(config_kind),
            message=_scrub_secrets(str(exc), forbidden_secret_values),
            field_path=field_path or "llm.api_key",
            source_file=source_file,
            hint=exc.hint or "Use api_key_env or provide a startup-only runtime secret.",
            details=_scrub_details(
                {
                    "config_kind": config_kind,
                    "provider": exc.provider,
                    "key_source": exc.key_source,
                    "missing_env": exc.missing_env,
                },
                forbidden_secret_values,
            ),
        )

    if isinstance(exc, ConfigLoadError):
        return ConfigError(
            error_code=_error_code_for_kind(config_kind),
            message=_scrub_secrets(str(exc), forbidden_secret_values),
            field_path=field_path or exc.field_path,
            source_file=source_file or exc.source_file,
            hint=exc.hint or "Fix the configuration file before startup.",
            details={"config_kind": exc.config_kind or config_kind},
        )

    if isinstance(exc, PathSecurityError):
        return ConfigError(
            error_code=_error_code_for_kind(config_kind),
            message=_scrub_secrets(str(exc), forbidden_secret_values),
            field_path=field_path,
            source_file=source_file,
            hint="Keep configuration paths under the allowed config root or run workspace.",
            details={"config_kind": config_kind, "path": exc.path, "root": exc.root},
        )

    if isinstance(exc, AutoLayoutError):
        return auto_layout_error_to_config_error(exc, source_file=source_file)

    if isinstance(exc, LayoutResolutionError):
        return layout_error_to_config_error(exc, source_file=source_file)

    return ConfigError(
        error_code=_error_code_for_kind(config_kind),
        message=_scrub_secrets(str(exc), forbidden_secret_values),
        field_path=field_path,
        source_file=source_file,
        hint="Fix the configuration error before startup.",
        details={"config_kind": config_kind},
    )


def _error_code_for_kind(config_kind: str) -> str:
    return CONFIG_KIND_ERROR_CODES.get(config_kind, "CFG_E_001")


def _format_field_path(loc: object) -> str:
    if not loc:
        return ""
    if isinstance(loc, str):
        return loc
    parts = []
    for item in loc:
        if isinstance(item, int):
            if not parts:
                parts.append(f"[{item}]")
            else:
                parts[-1] = f"{parts[-1]}[{item}]"
        else:
            parts.append(str(item))
    return ".".join(parts)


def _hint_for_kind(config_kind: str, field_path: str) -> str:
    if config_kind == "scenario":
        return f"Check scenario.yaml field '{field_path}' against ScenarioConfig."
    if config_kind == "experiment":
        return f"Check experiment.yaml field '{field_path}' against ExperimentConfig."
    if config_kind == "dataset":
        return f"Check dataset.yaml field '{field_path}' against DatasetConfig."
    return "Check the resolved configuration before startup."


def _scrub_details(value: object, forbidden_secret_values: Optional[Iterable[str]]):
    if isinstance(value, dict):
        return {
            key: _scrub_details(item, forbidden_secret_values)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_scrub_details(item, forbidden_secret_values) for item in value]
    if isinstance(value, tuple):
        return tuple(_scrub_details(item, forbidden_secret_values) for item in value)
    if isinstance(value, str):
        return _scrub_secrets(value, forbidden_secret_values)
    return value


def _scrub_secrets(
    value: str, forbidden_secret_values: Optional[Iterable[str]]
) -> str:
    scrubbed = value
    for secret in forbidden_secret_values or []:
        if secret:
            scrubbed = scrubbed.replace(secret, "[REDACTED]")
    return scrubbed


__all__ = [
    "ConfigError",
    "StartupFailureResult",
    "config_error_from_exception",
    "pydantic_errors_to_config_errors",
]
