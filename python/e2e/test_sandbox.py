import os

import pytest

import zelf

BASE = os.environ.get("ZELF_BASE_URL", "https://sandbox-api.hellozelf.com")
KEY = os.environ.get("ZELF_API_KEY", "sk_zelf_sandbox_demo")


@pytest.fixture(scope="module")
def client():
    with zelf.ZelfAPIClient(api_key=KEY, base_url=BASE, timeout=30.0) as instance:
        yield instance


def test_usage_decodes(client):
    assert client.usage.retrieve() is not None


def test_a_page_decodes_every_row(client):
    page = client.content.list(page_size=2)
    assert page.item_count == 2
    assert all(row.id.startswith("con_") for row in page.results)


def test_auto_paging_stops_at_the_bound(client):
    page = client.content.list(page_size=2)
    rows = list(page.auto_paging(max_pages=2))
    assert len(rows) == 4


def test_a_bad_key_raises_the_typed_error():
    with zelf.ZelfAPIClient(api_key="sk_zelf_" + "9" * 64, base_url=BASE, max_retries=0) as bad:
        with pytest.raises(zelf.AuthenticationError) as caught:
            bad.usage.retrieve()
    assert caught.value.status_code == 401
    assert caught.value.code == "INVALID_API_KEY"


def test_a_rate_limit_is_retried_then_surfaced():
    with zelf.ZelfAPIClient(
        api_key=KEY,
        base_url=BASE,
        max_retries=1,
        default_headers={"x-sandbox-force-error": "RATE_LIMIT_EXCEEDED"},
    ) as throttled:
        with pytest.raises(zelf.RateLimitError) as caught:
            throttled.usage.retrieve()
    assert caught.value.status_code == 429


def test_event_types_are_listed(client):
    events = client.webhooks.list_events()
    assert events
