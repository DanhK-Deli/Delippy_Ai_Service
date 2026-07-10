from typing import Any, Dict, List, Optional
from datetime import datetime, timedelta
from app.database.mongodb import get_db
from app.database.conversation_repository import cosine_similarity

# Concept->parse cache TTL. A cached entry maps a phrasing to a semantic parse
# (intent/category/query_q/expanded_queries/purpose). That mapping is far more
# stable than live product data (cache_repository uses 24h for price/stock), but
# NOT permanent: the catalog and ontology change (this project reshapes category
# resolution regularly), so entries must self-heal by ageing out rather than
# living forever like the removed aliases.json learning loop. 14 days balances
# real cross-user reuse against flushing a now-stale mapping fast enough.
_PARSE_CACHE_TTL_DAYS = 14

# Cosine-similarity floor for treating two queries as the SAME shopping concept.
# Higher-stakes than history-RAG relevance (a reused parse rewrites category +
# keywords for an entire search), and the failure is ASYMMETRIC: a false hit
# runs a WRONG search, whereas a miss just falls back to the normal Gemini parse
# (status quo, no worse). So err strict. This is a reasoned starting point, not
# yet measured against real traffic - every cache HIT logs its similarity (see
# parser.py), so tune this from those real values before loosening it.
_PARSE_CACHE_MIN_SIMILARITY = 0.86


class ParseCacheRepository:
    """Global (cross-user, cross-session) semantic cache for the AI-PARSER step
    ONLY - distinct from cache_repository's exact-key search-results cache.
    Lets the orchestrator skip a Gemini parse call when a sufficiently similar
    PAST query was already parsed AND led to a confirmed successful search.

    Two structural safety properties (deliberately unlike the removed
    aliases.json learning loop, which allowed unvalidated permanent global
    writes and was a data-poisoning risk):
      1. Only a parse that produced REAL products gets written (the orchestrator
         gates the write on non-empty live-verified evidence.products). A wrong
         parse finds nothing, so it can never enter the cache - no manual review
         needed, poisoning is prevented by construction.
      2. Every entry TTLs out (self-healing) - never a permanent knowledge file.
    """

    def __init__(self, collection_name: str = "parse_cache"):
        self.collection_name = collection_name

    async def ensure_ttl_index(self) -> None:
        """Native TTL cleanup (Mongo deletes docs once expires_at passes) so the
        in-memory cosine scan in lookup() stays bounded to live entries.
        Idempotent - safe to call on every startup."""
        db = await get_db()
        await db[self.collection_name].create_index("expires_at", expireAfterSeconds=0)

    async def store(self, query_text: str, embedding: List[float], parse: Dict[str, Any]) -> None:
        """Persist a confirmed-successful AI parse. `embedding` is the caller's
        already-computed query vector (reused, never re-embedded here).
        brand/price are intentionally NOT part of `parse` - they are turn-
        specific and re-extracted deterministically each turn, so a cache hit
        must apply THIS turn's brand/price, not the original query's."""
        if not embedding or not parse or not parse.get("query_q"):
            return
        db = await get_db()
        now = datetime.utcnow()
        await db[self.collection_name].insert_one({
            "query_text": query_text,
            "embedding": embedding,
            "parse": parse,
            "created_at": now,
            "expires_at": now + timedelta(days=_PARSE_CACHE_TTL_DAYS),
        })

    async def lookup(self, embedding: List[float]) -> Optional[Dict[str, Any]]:
        """Return the most similar non-expired cached parse if it clears
        _PARSE_CACHE_MIN_SIMILARITY, else None. In-memory cosine over live
        entries (same approach as conversation_repository.get_relevant_history);
        migrate to Atlas $vectorSearch - like product_vector_repository - if the
        live-entry set ever grows large enough for the linear scan to matter."""
        if not embedding:
            return None
        db = await get_db()
        now = datetime.utcnow()
        best: Optional[tuple] = None  # (similarity, doc)
        cursor = db[self.collection_name].find({"expires_at": {"$gt": now}})
        async for doc in cursor:
            emb = doc.get("embedding")
            sim = cosine_similarity(embedding, emb) if emb else 0.0
            if best is None or sim > best[0]:
                best = (sim, doc)
        if best and best[0] >= _PARSE_CACHE_MIN_SIMILARITY:
            sim, doc = best
            created = doc.get("created_at") or now
            return {
                "parse": doc.get("parse"),
                "similarity": sim,
                "age_days": (now - created).days,
                "query_text": doc.get("query_text"),
            }
        return None


parse_cache_repo = ParseCacheRepository()
