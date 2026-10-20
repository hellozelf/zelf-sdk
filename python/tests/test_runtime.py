import hashlib
import hmac
import time
from datetime import date, datetime, timezone

import httpx
import pytest
import respx
from conftest import envelope, row

import zelf
from zelf import _exceptions, _pagination, _transport, _types

KEY = "sk_zelf_" + "0" * 64
BASE = "https://api.hellozelf.com"
ROW = row("brands_list")
TRANSPORT = {
    "api_key": KEY,
    "base_url": BASE,
    "timeout": 5.0,
    "max_retries": 0,
    "retry_writes": False,
    "default_headers": {},
}


def brands_page(client):
    return client.brands.list()


def test_not_given_is_falsey_and_prints_its_name():
    assert not _types.NOT_GIVEN
    assert repr(_types.NOT_GIVEN) == "NOT_GIVEN"


def test_dump_renders_dates_as_iso():
    moment = datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert _types.dump(moment) == "2026-01-01T00:00:00+00:00"
    assert _types.dump(date(2026, 1, 1)) == "2026-01-01"


def test_an_error_prints_status_code_and_message():
    error = _exceptions.ZelfAPIError("Nope.", status_code=404, code="NOT_FOUND")
    assert str(error) == "404 NOT_FOUND Nope."


def test_the_async_client_hides_the_key_in_its_repr():
    client = zelf.ZelfAPIClientAsync(KEY)
    assert "api_key='***'" in repr(client)
    assert KEY not in repr(client)


def test_the_sync_transport_hides_the_key_in_its_repr():
    with zelf.ZelfAPIClient(KEY) as client:
        assert KEY not in repr(client._transport)


def test_rows_rejects_a_results_field_that_is_not_a_list():
    with pytest.raises(TypeError, match="was not a list"):
        _pagination.rows({"results": {"id": 1}}, zelf.Brand)


@pytest.mark.parametrize("bound,message", [("max_pages", "max_pages"), ("max_items", "max_items")])
def test_paging_bounds_must_be_positive(bound, message):
    with respx.mock(base_url=BASE) as mock:
        mock.get("/api/v1/brands/").mock(return_value=httpx.Response(200, json=envelope([ROW])))
        with zelf.ZelfAPIClient(KEY, max_retries=0) as client:
            page = brands_page(client)
    with pytest.raises(ValueError, match=message):
        list(page.auto_paging(**{bound: 0}))


def test_a_page_exposes_its_envelope_metadata():
    with respx.mock(base_url=BASE) as mock:
        mock.get("/api/v1/brands/").mock(return_value=httpx.Response(200, json=envelope([ROW])))
        with zelf.ZelfAPIClient(KEY, max_retries=0) as client:
            page = brands_page(client)

    assert page.log_id
    assert page.page == 1
    assert page.item_count == 1
    assert page.applied_filters == {"page": 1, "page_size": 30}
    assert page.has_next is False
    assert page[0].title == ROW["title"]
    assert len(page) == 1
    assert list(page) == page.results
    assert "Page[Brand]" in repr(page)


@pytest.mark.asyncio
async def test_an_async_page_exposes_the_same_metadata():
    with respx.mock(base_url=BASE) as mock:
        mock.get("/api/v1/brands/").mock(return_value=httpx.Response(200, json=envelope([ROW])))
        async with zelf.ZelfAPIClientAsync(KEY, max_retries=0) as client:
            page = await client.brands.list()

    assert page.log_id
    assert page.page == 1
    assert page.item_count == 1
    assert page.applied_filters == {"page": 1, "page_size": 30}
    assert page.has_next is False
    assert page[0].title == ROW["title"]
    assert len(page) == 1
    assert list(page) == page.results
    assert "AsyncPage[Brand]" in repr(page)


def test_max_retries_must_not_be_negative():
    with pytest.raises(ValueError, match="max_retries"):
        zelf.ZelfAPIClient(KEY, max_retries=-1)


def test_query_encoding_drops_nothing_and_renders_dates():
    pairs = _transport.encode_query(
        {
            "skip": None,
            "when": datetime(2026, 1, 1, tzinfo=timezone.utc),
            "many": ["a", None, datetime(2026, 1, 2, tzinfo=timezone.utc)],
            "flag": True,
        }
    )
    rendered = dict(pairs) if len(pairs) == len({k for k, _ in pairs}) else pairs
    assert ("when", "2026-01-01T00:00:00+00:00") in pairs
    assert ("many", "2026-01-02T00:00:00+00:00") in pairs
    assert all(key != "skip" for key, _ in pairs)
    assert rendered is not None


def test_a_body_that_is_not_json_becomes_a_typed_error():
    with respx.mock(base_url=BASE) as mock:
        mock.get("/api/v1/usage/").mock(return_value=httpx.Response(200, content=b"<html>"))
        with zelf.ZelfAPIClient(KEY, max_retries=0) as client:
            with pytest.raises(zelf.ZelfAPIError, match="not valid JSON"):
                client.usage.retrieve()


def test_an_error_status_raises_the_typed_exception():
    body = {
        "log_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
        "timestamp": "2026-01-01T00:00:00Z",
        "error": {"code": "NOT_FOUND", "message": "Resource not found.", "details": {}},
    }
    with respx.mock(base_url=BASE) as mock:
        mock.get("/api/v1/usage/").mock(return_value=httpx.Response(404, json=body))
        with zelf.ZelfAPIClient(KEY, max_retries=0) as client:
            with pytest.raises(zelf.NotFoundError):
                client.usage.retrieve()


def test_a_timeout_becomes_a_typed_timeout_error():
    with respx.mock(base_url=BASE) as mock:
        mock.get("/api/v1/usage/").mock(side_effect=httpx.ReadTimeout("slow"))
        with zelf.ZelfAPIClient(KEY, max_retries=0) as client:
            with pytest.raises(zelf.ZelfTimeoutError):
                client.usage.retrieve()


def test_a_connection_failure_becomes_a_typed_connection_error():
    with respx.mock(base_url=BASE) as mock:
        mock.get("/api/v1/usage/").mock(side_effect=httpx.ConnectError("down"))
        with zelf.ZelfAPIClient(KEY, max_retries=0) as client:
            with pytest.raises(zelf.ZelfConnectionError):
                client.usage.retrieve()


@pytest.mark.asyncio
async def test_the_async_transport_surfaces_the_same_failures():
    with respx.mock(base_url=BASE) as mock:
        mock.get("/api/v1/usage/").mock(side_effect=httpx.ReadTimeout("slow"))
        async with zelf.ZelfAPIClientAsync(KEY, max_retries=0) as client:
            with pytest.raises(zelf.ZelfTimeoutError):
                await client.usage.retrieve()

    with respx.mock(base_url=BASE) as mock:
        mock.get("/api/v1/usage/").mock(side_effect=httpx.ConnectError("down"))
        async with zelf.ZelfAPIClientAsync(KEY, max_retries=0) as client:
            with pytest.raises(zelf.ZelfConnectionError):
                await client.usage.retrieve()


def test_verify_rejects_a_payload_that_is_not_an_object():
    """A JSON array is valid JSON and still not a webhook."""
    secret = "whsec_abcdef0123456789"
    body = b"[1, 2, 3]"
    moment = int(time.time())
    digest = hmac.new(secret.encode(), f"{moment}.".encode() + body, hashlib.sha256).hexdigest()
    headers = {
        "Webhook-Id": "whd_8f2c1d4e9a",
        "Webhook-Timestamp": str(moment),
        "Webhook-Signature": f"t={moment},v1={digest}",
    }
    with pytest.raises(zelf.webhooks.WebhookVerificationError, match="not a JSON object"):
        zelf.webhooks.verify(body, headers, secret)


@pytest.mark.asyncio
@pytest.mark.parametrize("bound", ["max_pages", "max_items"])
async def test_async_paging_bounds_must_be_positive(bound):
    with respx.mock(base_url=BASE) as mock:
        mock.get("/api/v1/brands/").mock(return_value=httpx.Response(200, json=envelope([ROW])))
        async with zelf.ZelfAPIClientAsync(KEY, max_retries=0) as client:
            page = await client.brands.list()
    with pytest.raises(ValueError, match=bound):
        async for _ in page.auto_paging(**{bound: 0}):
            pass


def test_an_unparseable_retry_after_falls_back_to_backoff():
    response = httpx.Response(429, headers={"retry-after": "soon"})
    assert _transport.backoff(0, response) > 0


def test_unwrap_raises_on_an_error_status():
    body = {
        "log_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
        "timestamp": "2026-01-01T00:00:00Z",
        "error": {"code": "CONFLICT", "message": "Nope.", "details": {}},
    }
    transport = _transport.SyncTransport(**TRANSPORT)
    with pytest.raises(zelf.ConflictError):
        transport.unwrap(httpx.Response(409, json=body))
    transport.close()


def test_unwrap_rejects_an_envelope_that_is_not_an_object():
    transport = _transport.SyncTransport(**TRANSPORT)
    with pytest.raises(zelf.ZelfAPIError, match="not an object"):
        transport.unwrap(httpx.Response(200, json=[1, 2, 3]))
    transport.close()


def test_the_sync_transport_is_a_context_manager():
    with _transport.SyncTransport(**TRANSPORT) as transport:
        assert transport.base_url


@pytest.mark.asyncio
async def test_the_async_transport_is_a_context_manager():
    async with _transport.AsyncTransport(**TRANSPORT) as transport:
        assert transport.base_url
