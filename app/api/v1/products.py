from typing import Optional

import httpx
from fastapi import APIRouter, Query, Request, BackgroundTasks
from fastapi.responses import JSONResponse

from app.models.ecommerce.product import (
    ProductDetailResponse,
    ProductSearchResponse,
)
from app.client.delippy_client import delippy_client
from app.jobs.sync_products import sync_products, sync_categories

router = APIRouter(prefix="/api/v1", tags=["Products"])


@router.post("/products/sync")
async def trigger_sync(background_tasks: BackgroundTasks):
    async def run_sync():
        print("\n[SyncJob] Starting background sync categories + products...")
        try:
            await sync_categories()
            await sync_products()
            print("[SyncJob] Background sync completed successfully.\n")
        except Exception as e:
            print(f"\n[SyncJob] Background sync failed: {e}\n")

    background_tasks.add_task(run_sync)
    return {"success": True, "message": "Product and category synchronization started in the background."}


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


@router.get("/products", response_model=ProductSearchResponse)
async def list_products(
    request: Request,
    category_id: Optional[int] = Query(default=None),
    subcategory_id: Optional[int] = Query(default=None),
    childcategory_id: Optional[int] = Query(default=None),
    sort: str = Query(default="newest"),
    price_min: Optional[int] = Query(default=None),
    price_max: Optional[int] = Query(default=None),
    cursor: Optional[str] = Query(default=None),
):
    params = {
        "category_id": category_id,
        "subcategory_id": subcategory_id,
        "childcategory_id": childcategory_id,
        "sort": sort,
        "price_min": price_min,
        "price_max": price_max,
        "cursor": cursor,
    }
    params = {key: value for key, value in params.items() if value is not None}
    return await _proxy(delippy_client.get_products, params=params, token=_auth_header(request))


@router.get("/products/search", response_model=ProductSearchResponse)
async def search_products(
    request: Request,
    q: str = Query(..., min_length=2, max_length=100),
    category_id: Optional[int] = Query(default=None),
    sort: str = Query(default="newest"),
    price_min: Optional[int] = Query(default=None),
    price_max: Optional[int] = Query(default=None),
    page: int = Query(default=1),
    per_page: int = Query(default=15),
):
    params = {
        "q": q,
        "category_id": category_id,
        "sort": sort,
        "price_min": price_min,
        "price_max": price_max,
        "page": page,
        "per_page": per_page,
    }
    params = {key: value for key, value in params.items() if value is not None}
    return await _proxy(delippy_client.search_products, params=params, token=_auth_header(request))


@router.get("/products/featured", response_model=ProductSearchResponse)
async def featured_products(request: Request, cursor: Optional[str] = Query(default=None), per_page: int = Query(default=20)):
    params = {"cursor": cursor, "per_page": per_page}
    params = {key: value for key, value in params.items() if value is not None}
    return await _proxy(delippy_client.get_featured_products, params=params, token=_auth_header(request))


@router.get("/products/bestselling", response_model=ProductSearchResponse)
async def bestselling_products(request: Request, cursor: Optional[str] = Query(default=None), per_page: int = Query(default=20)):
    params = {"cursor": cursor, "per_page": per_page}
    params = {key: value for key, value in params.items() if value is not None}
    return await _proxy(delippy_client.get_bestselling_products, params=params, token=_auth_header(request))


@router.get("/products/{slug}", response_model=ProductDetailResponse)
async def product_detail(request: Request, slug: str):
    return await _proxy(delippy_client.get_product_detail, slug, token=_auth_header(request))


@router.get("/products/{slug}/related", response_model=ProductSearchResponse)
async def related_products(request: Request, slug: str, cursor: Optional[str] = Query(default=None), per_page: int = Query(default=10)):
    params = {"cursor": cursor, "per_page": per_page}
    params = {key: value for key, value in params.items() if value is not None}
    return await _proxy(delippy_client.get_related_products, slug, params=params, token=_auth_header(request))
