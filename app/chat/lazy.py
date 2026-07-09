from typing import Awaitable, Callable, Generic, TypeVar

T = TypeVar("T")

class Lazy(Generic[T]):
    """Wraps an async computation that may never be needed. Deterministic
    (rule-based) code paths never call .get(), so the wrapped work (a Mongo
    scan + cosine-similarity pass, in the current use case) simply never
    runs for them. Memoized so two different LLM-fallback branches in the
    same request (parser + formatter) share one computation instead of
    paying for it twice."""

    def __init__(self, factory: Callable[[], Awaitable[T]]) -> None:
        self._factory = factory
        self._value: T = None
        self._ready = False

    async def get(self) -> T:
        if not self._ready:
            self._value = await self._factory()
            self._ready = True
        return self._value
