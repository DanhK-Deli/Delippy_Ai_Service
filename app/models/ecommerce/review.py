from typing import Optional

from pydantic import BaseModel, Field

from .common import PaginationMeta


class ReviewUser(BaseModel):
    id: int
    name: str
    photo: Optional[str] = None


class ReviewProductBrief(BaseModel):
    id: int
    name: str
    slug: str
    photo: Optional[str] = None


class ReviewItem(BaseModel):
    id: int
    rating: int
    review: Optional[str] = None
    photo: Optional[str] = None
    review_date: Optional[str] = None
    user: ReviewUser
    product: Optional[ReviewProductBrief] = None


class ReviewSummary(BaseModel):
    average_rating: float = 0
    total_reviews: int = 0
    rating_distribution: dict[str, int] = Field(default_factory=dict)


class ReviewCreateRequest(BaseModel):
    rating: int = Field(ge=1, le=5)
    review: Optional[str] = Field(default=None, max_length=1000)


class ReviewListResponse(BaseModel):
    success: bool = True
    code: int = 1000
    message: Optional[str] = None
    data: list[ReviewItem] = Field(default_factory=list)
    meta: Optional[PaginationMeta] = None


class ReviewSummaryResponse(BaseModel):
    success: bool = True
    code: int = 1000
    message: Optional[str] = None
    data: ReviewSummary
