from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class HelpRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    session_id: Optional[str] = None
    user_id: Optional[str] = None
    # Plan §8 - the client UI lets the customer pick an existing order
    # directly instead of typing/pasting an order code; when present this
    # becomes the turn's sticky active_business_object (see
    # app/help/conversation_state.py), skipping order-code extraction
    # entirely for this turn.
    selected_order_id: Optional[str] = None


class HelpResponse(BaseModel):
    answer: str
    case: Optional[str] = None  # GENERAL | ORDER | PROMOTION | ACCOUNT | APP_ISSUE | OUT_OF_SCOPE
    intent: Optional[str] = None
    domain: Optional[str] = None
    mode: str = "rule"  # "fast_path" | "ask_order_topic" | "resumed" | "understood" | "ask_clarification" | "ask_entity" | "ask_confirmation" | "cancelled" | "unauthenticated" | "retry_later" | "escalated" | "grounding_failed" | "resolved" | "out_of_scope"
    confidence: Optional[float] = None
    escalated: bool = False
    ticket_id: Optional[str] = None
    follow_up_questions: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    data: Optional[Dict[str, Any]] = None
    # Debug/observability metrics - populated by process_help_message(), not
    # required for the chatbot to function. response_time_ms covers the
    # whole request (Step 1 + Step 2 backend calls + Step 3 + persistence);
    # tokens_used is LLM tokens only (0 on the fast-path, which never calls
    # an LLM at all).
    response_time_ms: Optional[float] = None
    tokens_used: Optional[int] = None
