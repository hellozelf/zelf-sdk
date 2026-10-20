import hashlib
import hmac
import json
import time

import pytest

from zelf import webhooks

SECRET = "whsec_abcdef0123456789"
BODY = json.dumps(
    {"id": "whd_8f2c1d4e9a", "type": "content.snapshot", "delivered_at": 1718000000},
    separators=(",", ":"),
).encode()


def sign(payload: bytes, secret: str, timestamp: int) -> dict[str, str]:
    """Mirrors the signing scheme the API documents."""
    digest = hmac.new(secret.encode(), f"{timestamp}.".encode() + payload, hashlib.sha256)
    return {
        "Webhook-Id": "whd_8f2c1d4e9a",
        "Webhook-Timestamp": str(timestamp),
        "Webhook-Signature": f"t={timestamp},v1={digest.hexdigest()}",
    }


def test_a_genuine_delivery_verifies_and_returns_its_payload():
    now = time.time()
    headers = sign(BODY, SECRET, int(now))

    payload = webhooks.verify(BODY, headers, SECRET, now=now)

    assert payload["id"] == "whd_8f2c1d4e9a"
    assert payload["type"] == "content.snapshot"


def test_header_lookup_is_case_insensitive():
    now = time.time()
    headers = {k.lower(): v for k, v in sign(BODY, SECRET, int(now)).items()}

    assert webhooks.verify(BODY, headers, SECRET, now=now)


def test_a_forged_signature_is_rejected():
    now = time.time()
    headers = sign(BODY, "whsec_wrong_secret", int(now))

    with pytest.raises(webhooks.WebhookVerificationError, match="No signature matched"):
        webhooks.verify(BODY, headers, SECRET, now=now)


def test_a_tampered_body_is_rejected():
    now = time.time()
    headers = sign(BODY, SECRET, int(now))

    with pytest.raises(webhooks.WebhookVerificationError, match="No signature matched"):
        webhooks.verify(BODY + b" ", headers, SECRET, now=now)


def test_an_old_delivery_is_rejected_as_a_replay():
    stale = int(time.time()) - 4000
    headers = sign(BODY, SECRET, stale)

    with pytest.raises(webhooks.WebhookVerificationError, match="replay"):
        webhooks.verify(BODY, headers, SECRET)


def test_a_future_timestamp_is_also_rejected():
    ahead = int(time.time()) + 4000
    headers = sign(BODY, SECRET, ahead)

    with pytest.raises(webhooks.WebhookVerificationError, match="replay"):
        webhooks.verify(BODY, headers, SECRET)


def test_either_secret_verifies_during_a_rotation():
    now = time.time()
    headers = sign(BODY, "whsec_new", int(now))

    assert webhooks.verify(BODY, headers, ["whsec_old", "whsec_new"], now=now)


def test_a_missing_signature_header_is_rejected():
    with pytest.raises(webhooks.WebhookVerificationError, match="Missing Webhook-Signature"):
        webhooks.verify(BODY, {"Webhook-Id": "whd_1"}, SECRET)


@pytest.mark.parametrize("header", ["", "garbage", "t=abc,v1=ff", "v1=ff", "t=1718000000"])
def test_a_malformed_signature_header_is_rejected(header):
    with pytest.raises(webhooks.WebhookVerificationError):
        webhooks.verify(BODY, {"Webhook-Signature": header}, SECRET)


def test_passing_a_decoded_string_is_refused():
    """Re-encoding the body changes the bytes, so the signature would never match."""
    now = time.time()
    headers = sign(BODY, SECRET, int(now))

    with pytest.raises(TypeError, match="raw request bytes"):
        webhooks.verify(BODY.decode(), headers, SECRET, now=now)


def test_a_non_json_body_is_rejected_after_the_signature_checks_out():
    now = time.time()
    payload = b"not json"
    headers = sign(payload, SECRET, int(now))

    with pytest.raises(webhooks.WebhookVerificationError, match="not valid JSON"):
        webhooks.verify(payload, headers, SECRET, now=now)


def test_no_secret_is_a_programming_error():
    now = time.time()
    with pytest.raises(ValueError, match="At least one signing secret"):
        webhooks.verify(BODY, sign(BODY, SECRET, int(now)), [], now=now)
