import hashlib
import hmac
import json
import time

import httpx
import pytest
import respx

from zelf import webhooks

SECRET = "whsec_abcdef0123456789"


def snapshot(files=None, items=None, event="content.snapshot"):
    data = {"item_count": 1}
    if files is not None:
        data["files"] = files
    if items is not None:
        data["items"] = items
        data["item_count"] = len(items)
    return {
        "id": "whd_8f2c1d4e9a",
        "type": event,
        "subscription_id": "whs_5Kq9Wd2pBxLm",
        "delivered_at": 1718000000,
        "livemode": True,
        "resource": "content",
        "resource_filters": {},
        "delivery_mode": "manifest" if files is not None else "inline",
        "data": data,
    }


def sign(payload: bytes, secret: str, timestamp: int) -> dict[str, str]:
    digest = hmac.new(secret.encode(), f"{timestamp}.".encode() + payload, hashlib.sha256)
    return {"Webhook-Signature": f"t={timestamp},v1={digest.hexdigest()}"}


def delivery(body: dict, secret: str = SECRET):
    payload = json.dumps(body, separators=(",", ":")).encode()
    now = time.time()
    return payload, sign(payload, secret, int(now)), now


def test_parse_returns_a_typed_event():
    payload, headers, now = delivery(snapshot(items=[{"id": "con_1"}]))

    event = webhooks.parse(payload, headers, SECRET, now=now)

    assert isinstance(event, webhooks.WebhookEvent)
    assert event.event_type is webhooks.EventType.CONTENT_SNAPSHOT
    assert event.id == "whd_8f2c1d4e9a"
    assert event.subscription_id == "whs_5Kq9Wd2pBxLm"
    assert event.livemode is True
    assert event.delivered_at.year == 2024
    assert event.items == [{"id": "con_1"}]
    assert event.files == []
    assert "content.snapshot" in repr(event)


def test_the_raw_payload_survives_a_field_the_sdk_does_not_know():
    body = snapshot(items=[]) | {"a_field_from_the_future": 42}
    payload, headers, now = delivery(body)

    event = webhooks.parse(payload, headers, SECRET, now=now)

    assert event.raw["a_field_from_the_future"] == 42


def test_the_event_type_enum_covers_every_declared_event():
    assert {member.value for member in webhooks.EventType} == {
        "content.snapshot",
        "creator.snapshot",
        "creator_vetting.completed",
        "ai_analysis.completed",
    }


def test_an_event_type_member_compares_equal_to_its_wire_value():
    assert webhooks.EventType.CONTENT_SNAPSHOT == "content.snapshot"
    assert str(webhooks.EventType.CONTENT_SNAPSHOT) == "content.snapshot"
    assert webhooks.EventType.known("content.snapshot")
    assert not webhooks.EventType.known("content.exploded")


def test_an_unrecognised_wire_type_leaves_event_type_as_none():
    payload, headers, now = delivery(snapshot(items=[], event="content.from_the_future"))

    event = webhooks.parse(payload, headers, SECRET, now=now)

    assert event.type == "content.from_the_future"
    assert event.event_type is None


def test_the_handler_routes_to_the_listener_for_the_type():
    handler = webhooks.WebhookHandler(SECRET)
    seen = []

    @handler.on(webhooks.EventType.CONTENT_SNAPSHOT)
    def on_content(event):
        seen.append(("content", event.id))
        return "handled"

    @handler.on(webhooks.EventType.CREATOR_SNAPSHOT)
    def on_creator(event):
        seen.append(("creator", event.id))

    payload, headers, now = delivery(snapshot(items=[]))
    results = handler.handle(payload, headers, now=now)

    assert seen == [("content", "whd_8f2c1d4e9a")]
    assert results == ["handled"]


def test_one_listener_can_take_several_types():
    handler = webhooks.WebhookHandler(SECRET)
    seen = []
    handler.on(webhooks.EventType.CONTENT_SNAPSHOT, webhooks.EventType.CREATOR_SNAPSHOT)(
        seen.append
    )

    payload, headers, now = delivery(snapshot(items=[], event="creator.snapshot"))
    handler.handle(payload, headers, now=now)

    assert [event.type for event in seen] == ["creator.snapshot"]


def test_an_unmatched_event_falls_back_when_a_fallback_is_set():
    handler = webhooks.WebhookHandler(SECRET)
    seen = []
    handler.on_any(seen.append)

    payload, headers, now = delivery(snapshot(items=[], event="ai_analysis.completed"))
    handler.handle(payload, headers, now=now)

    assert [event.type for event in seen] == ["ai_analysis.completed"]


def test_an_unmatched_event_with_no_fallback_is_a_no_op():
    handler = webhooks.WebhookHandler(SECRET)

    payload, headers, now = delivery(snapshot(items=[], event="ai_analysis.completed"))

    assert handler.handle(payload, headers, now=now) == []


def test_registering_an_unknown_event_type_fails_loudly():
    handler = webhooks.WebhookHandler(SECRET)

    with pytest.raises(ValueError, match="Unknown event type"):
        handler.on("content.exploded")(lambda event: None)
    with pytest.raises(ValueError, match="at least one event type"):
        handler.on()(lambda event: None)


def test_no_listener_runs_when_the_signature_is_bad():
    handler = webhooks.WebhookHandler(SECRET)
    seen = []
    handler.on_any(seen.append)

    payload, headers, now = delivery(snapshot(items=[]), secret="whsec_wrong")

    with pytest.raises(webhooks.WebhookVerificationError):
        handler.handle(payload, headers, now=now)
    assert seen == []


NDJSON = b'{"id":"con_1"}\n{"id":"con_2"}\n'
DIGEST = hashlib.sha256(NDJSON).hexdigest()


def manifest(sha256=DIGEST):
    return snapshot(
        files=[
            {
                "format": "ndjson",
                "expires_at": 1718000000,
                "sha256": sha256,
                "size_bytes": len(NDJSON),
                "item_count": 2,
                "download_url": "https://storage.googleapis.com/zelf/whd_1.ndjson?sig=x",
            }
        ]
    )


@respx.mock
def test_rows_downloads_the_manifest_and_yields_each_line():
    route = respx.get("https://storage.googleapis.com/zelf/whd_1.ndjson").mock(
        return_value=httpx.Response(200, content=NDJSON)
    )
    payload, headers, now = delivery(manifest())
    event = webhooks.parse(payload, headers, SECRET, now=now)

    assert list(event.rows()) == [{"id": "con_1"}, {"id": "con_2"}]
    assert route.called


@respx.mock
def test_rows_rejects_a_download_whose_checksum_does_not_match():
    respx.get("https://storage.googleapis.com/zelf/whd_1.ndjson").mock(
        return_value=httpx.Response(200, content=b'{"id":"tampered"}\n')
    )
    payload, headers, now = delivery(manifest())
    event = webhooks.parse(payload, headers, SECRET, now=now)

    with pytest.raises(webhooks.WebhookVerificationError, match="does not match"):
        list(event.rows())


@respx.mock
def test_rows_rejects_a_manifest_that_published_no_digest():
    respx.get("https://storage.googleapis.com/zelf/whd_1.ndjson").mock(
        return_value=httpx.Response(200, content=NDJSON)
    )
    payload, headers, now = delivery(manifest(sha256=""))
    event = webhooks.parse(payload, headers, SECRET, now=now)

    with pytest.raises(webhooks.WebhookVerificationError, match="no sha256"):
        list(event.rows())


@respx.mock
def test_rows_reads_an_unchecked_file_when_verification_is_waived():
    respx.get("https://storage.googleapis.com/zelf/whd_1.ndjson").mock(
        return_value=httpx.Response(200, content=NDJSON)
    )
    payload, headers, now = delivery(manifest(sha256=""))
    event = webhooks.parse(payload, headers, SECRET, now=now)

    assert list(event.rows(verify_checksum=False)) == [{"id": "con_1"}, {"id": "con_2"}]


@respx.mock
def test_a_failed_download_surfaces_the_http_error():
    respx.get("https://storage.googleapis.com/zelf/whd_1.ndjson").mock(
        return_value=httpx.Response(403)
    )
    payload, headers, now = delivery(manifest())
    event = webhooks.parse(payload, headers, SECRET, now=now)

    with pytest.raises(httpx.HTTPStatusError):
        list(event.rows())


def test_an_event_reports_its_delivery_mode_and_statistics():
    body = snapshot(items=[{"id": "con_1"}])
    body["data"]["statistics"] = {"post_count": 1, "total_views": 10}
    payload, headers, now = delivery(body)

    event = webhooks.parse(payload, headers, SECRET, now=now)

    assert event.delivery_mode == "inline"
    assert event.statistics is not None


def test_statistics_is_none_when_the_push_carries_none():
    payload, headers, now = delivery(snapshot(items=[]))

    event = webhooks.parse(payload, headers, SECRET, now=now)

    assert event.statistics is None
