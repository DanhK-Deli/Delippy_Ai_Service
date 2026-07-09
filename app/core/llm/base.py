from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Generic, List, Optional, Type, TypeVar

from pydantic import BaseModel

T = TypeVar("T")
M = TypeVar("M", bound=BaseModel)


@dataclass
class LLMResult(Generic[T]):
    """Wraps a provider call result together with the token usage for that
    single call. Deliberately not stored on the provider instance - a shared
    mutable last_prompt_tokens attribute is a race condition once multiple
    async requests hit the same provider singleton concurrently."""
    value: T
    prompt_tokens: int = 0
    completion_tokens: int = 0


class LLMProvider(ABC):
    name: str = "base"

    @abstractmethod
    def is_available(self) -> bool:
        ...

    @abstractmethod
    async def generate_text(
        self,
        prompt: str,
        system_instruction: Optional[str] = None,
        model_tier: str = "cheap",
    ) -> LLMResult[str]:
        ...

    @abstractmethod
    async def generate_structured(
        self,
        prompt: str,
        response_schema: Type[M],
        system_instruction: Optional[str] = None,
        model_tier: str = "cheap",
    ) -> LLMResult[M]:
        ...

    @abstractmethod
    def embed(
        self,
        text: str,
        task_type: Optional[str] = None,
        output_dimensionality: Optional[int] = None,
    ) -> List[float]:
        """task_type ("RETRIEVAL_DOCUMENT" when embedding a product to index,
        "RETRIEVAL_QUERY" when embedding a user query) and
        output_dimensionality are Gemini-specific asymmetric-retrieval/
        Matryoshka-embedding knobs - providers that don't support them
        (OpenAI's `dimensions` param is a partial equivalent; Claude has no
        embedding API at all) just ignore what they can't honor."""
        ...
