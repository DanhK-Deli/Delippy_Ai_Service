from typing import Optional

import httpx
from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from app.models.ecommerce.order import (
    OrderCreateRequest,
    OrderActionResponse,
    OrderDetail,
    OrderDetailResponse,
    OrderListResponse,
    OrderPreviewRequest,
    OrderPreviewResponse,
    PaymentMethod,
    PaymentMethodsResponse,
    ShippingFeeRequest,
    ShippingFeeResponse,
    ShippingMethod,
    ShippingMethodsResponse,
)
from app.client.delippy_client import delippy_client

router = APIRouter(prefix="/api/v1", tags=["Orders"])


def _auth_header(request: Request) -> Optional[str]:
    return request.headers.get("authorization")


async def _proxy(callable_obj, *args, **kwargs):
    try:
        return await callable_obj(*args, **kwargs)
    except httpx.HTTPStatusError as exc:
        content = None
        try:
            content = exc.response.json()
        except Exception:
            content = {"success": False, "message": exc.response.text or "Upstream error"}
        return JSONResponse(status_code=exc.response.status_code, content=content)
    except httpx.RequestError as exc:
        return JSONResponse(status_code=502, content={"success": False, "message": f"Delippy API unavailable: {exc}"})


@router.get("/shipping-methods", response_model=ShippingMethodsResponse)
async def shipping_methods(request: Request):
    return await _proxy(delippy_client.get_shipping_methods, token=_auth_header(request))


@router.get("/payment-methods", response_model=PaymentMethodsResponse)
async def payment_methods(request: Request):
    return await _proxy(delippy_client.get_payment_methods, token=_auth_header(request))


@router.post("/orders/shipping-fee", response_model=ShippingFeeResponse)
async def shipping_fee(request: Request, payload: ShippingFeeRequest):
    return await _proxy(delippy_client.estimate_shipping_fee, payload.model_dump(), token=_auth_header(request))


@router.post("/orders/preview", response_model=OrderPreviewResponse)
async def preview_order(request: Request, payload: OrderPreviewRequest):
    return await _proxy(delippy_client.preview_order, payload.model_dump(exclude_none=True), token=_auth_header(request))


@router.post("/orders", response_model=OrderDetailResponse)
async def create_order(request: Request, payload: OrderCreateRequest):
    return await _proxy(delippy_client.create_order, payload.model_dump(exclude_none=True), token=_auth_header(request))


@router.get("/orders", response_model=OrderListResponse)
async def list_orders(request: Request, status: Optional[str] = Query(default=None), per_page: int = Query(default=15), page: int = Query(default=1)):
    params = {"status": status, "per_page": per_page, "page": page}
    params = {key: value for key, value in params.items() if value is not None}
    return await _proxy(delippy_client.list_orders, params=params, token=_auth_header(request))


@router.get("/orders/{order_number}", response_model=OrderDetailResponse)
async def order_detail(request: Request, order_number: str):
    return await _proxy(delippy_client.get_order_detail, order_number, token=_auth_header(request))


@router.post("/orders/{order_number}/cancel", response_model=OrderActionResponse)
async def cancel_order(request: Request, order_number: str):
    return await _proxy(delippy_client.cancel_order, order_number, token=_auth_header(request))


@router.get("/orders/{order_number}/payment-status", response_model=OrderActionResponse)
async def payment_status(request: Request, order_number: str):
    return await _proxy(delippy_client.payment_status, order_number, token=_auth_header(request))
