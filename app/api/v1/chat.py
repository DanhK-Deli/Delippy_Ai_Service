from typing import Optional
from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

# Local simple models to decouple from old models
class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    session_id: Optional[str] = None
    user_id: Optional[str] = None

class ChatResponse(BaseModel):
    summary: str
    answer: str
    intent: str
    mode: str
    confidence: float
    highlights: list[str] = []
    follow_up_actions: list[dict] = []
    warnings: list[str] = []
    source_list: list[dict] = []
    data: Optional[dict] = None
    response_time_ms: Optional[float] = None
    tokens_used: Optional[int] = None


router = APIRouter(prefix="/api/v1", tags=["Chat"])

@router.post("/chat", response_model=ChatResponse)
async def chat(request: Request, payload: ChatRequest):
    from app.chat.orchestrator import orchestrator
    session_id = payload.session_id or request.headers.get("x-session-id") or payload.user_id or "anonymous"
    response_data = await orchestrator.process_message(
        message=payload.message,
        session_id=session_id,
    )
    return ChatResponse(**response_data)
