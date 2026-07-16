from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional

# Same 10-minute TTL convention as /chat's GAP_FILL (app/chat/orchestrator.py)
# and v1's own AWAITING_TTL_MINUTES - only the transient "pending" sub-state
# expires; active_business_object/case are sticky across turns until the
# customer's own message points at a different object (see reset_if_switched).
PENDING_TTL_MINUTES = 10


class ConversationState(str, Enum):
    """The Business Conversation State layer agreed on top of the Case ->
    Business Object -> Document pipeline: LLM #1 only understands intent, it
    never decides confirmation/slot-filling/case-switch logic itself. Every
    multi-turn "still waiting on something" situation is one of these named
    states instead of an untyped dict with ad hoc keys.

    CLARIFYING/COLLECTING_ENTITY/AWAITING_CONFIRMATION/AWAITING_EVIDENCE are
    transient "pending" states (see make_pending/get_active_pending) - they
    expire and clear on their own. ACTIVE_CASE is not a pending state; it is
    the absence of any pending sub-state while a case/active_business_object
    is still set (used for observability/logging, e.g. what the orchestrator
    reports as the outgoing state after a turn resolves cleanly)."""

    CLARIFYING = "CLARIFYING"
    COLLECTING_ENTITY = "COLLECTING_ENTITY"
    AWAITING_CONFIRMATION = "AWAITING_CONFIRMATION"
    AWAITING_EVIDENCE = "AWAITING_EVIDENCE"
    ACTIVE_CASE = "ACTIVE_CASE"


_STATE_KEY = "conversation_state"


LAST_RESOLVED_TTL_MINUTES = 10


def _empty_state() -> Dict[str, Any]:
    return {
        "case": None,
        "business_object_id": None,
        "active_business_object": None,  # {"type": "order", "id": "DEL123456"} - sticky UI/chat-selected context (plan §8/§9)
        "pending": None,
        "last_resolved": None,  # {"business_object_ids": [...], "entities": {...}, "expires_at": ...}
    }


def get_conversation_state(memory: Dict[str, Any]) -> Dict[str, Any]:
    """Always returns a dict (creating + attaching an empty one to `memory`
    on first use) so every caller can read/write its keys directly instead of
    guarding against a missing top-level key everywhere."""
    state = memory.get(_STATE_KEY)
    if not isinstance(state, dict):
        state = _empty_state()
        memory[_STATE_KEY] = state
    return state


def make_pending(
    state: ConversationState,
    *,
    pending_entity: Optional[str] = None,
    pending_options: Optional[List[str]] = None,
    collected_entities: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    now = datetime.utcnow()
    return {
        "state": state.value,
        "pending_entity": pending_entity,
        "pending_options": pending_options,
        "collected_entities": collected_entities or {},
        "created_at": now.isoformat(),
        "expires_at": (now + timedelta(minutes=PENDING_TTL_MINUTES)).isoformat(),
    }


def get_active_pending(memory: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The current pending sub-state if present and not expired, else None
    (silently expired - same behavior as v1's get_active_awaiting)."""
    pending = get_conversation_state(memory).get("pending")
    if not pending:
        return None
    expires_at = pending.get("expires_at")
    if expires_at:
        try:
            if datetime.fromisoformat(expires_at) < datetime.utcnow():
                return None
        except ValueError:
            return None
    return pending


def set_pending(memory: Dict[str, Any], pending: Optional[Dict[str, Any]]) -> None:
    get_conversation_state(memory)["pending"] = pending


def clear_pending(memory: Dict[str, Any]) -> None:
    get_conversation_state(memory)["pending"] = None


def set_active_case(
    memory: Dict[str, Any],
    *,
    case: str,
    business_object_id: str,
    active_business_object: Optional[Dict[str, str]] = None,
) -> None:
    """Marks a case as the sticky context for follow-up turns (ACTIVE_CASE).
    Only call this once a turn has actually resolved (business object
    executed, response rendered) - not while still CLARIFYING/collecting
    entities for it."""
    state = get_conversation_state(memory)
    state["case"] = case
    state["business_object_id"] = business_object_id
    if active_business_object is not None:
        state["active_business_object"] = active_business_object


def reset_if_switched(memory: Dict[str, Any], new_active_business_object: Optional[Dict[str, str]]) -> bool:
    """Anti-leak guard (the exact bug class this layer exists to prevent -
    see project memory on stale consultation-level/subcategory context
    bleeding into later turns): if this turn's message resolves to a
    DIFFERENT concrete business object (e.g. a different order_id) than the
    one currently active, wipe collected_entities/pending/case BEFORE the new
    turn's data is written in - never merge old collected state into a new
    object's context. Returns True if a switch (and reset) happened."""
    if not new_active_business_object:
        return False
    state = get_conversation_state(memory)
    current = state.get("active_business_object")
    if current and (current.get("type"), current.get("id")) != (
        new_active_business_object.get("type"), new_active_business_object.get("id")
    ):
        memory[_STATE_KEY] = _empty_state()
        get_conversation_state(memory)["active_business_object"] = new_active_business_object
        return True
    return False


def set_last_resolved(memory: Dict[str, Any], business_object_ids: List[str], entities: Dict[str, Any]) -> None:
    """Remembers the full entity bundle of a just-completed flow (ticket
    created / Step 3 answered) for a short window - NOT the same thing as
    active_business_object (which only tracks the order id). Fixes a real
    gap: a customer correcting themselves right after submitting a return
    request ("tôi nói lộn vì đưa sai hàng") was being asked for the product
    all over again, because once a flow finished its collected_entities were
    discarded entirely and the next turn started from zero. This lets the
    orchestrator backfill still-missing entities from the just-completed
    attempt when the SAME business object comes up again immediately after."""
    now = datetime.utcnow()
    get_conversation_state(memory)["last_resolved"] = {
        "business_object_ids": sorted(business_object_ids),
        "entities": {k: v for k, v in entities.items() if not k.startswith("_")},
        "expires_at": (now + timedelta(minutes=LAST_RESOLVED_TTL_MINUTES)).isoformat(),
    }


def get_last_resolved(memory: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    last = get_conversation_state(memory).get("last_resolved")
    if not last:
        return None
    expires_at = last.get("expires_at")
    if expires_at:
        try:
            if datetime.fromisoformat(expires_at) < datetime.utcnow():
                return None
        except ValueError:
            return None
    return last


def clear_all(memory: Dict[str, Any]) -> None:
    memory[_STATE_KEY] = _empty_state()
