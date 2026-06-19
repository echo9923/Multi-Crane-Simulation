from __future__ import annotations

from typing import Any, Iterable, Optional

from fastapi import HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from backend.app.core.config_errors import config_error_from_exception
from backend.app.schemas.errors import ConfigError

from .schemas import ApiErrorResponse, M_E_CONFIG_INVALID, M_E_INTERNAL


class ApiException(HTTPException):
    def __init__(
        self,
        *,
        status_code: int,
        code: str,
        message: str,
        details: Optional[dict[str, Any]] = None,
    ) -> None:
        self.code = code
        self.message = message
        self.details = dict(details or {})
        super().__init__(
            status_code=status_code,
            detail={
                "code": code,
                "message": message,
                "details": self.details,
            },
        )


class ConfigValidationApiError(ApiException):
    def __init__(
        self,
        message: str,
        *,
        details: Optional[dict[str, Any]] = None,
        status_code: int = 422,
    ) -> None:
        super().__init__(
            status_code=status_code,
            code=M_E_CONFIG_INVALID,
            message=message,
            details=details,
        )


def register_exception_handlers(app: Any) -> None:
    @app.exception_handler(ApiException)
    async def api_exception_handler(
        request: Request, exc: ApiException
    ) -> JSONResponse:
        return _error_response(
            status_code=exc.status_code,
            code=exc.code,
            message=exc.message,
            details=exc.details,
        )

    @app.exception_handler(RequestValidationError)
    async def request_validation_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return _error_response(
            status_code=422,
            code=M_E_CONFIG_INVALID,
            message="request validation failed",
            details={"errors": exc.errors()},
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(
        request: Request, exc: Exception
    ) -> JSONResponse:
        return _error_response(
            status_code=500,
            code=M_E_INTERNAL,
            message="internal server error",
            details={"exception_type": type(exc).__name__},
        )


def config_api_error_from_exception(
    exc: Exception,
    *,
    config_kind: str,
    source_file: Optional[str] = None,
    field_path: Optional[str] = None,
    forbidden_secret_values: Optional[Iterable[str]] = None,
) -> ConfigValidationApiError:
    if isinstance(exc, ValidationError):
        raw_errors = _scrub_error_details(exc.errors(), forbidden_secret_values)
        first = raw_errors[0] if raw_errors else {}
        loc = first.get("loc", ())
        field = ".".join(str(part) for part in loc) if loc else field_path
        message = _scrub_error_text(
            str(first.get("msg") or "configuration validation failed"),
            forbidden_secret_values,
        )
        details = {
            "config_kind": config_kind,
            "field_path": field,
            "source_file": source_file,
            "errors": raw_errors,
        }
        return ConfigValidationApiError(message, details=details)

    config_error = config_error_from_exception(
        exc,
        config_kind=config_kind,
        source_file=source_file,
        field_path=field_path,
        forbidden_secret_values=forbidden_secret_values,
    )
    return config_api_error_from_config_error(config_error)


def _scrub_error_details(
    value: Any,
    forbidden_secret_values: Optional[Iterable[str]],
) -> Any:
    if isinstance(value, dict):
        return {
            key: _scrub_error_details(item, forbidden_secret_values)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_scrub_error_details(item, forbidden_secret_values) for item in value]
    if isinstance(value, tuple):
        return tuple(
            _scrub_error_details(item, forbidden_secret_values)
            for item in value
        )
    if isinstance(value, str):
        return _scrub_error_text(value, forbidden_secret_values)
    return value


def _scrub_error_text(
    value: str,
    forbidden_secret_values: Optional[Iterable[str]],
) -> str:
    scrubbed = value
    for secret in forbidden_secret_values or []:
        if secret:
            scrubbed = scrubbed.replace(secret, "[REDACTED]")
    return scrubbed


def config_api_error_from_config_error(
    error: ConfigError,
) -> ConfigValidationApiError:
    details = {
        "config_kind": error.details.get("config_kind"),
        "field_path": error.field_path,
        "source_file": error.source_file,
        "hint": error.hint,
        "config_error_code": error.error_code,
    }
    details.update(error.details)
    return ConfigValidationApiError(error.message, details=details)


def _error_response(
    *,
    status_code: int,
    code: str,
    message: str,
    details: Optional[dict[str, Any]] = None,
) -> JSONResponse:
    payload = ApiErrorResponse(
        code=code,
        message=message,
        details=dict(details or {}),
    )
    return JSONResponse(
        status_code=status_code,
        content=payload.model_dump(mode="json"),
    )


__all__ = [
    "ApiException",
    "ConfigValidationApiError",
    "config_api_error_from_config_error",
    "config_api_error_from_exception",
    "register_exception_handlers",
]
