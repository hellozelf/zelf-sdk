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


@respx.mock
def test_a_refusal_prints_the_field_and_the_limit(client):
    """A caller reads the exception, not its `.details`, so the reason belongs there."""
    body = error("VALIDATION_ERROR", "Request validation failed.")
    body["error"]["details"] = {"posted_after": ["Must not exceed 366 days."]}
    respx.get(f"{BASE}/api/v1/content/").mock(return_value=httpx.Response(400, json=body))

    with pytest.raises(zelf.BadRequestError) as caught:
        client.content.list(search="x")

    printed = str(caught.value)
    assert "posted_after: Must not exceed 366 days." in printed
    assert "VALIDATION_ERROR" in printed


@respx.mock
def test_a_reason_that_is_not_a_list_is_printed_as_it_came(client):
    """The API usually sends a list per field, but one string is just as valid."""
    body = error("VALIDATION_ERROR", "Request validation failed.")
    body["error"]["details"] = {"page": "Must be 1 or greater."}
    respx.get(f"{BASE}/api/v1/content/").mock(return_value=httpx.Response(400, json=body))

    with pytest.raises(zelf.BadRequestError) as caught:
        client.content.list(search="x")

    assert "page: Must be 1 or greater." in str(caught.value)
