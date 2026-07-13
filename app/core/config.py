import os

class Settings:
    AI_PROVIDER: str = os.getenv("AI_PROVIDER", "gemini").strip().lower()

    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY")
    GEMINI_MODEL_CHEAP: str = os.getenv("GEMINI_MODEL_CHEAP", os.getenv("GEMINI_ARTICLE_MODEL", "gemini-2.5-flash"))
    GEMINI_MODEL_COMPLEX: str = os.getenv("GEMINI_MODEL_COMPLEX", os.getenv("GEMINI_ANALYSIS_MODEL", "gemini-2.5-flash"))
    GEMINI_EMBEDDING_MODEL: str = os.getenv("GEMINI_EMBEDDING_MODEL", "models/gemini-embedding-2")
    # Pinned output size for PRODUCT vectors (product_embeddings collection)
    # and the Atlas Search index built on it - the model's raw default is
    # 3072-dim (verified empirically), but Atlas index numDimensions must
    # match exactly whatever we actually store, so this must never change
    # without re-syncing every embedding + recreating the index. 1536 keeps
    # storage/query cost down while still Matryoshka-normalized (confirmed
    # L2 norm ~1.0) for cosine similarity.
    EMBEDDING_DIMENSION: int = int(os.getenv("EMBEDDING_DIMENSION", "768"))

    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY")
    OPENAI_MODEL_CHEAP: str = os.getenv("OPENAI_MODEL_CHEAP", "gpt-4o-mini")
    OPENAI_MODEL_COMPLEX: str = os.getenv("OPENAI_MODEL_COMPLEX", "gpt-4o")
    OPENAI_EMBEDDING_MODEL: str = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")

    # DeepSeek and any other OpenAI-wire-compatible provider (Groq, Mistral,
    # a self-trained model served via vLLM/Ollama/TGI, ...) are NOT declared
    # here - app/core/llm/factory.py builds them straight from
    # <PROVIDER>_API_KEY / <PROVIDER>_BASE_URL / <PROVIDER>_MODEL_CHEAP /
    # <PROVIDER>_MODEL_COMPLEX env vars, so adding one is config-only.

    ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY")
    CLAUDE_MODEL_CHEAP: str = os.getenv("CLAUDE_MODEL_CHEAP", "claude-haiku-4-5")
    CLAUDE_MODEL_COMPLEX: str = os.getenv("CLAUDE_MODEL_COMPLEX", "claude-sonnet-5")

    MONGO_URI: str = os.getenv("MONGO_CORE_URI") or os.getenv("MONGO_URI", "")
    MONGO_DB_NAME: str = os.getenv("MONGO_DB_NAME", "delippy_ai")
    DELIPPY_API_BASE_URL: str = os.getenv("DELIPPY_API_BASE_URL", "https://dev.delippy.com/api/v1")
    DELIPPY_API_TIMEOUT: float = float(os.getenv("DELIPPY_API_TIMEOUT", "8"))

    # "legacy" (category+keyword via /products/search, unchanged behavior) |
    # "vector" (Atlas $vectorSearch on product_embeddings, requires
    # sync_products() + the index to have been run first) | "shadow" (serves
    # legacy results but also runs the vector path and logs both for
    # comparison) | "hybrid" (default - routes each query to vector-first or
    # legacy-first based on intent, cross-falls-back to the other path on a
    # zero-result miss). See app/retrieval/search_engine.py.
    #
    # Was briefly reverted to "legacy" (2026-07-10) after diagnosing that
    # gemini-embedding-2 embeds a brand name or a number+unit spec ("Toshiba",
    # "10,5Kg") appended to a short product-type phrase by collapsing
    # similarity ~25-30 points each (task_type has no effect - separately
    # confirmed via raw REST, not the actual cause) - every real product name
    # has both, so candidate scores clustered too tightly to discriminate.
    # Fixed by stripping detected brand + spec/unit tokens before embedding
    # (see sync_products.py's _strip_brand/_strip_specs) and no longer
    # folding context.brand into the vector query text (search_engine.py's
    # _search_vector) - re-verified after a full catalog re-sync: the real
    # match now ranks #1 with a real margin instead of being outscored by
    # unrelated noise. Restored to "hybrid" as default.
    RETRIEVAL_MODE: str = os.getenv("RETRIEVAL_MODE", "hybrid").strip().lower()

settings = Settings()
