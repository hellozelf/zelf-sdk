import json
from pathlib import Path

import pytest

import zelf
from zelf import _pagination

FIXTURES = json.loads((Path(__file__).parents[2] / "fixtures" / "fixtures.json").read_text())
OPERATIONS = FIXTURES["operations"]
ENVELOPES = FIXTURES["envelopes"]
PUBLISHED = set(FIXTURES["published"])

# Defects in spec/openapi.yaml, not in the SDK. Each entry is a spec fix waiting to
# happen; when one lands the xfail turns into an XPASS and the entry comes out.
SPEC_DEFECTS: dict[str, str] = {}

# Operations the spec ships no response example for. Their envelopes are built
# from the schemas instead, so they are still checked below, but they prove the
# generator agrees with itself rather than that the documentation is right.
UNDOCUMENTED = sorted(set(OPERATIONS) - PUBLISHED)


@pytest.mark.parametrize("operation", sorted(ENVELOPES))
def test_every_example_validates_against_its_model(operation, request):
    """Every envelope must satisfy the schema its operation declares.

    For a published example a failure is a defect in spec/openapi.yaml: the reference
    documentation is showing users a shape the API does not describe. For a
    synthesized one it is a defect in codegen/samples.py.
    """
    if operation in SPEC_DEFECTS:
        request.node.add_marker(pytest.mark.xfail(reason=SPEC_DEFECTS[operation], strict=True))
    meta = OPERATIONS[operation]
    if meta["model"] is None:
        pytest.skip("endpoint returns no body")

    envelope = ENVELOPES[operation]
    _pagination.envelope(envelope)
    parsed = _pagination.rows(envelope, getattr(zelf, meta["model"]))
    assert parsed, f"{operation} publishes an empty results array"


def test_every_paginated_example_carries_the_full_envelope():
    for name, envelope in ENVELOPES.items():
        missing = {"log_id", "timestamp", "results", "item_count", "page"} - set(envelope)
        assert not missing, f"{name} example is missing envelope keys: {sorted(missing)}"


@pytest.mark.xfail(strict=True, reason="the webhook endpoints publish no response example")
def test_every_operation_has_a_published_example():
    assert UNDOCUMENTED == [], f"operations with no response example: {UNDOCUMENTED}"


def test_every_operation_has_an_envelope_to_check():
    assert sorted(set(OPERATIONS) - set(ENVELOPES)) == []
