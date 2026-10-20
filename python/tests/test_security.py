import httpx
import pytest
import respx
from conftest import envelope, row

import zelf

BASE = "https://api.hellozelf.com"


@respx.mock
def test_the_api_key_travels_in_a_header_and_never_in_the_url(client, api_key):
    route = respx.get(f"{BASE}/api/v1/usage/").mock(
        return_value=httpx.Response(200, json=envelope([row("usage_retrieve")]))
    )
    client.usage.retrieve()

    request = route.calls.last.request
    assert request.headers["x-api-key"] == api_key
    assert api_key not in str(request.url)
    assert request.headers["user-agent"].startswith("zelf-python/")


def test_the_api_key_stays_out_of_repr(api_key):
    client = zelf.ZelfAPIClient(api_key)

    assert api_key not in repr(client)
    assert api_key not in repr(client._transport.api_key)
    assert api_key not in repr(vars(client._transport)["api_key"])
    assert str(client._transport.api_key) == api_key


def test_a_missing_key_fails_before_any_request(monkeypatch):
    monkeypatch.delenv("ZELF_API_KEY", raising=False)
    with pytest.raises(ValueError, match="api_key is required"):
        zelf.ZelfAPIClient()


def test_the_key_falls_back_to_the_environment(monkeypatch):
    monkeypatch.setenv("ZELF_API_KEY", "sk_from_env")

    assert str(zelf.ZelfAPIClient()._transport.api_key) == "sk_from_env"


@respx.mock
def test_path_parameters_are_url_encoded(client):
    route = respx.get(url__regex=rf"{BASE}/api/v1/content/.+/").mock(
        return_value=httpx.Response(200, json=envelope([row("content_list")]))
    )
    client.content.details("con/../../admin")

    # `.path` is the decoded view; `.raw_path` is what goes on the wire, and it
    # must keep the slashes escaped so an id cannot walk out of the endpoint.
    url = route.calls.last.request.url
    assert url.raw_path == b"/api/v1/content/con%2F..%2F..%2Fadmin/"
    assert str(url).startswith("https://api.hellozelf.com/api/v1/content/con%2F")


def test_an_empty_path_parameter_is_rejected(client):
    with pytest.raises(ValueError, match="must not be empty"):
        client.content.details("")
