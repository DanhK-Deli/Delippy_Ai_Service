import asyncio
from app.client.delippy_client import delippy_client
from app.retrieval.search_engine import search_engine
from app.models.shopping_context import ShoppingContext

async def warmup():
    print("[Job] Warming up search cache...")
    queries = ["iphone", "laptop", "asus", "vinamilk", "sữa", "samsung"]
    for q in queries:
        ctx = ShoppingContext(intent="SEARCH", query_q=q)
        # Search will automatically cache the results in MongoDB search_cache collection
        await search_engine.search(ctx)
        print(f"[Job] Warmed up cache for: {q}")
    print("[Job] Cache warmup completed successfully!")

if __name__ == "__main__":
    asyncio.run(warmup())
