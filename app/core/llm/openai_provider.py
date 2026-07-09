from __future__ import annotations

from typing import List, Optional

from app.core.config import settings
from app.core.llm.openai_compatible import OpenAICompatibleProvider


class OpenAIProvider(OpenAICompatibleProvider):
    name = "openai"

    def __init__(self) -> None:
        super().__init__(
            api_key=settings.OPENAI_API_KEY,
            model_cheap=settings.OPENAI_MODEL_CHEAP,
            model_complex=settings.OPENAI_MODEL_COMPLEX,
        )

    def embed(
        self,
        text: str,
        task_type: Optional[str] = None,
        output_dimensionality: Optional[int] = None,
    ) -> List[float]:
        # OpenAI has no task_type/asymmetric-retrieval concept - only the
        # "dimensions" truncation param, a partial equivalent of Gemini's
        # output_dimensionality (text-embedding-3-* models only).
        if not text or not self.is_available():
            return []
        try:
            kwargs = {"model": settings.OPENAI_EMBEDDING_MODEL, "input": text}
            if output_dimensionality:
                kwargs["dimensions"] = output_dimensionality
            response = self.client.embeddings.create(**kwargs)
            return response.data[0].embedding if response.data else []
        except Exception as e:
            print(f"\n[OpenAI Provider - Error in Embedding] {e}\n")
            return []
