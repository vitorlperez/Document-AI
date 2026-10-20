"""Request-scoped Space filter (ADR-0021 D4): a narrowing, never a widening.

The caller (route or agent entry point) opens ``narrowed_to_spaces`` once; every ``SpaceAccessResolver.resolve``
inside the request then intersects the person's own Spaces with it. The model never supplies it: it is
not an argument of any tool, so a prompt cannot move the boundary.
"""

from collections.abc import Collection, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from uuid import UUID

_space_filter: ContextVar[frozenset[UUID] | None] = ContextVar("space_filter", default=None)


def current_space_filter() -> frozenset[UUID] | None:
    return _space_filter.get()


@contextmanager
def narrowed_to_spaces(space_ids: Collection[UUID] | None) -> Iterator[None]:
    """``None`` leaves the surrounding filter untouched; a nested filter intersects with it, never replaces it."""
    if space_ids is None:
        yield
        return
    current = _space_filter.get()
    token = _space_filter.set(frozenset(space_ids) if current is None else current & frozenset(space_ids))
    try:
        yield
    finally:
        _space_filter.reset(token)
