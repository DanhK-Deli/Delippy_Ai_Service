from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional

# Same 10-minute TTL convention as /chat's GAP_FILL (app/chat/orchestrator.py).
AWAITING_TTL_MINUTES = 10


class HelpAwaitAction(str, Enum):
    """Every multi-turn "still waiting on something" state the /help flow
    executor can be in - explicit states instead of an untyped dict with
    ad hoc keys, so adding a new one is "add an enum value + one resume
    handler in rule_engine.py", not "invent another string somewhere"."""

    AWAITING_ENTITY = "AWAITING_ENTITY"                # one specific required_entity value (order id, phone...)
    AWAITING_CONFIRMATION = "AWAITING_CONFIRMATION"     # yes/no before a mutating action (order cancel)
    AWAITING_EVIDENCE = "AWAITING_EVIDENCE"             # image/video attachment (return/refund flows)
    AWAITING_CLARIFICATION = "AWAITING_CLARIFICATION"   # user was shown a tied-candidate menu, picking one


def make_awaiting(
    state: HelpAwaitAction,
    ko_id: str,
    *,
    pending_entity: Optional[str] = None,
    pending_options: Optional[List[str]] = None,
    collected_entities: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Builds the memory["awaiting"] dict (see app/help/state.py's module
    docstring / the approved plan §2). Own key, never shared with /chat's
    own `memory` - kept in a separate Mongo collection too (session.py)."""
    now = datetime.utcnow()
    return {
        "state": state.value,
        "ko_id": ko_id,
        "pending_entity": pending_entity,
        "pending_options": pending_options,
        "collected_entities": collected_entities or {},
        "created_at": now.isoformat(),
        "expires_at": (now + timedelta(minutes=AWAITING_TTL_MINUTES)).isoformat(),
    }


def get_active_awaiting(memory: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The current memory["awaiting"] dict if present and not expired, else
    None (silently expired - same behavior as /chat's own GAP_FILL check)."""
    awaiting = memory.get("awaiting")
    if not awaiting:
        return None
    expires_at = awaiting.get("expires_at")
    if expires_at:
        try:
            if datetime.fromisoformat(expires_at) < datetime.utcnow():
                return None
        except ValueError:
            return None
    return awaiting


def clear_awaiting(memory: Dict[str, Any]) -> None:
    memory.pop("awaiting", None)
