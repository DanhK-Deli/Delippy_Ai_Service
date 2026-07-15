import random
import string
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from app.database.mongodb import get_db


class EscalationAction(str, Enum):
    """What happens when a Knowledge Object's flow can't complete
    automatically - see the approved plan §6. Deterministic mapping below,
    never a per-developer judgment call at the call site."""

    CREATE_TICKET = "CREATE_TICKET"            # default: async human follow-up
    SHOW_HOTLINE = "SHOW_HOTLINE"               # give a phone number immediately (critical priority)
    TRANSFER_LIVE_CHAT = "TRANSFER_LIVE_CHAT"   # hand off to a live-chat queue, if contact.json defines one
    RETRY_LATER = "RETRY_LATER"                 # transient failure - ask to retry, no ticket yet
    ASK_EMAIL_FOLLOWUP = "ASK_EMAIL_FOLLOWUP"   # needs async documentation (e.g. VAT invoice)


def escalation_actions_for(
    ko: Dict[str, Any],
    *,
    transient_error: bool = False,
    retry_already_attempted: bool = False,
) -> List[EscalationAction]:
    """priority=="critical" -> SHOW_HOTLINE + CREATE_TICKET together (matches
    "escalate ngay lập tức, ưu tiên khẩn" wording on those Knowledge Objects);
    CONTACT_WANT_HUMAN -> TRANSFER_LIVE_CHAT (caller falls back to
    CREATE_TICKET itself if contact.json defines no live-chat channel);
    a transient tool-call error -> RETRY_LATER on first occurrence this
    session, CREATE_TICKET if the same Knowledge Object fails again;
    everything else -> CREATE_TICKET."""
    if transient_error:
        return [EscalationAction.CREATE_TICKET] if retry_already_attempted else [EscalationAction.RETRY_LATER]
    priority = (ko or {}).get("priority")
    if priority == "critical":
        return [EscalationAction.SHOW_HOTLINE, EscalationAction.CREATE_TICKET]
    if (ko or {}).get("id") == "CONTACT_WANT_HUMAN":
        return [EscalationAction.TRANSFER_LIVE_CHAT]
    return [EscalationAction.CREATE_TICKET]


def _generate_ticket_id() -> str:
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=4))
    return f"HLP-{datetime.utcnow().strftime('%y%m%d%H%M%S')}-{suffix}"


class HelpTicketRepository:
    """No backend ticket-creation API exists yet (TOOL_CONTACT_TICKET_CREATE
    is MISSING_NEEDS_BUILD in tool.json) - this is the stub the plan calls
    for: writes to a new "help_tickets" Mongo collection (same shared DB, no
    new config - see app/core/database.py) and returns a synthetic id.
    Swapping this for a real backend call later is a one-function change;
    nothing upstream needs to know the difference."""

    def __init__(self, collection_name: str = "help_tickets"):
        self.collection_name = collection_name

    async def create_ticket(
        self,
        *,
        domain: str,
        ko_id: str,
        entities: Dict[str, Any],
        conversation_snippet: List[Dict[str, str]],
        priority: str = "normal",
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> str:
        ticket_id = _generate_ticket_id()
        db = await get_db()
        await db[self.collection_name].insert_one({
            "ticket_id": ticket_id,
            "domain": domain,
            "ko_id": ko_id,
            "entities": entities,
            "conversation_snippet": conversation_snippet,
            "priority": priority,
            "session_id": session_id,
            "user_id": user_id,
            "status": "open",
            "created_at": datetime.utcnow().isoformat(),
        })
        return ticket_id


help_ticket_repo = HelpTicketRepository()
