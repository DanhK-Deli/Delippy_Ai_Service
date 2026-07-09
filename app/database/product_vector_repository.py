from typing import Any, Dict, List, Optional
from app.core.config import settings
from app.database.mongodb import get_db

VECTOR_INDEX_NAME = "product_vector_index"

class ProductVectorRepository:
    """Backs the semantic-retrieval product index (see app/jobs/sync_products.py
    and app/retrieval/search_engine.py). One document per product: slug,
    name, embedding vector, category_id/subcategory_id (for Atlas
    $vectorSearch pre-filters), and price_at_sync - which is ONLY a coarse
    signal, never trusted for an actual transaction; search_engine always
    re-fetches live price/stock via search_provider.get_details() before
    presenting a product to the user."""

    def __init__(self, collection_name: str = "product_embeddings"):
        self.collection_name = collection_name

    async def upsert(self, doc: Dict[str, Any]) -> None:
        db = await get_db()
        await db[self.collection_name].replace_one({"slug": doc["slug"]}, doc, upsert=True)

    async def prune_stale(self, sync_run_id: str) -> int:
        """Deletes every document NOT stamped with this run's id - i.e.
        products no longer returned by any category/subcategory crawl this
        run (deleted/deactivated). Only call this after a FULLY successful
        crawl - calling it after a partial/failed run would mass-delete
        products that simply weren't reached yet."""
        db = await get_db()
        result = await db[self.collection_name].delete_many({"synced_at": {"$ne": sync_run_id}})
        return result.deleted_count

    async def count(self) -> int:
        db = await get_db()
        return await db[self.collection_name].count_documents({})

    async def ensure_vector_index(self) -> str:
        """Idempotently creates the Atlas Vector Search index this
        repository's vector_search() depends on (requires pymongo>=4.7,
        confirmed available - see scripts/atlas_vector_index.md). Safe to
        call repeatedly: Atlas rejects a duplicate-name create with a normal
        error, which is treated as "already exists" here. A newly-created
        index is NOT immediately queryable - Atlas needs time to build it
        (check via list_search_indexes()'s `queryable` field)."""
        from pymongo.operations import SearchIndexModel
        db = await get_db()
        coll = db[self.collection_name]
        definition = {
            "fields": [
                {"type": "vector", "path": "embedding", "numDimensions": settings.EMBEDDING_DIMENSION, "similarity": "cosine"},
                {"type": "filter", "path": "category_id"},
                {"type": "filter", "path": "subcategory_id"},
            ]
        }
        model = SearchIndexModel(definition=definition, name=VECTOR_INDEX_NAME, type="vectorSearch")
        try:
            await coll.create_search_index(model)
            return f"created '{VECTOR_INDEX_NAME}'"
        except Exception as e:
            if "already exists" in str(e).lower() or "duplicate" in str(e).lower():
                return f"'{VECTOR_INDEX_NAME}' already exists"
            raise

    async def index_status(self) -> Optional[Dict[str, Any]]:
        db = await get_db()
        coll = db[self.collection_name]
        async for idx in coll.list_search_indexes():
            if idx.get("name") == VECTOR_INDEX_NAME:
                return idx
        return None

    async def vector_search(
        self,
        query_vector: List[float],
        limit: int = 20,
        num_candidates: int = 200,
        category_id: Optional[int] = None,
        subcategory_id: Optional[int] = None,
        index_name: str = VECTOR_INDEX_NAME,
    ) -> List[Dict[str, Any]]:
        """$vectorSearch aggregation - see scripts/atlas_vector_index.md for
        the index definition this depends on. Returns docs with an added
        `score` field (Atlas's normalized cosine score, [0,1])."""
        db = await get_db()
        filter_clause: Dict[str, Any] = {}
        if category_id is not None:
            filter_clause["category_id"] = category_id
        if subcategory_id is not None:
            filter_clause["subcategory_id"] = subcategory_id

        vector_search_stage: Dict[str, Any] = {
            "index": index_name,
            "path": "embedding",
            "queryVector": query_vector,
            "numCandidates": num_candidates,
            "limit": limit,
        }
        if filter_clause:
            vector_search_stage["filter"] = filter_clause

        pipeline = [
            {"$vectorSearch": vector_search_stage},
            {"$project": {
                "_id": 0,
                "slug": 1,
                "name": 1,
                "category_id": 1,
                "subcategory_id": 1,
                "price_at_sync": 1,
                "score": {"$meta": "vectorSearchScore"},
            }},
        ]
        cursor = db[self.collection_name].aggregate(pipeline)
        return [doc async for doc in cursor]

product_vector_repo = ProductVectorRepository()
