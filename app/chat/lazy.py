import asyncio
from typing import Awaitable, Callable, Generic, Optional, TypeVar

T = TypeVar("T")

class Lazy(Generic[T]):
    """Wraps an async computation that may never be needed. Deterministic
    (rule-based) code paths never call .get(), so the wrapped work (a Mongo
    scan + cosine-similarity pass, or an embedding call, in current use
    cases) simply never runs for them. Memoized via a single shared Task so
    concurrent first-callers (e.g. a background save task racing the parser,
    both wanting the same query embedding) await the SAME in-flight call
    instead of each kicking off their own - a plain "if not ready" flag would
    let both slip through before either finishes and set _ready."""

    def __init__(self, factory: Callable[[], Awaitable[T]]) -> None:
        self._factory = factory
        self._task: Optional["asyncio.Task[T]"] = None

    async def get(self) -> T:
        if self._task is None:
            self._task = asyncio.ensure_future(self._factory())
        return await self._task
