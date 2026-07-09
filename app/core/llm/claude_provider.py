from __future__ import annotations

from typing import List, Optional, Type

from app.core.config import settings
from app.core.llm.base import LLMProvider, LLMResult, M


class ClaudeProvider(LLMProvider):
    """Scaffold only - no anthropic SDK call wired up yet since there's no
    Anthropic API key to test against. Selecting AI_PROVIDER=claude boots the
    app fine (is_available() just reports False), but any actual generate
    call raises NotImplementedError instead of silently doing the wrong
    thing. TODO when a real key is available: implement via the `anthropic`
    SDK's messages API, using a forced tool-use call for generate_structured
    since Claude has no native JSON-schema response mode."""

    name = "claude"

    def __init__(self) -> None:
        self.api_key = settings.ANTHROPIC_API_KEY
        self.models = {"cheap": settings.CLAUDE_MODEL_CHEAP, "complex": settings.CLAUDE_MODEL_COMPLEX}

    def is_available(self) -> bool:
        return False

    def _not_implemented(self) -> NotImplementedError:
        return NotImplementedError(
            "ClaudeProvider is a scaffold - implement via the `anthropic` SDK before selecting AI_PROVIDER=claude."
        )

    async def generate_text(self, prompt: str, system_instruction: Optional[str] = None, model_tier: str = "cheap") -> LLMResult[str]:
        raise self._not_implemented()

    async def generate_structured(self, prompt: str, response_schema: Type[M], system_instruction: Optional[str] = None, model_tier: str = "cheap") -> LLMResult[M]:
        raise self._not_implemented()

    def embed(
        self,
        text: str,
        task_type: Optional[str] = None,
        output_dimensionality: Optional[int] = None,
    ) -> List[float]:
        return []
