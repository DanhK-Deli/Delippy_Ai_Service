from typing import Optional, Union

from pydantic import BaseModel, Field

from .common import PaginationMeta


class ProductSearchRequest(BaseModel):
    q: Optional[str] = Field(default=None, min_length=2, max_length=100)
    keyword: Optional[str] = None
    category_id: Optional[int] = None
    subcategory_id: Optional[int] = None
    childcategory_id: Optional[int] = None
    brand: Optional[str] = None
    price_min: Optional[int] = None
    price_max: Optional[int] = None
    sort: str = "newest"
    page: Optional[int] = 1
    per_page: Optional[int] = 15
    cursor: Optional[str] = None


class ProductCard(BaseModel):
    id: int
    name: str
    slug: str
    thumbnail: Optional[str] = None
    price: Optional[float] = None
    original_price: Optional[float] = None
    discount_percent: Optional[int] = None
    badges: list[Union[str, dict]] = Field(default_factory=list)
    rating: Optional[float] = None
    ratings_count: Optional[int] = None
    sold_count: Optional[int] = None
    point: Optional[int] = None


class ProductCategory(BaseModel):
    id: Optional[int] = None
    name: Optional[str] = None
    slug: Optional[str] = None


class ProductSeller(BaseModel):
    id: Optional[int] = None
    shop_name: Optional[str] = None
    photo: Optional[str] = None
    shop_image: Optional[str] = None
    total_products: Optional[int] = None


class ProductOptionValue(BaseModel):
    label: str
    price_extra: float = 0


class ProductCustomOption(BaseModel):
    key: str
    values: list[ProductOptionValue] = Field(default_factory=list)


class ProductDetail(BaseModel):
    id: int
    name: str
    slug: str
    sku: Optional[str] = None
    photo: Optional[str] = None
    thumbnail: Optional[str] = None
    price: Optional[float] = None
    original_price: Optional[float] = None
    discount_percent: Optional[int] = None
    stock: Optional[int] = None
    weight: Optional[Union[str, float, int]] = None
    details: Optional[str] = None
    badges: list[Union[str, dict]] = Field(default_factory=list)
    variant_colors: list[str] = Field(default_factory=list)
    sizes: list[dict] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    rating: Optional[float] = None
    ratings_count: Optional[int] = None
    sold_count: Optional[int] = None
    point: Optional[int] = None
    is_tax_inclusive: Optional[bool] = None
    tax_rate: Optional[float] = None
    category: Optional[ProductCategory] = None
    seller: Optional[ProductSeller] = None
    custom_options: list[ProductCustomOption] = Field(default_factory=list)
    galleries: list[Optional[str]] = Field(default_factory=list)


class ProductSearchResponse(BaseModel):
    success: bool = True
    code: int = 1000
    data: list[ProductCard] = Field(default_factory=list)
    meta: Optional[PaginationMeta] = None


class ProductDetailResponse(BaseModel):
    success: bool = True
    code: int = 1000
    data: ProductDetail
