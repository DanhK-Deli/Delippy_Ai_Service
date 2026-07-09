from __future__ import annotations

from typing import List, Optional

from app.core.llm.openai_compatible import OpenAICompatibleProvider


class GenericOpenAICompatibleProvider(OpenAICompatibleProvider):
    """Any provider that speaks the OpenAI chat-completions wire format but
    isn't one of the built-ins (Gemini/OpenAI/Claude). Fully driven by env
    vars via factory.py's naming convention - this is what lets someone add
    a brand new provider (DeepSeek, Groq, Mistral, a self-trained model
    served through vLLM/Ollama/TGI, ...) without writing any code, as long
    as it's OpenAI-wire-compatible. A backend with a genuinely different
    wire protocol still needs its own LLMProvider subclass."""

    def __init__(self, name: str, api_key: Optional[str], base_url: str, model_cheap: str, model_complex: str, embedding_model: Optional[str] = None) -> None:
        super().__init__(api_key=api_key, model_cheap=model_cheap, model_complex=model_complex, base_url=base_url)
        self.name = name
        self.embedding_model = embedding_model

    def embed(
        self,
        text: str,
        task_type: Optional[str] = None,
        output_dimensionality: Optional[int] = None,
    ) -> List[float]:
        if not text or not self.is_available() or not self.embedding_model:
            return []
        try:
            kwargs = {"model": self.embedding_model, "input": text}
            if output_dimensionality:
                kwargs["dimensions"] = output_dimensionality
            response = self.client.embeddings.create(**kwargs)
            return response.data[0].embedding if response.data else []
        except Exception as e:
            print(f"\n[{self.name} Provider - Error in Embedding] {e}\n")
            return []
