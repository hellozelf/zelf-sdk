import httpx
import pytest
import respx
from conftest import error

import zelf

BASE = "https://api.hellozelf.com"


@pytest.mark.parametrize(
    ("status", "code", "expected"),
    [
        (400, "VALIDATION_ERROR", zelf.BadRequestError),
        (401, "INVALID_API_KEY", zelf.AuthenticationError),
        (403, "BRAND_ACCESS_DENIED", zelf.PermissionDeniedError),
        (404, "NOT_FOUND", zelf.NotFoundError),
        (429, "RATE_LIMIT_EXCEEDED", zelf.RateLimitError),
        (500, "INTERNAL_ERROR", zelf.InternalServerError),
        (503, "SERVICE_UNAVAILABLE", zelf.ServiceUnavailableError),
    ],
)
@respx.mock
def test_each_status_maps_to_its_own_exception(client, status, code, expected):
    respx.get(f"{BASE}/api/v1/content/").mock(
        return_value=httpx.Response(status, json=error(code, "Something went wrong."))
    )
    with pytest.raises(expected) as caught:
        client.content.list(search="x")

    assert caught.value.status_code == status
    assert caught.value.code == code
    assert caught.value.log_id == "3fa85f64-5717-4562-b3fc-2c963f66afa6"
    assert isinstance(caught.value, zelf.ZelfAPIError)


@respx.mock
def test_an_unparseable_error_body_still_raises_a_typed_error(client):
    respx.get(f"{BASE}/api/v1/content/").mock(
        return_value=httpx.Response(500, text="<html>gateway</html>")
    )
    with pytest.raises(zelf.InternalServerError) as caught:
        client.content.list(search="x")

    assert caught.value.code is None
    assert "HTTP 500" in caught.value.message


@respx.mock
def test_a_connection_failure_raises_a_connection_error(client):
    respx.get(f"{BASE}/api/v1/content/").mock(side_effect=httpx.ConnectError("refused"))

    with pytest.raises(zelf.ZelfConnectionError):
        client.content.list(search="x")


@respx.mock
def test_a_timeout_raises_a_timeout_error(client):
    respx.get(f"{BASE}/api/v1/content/").mock(side_effect=httpx.ReadTimeout("slow"))

    with pytest.raises(zelf.ZelfTimeoutError):
        client.content.list(search="x")
