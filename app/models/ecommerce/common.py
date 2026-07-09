from typing import Any, Optional

from pydantic import BaseModel, Field


class ApiResponse(BaseModel):
    success: bool = True
    code: int = 1000
    message: Optional[str] = None


class ErrorResponse(BaseModel):
    success: bool = False
    code: int = 3000
    message: str


class PaginationMeta(BaseModel):
    current_page: Optional[int] = None
    last_page: Optional[int] = None
    per_page: Optional[int] = None
    total: Optional[int] = None
    from_item: Optional[int] = Field(default=None, alias="from")
    to_item: Optional[int] = Field(default=None, alias="to")
    next_cursor: Optional[str] = None
    has_more: Optional[bool] = None


class SourceReference(BaseModel):
    name: str
    type: str = "api"
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    metadata: dict[str, Any] = Field(default_factory=dict)
