from __future__ import annotations

from typing import Any, Dict, Iterable, Optional, Set

from pydantic import ValidationError

from backend.app.schemas.crane import (
    CraneModelLibrary,
    CraneModelSpec,
    crane_model_spec_from_config,
)
from backend.app.schemas.errors import ConfigError


BUILTIN_CRANE_MODELS: Dict[str, Dict[str, Any]] = {
    "generic_flat_top_55m": {
        "model_id": "generic_flat_top_55m",
        "jib_length_m": 55.0,
        "counter_jib_length_m": 15.0,
        "mast_height_range_m": [40.0, 65.0],
        "max_load_t": 6.0,
        "max_load_radius_m": 15.0,
        "tip_load_t": 1.5,
        "rated_moment_t_m": 90.0,
        "slew_speed_max_deg_s": 0.8,
        "slew_acc_max_deg_s2": 0.3,
        "trolley_r_min_m": 5.0,
        "trolley_r_max_m": 50.0,
        "trolley_speed_max_m_s": 0.5,
        "trolley_acc_max_m_s2": 0.4,
        "cable_length_min_m": 2.0,
        "cable_length_max_m": 60.0,
        "hoist_speed_max_m_s": 0.6,
        "hoist_acc_max_m_s2": 0.5,
        "min_clearance_below_jib_m": 2.0,
    }
}


class CraneModelLibraryError(ValueError):
    def __init__(
        self,
        message: str,
        *,
        model_id: Optional[str],
        reason: str,
        field_path: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.model_id = model_id
        self.reason = reason
        self.field_path = field_path
        self.details = details or {}


def build_crane_model_library(
    yaml_models: Iterable[object],
) -> CraneModelLibrary:
    library: CraneModelLibrary = {}
    for model_id, payload in BUILTIN_CRANE_MODELS.items():
        library[model_id] = _build_spec(payload, source="builtin", index=None)

    seen_yaml_ids: Set[str] = set()
    for index, payload in enumerate(yaml_models):
        model_id = _model_id_from_payload(payload)
        if model_id in seen_yaml_ids:
            raise CraneModelLibraryError(
                f"duplicate crane model_id: {model_id}",
                model_id=model_id,
                reason="duplicate_model_id",
                field_path=f"crane_models[{index}].model_id",
            )
        seen_yaml_ids.add(model_id)
        source = "yaml_override" if model_id in BUILTIN_CRANE_MODELS else "yaml_new"
        library[model_id] = _build_spec(payload, source=source, index=index)
    return library


def crane_model_error_to_config_error(
    error: CraneModelLibraryError,
    *,
    source_file: Optional[str] = None,
) -> ConfigError:
    details = dict(error.details)
    details["reason"] = error.reason
    details["model_id"] = error.model_id
    return ConfigError(
        error_code="LAY_E_003",
        message=str(error),
        field_path=error.field_path,
        source_file=source_file,
        hint="Fix crane_models before startup.",
        details=details,
    )


def _build_spec(payload: object, *, source: str, index: Optional[int]) -> CraneModelSpec:
    model_id = _model_id_from_payload(payload)
    try:
        return crane_model_spec_from_config(payload, source=source)  # type: ignore[arg-type]
    except (KeyError, TypeError, ValidationError, ValueError) as exc:
        reason = _reason_from_exception(exc)
        raise CraneModelLibraryError(
            f"invalid crane model '{model_id}': {reason}",
            model_id=model_id,
            reason=reason,
            field_path=_field_path_for_reason(reason, index),
            details={"constraint": reason},
        ) from exc


def _model_id_from_payload(payload: object) -> str:
    if hasattr(payload, "model_id"):
        return str(getattr(payload, "model_id"))
    if isinstance(payload, dict):
        return str(payload.get("model_id"))
    return ""


def _reason_from_exception(exc: Exception) -> str:
    text = str(exc)
    if "max_load_radius_m must be <= jib_length_m" in text:
        return "max_load_radius_exceeds_jib_length"
    if "trolley_r_max_m must be <= jib_length_m" in text:
        return "trolley_r_max_exceeds_jib_length"
    if "tip_load_t must be <= max_load_t" in text:
        return "tip_load_exceeds_max_load"
    if "mast_height_range_m" in text:
        return "invalid_mast_height_range"
    if "load_chart_points" in text:
        return "invalid_load_chart_points"
    return "invalid_crane_model"


def _field_path_for_reason(reason: str, index: Optional[int]) -> Optional[str]:
    if index is None:
        return None
    field_by_reason = {
        "max_load_radius_exceeds_jib_length": "max_load_radius_m",
        "trolley_r_max_exceeds_jib_length": "trolley_r_max_m",
        "tip_load_exceeds_max_load": "tip_load_t",
        "invalid_mast_height_range": "mast_height_range_m",
        "invalid_load_chart_points": "load_chart_points",
    }
    field = field_by_reason.get(reason)
    if field is None:
        return f"crane_models[{index}]"
    return f"crane_models[{index}].{field}"
