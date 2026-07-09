from typing import Optional

import httpx
from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import JSONResponse

from app.models.ecommerce.account import (
    AuthActionResponse,
    ChangePasswordRequest,
    Profile,
    ProfileResponse,
    ProfileUpdateRequest,
    TokenRefreshEnvelope,
)
from app.client.delippy_client import delippy_client

router = APIRouter(prefix="/api/v1/auth", tags=["Account"])


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


@router.get("/profile", response_model=ProfileResponse)
async def get_profile(request: Request):
    return await _proxy(delippy_client.get_profile, token=_auth_header(request))


@router.post("/profile", response_model=ProfileResponse)
async def update_profile(
    request: Request,
    name: Optional[str] = Form(default=None),
    email: Optional[str] = Form(default=None),
    phone: Optional[str] = Form(default=None),
    address: Optional[str] = Form(default=None),
    photo: Optional[UploadFile] = File(default=None),
):
    payload = {"name": name, "email": email, "phone": phone, "address": address}
    payload = {key: value for key, value in payload.items() if value is not None}
    files = None
    if photo is not None:
        files = {"photo": (photo.filename, await photo.read(), photo.content_type or "application/octet-stream")}
    return await _proxy(delippy_client.update_profile, payload, files=files, token=_auth_header(request))


@router.post("/change-password", response_model=AuthActionResponse)
async def change_password(request: Request, payload: ChangePasswordRequest):
    return await _proxy(delippy_client.change_password, payload.model_dump(), token=_auth_header(request))


@router.post("/refresh", response_model=TokenRefreshEnvelope)
async def refresh_token(request: Request):
    return await _proxy(delippy_client.refresh_token, token=_auth_header(request))


@router.post("/logout", response_model=AuthActionResponse)
async def logout(request: Request):
    return await _proxy(delippy_client.logout, token=_auth_header(request))
