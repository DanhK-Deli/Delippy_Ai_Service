from pydantic import BaseModel, Field
from typing import Optional, List

class ShoppingContext(BaseModel):
    intent: str = "SEARCH"
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
