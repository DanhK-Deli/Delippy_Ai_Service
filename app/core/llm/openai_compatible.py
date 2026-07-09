from __future__ import annotations

import json
from typing import List, Optional, Type

from app.core.llm.base import LLMProvider, LLMResult, M


class OpenAICompatibleProvider(LLMProvider):
    """Shared implementation for any provider that speaks the OpenAI chat
    completions wire format (OpenAI itself, DeepSeek, ...). Subclasses only
    need to supply api_key / base_url / model names - structured output is
    emulated everywhere via response_format=json_object since DeepSeek does
    not support OpenAI's stricter json_schema mode."""

    def __init__(self, api_key: Optional[str], model_cheap: str, model_complex: str, base_url: Optional[str] = None) -> None:
        self.client = None
        if api_key:
            from openai import OpenAI
            # Sync client, same as GeminiProvider's sync google-genai client -
            # generate_text/generate_structured stay `async def` for interface
            # consistency but wrap a blocking SDK call, matching the existing
            # Gemini provider pattern rather than introducing a second style.
            self.client = OpenAI(api_key=api_key, base_url=base_url)
        self.models = {"cheap": model_cheap, "complex": model_complex}

    def is_available(self) -> bool:
        return self.client is not None

    def _unavailable_error(self) -> RuntimeError:
        return RuntimeError(f"{self.name} API key is not set. {self.name} provider is unavailable.")

    async def generate_text(self, prompt: str, system_instruction: Optional[str] = None, model_tier: str = "cheap") -> LLMResult[str]:
        if not self.is_available():
            raise self._unavailable_error()

        messages = []
        if system_instruction:
            messages.append({"role": "system", "content": system_instruction})
        messages.append({"role": "user", "content": prompt})

        model = self.models.get(model_tier, self.models["cheap"])
        response = self.client.chat.completions.create(model=model, messages=messages)
        prompt_tokens, completion_tokens = self._usage(response)
        return LLMResult(value=response.choices[0].message.content or "", prompt_tokens=prompt_tokens, completion_tokens=completion_tokens)

    async def generate_structured(self, prompt: str, response_schema: Type[M], system_instruction: Optional[str] = None, model_tier: str = "cheap") -> LLMResult[M]:
        if not self.is_available():
            raise self._unavailable_error()

        schema_json = json.dumps(response_schema.model_json_schema(), ensure_ascii=False)
        system_text = (
            (system_instruction + "\n\n" if system_instruction else "")
            + "You must respond with ONLY a single valid JSON object matching this JSON schema. "
            + "No markdown, no code fences, no explanation.\nSchema:\n" + schema_json
        )
        messages = [
            {"role": "system", "content": system_text},
            {"role": "user", "content": prompt},
        ]

        model = self.models.get(model_tier, self.models["cheap"])
        response = self.client.chat.completions.create(
            model=model,
            messages=messages,
            response_format={"type": "json_object"},
        )
        prompt_tokens, completion_tokens = self._usage(response)
        value = response_schema.model_validate_json(response.choices[0].message.content)
        return LLMResult(value=value, prompt_tokens=prompt_tokens, completion_tokens=completion_tokens)

    def embed(
        self,
        text: str,
        task_type: Optional[str] = None,
        output_dimensionality: Optional[int] = None,
    ) -> List[float]:
        return []

    @staticmethod
    def _usage(response) -> tuple[int, int]:
        usage = response.usage
        if not usage:
            return 0, 0
        return usage.prompt_tokens or 0, usage.completion_tokens or 0
