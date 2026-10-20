import httpx
import pytest
import respx
from conftest import envelope, row

import zelf

BASE = "https://api.hellozelf.com"
CONTENT = row("content_list")


def pages(count: int):
    return [
        httpx.Response(
            200,
            json=envelope(
                [CONTENT | {"id": f"con_{n}"}],
                page=n,
                next_page=n + 1 if n < count else None,
            ),
        )
        for n in range(1, count + 1)
    ]


@respx.mock
def test_max_pages_stops_the_walk_early(client):
    route = respx.get(f"{BASE}/api/v1/content/").mock(side_effect=pages(5))

    found = [item.id for item in client.content.list(search="x").auto_paging(max_pages=3)]

    assert found == ["con_1", "con_2", "con_3"]
    assert route.call_count == 3


@respx.mock
def test_max_pages_of_one_makes_no_further_request(client):
    route = respx.get(f"{BASE}/api/v1/content/").mock(side_effect=pages(5))

    found = [item.id for item in client.content.list(search="x").auto_paging(max_pages=1)]

    assert found == ["con_1"]
    assert route.call_count == 1


@respx.mock
def test_max_items_stops_before_fetching_a_page_it_does_not_need(client):
    route = respx.get(f"{BASE}/api/v1/content/").mock(side_effect=pages(5))

    found = [item.id for item in client.content.list(search="x").auto_paging(max_items=2)]

    assert found == ["con_1", "con_2"]
    assert route.call_count == 2


@respx.mock
def test_pages_honours_max_pages(client):
    route = respx.get(f"{BASE}/api/v1/content/").mock(side_effect=pages(5))

    seen = [page.page for page in client.content.list(search="x").pages(max_pages=2)]

    assert seen == [1, 2]
    assert route.call_count == 2


@respx.mock
def test_no_limit_walks_everything(client):
    route = respx.get(f"{BASE}/api/v1/content/").mock(side_effect=pages(4))

    found = [item.id for item in client.content.list(search="x").auto_paging()]

    assert found == ["con_1", "con_2", "con_3", "con_4"]
    assert route.call_count == 4


@pytest.mark.parametrize("kwargs", [{"max_pages": 0}, {"max_pages": -1}, {"max_items": 0}])
@respx.mock
def test_a_limit_below_one_is_rejected(client, kwargs):
    respx.get(f"{BASE}/api/v1/content/").mock(side_effect=pages(2))
    page = client.content.list(search="x")

    with pytest.raises(ValueError):
        list(page.auto_paging(**kwargs))


@respx.mock
async def test_the_async_client_honours_max_pages():
    respx.get(f"{BASE}/api/v1/content/").mock(side_effect=pages(5))

    async with zelf.ZelfAPIClientAsync("sk_test", max_retries=0) as client:
        page = await client.content.list(search="x")
        found = [item.id async for item in page.auto_paging(max_pages=2)]

    assert found == ["con_1", "con_2"]


@respx.mock
async def test_the_async_client_honours_max_items():
    respx.get(f"{BASE}/api/v1/content/").mock(side_effect=pages(5))

    async with zelf.ZelfAPIClientAsync("sk_test", max_retries=0) as client:
        page = await client.content.list(search="x")
        found = [item.id async for item in page.auto_paging(max_items=3)]

    assert found == ["con_1", "con_2", "con_3"]


def test_the_async_client_keeps_its_former_name():
    assert zelf.AsyncZelfAPIClient is zelf.ZelfAPIClientAsync
