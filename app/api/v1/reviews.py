from typing import Optional

import httpx
from fastapi import APIRouter, File, Form, Query, Request, UploadFile
from fastapi.responses import JSONResponse

from app.models.ecommerce.review import (
    ReviewListResponse,
    ReviewSummaryResponse,
)
from app.client.delippy_client import delippy_client

router = APIRouter(prefix="/api/v1", tags=["Reviews"])


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


@router.get("/products/{product_id}/reviews", response_model=ReviewListResponse)
async def list_reviews(request: Request, product_id: int, page: int = Query(default=1), per_page: int = Query(default=10)):
    params = {"page": page, "per_page": per_page}
    return await _proxy(delippy_client.get_reviews, product_id, params=params, token=_auth_header(request))


@router.get("/products/{product_id}/reviews/summary", response_model=ReviewSummaryResponse)
async def review_summary(request: Request, product_id: int):
    return await _proxy(delippy_client.get_review_summary, product_id, token=_auth_header(request))


@router.post("/products/{product_id}/reviews")
async def create_review(
    request: Request,
    product_id: int,
    rating: int = Form(...),
    review: Optional[str] = Form(default=None),
    photo: Optional[UploadFile] = File(default=None),
):
    payload = {"rating": str(rating), "review": review or ""}
    files = None
    if photo is not None:
        files = {"photo": (photo.filename, await photo.read(), photo.content_type or "application/octet-stream")}
    return await _proxy(delippy_client.create_review, product_id, data=payload, files=files, token=_auth_header(request))


@router.get("/my-reviews", response_model=ReviewListResponse)
async def my_reviews(request: Request, page: int = Query(default=1), per_page: int = Query(default=10)):
    params = {"page": page, "per_page": per_page}
    return await _proxy(delippy_client.get_my_reviews, params=params, token=_auth_header(request))
