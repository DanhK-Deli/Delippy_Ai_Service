from pydantic import BaseModel, Field
from typing import Optional, List, Literal, Dict, Any

class ResponsePlan(BaseModel):
    """Output of ResponsePlanner: WHAT to say and WHAT should happen next,
    never HOW to word it. response_formatter reads this instead of
    re-deriving consultative/is_broad_query/next_action itself - see
    app/chat/response_planner.py for the decision logic this replaces
    (previously scattered across response_formatter.py and orchestrator.py)."""

    type: Literal[
        "SEARCH_RESULT", "ZERO_RESULT", "CONSULT", "COMPARE",
        "DETAIL", "DETAIL_FOCUS", "FAQ", "CLARIFICATION", "FOLLOWUP",
    ] = "SEARCH_RESULT"
    # Mirrors the old conversation.memory["awaiting"]["action"] values
    # (SELECT_PRODUCT / SEARCH / PRODUCT_INFO / COMPARE) - see
    # orchestrator.py's pending-action block, now sourced from here instead
    # of being recomputed inline.
    next_action: Optional[str] = None
    show_products: int = 0
    show_menu: bool = False
    consultative: bool = False
    is_broad_query: bool = False
    # Symbolic tags (e.g. "out_of_stock", "low_confidence"), not rendered
    # Vietnamese text - formatter maps each tag to its sentence.
    warnings: List[str] = Field(default_factory=list)
    # Whatever `next_action` needs to resume deterministically later (e.g.
    # {"product": {"name","slug"}, "candidate": {"name","slug"}} for a
    # PRODUCT_INFO->COMPARE suggestion) - persisted into
    # conversation.memory["awaiting"]["target"] by orchestrator.py, read back
    # by memory_resolver.resolve_followup()'s caller. None when next_action
    # has nothing more specific to resume than its bare label.
    target: Optional[Dict[str, Any]] = None
    # Short debug label for why `next_action`/`target` were chosen (e.g.
    # "related_product") - not shown to the user, just makes a later
    # `awaiting` dump readable without re-deriving the reasoning.
    reason: Optional[str] = None
    # Only set when type == "DETAIL_FOCUS" - which narrow field(s) the user
    # actually asked about (see intent_classifier.classify_product_focus).
    # Kept separate from `target` (which persists into
    # conversation.memory["awaiting"] for a later follow-up to resolve
    # against) since this is purely a rendering instruction for THIS turn.
    product_focus: Optional[Dict[str, bool]] = None
