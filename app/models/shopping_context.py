from pydantic import BaseModel, Field, PrivateAttr
from typing import Optional, List

class ShoppingContext(BaseModel):
    intent: str = "SEARCH"
    # Only meaningful for GREETING/SOCIAL/CHITCHAT - picks which reply pool
    # in ontology.chitchat_responses to draw from. Set deterministically to
    # "greeting" for GREETING (never reaches the AI parser); for SOCIAL it's
    # "compliment"/"no_intent", for CHITCHAT it's
    # "out_of_scope"/"toxicity"/"help_capabilities" - both from the AI parser
    # (parser_prompt.txt). null for every other intent.
    sub_intent: Optional[str] = None
    category: Optional[str] = None
    # Specific subcategory (e.g. "nạp mực in") the deterministic path
    # resolved from the RAW query text, if any - see ontology.find_category().
    # search_engine.search() falls back to re-resolving this from `category`
    # when it's unset (the AI-parser path never fills it directly), since a
    # deterministic re-resolution from an already-resolved top-level slug
    # (as opposed to the original free-text query) can no longer recover it.
    subcategory: Optional[str] = None
    brand: Optional[str] = None
    price_min: Optional[int] = None
    price_max: Optional[int] = None
    purpose: Optional[str] = None
    compare_targets: List[str] = Field(default_factory=list)
    product: Optional[str] = None
    query_q: Optional[str] = None
    # 2-4 alternative search phrases for query_q (synonyms/related terms) the
    # AI parser can supply for free while it's already running - used as a
    # first retry attempt before search_engine falls back to a dedicated
    # (lazy, zero-result-only) expansion call. See search_engine.search_or_expand.
    expanded_queries: List[str] = Field(default_factory=list)

    # Internal parse-provenance signals (NOT part of the data, NOT sent to /
    # produced by Gemini's structured output - PrivateAttr keeps them out of the
    # response_schema, see gemini_provider.generate_structured). Set by
    # query_parser.parse(): _parse_source is "ai" only when a fresh Gemini parse
    # ran (vs a cache hit / deterministic / reference path), and _ai_parse holds
    # that raw AI interpretation (pre memory-merge) so the orchestrator can write
    # it to the semantic parse cache iff the search then succeeds. See
    # app/database/parse_cache_repository.py.
    _parse_source: Optional[str] = PrivateAttr(default=None)
    _ai_parse: Optional[dict] = PrivateAttr(default=None)
