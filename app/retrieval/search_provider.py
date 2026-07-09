from typing import List, Dict, Any, Optional
from app.client.delippy_client import delippy_client

class SearchProvider:
    async def search(self, q: str, category_id: Optional[int] = None, sort: Optional[str] = None, price_min: Optional[int] = None, price_max: Optional[int] = None) -> List[Dict[str, Any]]:
        try:
            res = await delippy_client.search_products(
                q=q, category_id=category_id, sort=sort,
                price_min=price_min, price_max=price_max
            )
            if res.get("success") and "data" in res:
                return res["data"]
            return []
        except Exception:
            return []

    async def list_by_category(self, category_id: int, limit: int = 3) -> List[Dict[str, Any]]:
        try:
            res = await delippy_client.get_products(params={"category_id": category_id})
            if res.get("success") and "data" in res:
                return res["data"][:limit]
            return []
        except Exception:
            return []

    async def list_products(
        self,
        category_id: Optional[int] = None,
        subcategory_id: Optional[int] = None,
        price_min: Optional[int] = None,
        price_max: Optional[int] = None,
        limit: int = 15,
    ) -> List[Dict[str, Any]]:
        """Browse via GET /products (no keyword text) - used when there's no
        usable query_q (a pure category/subcategory browse, e.g. the user
        just picked a subcategory from the zero-result menu). /products/search
        requires q >= 2 chars and 422s on anything shorter (see
        api-docs/product_api.md) - it also has no subcategory_id param at
        all, only category_id, so subcategory-level filtering is ONLY
        possible through this endpoint, never through search()."""
        try:
            params: Dict[str, Any] = {}
            if category_id:
                params["category_id"] = category_id
            if subcategory_id:
                params["subcategory_id"] = subcategory_id
            if price_min is not None:
                params["price_min"] = price_min
            if price_max is not None:
                params["price_max"] = price_max
            res = await delippy_client.get_products(params=params)
            if res.get("success") and "data" in res:
                return res["data"][:limit]
            return []
        except Exception:
            return []

    async def get_details(self, slug: str) -> Optional[Dict[str, Any]]:
        try:
            res = await delippy_client.get_product_detail(slug)
            if res.get("success") and "data" in res:
                return res["data"]
            return None
        except Exception:
            return None

    async def get_related(self, slug: str) -> List[Dict[str, Any]]:
        try:
            res = await delippy_client.get_related_products(slug)
            if res.get("success") and "data" in res:
                return res["data"]
            return []
        except Exception:
            return []

    async def get_reviews_summary(self, product_id: int) -> Optional[Dict[str, Any]]:
        try:
            res = await delippy_client.get_review_summary(product_id)
            if res.get("success") and "data" in res:
                return res["data"]
            return None
        except Exception:
            return None

search_provider = SearchProvider()
