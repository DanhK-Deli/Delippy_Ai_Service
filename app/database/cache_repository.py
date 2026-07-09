from typing import Optional, Any
from app.database.mongodb import get_db
from datetime import datetime, timedelta

class CacheRepository:
    def __init__(self, collection_name: str = "search_cache"):
        self.collection_name = collection_name

    async def get_cached_search(self, query_key: str) -> Optional[Any]:
        db = await get_db()
        doc = await db[self.collection_name].find_one({"query_key": query_key})
        if doc:
            expires_at = doc.get("expires_at")
            if expires_at and datetime.utcnow() < expires_at:
                return doc.get("data")
            await db[self.collection_name].delete_one({"query_key": query_key})
        return None

    async def set_cached_search(self, query_key: str, data: Any, ttl_seconds: int = 86400) -> None:
        db = await get_db()
        expires_at = datetime.utcnow() + timedelta(seconds=ttl_seconds)
        await db[self.collection_name].replace_one(
            {"query_key": query_key},
            {
                "query_key": query_key,
                "data": data,
                "expires_at": expires_at,
                "created_at": datetime.utcnow()
            },
            upsert=True
        )

cache_repo = CacheRepository()
