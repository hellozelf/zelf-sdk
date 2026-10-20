import httpx
import respx
from conftest import envelope, error, row

import zelf

BASE = "https://api.hellozelf.com"


@respx.mock
def test_a_rate_limited_read_is_retried_then_succeeds(monkeypatch):
    monkeypatch.setattr("zelf._transport.time.sleep", lambda _: None)
    route = respx.get(f"{BASE}/api/v1/content/").mock(
        side_effect=[
            httpx.Response(429, json=error("RATE_LIMIT_EXCEEDED", "Slow down.")),
            httpx.Response(200, json=envelope([row("content_list")])),
        ]
    )
    with zelf.ZelfAPIClient("sk_test", max_retries=2) as client:
        page = client.content.list(search="x")

    assert len(page) == 1
    assert route.call_count == 2


@respx.mock
def test_retries_stop_at_the_configured_limit(monkeypatch):
    monkeypatch.setattr("zelf._transport.time.sleep", lambda _: None)
    route = respx.get(f"{BASE}/api/v1/content/").mock(
        return_value=httpx.Response(503, json=error("SERVICE_UNAVAILABLE", "Down."))
    )
    with zelf.ZelfAPIClient("sk_test", max_retries=2) as client:
        try:
            client.content.list(search="x")
        except zelf.ServiceUnavailableError:
            pass

    assert route.call_count == 3


@respx.mock
def test_a_write_is_not_retried_by_default(monkeypatch):
    """The API documents no Idempotency-Key, so a retried create could run twice."""
    monkeypatch.setattr("zelf._transport.time.sleep", lambda _: None)
    route = respx.post(f"{BASE}/api/v1/creator_sync/").mock(
        return_value=httpx.Response(503, json=error("SERVICE_UNAVAILABLE", "Down."))
    )
    with zelf.ZelfAPIClient("sk_test", max_retries=3) as client:
        try:
            client.creator_sync.create(profile_url="https://tiktok.com/@zelf")
        except zelf.ServiceUnavailableError:
            pass

    assert route.call_count == 1


@respx.mock
def test_a_write_is_retried_only_when_asked(monkeypatch):
    monkeypatch.setattr("zelf._transport.time.sleep", lambda _: None)
    route = respx.post(f"{BASE}/api/v1/creator_sync/").mock(
        return_value=httpx.Response(503, json=error("SERVICE_UNAVAILABLE", "Down."))
    )
    with zelf.ZelfAPIClient("sk_test", max_retries=2, retry_writes=True) as client:
        try:
            client.creator_sync.create(profile_url="https://tiktok.com/@zelf")
        except zelf.ServiceUnavailableError:
            pass

    assert route.call_count == 3


@respx.mock
def test_a_client_error_is_never_retried(monkeypatch):
    monkeypatch.setattr("zelf._transport.time.sleep", lambda _: None)
    route = respx.get(f"{BASE}/api/v1/content/").mock(
        return_value=httpx.Response(400, json=error("VALIDATION_ERROR", "Bad."))
    )
    with zelf.ZelfAPIClient("sk_test", max_retries=3) as client:
        try:
            client.content.list(search="x")
        except zelf.BadRequestError:
            pass

    assert route.call_count == 1


def test_retry_after_is_honoured_over_the_backoff_curve():
    from zelf._transport import backoff

    response = httpx.Response(429, headers={"retry-after": "7"})
    assert backoff(0, response) == 7.0
    assert backoff(0, httpx.Response(429, headers={"retry-after": "9999"})) == 60.0
    assert 0 < backoff(0, None) <= 0.5
