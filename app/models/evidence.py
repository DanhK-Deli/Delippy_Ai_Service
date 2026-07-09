from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any

class Evidence(BaseModel):
    products: List[Dict[str, Any]] = Field(default_factory=list)
    faq_answer: Optional[str] = None
    details: Optional[Dict[str, Any]] = None
    comparison_results: List[Dict[str, Any]] = Field(default_factory=list)
    related_products: List[Dict[str, Any]] = Field(default_factory=list)
    not_found: List[str] = Field(default_factory=list)
    error: Optional[str] = None
    # True when the top search result shares less than half its query's
    # meaningful words with the product actually returned (see
    # ranker.top_match_confidence) - a cheap, LLM-free signal that the result
    # is a weak/coincidental keyword hit rather than a real semantic match
    # (e.g. "bánh bao kim cương giá 9 tỷ" only sharing the word "bánh" with
    # whatever cake product got returned). Optional/None (not False) so it's
    # omitted from the LLM evidence payload entirely unless actually true.
    low_confidence: Optional[bool] = None
    # Set by orchestrator (ontology.subcategories_for) when a SEARCH turn's
    # category resolved but every retry/expansion still found nothing -
    # response_formatter renders this into a numbered menu instead of a
    # dead-end message. Orchestrator ALSO persists the same dict (with real
    # subcategory ids) into conversation.memory so a later "chọn số N" can
    # resolve deterministically - see parser.py's ordinal-reference shortcut.
    subcategory_menu: Optional[Dict[str, Any]] = None
