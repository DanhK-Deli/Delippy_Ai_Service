from __future__ import annotations

from typing import List, Optional, Type

from google import genai
from google.genai import types

from app.core.config import settings
from app.core.llm.base import LLMProvider, LLMResult, M


class GeminiProvider(LLMProvider):
    name = "gemini"

    def __init__(self) -> None:
        self.client = genai.Client(api_key=settings.GEMINI_API_KEY) if settings.GEMINI_API_KEY else None
        self.models = {
            "cheap": settings.GEMINI_MODEL_CHEAP,
            "complex": settings.GEMINI_MODEL_COMPLEX,
        }

    def is_available(self) -> bool:
        return self.client is not None

    async def generate_text(self, prompt: str, system_instruction: Optional[str] = None, model_tier: str = "cheap") -> LLMResult[str]:
        if not self.is_available():
            raise RuntimeError("GEMINI_API_KEY is not set. Gemini provider is unavailable.")

        config = types.GenerateContentConfig()
        if system_instruction:
            config.system_instruction = system_instruction

        model = self.models.get(model_tier, self.models["cheap"])
        response = self.client.models.generate_content(model=model, contents=prompt, config=config)
        prompt_tokens, completion_tokens = self._usage(response)
        return LLMResult(value=response.text or "", prompt_tokens=prompt_tokens, completion_tokens=completion_tokens)

    async def generate_structured(self, prompt: str, response_schema: Type[M], system_instruction: Optional[str] = None, model_tier: str = "cheap") -> LLMResult[M]:
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

        model = self.models.get(model_tier, self.models["cheap"])
        response = self.client.models.generate_content(model=model, contents=prompt, config=config)
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
