from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel


class NotGiven:
    """Marks an argument the caller never passed.

    The API treats an omitted field and an explicit `null` differently on PATCH
    endpoints, so `None` has to stay usable as a real value.
    """

    __slots__ = ()

    def __bool__(self) -> bool:
        return False

    def __repr__(self) -> str:
        return "NOT_GIVEN"


NOT_GIVEN = NotGiven()


def dump(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json", exclude_unset=True, by_alias=True)
    if isinstance(value, (list, tuple, set)):
        return [dump(item) for item in value]
    if isinstance(value, dict):
        return {key: dump(item) for key, item in value.items()}
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def given(values: dict[str, Any]) -> dict[str, Any]:
    """Drop the arguments the caller omitted, keeping explicit `None`s."""
    return {key: value for key, value in values.items() if not isinstance(value, NotGiven)}


def body(values: dict[str, Any]) -> dict[str, Any]:
    return {key: dump(value) for key, value in given(values).items()}
