from __future__ import annotations
import asyncio
from typing import List, Optional, Type

from google import genai
from google.genai import types

from app.core.config import settings
from app.core.llm.base import LLMProvider, LLMResult, M


class GeminiProvider(LLMProvider):
    name = "gemini"

    # Gemini 2.5 Flash defaults to dynamic thinking (budget=-1) when
    # thinking_config isn't set, silently spending latency/tokens even on
    # pure extraction/formatting tasks with no multi-step reasoning to do -
    # confirmed root cause of parser/formatter/scorer calls taking 5-19s on
    # ~100-1000 token outputs. "cheap" calls are all such tasks. "deep_dive"
    # (format_product_deep_dive) keeps a small explicit budget since it has
    # to judge whether it actually recognizes a product rather than
    # inventing specs - but deliberately uses the SAME model as "cheap"
    # (see self.models below), not "complex": GEMINI_MODEL_COMPLEX falls
    # back to GEMINI_ANALYSIS_MODEL in .env, which is gemini-2.5-pro in this
    # deployment - several times pricier than flash per token. Reusing
    # model_tier="complex" just to get a bigger thinking budget silently
    # routed deep-dive onto pro instead of flash (confirmed live - a real
    # bug this comment replaces). "complex" itself is kept defined and
    # untouched for any future call site that genuinely needs a stronger
    # model, not just more thinking budget. deep_dive's own budget was cut
    # from 1024 to 256 - thinking tokens are generated (and cost latency)
    # just like visible output, so a big budget directly worked against the
    # "make deep-dive fast" goal; 256 is enough to catch an obviously-unknown
    # product without adding much generation time.
    # "product_focus" (format_product_focus_reply) needs no reasoning at all -
    # it's just wording 1-2 already-known facts (giá/size/màu) naturally, not
    # judging whether a product is recognized like "deep_dive" does.
    _THINKING_BUDGET = {"cheap": 0, "complex": 1024, "deep_dive": 256, "product_focus": 0}

    # Hard backstop on deep-dive length: product_deep_dive_prompt.txt already
    # asks for "150-200 từ" in plain text, but that's a soft request the
    # model doesn't reliably obey (confirmed live - one real product got a
    # 650-token/~350-word essay despite the prompt's own word-count line).
    # IMPORTANT: Gemini counts thinking tokens against this SAME budget, not
    # separately - confirmed live (max_output_tokens=500 with thinking_budget
    # =1024 spent 478 tokens "thinking" and left only 18 for the actual
    # answer, truncating it mid-sentence with finish_reason=MAX_TOKENS). 900
    # comfortably covers deep_dive's 256 thinking-token budget PLUS a
    # well-behaved ~150-250-word visible answer, with margin to finish the
    # last sentence naturally instead of cutting off. Other tiers are
    # untouched (None = SDK default, unbounded) - parser/formatter/scorer
    # outputs are already shape-bounded by their own schema/task, so a cap
    # there risks truncating a legitimate structured response instead of
    # protecting against a runaway one.
    # product_focus's own prompt asks for "tối đa 40 từ" - 150 tokens is
    # already generous headroom for that (no thinking budget to share it
    # with, unlike deep_dive), just a backstop against a runaway reply.
    _MAX_OUTPUT_TOKENS = {"deep_dive": 900, "product_focus": 150}

    def __init__(self) -> None:
        self.client = genai.Client(api_key=settings.GEMINI_API_KEY) if settings.GEMINI_API_KEY else None
        self.models = {
            "cheap": settings.GEMINI_MODEL_CHEAP,
            "complex": settings.GEMINI_MODEL_COMPLEX,
            # Explicit, not relying on the unrecognized-tier fallback below:
            # deep-dive always uses the cheap/flash model, only the thinking
            # budget differs (see _THINKING_BUDGET above).
            "deep_dive": settings.GEMINI_MODEL_CHEAP,
            "product_focus": settings.GEMINI_MODEL_CHEAP,
        }

    def is_available(self) -> bool:
        return self.client is not None

    async def generate_text(self, prompt: str, system_instruction: Optional[str] = None, model_tier: str = "cheap", timeout: float = 20.0) -> LLMResult[str]:
        if not self.is_available():
            raise RuntimeError("GEMINI_API_KEY is not set. Gemini provider is unavailable.")

        config = types.GenerateContentConfig()
        if system_instruction:
            config.system_instruction = system_instruction
        config.thinking_config = types.ThinkingConfig(
            thinking_budget=self._THINKING_BUDGET.get(model_tier, 0)
        )
        max_tokens = self._MAX_OUTPUT_TOKENS.get(model_tier)
        if max_tokens:
            config.max_output_tokens = max_tokens

        model = self.models.get(model_tier, self.models["cheap"])
        try:
            response = await asyncio.wait_for(
                self.client.aio.models.generate_content(model=model, contents=prompt, config=config),
                timeout=timeout
            )
        except asyncio.TimeoutError:
            raise RuntimeError(f"Gemini API call timed out after {timeout} seconds due to network congestion or API latency.")
        prompt_tokens, completion_tokens = self._usage(response)
        return LLMResult(value=response.text or "", prompt_tokens=prompt_tokens, completion_tokens=completion_tokens)

    async def generate_structured(self, prompt: str, response_schema: Type[M], system_instruction: Optional[str] = None, model_tier: str = "cheap", timeout: float = 10.0) -> LLMResult[M]:
        if not self.is_available():
            raise RuntimeError("GEMINI_API_KEY is not set. Gemini provider is unavailable.")

        # google-genai's response_schema= path runs the Pydantic class through
        # its own internal schema conversion, which (as of 2.4.0) raises a
        # client-side "additionalProperties is only supported in Gemini
        # Enterprise Agent Platform mode" ValueError for any model with a
        # public Dict[str, X] field or an `extra=` model_config - an upstream
        # SDK bug (reported, closed "not planned"). response_json_schema=
        # takes the already-generated JSON schema directly and skips that
        # validation gate entirely, so this is immune to it regardless of
        # what fields the Pydantic model gains later.
        config = types.GenerateContentConfig(
            response_mime_type="application/json",
            response_json_schema=response_schema.model_json_schema(),
        )
        if system_instruction:
            config.system_instruction = system_instruction
        config.thinking_config = types.ThinkingConfig(
            thinking_budget=self._THINKING_BUDGET.get(model_tier, 0)
        )

        model = self.models.get(model_tier, self.models["cheap"])
        try:
            response = await asyncio.wait_for(
                self.client.aio.models.generate_content(model=model, contents=prompt, config=config),
                timeout=timeout
            )
        except asyncio.TimeoutError:
            raise RuntimeError(f"Gemini API call timed out after {timeout} seconds due to network congestion or API latency.")
        prompt_tokens, completion_tokens = self._usage(response)
        value = response_schema.model_validate_json(response.text)
        return LLMResult(value=value, prompt_tokens=prompt_tokens, completion_tokens=completion_tokens)

    def embed(
        self,
        text: str,
        task_type: Optional[str] = None,
        output_dimensionality: Optional[int] = None,
    ) -> List[float]:
        if not text or not self.is_available():
            return []
        try:
            config = types.EmbedContentConfig(
                task_type=task_type,
                output_dimensionality=output_dimensionality,
            )
            response = self.client.models.embed_content(model=settings.GEMINI_EMBEDDING_MODEL, contents=text, config=config)
            if response.embeddings:
                return response.embeddings[0].values
            return []
        except Exception as e:
            print(f"\n[Gemini Provider - Error in Embedding] {e}\n")
            return []

    @staticmethod
    def _usage(response) -> tuple[int, int]:
        usage = response.usage_metadata
        if not usage:
            return 0, 0
        return usage.prompt_token_count or 0, usage.candidates_token_count or 0
