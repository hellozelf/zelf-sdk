import httpx
import pytest
import respx
from conftest import envelope, error, row

import zelf

BASE = "https://api.hellozelf.com"
CONTENT = row("content_list")


@pytest.fixture
async def aclient():
    async with zelf.AsyncZelfAPIClient("sk_test", max_retries=0) as instance:
        yield instance


@respx.mock
async def test_the_async_client_lists_content(aclient):
    respx.get(f"{BASE}/api/v1/content/").mock(
        return_value=httpx.Response(200, json=envelope([CONTENT]))
    )
    page = await aclient.content.list(search="x")

    assert isinstance(page, zelf.AsyncPage)
    assert page.results[0].id == CONTENT["id"]


@respx.mock
async def test_async_auto_paging_walks_every_page(aclient):
    respx.get(f"{BASE}/api/v1/content/").mock(
        side_effect=[
            httpx.Response(200, json=envelope([CONTENT | {"id": "con_1"}], page=1, next_page=2)),
            httpx.Response(200, json=envelope([CONTENT | {"id": "con_2"}], page=2)),
        ]
    )
    found = [item.id async for item in (await aclient.content.list(search="x")).auto_paging()]

    assert found == ["con_1", "con_2"]


@respx.mock
async def test_the_async_client_raises_the_same_typed_errors(aclient):
    respx.get(f"{BASE}/api/v1/content/").mock(
        return_value=httpx.Response(401, json=error("INVALID_API_KEY", "Nope."))
    )
    with pytest.raises(zelf.AuthenticationError) as caught:
        await aclient.content.list(search="x")

    assert caught.value.code == "INVALID_API_KEY"


@respx.mock
async def test_the_async_client_retries_reads(monkeypatch):
    async def instant(_):
        return None

    monkeypatch.setattr("zelf._transport.anyio.sleep", instant)
    route = respx.get(f"{BASE}/api/v1/content/").mock(
        side_effect=[
            httpx.Response(429, json=error("RATE_LIMIT_EXCEEDED", "Slow down.")),
            httpx.Response(200, json=envelope([CONTENT])),
        ]
    )
    async with zelf.AsyncZelfAPIClient("sk_test", max_retries=1) as client:
        page = await client.content.list(search="x")

    assert len(page) == 1
    assert route.call_count == 2


def test_both_clients_expose_the_same_surface():
    sync = zelf.ZelfAPIClient("sk_test")
    asynchronous = zelf.AsyncZelfAPIClient("sk_test")
    resources = sorted(k for k in vars(sync) if not k.startswith("_"))

    assert resources == sorted(k for k in vars(asynchronous) if not k.startswith("_"))
    for name in resources:
        sync_methods = {m for m in dir(getattr(sync, name)) if not m.startswith("_")}
        async_methods = {m for m in dir(getattr(asynchronous, name)) if not m.startswith("_")}
        assert sync_methods == async_methods, name
