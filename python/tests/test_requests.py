from datetime import datetime, timezone

import httpx
import pytest
import respx
from conftest import envelope, row
from pydantic import ValidationError

import zelf

BASE = "https://api.hellozelf.com"
CONTENT = row("content_list")


@respx.mock
def test_list_returns_a_typed_page(client):
    route = respx.get(f"{BASE}/api/v1/content/").mock(
        return_value=httpx.Response(200, json=envelope([CONTENT]))
    )
    page = client.content.list(search="running shoes")

    assert isinstance(page, zelf.Page)
    assert page.results[0].id == CONTENT["id"]
    assert page.results[0].view_count == CONTENT["view_count"]
    assert page.results[0].posted_at == datetime(2026, 5, 12, 16, 0, tzinfo=timezone.utc)
    assert page.item_count == 1
    assert page.has_next is False
    assert [item.id for item in page] == [CONTENT["id"]]
    assert route.calls.last.request.url.params["search"] == "running shoes"


@respx.mock
def test_a_single_read_unwraps_the_envelope(client):
    respx.get(url__regex=rf"{BASE}/api/v1/content/.+/").mock(
        return_value=httpx.Response(200, json=envelope([CONTENT]))
    )
    found = client.content.details(CONTENT["id"])

    assert isinstance(found, zelf.Content)
    assert found.id == CONTENT["id"]


@respx.mock
def test_a_single_read_that_matches_nothing_raises_not_found(client):
    respx.get(url__regex=rf"{BASE}/api/v1/content/.+/").mock(
        return_value=httpx.Response(200, json=envelope([]))
    )
    with pytest.raises(zelf.NotFoundError) as caught:
        client.content.details("con_missing")

    assert caught.value.status_code == 404
    assert caught.value.code == "NOT_FOUND"
    assert caught.value.log_id
    assert "No Content matched" in str(caught.value)


@respx.mock
def test_a_row_the_model_cannot_read_raises_a_zelf_error(client):
    respx.get(url__regex=rf"{BASE}/api/v1/content/.+/").mock(
        return_value=httpx.Response(200, json=envelope([CONTENT | {"view_count": "many"}]))
    )
    with pytest.raises(zelf.ZelfError) as caught:
        client.content.details("con_1")

    error = caught.value
    assert isinstance(error, zelf.ResponseParseError)
    assert error.field == "view_count"
    assert error.log_id
    assert "view_count" in str(error)
    assert isinstance(error.__cause__, ValidationError)


@respx.mock
def test_a_row_that_is_not_an_object_names_no_field(client):
    respx.get(url__regex=rf"{BASE}/api/v1/content/.+/").mock(
        return_value=httpx.Response(200, json=envelope(["not an object"]))
    )
    with pytest.raises(zelf.ResponseParseError) as caught:
        client.content.details("con_1")

    assert caught.value.field is None
    assert "Content" in str(caught.value)


@respx.mock
def test_auto_paging_walks_every_page(client):
    pages = [
        httpx.Response(200, json=envelope([CONTENT | {"id": "con_1"}], page=1, next_page=2)),
        httpx.Response(200, json=envelope([CONTENT | {"id": "con_2"}], page=2, next_page=3)),
        httpx.Response(200, json=envelope([CONTENT | {"id": "con_3"}], page=3)),
    ]
    route = respx.get(f"{BASE}/api/v1/content/").mock(side_effect=pages)

    found = [item.id for item in client.content.list(search="x").auto_paging()]

    assert found == ["con_1", "con_2", "con_3"]
    assert [call.request.url.params.get("page") for call in route.calls] == [None, "2", "3"]


@respx.mock
def test_a_list_endpoint_without_paging_returns_a_plain_list(client):
    respx.get(f"{BASE}/api/v1/brands/catalog/categories/").mock(
        return_value=httpx.Response(
            200,
            json=envelope(row("brands_catalog_categories") and [row("brands_catalog_categories")]),
        )
    )
    found = client.brands.catalog_categories()

    assert isinstance(found, list)
    assert found[0].id == row("brands_catalog_categories")["id"]


@respx.mock
def test_an_endpoint_with_no_body_returns_none(client):
    route = respx.post(url__regex=rf"{BASE}/api/v1/webhooks/subscriptions/.+/send_test/").mock(
        return_value=httpx.Response(202)
    )
    assert client.webhooks.send_test("whs_1") is None
    assert route.called
