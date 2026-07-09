import os
import re
import time
from typing import Any, Optional
import httpx
from dotenv import load_dotenv

load_dotenv()

DEFAULT_BASE_URL = os.getenv("DELIPPY_API_BASE_URL", "https://dev.delippy.com/api/v1")
DEFAULT_TIMEOUT = float(os.getenv("DELIPPY_API_TIMEOUT", "8.0"))
DEFAULT_VERIFY_SSL = os.getenv("DELIPPY_API_VERIFY_SSL", "true").lower() in ("true", "1", "yes")

# Default cooldown when the backend 429s but tells us nothing about how long to
# wait - matches the dev backend's own "Please try again in 30 seconds" message.
_DEFAULT_429_COOLDOWN = 30.0


class DelippyRateLimitedError(Exception):
    """Raised when a call is short-circuited because the backend recently
    returned 429 and we're still inside the in-process cooldown window. The
    message deliberately contains "429" so existing callers that sniff for it
    (e.g. sync_products._get_products_with_retry) still treat it as rate-limited."""


class DelippyClient:
    # Class-level (shared across every instance/caller) monotonic timestamp:
    # while now() < this, all requests short-circuit instead of firing. The dev
    # backend rate-limits hard, and search re-verify fans out ~20 concurrent
    # product-detail calls (search_engine._LIVE_VERIFY_CONCURRENCY) - once one
    # of them 429s, letting the rest of that same burst keep hitting the wall
    # just deepens and prolongs the cooldown for every other chat request too.
    _cooldown_until: float = 0.0
    def __init__(self, base_url: str = DEFAULT_BASE_URL, timeout: float = DEFAULT_TIMEOUT, verify_ssl: bool = DEFAULT_VERIFY_SSL):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.verify_ssl = verify_ssl

    async def _request(
        self,
        method: str,
        path: str,
        *,
        token: Optional[str] = None,
        params: Optional[dict] = None,
        json_body: Optional[dict] = None,
        data: Optional[dict] = None,
        files: Optional[dict] = None,
        headers: Optional[dict] = None
    ) -> dict:
        remaining = DelippyClient._cooldown_until - time.monotonic()
        if remaining > 0:
            # Short-circuit instead of piling onto a backend that's already
            # rate-limiting us. Callers via search_provider treat this as a
            # normal miss (0 results); it clears itself once the window passes.
            print(f"\n[Delippy API Call] -> {method} {path} SKIPPED: backend in 429 cooldown ({remaining:.0f}s left)")
            raise DelippyRateLimitedError(f"Backend in 429 cooldown for {remaining:.0f}s more; skipping {method} {path}")

        request_headers = {"Accept": "application/json"}
        if headers:
            request_headers.update(headers)
        if token:
            request_headers["Authorization"] = token if token.startswith("Bearer ") else f"Bearer {token}"

        print(f"\n[Delippy API Call] -> {method} {self.base_url}{path}")
        if params:
            print(f"  - Params   : {params}")
        if json_body:
            print(f"  - JSON Body: {json_body}")

        async with httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout, verify=self.verify_ssl, headers=request_headers) as client:
            try:
                response = await client.request(
                    method,
                    path,
                    params=params,
                    json=json_body,
                    data=data,
                    files=files
                )
                print(f"[Delippy API Response] <- Status: {response.status_code}")
                if response.status_code == 429:
                    cooldown = self._parse_retry_after(response)
                    DelippyClient._cooldown_until = time.monotonic() + cooldown
                    print(f"  - 429 Too Many Requests. Cooling down {cooldown:.0f}s; short-circuiting further calls until then.")
                if response.status_code == 404:
                    # Routine, EXPECTED during vector-search live re-verify: a
                    # product embedded at sync time can later be deleted/hidden
                    # on the backend, so GET /products/{slug} 404s. Not a
                    # systemic failure like 429/5xx. Callers (search_engine
                    # ._verify, search_provider) already treat a raised error as
                    # "drop this candidate", so we still raise - just log it
                    # quietly instead of with the alarming !!! error format.
                    print(f"[Delippy API] Product not found (404): {path}")
                elif response.status_code >= 400:
                    print(f"  - Error Content: {response.text}")
                response.raise_for_status()
                if not response.content:
                    return {"success": True, "code": response.status_code, "data": None}
                res_data = response.json()
                data_list = res_data.get("data", [])
                if isinstance(data_list, list):
                    print(f"  - Result Count: {len(data_list)}")
                elif isinstance(data_list, dict):
                    print(f"  - Result Keys: {list(data_list.keys())}")
                return res_data
            except httpx.HTTPStatusError as e:
                # 404 is already logged quietly above as an expected miss - don't
                # repeat it in the loud error format reserved for real failures.
                if e.response.status_code != 404:
                    print(f"[Delippy API Error] !!! {e}")
                raise e
            except Exception as e:
                print(f"[Delippy API Error] !!! {e}")
                raise e

    @staticmethod
    def _parse_retry_after(response: httpx.Response) -> float:
        """How long to back off after a 429. Prefer the standard Retry-After
        header; otherwise pull the number out of the throttle body (Laravel's
        "Too many attempts. Please try again in 30 seconds."); else a default."""
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            try:
                return max(1.0, float(retry_after))
            except ValueError:
                pass
        try:
            body = response.text or ""
        except Exception:
            body = ""
        match = re.search(r"in\s+(\d+)\s+second", body, re.IGNORECASE)
        if match:
            return max(1.0, float(match.group(1)))
        return _DEFAULT_429_COOLDOWN

    # Product APIs
    async def get_products(self, params: Optional[dict] = None, token: Optional[str] = None) -> dict:
        return await self._request("GET", "/products", token=token, params=params)

    async def search_products(self, q: str, category_id: Optional[int] = None, sort: Optional[str] = None, price_min: Optional[int] = None, price_max: Optional[int] = None, page: int = 1, per_page: int = 15, token: Optional[str] = None) -> dict:
        params = {"q": q, "page": page, "per_page": per_page}
        if category_id:
            params["category_id"] = category_id
        if sort:
            params["sort"] = sort
        if price_min is not None:
            params["price_min"] = price_min
        elif price_max is not None:
            params["price_min"] = 0

        if price_max is not None:
            params["price_max"] = price_max
        return await self._request("GET", "/products/search", token=token, params=params)

    async def get_featured_products(self, params: Optional[dict] = None, token: Optional[str] = None) -> dict:
        return await self._request("GET", "/products/featured", token=token, params=params)

    async def get_bestselling_products(self, params: Optional[dict] = None, token: Optional[str] = None) -> dict:
        return await self._request("GET", "/products/bestselling", token=token, params=params)

    async def get_product_detail(self, slug: str, token: Optional[str] = None) -> dict:
        return await self._request("GET", f"/products/{slug}", token=token)

    async def get_related_products(self, slug: str, params: Optional[dict] = None, token: Optional[str] = None) -> dict:
        return await self._request("GET", f"/products/{slug}/related", token=token, params=params)

    # Category APIs
    async def get_categories(self, token: Optional[str] = None) -> dict:
        return await self._request("GET", "/categories", token=token)

    async def get_category_detail(self, slug: str, token: Optional[str] = None) -> dict:
        return await self._request("GET", f"/categories/{slug}", token=token)

    async def get_category_products(self, slug: str, params: Optional[dict] = None, token: Optional[str] = None) -> dict:
        return await self._request("GET", f"/categories/{slug}/products", token=token, params=params)

    # Review APIs
    async def get_review_summary(self, product_id: int, token: Optional[str] = None) -> dict:
        return await self._request("GET", f"/products/{product_id}/reviews/summary", token=token)

    async def get_reviews(self, product_id: int, params: Optional[dict] = None, token: Optional[str] = None) -> dict:
        return await self._request("GET", f"/products/{product_id}/reviews", token=token, params=params)

    async def create_review(self, product_id: int, data: dict, files: Optional[dict] = None, token: Optional[str] = None) -> dict:
        return await self._request("POST", f"/products/{product_id}/reviews", token=token, data=data, files=files)

    async def get_my_reviews(self, params: Optional[dict] = None, token: Optional[str] = None) -> dict:
        return await self._request("GET", "/my-reviews", token=token, params=params)

    # Profile & Account APIs
    async def get_profile(self, token: Optional[str] = None) -> dict:
        return await self._request("GET", "/auth/profile", token=token)

    async def update_profile(self, data: dict, files: Optional[dict] = None, token: Optional[str] = None) -> dict:
        return await self._request("POST", "/auth/profile", token=token, data=data, files=files)

    async def change_password(self, data: dict, token: Optional[str] = None) -> dict:
        return await self._request("POST", "/auth/change-password", token=token, json_body=data)

    async def refresh_token(self, token: Optional[str] = None) -> dict:
        return await self._request("POST", "/auth/refresh", token=token)

    async def logout(self, token: Optional[str] = None) -> dict:
        return await self._request("POST", "/auth/logout", token=token)

    # Order APIs
    async def get_shipping_methods(self, token: Optional[str] = None) -> dict:
        return await self._request("GET", "/shipping-methods", token=token)

    async def get_payment_methods(self, token: Optional[str] = None) -> dict:
        return await self._request("GET", "/payment-methods", token=token)

    async def estimate_shipping_fee(self, data: dict, token: Optional[str] = None) -> dict:
        return await self._request("POST", "/orders/shipping-fee", token=token, json_body=data)

    async def preview_order(self, data: dict, token: Optional[str] = None) -> dict:
        return await self._request("POST", "/orders/preview", token=token, json_body=data)

    async def create_order(self, data: dict, token: Optional[str] = None) -> dict:
        return await self._request("POST", "/orders", token=token, json_body=data)

    async def list_orders(self, params: Optional[dict] = None, token: Optional[str] = None) -> dict:
        return await self._request("GET", "/orders", token=token, params=params)

    async def get_order_detail(self, order_number: str, token: Optional[str] = None) -> dict:
        return await self._request("GET", f"/orders/{order_number}", token=token)

    async def cancel_order(self, order_number: str, token: Optional[str] = None) -> dict:
        return await self._request("POST", f"/orders/{order_number}/cancel", token=token)

    async def payment_status(self, order_number: str, token: Optional[str] = None) -> dict:
        return await self._request("GET", f"/orders/{order_number}/payment-status", token=token)

delippy_client = DelippyClient()
