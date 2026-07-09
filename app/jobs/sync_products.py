import asyncio
import json
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from app.client.delippy_client import delippy_client
from app.client.llm_client import llm_client_wrapper
from app.core.config import settings
from app.database.product_vector_repository import product_vector_repo

# Concurrency cap for embed calls during sync - llm_provider.embed() is a
# blocking sync call (see gemini_provider.py), so each one is dispatched via
# asyncio.to_thread; the model itself only accepts ONE text per call despite
# the SDK's embed_content() accepting a list (verified empirically - a
# 3-string batch call to models/gemini-embedding-2 returns exactly 1
# embedding back, not 3), so this semaphore is the only lever for sync
# throughput.
_EMBED_CONCURRENCY = 8

async def _embed_product(name: str, category_name: str, subcategory_name: Optional[str]) -> List[float]:
    text = f"{name} - {category_name}" + (f" - {subcategory_name}" if subcategory_name else "")
    return await asyncio.to_thread(
        llm_client_wrapper.get_embedding,
        text,
        task_type="RETRIEVAL_DOCUMENT",
        output_dimensionality=settings.EMBEDDING_DIMENSION,
    )

def _is_malformed_slug(slug: Optional[str]) -> bool:
    """A well-formed dev-catalog product slug is dash-joined romanized words,
    usually with a trailing id blob - e.g. "set-do-choi-nau-an-2022fzy7196q2i",
    "10-hop-nhua-dung-thuc-pham-500ml". Live logs showed junk records whose slug
    is just the id with the name portion missing ("-2022ftd6393sdp", leading
    dash); embedding those only yields entries that 404 forever during live
    re-verify. This skips the obviously malformed ones so they never enter
    product_embeddings in the first place.

    CAVEAT: this only prevents NEW junk on the NEXT sync run. It does NOT remove
    junk ALREADY embedded by previous runs - that stale data keeps 404ing during
    live re-verify until a future full resync overwrites/prunes it (or a one-off
    cleanup, out of scope here). delippy_client.py's quiet-404 handling is what
    actually keeps today's EXISTING stale entries from being noisy; this only
    stops the problem growing."""
    s = (slug or "").strip().lower()
    if len(s) < 6:
        return True  # too short to be a real product slug
    if s.startswith("-") or s.endswith("-") or "--" in s:
        return True  # empty/missing name segment (e.g. "-2022ftd6393sdp")
    # Require at least one real word segment (>=2 ASCII letters, no digits):
    # a name-less id-only slug ("2022ftd6393sdp") has none, every real product
    # name has several. Conservative on purpose - a false skip permanently
    # excludes a product from vector search, so only clear junk is rejected.
    if not any(re.fullmatch(r"[a-z]{2,}", seg) for seg in s.split("-")):
        return True
    return False

_MAX_RETRIES = 4

async def _get_products_with_retry(params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The dev backend rate-limits aggressively (429 'Too many attempts')
    under this job's crawl volume (~130 category/subcategory slices back to
    back) - confirmed empirically, a bare run got 429'd on roughly half the
    later slices. Retries with backoff instead of silently treating a 429 as
    "0 products", which would otherwise look identical to a genuinely empty
    category and risk wrongly pruning still-valid products (see
    sync_products()'s had_errors guard, the other half of this fix)."""
    for attempt in range(_MAX_RETRIES):
        try:
            return await delippy_client.get_products(params=params)
        except Exception as e:
            is_rate_limited = "429" in str(e)
            if attempt == _MAX_RETRIES - 1 or not is_rate_limited:
                print(f"  [SyncProducts] Error fetching {params}: {e}")
                return None
            wait_s = 10 * (attempt + 1)
            print(f"  [SyncProducts] Rate-limited on {params}, retry {attempt + 1}/{_MAX_RETRIES} in {wait_s}s...")
            await asyncio.sleep(wait_s)
    return None

async def _sync_one_slice(
    category_id: int,
    subcategory_id: Optional[int],
    category_name: str,
    subcategory_name: Optional[str],
    sync_run_id: str,
    semaphore: asyncio.Semaphore,
) -> tuple[int, int, bool]:
    """Crawls every product under one category/subcategory pair (cursor
    pagination, 20/page - see api-docs/product_api.md) and upserts each as
    an embedding. Crawling by subcategory (not a flat GET /products) is the
    only way to tag products with category_id/subcategory_id at all: the
    list endpoint's ProductCard has no category field on it - a product
    only "knows" its category because of which filtered call returned it.
    Returns (count, skipped, had_error) - skipped counts malformed-slug
    records dropped before embedding (see _is_malformed_slug); had_error
    distinguishes "genuinely 0 products in this slice" from "couldn't fetch,
    don't trust this as 0"."""
    count = 0
    skipped = 0
    cursor = None
    while True:
        params: Dict[str, Any] = {"category_id": category_id}
        if subcategory_id:
            params["subcategory_id"] = subcategory_id
        if cursor:
            params["cursor"] = cursor

        res = await _get_products_with_retry(params)
        if res is None:
            return count, skipped, True
        if not res.get("success"):
            return count, skipped, True
        products = res.get("data") or []
        if not products:
            break

        # Drop obviously malformed records (missing/junk slug) before spending
        # an embed call on them - they'd only 404 on every later re-verify.
        valid_products = []
        for p in products:
            if _is_malformed_slug(p.get("slug")):
                skipped += 1
                continue
            valid_products.append(p)

        async def _process(p: Dict[str, Any]) -> Optional[Dict[str, Any]]:
            slug = p.get("slug")
            name = p.get("name")
            if not slug or not name:
                return None
            async with semaphore:
                vector = await _embed_product(name, category_name, subcategory_name)
            if not vector:
                return None
            return {
                "slug": slug,
                "name": name,
                "embedding": vector,
                "category_id": category_id,
                "subcategory_id": subcategory_id,
                "price_at_sync": p.get("price"),
                "synced_at": sync_run_id,
            }

        docs = await asyncio.gather(*(_process(p) for p in valid_products))
        for doc in docs:
            if doc:
                await product_vector_repo.upsert(doc)
                count += 1

        meta = res.get("meta") or {}
        if not meta.get("has_more"):
            break
        cursor = meta.get("next_cursor")
        if not cursor:
            break
    return count, skipped, False

async def sync_products():
    """Full-catalog embedding sync - see scripts/atlas_vector_index.md for
    the Atlas Vector Search index this feeds, and search_engine.py for how
    it's queried. v1: embeds `name + category + subcategory` only (no
    per-product GET /products/{slug} detail call for the real description -
    that's a v2 upgrade once this proves out, since it would add several
    thousand extra HTTP calls per run for a "few thousand products" catalog).
    Relies on app/knowledge/categories.json (written by sync_categories())
    for the category/subcategory id+name pairs to crawl - run
    sync_categories() first if that file is missing or stale."""
    base_dir = os.path.dirname(os.path.dirname(__file__))
    categories_path = os.path.join(base_dir, "knowledge", "categories.json")
    if not os.path.exists(categories_path):
        print("[SyncProducts] categories.json not found - run sync_categories() first.")
        return
    with open(categories_path, "r", encoding="utf-8") as f:
        categories = json.load(f)

    sync_run_id = datetime.now(timezone.utc).isoformat()
    semaphore = asyncio.Semaphore(_EMBED_CONCURRENCY)

    print(f"[SyncProducts] Starting sync run {sync_run_id} across {len(categories)} categories...")
    total = 0
    total_skipped = 0
    had_any_error = False
    for category_name, cat_data in categories.items():
        category_id = cat_data.get("id")
        if not category_id:
            continue
        subcategories = cat_data.get("subcategories") or {}
        if not subcategories:
            n, skipped, had_error = await _sync_one_slice(category_id, None, category_name, None, sync_run_id, semaphore)
            print(f"  [SyncProducts] {category_name}: {n} products{' (FETCH ERROR - incomplete)' if had_error else ''}")
            total += n
            total_skipped += skipped
            had_any_error = had_any_error or had_error
            continue
        for sub_name, sub_id in subcategories.items():
            n, skipped, had_error = await _sync_one_slice(category_id, sub_id, category_name, sub_name, sync_run_id, semaphore)
            print(f"  [SyncProducts] {category_name} / {sub_name}: {n} products{' (FETCH ERROR - incomplete)' if had_error else ''}")
            total += n
            total_skipped += skipped
            had_any_error = had_any_error or had_error
            # Proactive throttle - the dev backend 429'd hard under a bare
            # back-to-back crawl of ~130 slices (confirmed empirically). A
            # small gap between slices is cheap insurance against the same
            # in production; _get_products_with_retry's backoff is the
            # reactive backstop for whatever this doesn't prevent.
            await asyncio.sleep(0.3)

    # Pruning deletes anything NOT stamped with this run's id, on the
    # assumption a full, successful crawl means "everything not seen is
    # gone". If ANY slice errored (e.g. rate-limited, see
    # _get_products_with_retry), that assumption is false - a product could
    # be perfectly valid but just not re-confirmed this run. Skip pruning
    # entirely rather than risk deleting live products; retry a full sync
    # once the errors are resolved.
    skipped_note = f" Skipped {total_skipped} malformed-slug record(s) (not embedded)." if total_skipped else ""
    if had_any_error:
        print(f"[SyncProducts] Done. Upserted {total} products this run.{skipped_note} "
              f"Skipped pruning - at least one category/subcategory slice failed to fetch, "
              f"so 'not seen this run' can't be trusted as 'no longer exists'. Re-run to prune safely.")
    else:
        deleted = await product_vector_repo.prune_stale(sync_run_id)
        print(f"[SyncProducts] Done. Upserted {total} products this run, pruned {deleted} stale entries.{skipped_note}")

async def sync_categories():
    print("[Job] Syncing categories from backend...")
    res = await delippy_client.get_categories()
    if res.get("success") and "data" in res:
        # Build category map
        cat_map = {}
        for cat in res["data"]:
            name = cat.get("name", "").lower()
            slug = cat.get("slug")
            sub_map = {}
            for sub in cat.get("subcategories", []):
                sub_name = sub.get("name", "").lower()
                sub_id = sub.get("id")
                sub_map[sub_name] = sub_id
                
            cat_map[name] = {
                "id": cat.get("id"),
                "slug": slug,
                "subcategories": sub_map
            }
            
        # Write to knowledge/categories.json
        base_dir = os.path.dirname(os.path.dirname(__file__))
        path = os.path.join(base_dir, "knowledge", "categories.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cat_map, f, ensure_ascii=False, indent=2)
        print("[Job] Categories synced successfully!")
    else:
        print("[Job] Failed to fetch categories.")

async def _run_cli():
    import sys
    target = sys.argv[1] if len(sys.argv) > 1 else "all"
    if target in ("categories", "all"):
        await sync_categories()
    if target in ("products", "all"):
        await sync_products()

if __name__ == "__main__":
    # python -m app.jobs.sync_products [categories|products|all]
    asyncio.run(_run_cli())
