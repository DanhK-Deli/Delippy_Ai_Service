import asyncio
import re
from typing import List, Dict, Any, Optional
from app.models.shopping_context import ShoppingContext
from app.models.evidence import Evidence
from app.retrieval.search_provider import search_provider
from app.retrieval.ranker import ranker, top_match_confidence
from app.retrieval.evidence_builder import evidence_builder
from app.database.cache_repository import cache_repo
from app.database.product_vector_repository import product_vector_repo
from app.knowledge.ontology import ontology
from app.understanding.query_expander import query_expander
from app.understanding.intent_classifier import is_advisory_query
from app.understanding.entity_extractor import entity_extractor
from app.client.llm_client import llm_client_wrapper
from app.core.config import settings

# Atlas $vectorSearch cosine score is normalized to [0,1] (higher = closer).
# Reasoned starting points, not yet measured against real traffic - tune via
# RETRIEVAL_MODE=shadow's side-by-side logging (see search()) before fully
# cutting over to "vector".
VECTOR_MIN_SCORE = 0.80          # below this: treat as a genuine miss (same zero-result UX as legacy)
VECTOR_LOW_CONFIDENCE_BAND = 0.84  # [MIN_SCORE, this): shown, but Evidence.low_confidence=True

# A vector search run WITHOUT a category pre-filter (the zero-result self-heal
# retry below, or a query that never resolved a category at all) has no
# semantic anchor, so raw cosine score alone is a far weaker relevance signal.
# A live incident had ~15-20 totally unrelated products (ấm siêu tốc, nồi cơm
# điện, giày thể thao...) clear VECTOR_MIN_SCORE for a "laptop" query that had
# no laptop in stock, then get fully live-re-verified at full concurrency and
# hammer the backend into a 429 cooldown. Hold the unanchored path to a higher
# bar, and even when it clears, only live-re-verify the top few candidates:
# that pool is both less trustworthy AND the source of the re-verify burst.
VECTOR_NO_CATEGORY_MIN_SCORE = 0.82
_VECTOR_NO_CATEGORY_VERIFY_LIMIT = 3

_VECTOR_CANDIDATE_LIMIT = 20
# Live re-verify (below) fires one GET /products/{slug} per candidate against
# the rate-limited backend, so it's the steady-state load driver, not just the
# incident's burst. Only the top 5 are ever displayed/sent to the LLM at once
# (response_formatter / orchestrator), so we re-verify just those 5 to keep the
# per-search backend fan-out as low as possible. Deliberate trade-off: re-verify
# DROPS candidates (out of stock, price/brand mismatch), so with no margin the
# first page can come up short of 5, and "xem thêm" pagination will often have
# little or nothing left to page through. Accepted in exchange for fewer
# concurrent backend calls per search (raise this if pagination coverage matters
# more than backend load later).
_VECTOR_VERIFY_LIMIT = 5
_LIVE_VERIFY_CONCURRENCY = 6

_WEAK_WORDS = {"cây", "trái", "bộ", "đồ", "món", "cái", "con", "chiếc", "bao", "hộp", "túi"}

def _has_keyword_overlap(product_name: str, query_q: Optional[str]) -> bool:
    if not query_q:
        return True
    
    # Tokenize query_q and extract specific/non-generic words
    q_words = [w.lower() for w in query_q.split() if len(w) > 1 or w.isdigit()]
    specific_q_words = [w for w in q_words if not ontology.is_generic_word(w)]
    
    # Fall back to using all query words if they are all classified as generic
    check_words = specific_q_words if specific_q_words else q_words
    if not check_words:
        return True
        
    p_name_lower = product_name.lower()
    matched_words = {w for w in check_words if re.search(rf"\b{re.escape(w)}\b", p_name_lower)}
    
    # Reject matching only one weak word when the query has multiple check words
    if len(check_words) >= 2 and len(matched_words) == 1:
        matched_word = next(iter(matched_words))
        if matched_word in _WEAK_WORDS:
            return False
            
    return len(matched_words) > 0

def _best_match(search_res: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Pick the first non-accessory result. A plain keyword search for a
    device name (e.g. "iphone 11") can just as easily return a charger/case
    whose title happens to mention it - without this, compare()/get_detail()'s
    self-heal would pick the accessory as "the product" instead of the device."""
    if not search_res:
        return None
    accessory_keywords = ontology.accessory_rules.get("accessory_keywords", [])
    for p in search_res:
        name_lower = p.get("name", "").lower()
        if not any(ak in name_lower for ak in accessory_keywords):
            return p
    return search_res[0]

class SearchEngine:
    async def search(self, context: ShoppingContext) -> Evidence:
        """Dispatches on RETRIEVAL_MODE (app/core/config.py) - "legacy" (the
        original category+keyword pipeline against /products/search,
        safest fallback), "vector" (Atlas $vectorSearch on product_embeddings
        - see app/database/product_vector_repository.py and
        app/jobs/sync_products.py), "shadow" (serves legacy results but
        also runs vector and logs both, to validate quality/coverage before
        actually cutting production traffic over), or "hybrid" (default -
        see _search_hybrid)."""
        mode = settings.RETRIEVAL_MODE
        if mode == "hybrid":
            return await self._search_hybrid(context)
        if mode == "vector":
            return await self._search_vector(context)
        if mode == "shadow":
            legacy_evidence = await self._search_legacy(context)
            try:
                vector_evidence = await self._search_vector(context)
                legacy_slugs = [p.get("slug") for p in legacy_evidence.products]
                vector_slugs = [p.get("slug") for p in vector_evidence.products]
                overlap = len(set(legacy_slugs) & set(vector_slugs))
                print(
                    f"\n[SearchEngine][shadow] query_q={context.query_q!r} purpose={context.purpose!r} -> "
                    f"legacy={len(legacy_slugs)} products, vector={len(vector_slugs)} products, "
                    f"slug overlap={overlap}"
                )
            except Exception as e:
                print(f"\n[SearchEngine][shadow] vector path errored (legacy result still served): {e}")
            return legacy_evidence
        return await self._search_legacy(context)

    async def _search_hybrid(self, context: ShoppingContext) -> Evidence:
        """Routes to whichever path suits the query's intent instead of
        running both wastefully (shadow) or the same path always (legacy/
        vector): purpose-driven or advisory queries ("tư vấn tủ lạnh tiết
        kiệm điện") have no crisp keyword to match against /products/search,
        so they go to vector first; everything else (a concrete product/
        brand/keyword) goes to legacy first, since it's cheaper (no
        embedding call) and already the more reliable path for exact terms.
        Either way, a zero-result miss on the chosen path immediately tries
        the other one before giving up - self-healing across paths instead
        of just within one."""
        vector_first = bool(context.purpose) or is_advisory_query(context.query_q or "")
        primary, primary_name = (self._search_vector, "vector") if vector_first else (self._search_legacy, "legacy")
        fallback, fallback_name = (self._search_legacy, "legacy") if vector_first else (self._search_vector, "vector")

        evidence = await primary(context)
        if evidence.products:
            return evidence
        print(f"\n[SearchEngine][hybrid] {primary_name} path returned 0 products - falling back to {fallback_name}.")
        return await fallback(context)

    async def _search_vector(self, context: ShoppingContext) -> Evidence:
        """Semantic retrieval path. Only category_id (top-level, 14 buckets)
        is used as a $vectorSearch pre-filter - NOT subcategory_id, even
        though ontology can usually produce one. Confirmed by a real live
        test: "thiết bị nhà bếp tiết kiệm điện" resolved category_id=85
        correctly, but find_category()'s subcategory GUESS landed on
        "thiết bị sử dụng trong nhà" (id 638) when the actual matching
        products (ấm siêu tốc, nồi cơm điện...) live under ids 635/639 -
        same subcategory keyword-tie unreliability patched all session, just
        showing up as a NEW failure mode here: a wrong-but-NONEMPTY filter
        silently returns 1 weak candidate instead of 0 (which would at
        least trigger a fallback). Unfiltered vs category_id-filtered
        vector search returned IDENTICAL top-8 results in that same test -
        semantic similarity alone already clusters into the right category
        most of the time, so subcategory pre-filtering is pure downside risk
        for retrieval, not upside. subcategory_id is still used for the
        pure-browse path below (list_products) - a user EXPLICITLY picking
        a subcategory off a menu is a deliberate action, not an AI guess."""
        category_id = None
        if context.category:
            cat_info = ontology.find_category(context.category)
            if cat_info:
                category_id = cat_info["id"]

        # Fold purpose into the embedded text - it's exactly the kind of need
        # ("tiết kiệm điện", "đi biển") that a keyword search never used but
        # semantic search benefits directly from. Deliberately NOT folding in
        # context.brand: live-measured, appending a brand name collapses this
        # embedding model's similarity the same way it does on the document
        # side (see sync_products.py's _strip_brand docstring) - "máy giặt
        # toshiba" vs a brand-stripped document scored 0.700 vs 0.936 without
        # it. Brand filtering already happens deterministically below (live
        # re-verify's exact-substring check), so dropping it here only
        # removes the dilution, not the actual filtering capability.
        query_text = " ".join(t for t in [context.query_q, context.purpose] if t).strip()

        if not query_text:
            # Nothing to embed at all - a pure category/subcategory browse
            # (e.g. the user picked a subcategory off the zero-result menu).
            # No staleness concern here since /products is live data already.
            # subcategory_id IS trusted here (see docstring) since it's an
            # explicit user pick, not an AI guess.
            subcategory_id = None
            if context.category and context.subcategory:
                subcategory_id = ontology.subcategory_id_for(context.category, context.subcategory)
            raw_results = await search_provider.list_products(
                category_id=category_id, subcategory_id=subcategory_id,
                price_min=context.price_min, price_max=context.price_max,
                limit=_VECTOR_CANDIDATE_LIMIT,
            )
            return evidence_builder.build_search_evidence(raw_results)

        cache_key = f"vecsearch:{query_text}:{category_id}"
        candidates = await cache_repo.get_cached_search(cache_key)
        if not candidates:
            query_vector = await asyncio.to_thread(
                llm_client_wrapper.get_embedding, query_text,
                task_type="RETRIEVAL_QUERY", output_dimensionality=settings.EMBEDDING_DIMENSION,
            )
            if not query_vector:
                print("\n[SearchEngine][vector] Embedding failed (provider unavailable/error) - returning empty evidence.")
                return Evidence()

            candidates = await product_vector_repo.vector_search(
                query_vector, limit=_VECTOR_CANDIDATE_LIMIT, category_id=category_id,
            )
            if not candidates and category_id:
                # Same self-heal idea as the legacy drop-category retry, and
                # cheap on the query side (no LLM call, just a second vector
                # query) - but the resulting pool is unanchored, so it's held
                # to VECTOR_NO_CATEGORY_MIN_SCORE and only its top few get
                # live-re-verified below. Drop category_id so it's cached under
                # (and re-read from) the no-category key, keeping the anchored
                # cache key holding only genuinely category-filtered results.
                print(f"\n[SearchEngine][vector] 0 candidates with category_id={category_id} filter - retrying without it.")
                candidates = await product_vector_repo.vector_search(query_vector, limit=_VECTOR_CANDIDATE_LIMIT)
                category_id = None
                cache_key = f"vecsearch:{query_text}:{category_id}"

            # Cache only slug+score+category ids (cheap, stable) - NEVER the
            # live price/stock, which get re-fetched fresh below every time
            # regardless of cache hit/miss.
            await cache_repo.set_cached_search(cache_key, candidates, ttl_seconds=3600)

        if not candidates:
            return Evidence()

        # category_id is None here iff no category filter was applied to the
        # candidates (never resolved, or dropped by the retry above) - the
        # cache key encodes it, so a cache hit can't misclassify this.
        category_anchored = category_id is not None
        min_score = VECTOR_MIN_SCORE if category_anchored else VECTOR_NO_CATEGORY_MIN_SCORE

        top_score = candidates[0].get("score", 0)
        if top_score < min_score:
            print(f"\n[SearchEngine][vector] Top score {top_score:.3f} below miss threshold {min_score} (category_anchored={category_anchored}) - treating as empty.")
            return Evidence()

        # Mandatory live re-verify: embeddings/price_at_sync can be stale
        # (synced periodically, not real-time) - never present a product
        # without re-checking its actual current price/stock first.
        semaphore = asyncio.Semaphore(_LIVE_VERIFY_CONCURRENCY)

        async def _verify(cand: Dict[str, Any]) -> Optional[Dict[str, Any]]:
            async with semaphore:
                try:
                    detail = await search_provider.get_details(cand["slug"])
                except Exception:
                    return None
            if not isinstance(detail, dict):
                return None
            detail["_vector_score"] = cand.get("score")
            return detail

        # Cap how many candidates we fan out live product-detail calls for:
        # re-verifying all ~20 at full concurrency is what triggered the 429
        # cascade, and even in steady state it doubles backend load for
        # pagination pages most users never open. The unanchored pool is held
        # tighter still - it's ranked by score but semantically noisy (see
        # VECTOR_NO_CATEGORY_MIN_SCORE), so only its very top few earn a call.
        verify_limit = _VECTOR_VERIFY_LIMIT if category_anchored else _VECTOR_NO_CATEGORY_VERIFY_LIMIT
        verify_candidates = candidates[:verify_limit]
        details = await asyncio.gather(*(_verify(c) for c in verify_candidates))

        verified: List[Dict[str, Any]] = []
        for detail in details:
            if not detail:
                continue
            
            # Calculate actual stock: sum of qty in sizes if sizes exist, otherwise top-level stock
            sizes = detail.get("sizes")
            if isinstance(sizes, list) and len(sizes) > 0:
                actual_stock = sum(int(sz.get("qty") or 0) for sz in sizes if isinstance(sz, dict))
            else:
                actual_stock = int(detail.get("stock") or 0)
            
            # Update detail stock with actual calculated stock
            detail["stock"] = actual_stock

            # Verify keyword overlap to filter out completely unrelated products (Bug 1 root fix)
            if not _has_keyword_overlap(detail.get("name", ""), context.query_q):
                continue

            price = detail.get("price")
            if context.price_min is not None and (price is None or price < context.price_min):
                continue
            if context.price_max is not None and (price is None or price > context.price_max):
                continue
            if context.brand and context.brand.lower() not in (detail.get("name") or "").lower():
                continue
            verified.append(detail)

        if not verified:
            print("\n[SearchEngine][vector] All candidates dropped by live price/stock/brand re-verify.")
            return Evidence()

        evidence = evidence_builder.build_search_evidence(verified)
        if top_score < VECTOR_LOW_CONFIDENCE_BAND:
            evidence.low_confidence = True
        return evidence

    async def _search_legacy(self, context: ShoppingContext) -> Evidence:
        cache_key = f"search:{context.query_q}:{context.category}:{context.brand}:{context.price_min}:{context.price_max}"

        # 1. Try Cache
        cached_data = await cache_repo.get_cached_search(cache_key)
        if cached_data:
            print(f"\n[SearchEngine] Cache HIT for key: {cache_key}")
            return evidence_builder.build_search_evidence(cached_data)

        print(f"\n[SearchEngine] Cache MISS. Querying backend...")

        # Determine category ID (+ the specific subcategory, for ranker.py's
        # mismatch check below). context.subcategory is already set when the
        # deterministic parser resolved it straight from the raw query text;
        # otherwise (AI-parser path) re-derive it here from context.category,
        # which for that path is still the AI's free-text label, not yet a
        # slug - find_category() can still reach its subcategory-scoring step
        # on that text.
        category_id = None
        intended_subcategory = context.subcategory
        if context.category:
            cat_info = ontology.find_category(context.category)
            if cat_info:
                category_id = cat_info["id"]
                if not intended_subcategory:
                    intended_subcategory = cat_info.get("subcategory")

        # Brand has no dedicated backend filter param (see delippy_client.py) -
        # ranker.py can only re-rank/filter whatever the backend already
        # returned for `q`, so a brand the backend never saw in the query
        # text can't be found no matter how the ranker scores it afterward.
        # Folding it into the free-text query is search by product and
        # search by brand collapsing into the same backend call.
        effective_q = context.query_q or ""
        if context.brand and context.brand.lower() not in effective_q.lower():
            effective_q = f"{effective_q} {context.brand}".strip()

        subcategory_id = None
        if intended_subcategory and context.category:
            subcategory_id = ontology.subcategory_id_for(context.category, intended_subcategory)

        # Backend API is the single source of truth for product data.
        # /products/search REQUIRES q >= 2 chars - it 422s on anything
        # shorter, and has no subcategory_id param at all (see
        # api-docs/product_api.md). A pure category/subcategory browse with
        # no free-text term (e.g. the user just picked a subcategory off the
        # zero-result menu, or an advisory follow-up stripped query_q down
        # to nothing) used to send q="" straight into /search and silently
        # get treated as "0 results" instead of the 422 it actually was -
        # that's what turned the zero-result subcategory menu into an
        # infinite loop (pick a subcategory -> 422 -> "still not found" ->
        # show the SAME menu again). The /products LIST endpoint has no q
        # param either, but that's fine here - it's also the only place
        # subcategory_id can actually reach the backend.
        if len(effective_q.strip()) >= 2:
            raw_results = await search_provider.search(
                q=effective_q,
                category_id=category_id,
                price_min=context.price_min,
                price_max=context.price_max
            )
        else:
            print(f"  - No usable free-text query - browsing category_id={category_id} subcategory_id={subcategory_id} via /products instead of /products/search.")
            raw_results = await search_provider.list_products(
                category_id=category_id,
                subcategory_id=subcategory_id,
                price_min=context.price_min,
                price_max=context.price_max
            )
        print(f"  - Backend search returned {len(raw_results)} results.")

        # Rank and drop irrelevant matches
        ranked_results = ranker.rank(raw_results, context, intended_subcategory=intended_subcategory)

        # Cache results
        await cache_repo.set_cached_search(cache_key, ranked_results, ttl_seconds=86400)

        evidence = evidence_builder.build_search_evidence(ranked_results)
        # Flag a weak top match - the ranker's relevance gate only requires
        # ONE keyword hit, which lets a single generic word (e.g. "bánh" in
        # "bánh bao kim cương giá 9 tỷ") drag in a result that shares almost
        # nothing else with the query. Doesn't change what's returned, just
        # lets response_formatter/the LLM hedge instead of presenting it as a
        # confident match.
        if ranked_results:
            confidence = top_match_confidence(ranked_results[0].get("name", ""), context.query_q)
            if confidence is not None and confidence < 0.5:
                evidence.low_confidence = True

            # A second, distinct weak spot the ratio above can't see: it's
            # computed over the WORDS THAT SURVIVED ranker's own filtering
            # (single-char, non-digit tokens are dropped there), so a query
            # like "máy i" silently loses "i" and is left comparing only
            # "máy" against the result - a 1/1 = 100% "confident" ratio, even
            # though half of what the user actually typed was discarded
            # first. If that surviving word is itself too generic to mean
            # anything on its own (ontology.is_generic_word - same df/N
            # signal that stops "máy" from locking a wrong category, see
            # ontology.find_category), the apparent 100% match is misleading
            # regardless of the ratio math.
            raw_words = (context.query_q or "").lower().split()
            kept_words = [w for w in raw_words if len(w) > 1 or w.isdigit()]
            if len(raw_words) > len(kept_words) and len(kept_words) <= 1:
                if not kept_words or ontology.is_generic_word(kept_words[0]):
                    evidence.low_confidence = True
        return evidence

    async def search_or_expand(self, context: ShoppingContext) -> Evidence:
        """Wraps search() with a zero-result retry: try the AI parser's free
        expanded_queries first (if any), otherwise make one lazy/dedicated
        LLM call to generate variants, and retry search with each until one
        returns products. Replaces the old "ask the user to teach the
        system" loop - this never writes anything anywhere, it just widens
        the net for this one request.

        In "vector" mode this whole retry chain is skipped - _search_vector
        already retries once internally (drop the category/subcategory
        filter, no LLM) and self-corrects a wrong category resolution by
        design (a wrong filter only narrows the candidate pool, it doesn't
        guarantee zero results the way a wrong category_id did against
        /products/search), so query_expander's LLM call would just be
        spending tokens on a problem vector search doesn't have. "hybrid"
        skips it for the same reason - _search_hybrid already cross-tries
        BOTH vector and legacy as its own self-heal before returning here,
        so a zero-result Evidence at this point already reflects both paths
        failing, not just one path that expansion could still rescue."""
        evidence = await self.search(context)
        if settings.RETRIEVAL_MODE in ("vector", "hybrid") or evidence.products or not context.query_q:
            return evidence

        # Category resolution is best-effort and can be wrong (find_category()
        # can mis-hit a subcategory in a totally unrelated top-level category -
        # e.g. "máy giặt" -> "xe máy" instead of "điện lạnh"). A wrong
        # category_id filter guarantees zero results no matter how the query
        # text is rephrased, so drop it once, for free, before spending tokens
        # on LLM query expansion.
        if context.category:
            print(f"\n[SearchEngine] Zero-result retry without category filter for '{context.query_q}'")
            no_category_evidence = await self.search(context.copy(update={"category": None}))
            if no_category_evidence.products:
                print(f"[SearchEngine] Dropping category filter found {len(no_category_evidence.products)} product(s). Using it.")
                return no_category_evidence

        variants = [v for v in context.expanded_queries if v and v.lower() != context.query_q.lower()]
        if not variants:
            variants = await query_expander.expand(context.query_q)

        for variant in variants:
            print(f"\n[SearchEngine] Zero-result retry with expanded query: '{variant}'")
            # Drop the category filter for variants too. context.category was
            # resolved for the ORIGINAL query_q and is even less likely to fit a
            # rephrased term (e.g. original "áo chống nắng" -> fashion/77, but
            # the variant "kem chống nắng" is sunscreen, health & beauty/76) -
            # keeping the stale category_id guaranteed 0 results for a variant
            # whose real products live elsewhere. Same "drop it, don't re-guess"
            # rationale as the category-drop retry above; harmless when the
            # category was right, since this only runs after the with-category
            # search already returned 0.
            variant_context = context.copy(update={"query_q": variant, "category": None})
            variant_evidence = await self.search(variant_context)
            if variant_evidence.products:
                print(f"[SearchEngine] Expanded query '{variant}' found {len(variant_evidence.products)} product(s). Using it.")
                return variant_evidence

        if variants:
            print(f"[SearchEngine] All {len(variants)} expanded variant(s) also returned 0 results for '{context.query_q}'.")
        return evidence

    async def get_detail(self, slug: str) -> Evidence:
        if not slug:
            # Empty slug means the caller couldn't resolve which product is
            # meant - GET /products/ (no id) hits the LIST endpoint, not a
            # 404, and returns a list where a dict is expected, crashing
            # product_id = detail.get("id") below. Bail out before calling
            # the API at all rather than guessing.
            return Evidence(error="Không xác định được sản phẩm cần xem chi tiết.")

        cache_key = f"detail:{slug}"
        cached_evidence_dict = await cache_repo.get_cached_search(cache_key)
        if cached_evidence_dict:
            return Evidence(**cached_evidence_dict)

        print(f"\n[SearchEngine] Detail requested for slug guess: '{slug}'")
        detail = None
        try:
            detail = await search_provider.get_details(slug)
        except Exception:
            pass
        if not isinstance(detail, dict):
            detail = None

        if not detail:
            # Self-healing: if direct fetch fails, search for matching product in API and use its actual slug
            cleaned_q = slug.replace("-", " ").replace("xem chi tiết", "").replace("chi tiết", "").strip()
            print(f"  - Direct fetch failed. Searching closest match for query: '{cleaned_q}'")
            search_res = await search_provider.search(q=cleaned_q)
            best_match = _best_match(search_res)
            if best_match:
                real_slug = best_match.get("slug")
                if real_slug and real_slug != slug:
                    print(f"  - Found real slug: '{real_slug}'. Re-fetching details...")
                    detail = await search_provider.get_details(real_slug)
                    if not isinstance(detail, dict):
                        detail = None
                    slug = real_slug

        if not detail:
            return Evidence(error=f"Không tìm thấy thông tin sản phẩm cho '{slug}'")

        product_id = detail.get("id")
        reviews_summary = None
        if product_id:
            reviews_summary = await search_provider.get_reviews_summary(product_id)

        related = await search_provider.get_related(slug)

        evidence = evidence_builder.build_detail_evidence(detail, reviews_summary, related)
        await cache_repo.set_cached_search(cache_key, evidence.dict(), ttl_seconds=1800)
        return evidence

    async def compare(self, context: ShoppingContext, cached_products: Optional[List[Dict[str, Any]]] = None) -> Evidence:
        details = []
        not_found = []
        # Position-based references ("so sánh số 1 và số 3", "so sánh 2 cái
        # đầu tiên") get resolved into compare_targets as each product's
        # EXACT name (see parser_prompt.txt) - so if it's one we already
        # have cached (just shown this session), look it up by that known
        # slug directly instead of re-searching the backend by the raw name
        # text. Full product titles are long/punctuation-heavy (e.g. "Laptop
        # Cũ Dell latitude e7450 cũ / i5*5300U/ RAM 8G/...") and routinely
        # return 0 results as a free-text query even though the product is
        # right there - that was silently degrading every position-based
        # compare into "not found" + an unrelated category listing.
        cached_by_name = {
            (p.get("name") or "").strip().lower(): p
            for p in (cached_products or []) if p.get("name") and p.get("slug")
        }
        for target in context.compare_targets[:3]:
            detail = None
            cached_hit = cached_by_name.get(target.strip().lower())
            if cached_hit:
                detail = await search_provider.get_details(cached_hit["slug"])
            if not detail:
                # /products/search does an AND-token match against the raw
                # query text, so a filler word inside `target` ("của", "là"...)
                # that never appears in the product's own name/title is
                # enough to zero out an otherwise-real match - confirmed
                # live: 'sữa bột của colos glucomi' (the raw compare target,
                # containing "của") returned 0 results against a catalog
                # product literally named "Sữa bột Colos Glucomin...",
                # while the SAME text with "của" stripped matched it fine.
                # clean_query_keywords is the same stopword strip the plain
                # SEARCH path already gets - falls back to the raw target if
                # cleaning empties it out entirely.
                cleaned_target = entity_extractor.clean_query_keywords(target) or target
                search_res = await search_provider.search(q=cleaned_target)
                best_match = _best_match(search_res)
                if best_match:
                    slug = best_match.get("slug")
                    if slug:
                        detail = await search_provider.get_details(slug)
            if detail:
                details.append(detail)
            else:
                not_found.append(target)

        suggestions = []
        if not_found:
            # A target wasn't in the catalog at all - offer real, in-catalog
            # alternatives instead of just an empty answer. Never invented:
            # only actual products from the category the targets themselves
            # point to (e.g. "iphone 15" -> "điện thoại & tablet").
            cat_info = ontology.find_category(" ".join(context.compare_targets))
            if cat_info:
                suggestions = await search_provider.list_by_category(cat_info["id"], limit=3)

        return evidence_builder.build_comparison_evidence(details, not_found, suggestions)

search_engine = SearchEngine()
