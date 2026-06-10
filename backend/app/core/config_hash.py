from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any


class ConfigHashError(ValueError):
    pass


_HASH_EXCLUDED_KEYS = {
    "resolved_config_hash",
    "created_at",
    "run_root",
    "run_path",
    "workspace_path",
    "log_path",
    "logs_path",
    "output_dir",
    "key_masked",
    "api_key",
    "full_api_key",
    "resolved_full_api_key",
    "raw_api_key",
    "secret",
    "token",
    "authorization",
}


def compute_resolved_config_hash(payload: Any) -> str:
    try:
        sanitized = _sanitize_for_hash(payload)
        encoded = json.dumps(
            sanitized,
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ConfigHashError("resolved_config_hash is not computable") from exc
    return hashlib.sha256(encoded).hexdigest()


def _sanitize_for_hash(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    value = deepcopy(value)
    if isinstance(value, dict):
        return {
            key: _sanitize_for_hash(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
            if key not in _HASH_EXCLUDED_KEYS
        }
    if isinstance(value, list):
        return [_sanitize_for_hash(item) for item in value]
    if isinstance(value, tuple):
        return [_sanitize_for_hash(item) for item in value]
    json.dumps(value)
    return value
