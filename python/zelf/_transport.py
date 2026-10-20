from __future__ import annotations

import random
import time
from collections.abc import Mapping
from datetime import date, datetime
from typing import Any
from urllib.parse import quote, urljoin

import anyio
import httpx

from . import _exceptions
from ._version import __version__

RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
# The API documents no Idempotency-Key header, so a retried write could create a
# second analysis, vetting, or sync job. Writes are retried only on request.
RETRY_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
MAX_BACKOFF = 8.0


class RedactedKey(str):
    """An API key that will not leak through repr(), logs, or tracebacks."""

    __slots__ = ()

    def __repr__(self) -> str:
        return "'***'"


def encode_query(params: Mapping[str, Any]) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for key, value in params.items():
        if value is None:
            continue
        if isinstance(value, bool):
            out.append((key, "true" if value else "false"))
        elif isinstance(value, (datetime, date)):
            out.append((key, value.isoformat()))
        elif isinstance(value, (list, tuple, set)):
            for item in value:
                if item is None:
                    continue
                if isinstance(item, (datetime, date)):
                    out.append((key, item.isoformat()))
                else:
                    out.append((key, str(item)))
        else:
            out.append((key, str(value)))
    return out


def backoff(attempt: int, response: httpx.Response | None) -> float:
    if response is not None:
        header = response.headers.get("retry-after")
        if header:
            try:
                return min(float(header), 60.0)
            except ValueError:
                pass
    return min(MAX_BACKOFF, 0.5 * (2**attempt)) * (0.5 + random.random() / 2)


def should_retry(method: str, response: httpx.Response | None, retry_writes: bool) -> bool:
    if method.upper() not in RETRY_SAFE_METHODS and not retry_writes:
        return False
    return response is None or response.status_code in RETRY_STATUSES


class BaseClient:
    def __init__(
        self,
        api_key: str,
        *,
        base_url: str,
        timeout: float,
        max_retries: int,
        retry_writes: bool,
        default_headers: Mapping[str, str] | None,
    ) -> None:
        if not api_key:
            raise ValueError("api_key is required. Pass it directly or set ZELF_API_KEY.")
        if max_retries < 0:
            raise ValueError("max_retries must be zero or greater.")
        self.api_key = RedactedKey(api_key)
        self.base_url = base_url.rstrip("/") + "/"
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_writes = retry_writes
        # The client's own key goes on last and a caller's copy of it is
        # dropped whatever its casing, so exactly one key reaches the wire.
        self._headers = {
            "accept": "application/json",
            "user-agent": f"zelf-python/{__version__}",
            **{
                name: value
                for name, value in (default_headers or {}).items()
                if name.lower() != "x-api-key"
            },
            "x-api-key": str(api_key),
        }

    def __repr__(self) -> str:
        return f"{type(self).__name__}(base_url={self.base_url!r}, api_key='***')"

    def build(
        self, path: str, path_params: Mapping[str, Any], query: Mapping[str, Any]
    ) -> tuple[str, list[tuple[str, str]]]:
        for name, value in path_params.items():
            if value is None or value == "":
                raise ValueError(f"{name} is required and must not be empty.")
            path = path.replace("{" + name + "}", quote(str(value), safe=""))
        return urljoin(self.base_url, path.lstrip("/")), encode_query(query)

    def unwrap(self, response: httpx.Response) -> dict[str, Any]:
        if response.status_code >= 400:
            raise _exceptions.parse(response)
        if response.status_code == 204 or not response.content:
            return {}
        try:
            body = response.json()
        except ValueError as exc:
            raise _exceptions.ZelfAPIError(
                "The API returned a response that is not valid JSON.",
                status_code=response.status_code,
                response=response,
            ) from exc
        if not isinstance(body, dict):
            raise _exceptions.ZelfAPIError(
                "The API returned a response envelope that is not an object.",
                status_code=response.status_code,
                response=response,
            )
        return body


class SyncTransport(BaseClient):
    def __init__(self, *args: Any, http_client: httpx.Client | None = None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._owns_client = http_client is None
        self._client = http_client or httpx.Client(timeout=self.timeout)

    def __enter__(self) -> SyncTransport:
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def request(
        self,
        method: str,
        path: str,
        *,
        path_params: Mapping[str, Any] | None = None,
        query: Mapping[str, Any] | None = None,
        body: Any = None,
    ) -> dict[str, Any]:
        url, params = self.build(path, path_params or {}, query or {})
        last: Exception | None = None
        for attempt in range(self.max_retries + 1):
            response = None
            try:
                response = self._client.request(
                    method, url, params=params, json=body, headers=self._headers
                )
                if response.status_code < 400:
                    return self.unwrap(response)
                last = _exceptions.parse(response)
            except httpx.TimeoutException as exc:
                last = _exceptions.ZelfTimeoutError(str(exc) or "Request timed out.")
            except httpx.TransportError as exc:
                last = _exceptions.ZelfConnectionError(str(exc) or "Connection failed.")
            if attempt == self.max_retries or not should_retry(method, response, self.retry_writes):
                break
            time.sleep(backoff(attempt, response))
        raise last if last else _exceptions.ZelfConnectionError()


class AsyncTransport(BaseClient):
    def __init__(
        self, *args: Any, http_client: httpx.AsyncClient | None = None, **kwargs: Any
    ) -> None:
        super().__init__(*args, **kwargs)
        self._owns_client = http_client is None
        self._client = http_client or httpx.AsyncClient(timeout=self.timeout)

    async def __aenter__(self) -> AsyncTransport:
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.close()

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def request(
        self,
        method: str,
        path: str,
        *,
        path_params: Mapping[str, Any] | None = None,
        query: Mapping[str, Any] | None = None,
        body: Any = None,
    ) -> dict[str, Any]:
        url, params = self.build(path, path_params or {}, query or {})
        last: Exception | None = None
        for attempt in range(self.max_retries + 1):
            response = None
            try:
                response = await self._client.request(
                    method, url, params=params, json=body, headers=self._headers
                )
                if response.status_code < 400:
                    return self.unwrap(response)
                last = _exceptions.parse(response)
            except httpx.TimeoutException as exc:
                last = _exceptions.ZelfTimeoutError(str(exc) or "Request timed out.")
            except httpx.TransportError as exc:
                last = _exceptions.ZelfConnectionError(str(exc) or "Connection failed.")
            if attempt == self.max_retries or not should_retry(method, response, self.retry_writes):
                break
            await anyio.sleep(backoff(attempt, response))
        raise last if last else _exceptions.ZelfConnectionError()
