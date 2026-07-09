from app.core.llm.base import LLMProvider, LLMResult
from app.core.llm.factory import get_llm_provider

llm_provider = get_llm_provider()

__all__ = ["LLMProvider", "LLMResult", "get_llm_provider", "llm_provider"]
