from typing import Optional

from pydantic import BaseModel, Field


class Profile(BaseModel):
    id: Optional[int] = None
    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    photo: Optional[str] = None
    address: Optional[str] = None
    ranking: Optional[str] = None
    reward_point: Optional[int] = None
    shopping_point: Optional[int] = None
    bank_account_number: Optional[str] = None
    bank_account_name: Optional[str] = None
    bank_name: Optional[str] = None
    bank_address: Optional[str] = None
    is_vendor: Optional[int] = None
    shop_name: Optional[str] = None
    shop_image: Optional[str] = None


class ProfileResponse(BaseModel):
    success: bool = True
    code: int = 1000
    data: Profile


class ProfileUpdateRequest(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class TokenRefreshResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int = 3600


class TokenRefreshEnvelope(BaseModel):
    success: bool = True
    code: int = 1000
    data: TokenRefreshResponse


class AuthActionResponse(BaseModel):
    success: bool = True
    code: int = 1000
    data: Optional[dict] = None
