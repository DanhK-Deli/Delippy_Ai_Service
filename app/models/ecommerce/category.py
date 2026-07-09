from typing import Optional

from pydantic import BaseModel, Field

from .common import PaginationMeta
from .product import ProductCard


class CategoryChild(BaseModel):
    id: int
    name: str
    slug: str


class CategorySubcategory(BaseModel):
    id: int
    name: str
    slug: str
    children: list[CategoryChild] = Field(default_factory=list)


class CategoryNode(BaseModel):
    id: int
    name: str
    slug: str
    icon_url: Optional[str] = None
    is_featured: Optional[bool] = None
    subcategories: list[CategorySubcategory] = Field(default_factory=list)


class CategoryListResponse(BaseModel):
    success: bool = True
    code: int = 1000
    data: list[CategoryNode] = Field(default_factory=list)


class CategoryDetailResponse(BaseModel):
    success: bool = True
    code: int = 1000
    data: CategoryNode


class CategoryProductsResponse(BaseModel):
    success: bool = True
    code: int = 1000
    data: list[ProductCard] = Field(default_factory=list)
    meta: Optional[PaginationMeta] = None
