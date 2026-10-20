from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from datetime import datetime
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ValidationError

from ._exceptions import EmptyResultError, ResponseParseError

T = TypeVar("T", bound=BaseModel)


class Envelope(BaseModel):
    """The response wrapper every ZelfAI endpoint returns."""

    log_id: str
    timestamp: datetime
    item_count: int
    page: int
    next: int | None = None
    previous: int | None = None
    applied_filters: dict[str, Any] = {}


def envelope(payload: dict[str, Any]) -> Envelope:
    return Envelope.model_validate({k: v for k, v in payload.items() if k != "results"})


def first_field(error: ValidationError) -> str | None:
    """The dotted path of the first field a row failed on."""
    for entry in error.errors():
        location = entry.get("loc") or ()
        if location:
            return ".".join(str(part) for part in location)
    return None


def rows(payload: dict[str, Any], model: type[T]) -> list[T]:
    results = payload.get("results") or []
    if not isinstance(results, list):
        raise TypeError("`results` was not a list; the API response shape changed.")
    parsed: list[T] = []
    for row in results:
        try:
            parsed.append(model.model_validate(row))
        except ValidationError as exc:
            # A pydantic error is not a ZelfError, so it would escape every
            # documented handler and take the response's log_id with it.
            raise ResponseParseError(
                f"The API returned a {model.__name__} this SDK could not read.",
                field=first_field(exc),
                log_id=payload.get("log_id"),
            ) from exc
    return parsed


def one(payload: dict[str, Any], model: type[T]) -> T:
    """Take the single row out of the envelope.

    Reads that match nothing come back as `200` with an empty `results` array
    rather than a `404`, so the empty case is raised as a not-found error.
    """
    found = rows(payload, model)
    if not found:
        raise EmptyResultError(
            f"No {model.__name__} matched the request.",
            status_code=404,
            code="NOT_FOUND",
            log_id=payload.get("log_id"),
        )
    return found[0]


class Page(Generic[T]):
    """One page of results, plus the envelope metadata that came with it."""

    def __init__(
        self,
        payload: dict[str, Any],
        model: type[T],
        fetch: Callable[[int], dict[str, Any]] | None = None,
    ) -> None:
        self.meta = envelope(payload)
        self.results: list[T] = rows(payload, model)
        self._model = model
        self._fetch = fetch

    @property
    def log_id(self) -> str:
        return self.meta.log_id

    @property
    def page(self) -> int:
        return self.meta.page

    @property
    def item_count(self) -> int:
        return self.meta.item_count

    @property
    def applied_filters(self) -> dict[str, Any]:
        return self.meta.applied_filters

    @property
    def has_next(self) -> bool:
        return self.meta.next is not None

    def __iter__(self) -> Iterator[T]:
        return iter(self.results)

    def __len__(self) -> int:
        return len(self.results)

    def __getitem__(self, index: int) -> T:
        return self.results[index]

    def __repr__(self) -> str:
        return (
            f"<Page[{self._model.__name__}] page={self.meta.page} "
            f"items={self.meta.item_count} has_next={self.has_next}>"
        )

    def next_page(self) -> Page[T] | None:
        if self._fetch is None or self.meta.next is None:
            return None
        return Page(self._fetch(self.meta.next), self._model, self._fetch)

    def pages(self, max_pages: int | None = None) -> Iterator[Page[T]]:
        """Yield this page and the ones after it.

        `max_pages` counts this page as the first, so `max_pages=1` yields only
        what has already been fetched and makes no further request.
        """
        if max_pages is not None and max_pages < 1:
            raise ValueError("max_pages must be 1 or greater.")
        current: Page[T] | None = self
        seen = 0
        while current is not None:
            yield current
            seen += 1
            if max_pages is not None and seen >= max_pages:
                return
            current = current.next_page()

    def auto_paging(
        self, max_pages: int | None = None, max_items: int | None = None
    ) -> Iterator[T]:
        """Walk the remaining pages, yielding one item at a time.

        `max_pages` bounds how many pages are fetched and `max_items` how many
        items come back. Either one stops the walk, so no page is requested
        once enough items are in hand.
        """
        if max_items is not None and max_items < 1:
            raise ValueError("max_items must be 1 or greater.")
        produced = 0
        for page in self.pages(max_pages):
            for row in page.results:
                yield row
                produced += 1
                if max_items is not None and produced >= max_items:
                    return


class AsyncPage(Generic[T]):
    def __init__(
        self,
        payload: dict[str, Any],
        model: type[T],
        fetch: Callable[[int], Awaitable[dict[str, Any]]] | None = None,
    ) -> None:
        self.meta = envelope(payload)
        self.results: list[T] = rows(payload, model)
        self._model = model
        self._fetch = fetch

    @property
    def log_id(self) -> str:
        return self.meta.log_id

    @property
    def page(self) -> int:
        return self.meta.page

    @property
    def item_count(self) -> int:
        return self.meta.item_count

    @property
    def applied_filters(self) -> dict[str, Any]:
        return self.meta.applied_filters

    @property
    def has_next(self) -> bool:
        return self.meta.next is not None

    def __iter__(self) -> Iterator[T]:
        return iter(self.results)

    def __len__(self) -> int:
        return len(self.results)

    def __getitem__(self, index: int) -> T:
        return self.results[index]

    def __repr__(self) -> str:
        return (
            f"<AsyncPage[{self._model.__name__}] page={self.meta.page} "
            f"items={self.meta.item_count} has_next={self.has_next}>"
        )

    async def next_page(self) -> AsyncPage[T] | None:
        if self._fetch is None or self.meta.next is None:
            return None
        return AsyncPage(await self._fetch(self.meta.next), self._model, self._fetch)

    async def pages(self, max_pages: int | None = None) -> AsyncIterator[AsyncPage[T]]:
        """Yield this page and the ones after it.

        `max_pages` counts this page as the first, so `max_pages=1` yields only
        what has already been fetched and makes no further request.
        """
        if max_pages is not None and max_pages < 1:
            raise ValueError("max_pages must be 1 or greater.")
        current: AsyncPage[T] | None = self
        seen = 0
        while current is not None:
            yield current
            seen += 1
            if max_pages is not None and seen >= max_pages:
                return
            current = await current.next_page()

    async def auto_paging(
        self, max_pages: int | None = None, max_items: int | None = None
    ) -> AsyncIterator[T]:
        """Walk the remaining pages, yielding one item at a time.

        `max_pages` bounds how many pages are fetched and `max_items` how many
        items come back. Either one stops the walk, so no page is requested
        once enough items are in hand.
        """
        if max_items is not None and max_items < 1:
            raise ValueError("max_items must be 1 or greater.")
        produced = 0
        async for page in self.pages(max_pages):
            for row in page.results:
                yield row
                produced += 1
                if max_items is not None and produced >= max_items:
                    return
