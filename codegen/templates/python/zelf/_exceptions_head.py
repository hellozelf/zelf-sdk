from __future__ import annotations

from typing import Any, Literal

import httpx


class ZelfError(Exception):
    pass


class ZelfConnectionError(ZelfError):
    def __init__(self, message: str = "Could not reach the ZelfAI API.") -> None:
        super().__init__(message)


class ZelfTimeoutError(ZelfConnectionError):
    def __init__(self, message: str = "Request to the ZelfAI API timed out.") -> None:
        super().__init__(message)


class ResponseParseError(ZelfError):
    """A row in a 2xx response did not match the model the SDK expects.

    The call reached the API and the API answered, so this is not an APIError.
    The field that failed and the response's log_id are carried so the call can
    be reported, and the pydantic error stays on `__cause__`.
    """

    def __init__(
        self,
        message: str,
        *,
        field: str | None = None,
        log_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.field = field
        self.log_id = log_id

    def __str__(self) -> str:
        parts = [self.message]
        if self.field:
            parts.append(f"(field={self.field})")
        if self.log_id:
            parts.append(f"(log_id={self.log_id})")
        return " ".join(parts)


class ZelfAPIError(ZelfError):
    status_code: int = 0

    def __init__(
        self,
        message: str,
        *,
        status_code: int,
        code: str | None = None,
        details: dict[str, Any] | None = None,
        log_id: str | None = None,
        response: httpx.Response | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.code = code
        self.details = details or {}
        self.log_id = log_id
        self.response = response

    def __str__(self) -> str:
        parts = [f"{self.status_code}"]
        if self.code:
            parts.append(self.code)
        parts.append(self.message)
        if self.log_id:
            parts.append(f"(log_id={self.log_id})")
        return " ".join(parts)


def parse(response: httpx.Response) -> ZelfAPIError:
    code = message = log_id = None
    details: dict[str, Any] = {}
    try:
        body = response.json()
    except ValueError:
        body = None
    if isinstance(body, dict):
        log_id = body.get("log_id")
        error = body.get("error")
        if isinstance(error, dict):
            code = error.get("code")
            message = error.get("message")
            details = error.get("details") or {}
    cls = STATUS_MAP.get(response.status_code, ZelfAPIError)
    return cls(
        message or f"HTTP {response.status_code} from the ZelfAI API.",
        status_code=response.status_code,
        code=code,
        details=details,
        log_id=log_id,
        response=response,
    )
