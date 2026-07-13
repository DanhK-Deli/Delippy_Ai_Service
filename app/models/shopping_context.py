from pydantic import BaseModel, Field, PrivateAttr
from typing import Literal, Optional, List, Dict

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
    # Only meaningful when intent is SEARCH (null otherwise) - how much
    # guidance this ask needs, replacing a binary SEARCH-vs-ADVISORY
    # classification decided too early from one message alone:
    # "none" (a specific product/brand/model - a plain lookup), "assist" (a
    # general product/brand ask - search normally, but nudge toward asking
    # for budget/purpose), "expert" (explicitly asked to be advised/compared -
    # needs a reasoned, explanatory answer, not just a list). See
    # parser_prompt.txt and response_formatter.py's needs_consultation.
    consultation_level: Optional[Literal["none", "assist", "expert"]] = None
    # 2-4 alternative search phrases for query_q (synonyms/related terms) the
    # AI parser can supply for free while it's already running - used as a
    # first retry attempt before search_engine falls back to a dedicated
    # (lazy, zero-result-only) expansion call. See search_engine.search_or_expand.
    expanded_queries: List[str] = Field(default_factory=list)
    # This turn's freeform Consultation Flow requirement answers (e.g.
    # {"family_size": "4 người"}) for attributes with no dedicated structured
    # field of their own - "budget"/"purpose" still resolve to price_min/
    # price_max/purpose above; everything else (family_size, camera_need,
    # occasion...) lives here instead. Set by orchestrator's
    # _resolve_gap_fill_answer(); read by response_formatter to surface into
    # the LLM's user_need payload. See app/knowledge/requirement_schema.json.
    _requirement_answers: Dict[str, str] = PrivateAttr(default_factory=dict)

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
    # Set by memory_resolver.resolve() when this turn is a bare confirm
    # ("có"/"ok"/"ừ"...) answering a still-live pending question
    # (memory["awaiting"]) that the Parser had no way to interpret and
    # defaulted to SOCIAL/CHITCHAT (see parser_prompt.txt's "ok" example).
    # Tells the orchestrator/response_formatter to treat this turn as an
    # advisory continuation of the cached context instead of either the
    # Parser's wrong guess or a fresh, contextless search.
    _force_advisory: bool = PrivateAttr(default=False)
