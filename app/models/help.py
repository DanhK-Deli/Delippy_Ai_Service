from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class HelpRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    session_id: Optional[str] = None
    user_id: Optional[str] = None


class HelpResponse(BaseModel):
    answer: str
    intent: Optional[str] = None
    domain: Optional[str] = None
    mode: str = "rule"  # "rule" | "llm_fallback" | "ask_clarification" | "unresolved"
    confidence: Optional[float] = None
    escalated: bool = False
    ticket_id: Optional[str] = None
    follow_up_questions: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    data: Optional[Dict[str, Any]] = None
    response_time_ms: Optional[float] = None
    tokens_used: Optional[int] = None

