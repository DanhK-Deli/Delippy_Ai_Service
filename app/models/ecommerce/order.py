from typing import Optional

from pydantic import BaseModel, Field

from .common import PaginationMeta


class ShippingMethod(BaseModel):
    key: str
    label: str
    description: Optional[str] = None
    estimated_days: Optional[int] = None
    is_active: bool = True


class ShippingMethodsResponse(BaseModel):
    success: bool = True
    code: int = 1000
    data: list[ShippingMethod] = Field(default_factory=list)


class PaymentMethod(BaseModel):
    key: str
    label: str
    description: Optional[str] = None
    is_active: bool = True


class PaymentMethodsResponse(BaseModel):
    success: bool = True
    code: int = 1000
    data: list[PaymentMethod] = Field(default_factory=list)


class ShippingFeeRequest(BaseModel):
    shipping_type: str
    province_id: int
    district_id: int


class ShippingFeeResponse(BaseModel):
    success: bool = True
    code: int = 1000
    data: dict[str, float] = Field(default_factory=dict)


class OrderPreviewRequest(BaseModel):
    shipping_type: str
    province_id: int
    district_id: int
    payment_method: Optional[str] = None
    coupon_code: Optional[str] = None
    vendor_coupon_codes: Optional[dict[str, str]] = None
    shopping_points: Optional[dict[str, int]] = None


class OrderPreviewResponse(BaseModel):
    success: bool = True
    code: int = 1000
    data: dict[str, dict[str, float]] = Field(default_factory=dict)


class OrderCustomer(BaseModel):
    name: str
    phone: str
    email: Optional[str] = None
    address: str
    province_id: int
    district_id: int
    ward_id: int


class OrderItem(BaseModel):
    product_id: int
    product_name: str
    thumbnail: Optional[str] = None
    qty: int
    unit_price: float
    line_total: float
    size: Optional[str] = None
    color: Optional[str] = None
    custom_option_key: Optional[list[str]] = None
    custom_option_value: Optional[list[str]] = None
    has_reviewed: Optional[bool] = None


class OrderTrack(BaseModel):
    title: str
    text: str
    created_at: str


class OrderAmounts(BaseModel):
    products: float = 0
    shipping_fee: float = 0
    coupon_discount: float = 0
    vendor_discount: float = 0
    sp_amount: float = 0
    tax_amount: float = 0
    total: float = 0


class OrderPayment(BaseModel):
    method: Optional[str] = None
    provider: Optional[str] = None
    status: Optional[str] = None
    qr_code_url: Optional[str] = None
    qr_content: Optional[str] = None
    amount: Optional[float] = None
    expired_at: Optional[str] = None


class OrderDetail(BaseModel):
    order_number: str
    status: str
    status_label: Optional[str] = None
    payment_status: Optional[str] = None
    payment_method: Optional[str] = None
    payment: Optional[OrderPayment] = None
    shipping_type: Optional[str] = None
    amounts: OrderAmounts
    customer: Optional[OrderCustomer] = None
    shipping_address: Optional[OrderCustomer] = None
    order_note: Optional[str] = None
    coupon_code: Optional[str] = None
    items: list[OrderItem] = Field(default_factory=list)
    tracks: list[OrderTrack] = Field(default_factory=list)
    created_at: Optional[str] = None


class OrderDetailResponse(BaseModel):
    success: bool = True
    code: int = 1000
    data: OrderDetail


class OrderListItem(BaseModel):
    order_number: str
    status: str
    status_label: Optional[str] = None
    payment_status: Optional[str] = None
    total: Optional[float] = None
    item_count: Optional[int] = None
    thumbnail: Optional[str] = None
    created_at: Optional[str] = None


class OrderListResponse(BaseModel):
    success: bool = True
    code: int = 1000
    data: list[OrderListItem] = Field(default_factory=list)
    meta: Optional[PaginationMeta] = None


class OrderActionResponse(BaseModel):
    success: bool = True
    code: int = 1000
    data: Optional[dict] = None


class OrderCreateRequest(BaseModel):
    customer_name: str
    customer_phone: str
    customer_email: str
    customer_address: str
    customer_province_id: int
    customer_district_id: int
    customer_ward_id: int
    is_shipdiff: bool = False
    shipping_name: Optional[str] = None
    shipping_phone: Optional[str] = None
    shipping_email: Optional[str] = None
    shipping_address: Optional[str] = None
    shipping_province_id: Optional[int] = None
    shipping_district_id: Optional[int] = None
    shipping_ward_id: Optional[int] = None
    shipping_type: str
    payment_method: str
    coupon_code: Optional[str] = None
    vendor_coupon_codes: Optional[dict[str, str]] = None
    shopping_points: Optional[dict[str, int]] = None
    order_note: Optional[str] = None
