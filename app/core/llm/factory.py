from __future__ import annotations

import os
from typing import Callable, Dict

from app.core.config import settings
from app.core.llm.base import LLMProvider
from app.core.llm.claude_provider import ClaudeProvider
from app.core.llm.gemini_provider import GeminiProvider
from app.core.llm.generic_openai_compatible import GenericOpenAICompatibleProvider
from app.core.llm.openai_provider import OpenAIProvider

# Providers with a bespoke SDK/wire protocol. Anything else falls back to
# _build_generic_openai_compatible below - no code change needed for a new
# provider as long as it speaks the OpenAI chat-completions format.
_BUILDERS: Dict[str, Callable[[], LLMProvider]] = {
    "gemini": GeminiProvider,
    "openai": OpenAIProvider,
    "claude": ClaudeProvider,
}

_cache: Dict[str, LLMProvider] = {}


def _build_generic_openai_compatible(name: str) -> LLMProvider:
    prefix = name.upper()
    base_url = os.getenv(f"{prefix}_BASE_URL")
    if not base_url:
        raise ValueError(
            f"AI_PROVIDER='{name}' is not a built-in provider (gemini/openai/claude). "
            f"For any OpenAI-wire-compatible backend (DeepSeek, Groq, Mistral, a self-trained "
            f"model served via vLLM/Ollama/TGI, ...) just set {prefix}_BASE_URL "
            f"(+ {prefix}_API_KEY, {prefix}_MODEL_CHEAP, {prefix}_MODEL_COMPLEX, optionally "
            f"{prefix}_EMBEDDING_MODEL) - no code change needed. "
            f"For a backend with a different wire protocol, add a new LLMProvider subclass "
            f"under app/core/llm/ and register it in _BUILDERS above."
        )
    api_key = os.getenv(f"{prefix}_API_KEY")
    model_cheap = os.getenv(f"{prefix}_MODEL_CHEAP", os.getenv(f"{prefix}_MODEL", name))
    model_complex = os.getenv(f"{prefix}_MODEL_COMPLEX", model_cheap)
    embedding_model = os.getenv(f"{prefix}_EMBEDDING_MODEL")
    return GenericOpenAICompatibleProvider(
        name=name,
        api_key=api_key,
        base_url=base_url,
        model_cheap=model_cheap,
        model_complex=model_complex,
        embedding_model=embedding_model,
    )


def get_llm_provider(provider_name: str = None) -> LLMProvider:
    name = (provider_name or settings.AI_PROVIDER).strip().lower()
    if name not in _cache:
        builder = _BUILDERS.get(name)
        _cache[name] = builder() if builder else _build_generic_openai_compatible(name)
    return _cache[name]
