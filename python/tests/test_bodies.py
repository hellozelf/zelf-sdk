import json

import httpx
import respx
from conftest import envelope, row

import zelf

BASE = "https://api.hellozelf.com"


def sent(route) -> dict:
    return json.loads(route.calls.last.request.read())


@respx.mock
def test_a_body_can_be_built_from_keyword_arguments(client):
    route = respx.post(f"{BASE}/api/v1/ai_analysis/").mock(
        return_value=httpx.Response(201, json=envelope([row("ai_analysis_create")]))
    )
    analysis = client.ai_analysis.create(
        name="Launch sentiment",
        topic="creator sentiment toward Zelf",
        content_filters={"search": "zelf", "posted_within_days": 30},
        analysis_scope=["CONTENT"],
    )

    assert isinstance(analysis, zelf.AiAnalysis)
    assert sent(route) == {
        "name": "Launch sentiment",
        "topic": "creator sentiment toward Zelf",
        "content_filters": {"search": "zelf", "posted_within_days": 30},
        "analysis_scope": ["CONTENT"],
    }


@respx.mock
def test_a_body_can_also_be_built_from_a_model(client):
    route = respx.post(f"{BASE}/api/v1/ai_analysis/").mock(
        return_value=httpx.Response(201, json=envelope([row("ai_analysis_create")]))
    )
    client.ai_analysis.create(
        name="Launch sentiment",
        topic="sentiment",
        content_filters=zelf.ContentFilterInputRequest(search="zelf"),
    )

    assert sent(route)["content_filters"] == {"search": "zelf"}


@respx.mock
def test_omitted_fields_are_left_out_of_the_body(client):
    route = respx.post(f"{BASE}/api/v1/creator_sync/").mock(
        return_value=httpx.Response(201, json=envelope([row("creator_sync_create")]))
    )
    client.creator_sync.create(profile_url="https://www.tiktok.com/@zelf")

    assert sent(route) == {"profile_url": "https://www.tiktok.com/@zelf"}


@respx.mock
def test_an_explicit_none_is_sent_as_null(client):
    """PATCH distinguishes "leave alone" from "clear", so None has to survive."""
    route = respx.patch(f"{BASE}/api/v1/brands/").mock(
        return_value=httpx.Response(200, json=envelope([row("brands_update")]))
    )
    client.brands.update(boolean_query=None)

    assert sent(route) == {"boolean_query": None}


@respx.mock
def test_query_values_are_encoded_for_the_wire(client):
    from datetime import datetime, timezone

    route = respx.get(f"{BASE}/api/v1/content/").mock(
        return_value=httpx.Response(200, json=envelope([]))
    )
    client.content.list(
        platform=["instagram", "tiktok"],
        is_owned=True,
        posted_after=datetime(2026, 1, 1, tzinfo=timezone.utc),
        search="running shoes",
    )
    params = route.calls.last.request.url.params

    assert params.get_list("platform") == ["instagram", "tiktok"]
    assert params["is_owned"] == "true"
    assert params["posted_after"] == "2026-01-01T00:00:00+00:00"
    assert "brand_id" not in params


@respx.mock
def test_a_scalar_is_accepted_where_the_api_repeats_a_key(client):
    route = respx.get(f"{BASE}/api/v1/content/").mock(
        return_value=httpx.Response(200, json=envelope([]))
    )
    client.content.list(platform="instagram", search="x")

    assert route.calls.last.request.url.params.get_list("platform") == ["instagram"]
