import json
from pathlib import Path

import pytest

import zelf

FIXTURES = json.loads((Path(__file__).parents[2] / "fixtures.json").read_text())


@pytest.fixture
def api_key() -> str:
    return "sk_test_not_a_real_key"


@pytest.fixture
def client(api_key):
    with zelf.ZelfAPIClient(api_key, max_retries=0) as instance:
        yield instance


def row(operation: str, index: int = 0) -> dict:
    return FIXTURES["envelopes"][operation]["results"][index]


def envelope(results, *, page=1, next_page=None):
    return {
        "log_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
        "timestamp": "2026-01-01T00:00:00Z",
        "applied_filters": {"page": page, "page_size": 30},
        "results": results,
        "item_count": len(results),
        "page": page,
        "next": next_page,
        "previous": page - 1 if page > 1 else None,
    }


def error(code: str, message: str) -> dict:
    return {
        "log_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
        "timestamp": "2026-01-01T00:00:00Z",
        "error": {"code": code, "message": message, "details": {}},
    }
