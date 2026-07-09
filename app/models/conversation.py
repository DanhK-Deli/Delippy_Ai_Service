from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime

class Conversation(BaseModel):
    session_id: str
    user_id: Optional[str] = None
    history: List[Dict[str, str]] = Field(default_factory=list)
    memory: Dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
