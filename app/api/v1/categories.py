from typing import Optional

import httpx
from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from app.models.ecommerce.category import (
    CategoryDetailResponse,
    CategoryListResponse,
    CategoryProductsResponse,
)
from app.client.delippy_client import delippy_client

router = APIRouter(prefix="/api/v1", tags=["Categories"])


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


@router.get("/categories", response_model=CategoryListResponse)
async def list_categories(request: Request):
    return await _proxy(delippy_client.get_categories, token=_auth_header(request))


@router.get("/categories/{slug}", response_model=CategoryDetailResponse)
async def category_detail(request: Request, slug: str):
    return await _proxy(delippy_client.get_category_detail, slug, token=_auth_header(request))


@router.get("/categories/{slug}/products", response_model=CategoryProductsResponse)
async def category_products(
    request: Request,
    slug: str,
    subcategory_id: Optional[int] = Query(default=None),
    childcategory_id: Optional[int] = Query(default=None),
    sort: str = Query(default="newest"),
    price_min: Optional[int] = Query(default=None),
    price_max: Optional[int] = Query(default=None),
    cursor: Optional[str] = Query(default=None),
):
    params = {
        "subcategory_id": subcategory_id,
        "childcategory_id": childcategory_id,
        "sort": sort,
        "price_min": price_min,
        "price_max": price_max,
        "cursor": cursor,
    }
    params = {key: value for key, value in params.items() if value is not None}
    return await _proxy(delippy_client.get_category_products, slug, params=params, token=_auth_header(request))
