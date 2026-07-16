import re
from typing import Any, Dict, List, Optional
from app.understanding.query_normalizer import query_normalizer
from app.understanding.intent_classifier import intent_classifier, is_advisory_query, REFERENCE_MARKERS, is_no_preference_reply
from app.understanding.few_shot_selector import select_examples, try_embedding_fastpath
from app.understanding.entity_extractor import entity_extractor
from app.chat.lazy import Lazy
from app.client.llm_client import llm_client_wrapper
from app.database.parse_cache_repository import parse_cache_repo
from app.models.shopping_context import ShoppingContext
from app.knowledge.ontology import ontology

def _weak_candidate_payload(weak: Dict[str, Any]) -> Dict[str, Optional[str]]:
    """Shapes an ontology.find_category_weak() result into what
    response_planner.py/response_formatter.py/memory_resolver.py need: a
    slug+subcategory pair to APPLY if the user confirms, plus a
    human-readable name to show IN the question. Prefers the subcategory
    name (already human-readable, e.g. "sữa - tả - bình sữa") since it's
    more specific than the top-level category display name."""
    return {
        "category": weak.get("slug"),
        "subcategory": weak.get("subcategory"),
        "display": weak.get("subcategory") or ontology.category_display_name(weak.get("slug")),
    }

# Matches "số 1", "phòng số 2", "sản phẩm số 3"... Deliberately NOT "thứ N" -
# "thứ 2"/"thứ 4"/"thứ 7" etc. are also the standard Vietnamese way to write
# weekdays (Monday/Wednesday/Saturday), so that pattern is left to the AI
# Parser (which has conversation context to disambiguate) rather than risking
# a wrong deterministic guess. "số N" carries no such calendar ambiguity.
_ORDINAL_REF_RE = re.compile(r"\bsố\s*(\d{1,2})\b")

# A BARE number ("2", "2.") as the entire message - only meaningful right
# after a numbered product list (response_formatter's structured menu tells
# the user exactly to reply this way), gated the same as _ORDINAL_REF_RE on
# product_options actually having that many items. fullmatch (not search) is
# deliberate: a number embedded in a longer sentence ("giá khoảng 2 triệu")
# must NOT be treated as picking item #2.
_BARE_ORDINAL_RE = re.compile(r"^(\d{1,2})[.\)]?$")

# "từ 1 đến 4" / "từ 2 tới 5" - a RANGE pick off the zero-result subcategory
# menu (see the subcategory_options branch below). Checked before the
# single-ordinal shortcut since it's a more specific pattern (two numbers).
_ORDINAL_RANGE_RE = re.compile(r"\btừ\s*(\d{1,2})\s*(?:đến|den|tới|toi|-)\s*(\d{1,2})\b")

# "so sánh 1 và 2" / "so sánh số 1 với số 3" - position-based compare against
# a just-shown numbered list, resolved directly to those items' NAMES (see
# search_engine.compare()'s cached-by-name lookup) with no AI parser call.
# Mirrors the AI parser's own position-based compare instructions
# (parser_prompt.txt) but deterministically, for the common two-number case.
_COMPARE_ORDINALS_RE = re.compile(
    r"(?:so sánh|so sanh)\s*(?:(?:số|so)\s*)?(\d{1,2})\s*(?:và|va|,|với|voi)\s*(?:(?:số|so)\s*)?(\d{1,2})\b"
)

# Splits a SHORT free-text compare ("so sánh sữa bột và vớ", "sữa bột khác gì
# vớ", "sữa bột vs vớ") into its two targets - reuses the exact connector
# phrases intent_classifier's own COMPARE check already fired on (see
# classify()'s "so sánh"/"khác gì"/" vs "/" so với " keyword list), so by the
# time this runs we already know one of them is present. maxsplit=1 so a
# target that itself contains a second "và" ("sữa và bột và vớ") still only
# splits once, at the FIRST connector - the two resulting halves are cleaned
# with clean_query_keywords() same as the rest of the deterministic path (see
# below), which strips the "so sánh"/"so sanh" lead-in on the left half.
_COMPARE_TARGET_SPLIT_RE = re.compile(
    r"\s*\b(?:so với|so voi|khác gì|khac gi|và|va|với|voi|vs)\b\s*"
)

class QueryParser:
    async def parse(
        self,
        query: str,
        history_lazy: Lazy,
        product_options: Optional[List[Dict[str, Any]]] = None,
        subcategory_options: Optional[List[Dict[str, Any]]] = None,
        subcategory_category_slug: Optional[str] = None,
        query_vector_lazy: Optional[Lazy] = None,
    ) -> ShoppingContext:
        # 1. Normalize
        normalized = query_normalizer.normalize(query)

        # 1.5a Position-based compare against a just-shown numbered list
        # ("so sánh 1 và 2") - checked before the single-ordinal shortcut
        # below since it's a more specific pattern (two numbers, not one).
        # Falls through to normal parsing when the list doesn't have both
        # positions (e.g. no product list shown yet, or an out-of-range index).
        compare_match = _COMPARE_ORDINALS_RE.search(normalized)
        if compare_match and product_options:
            i1, i2 = int(compare_match.group(1)), int(compare_match.group(2))
            if i1 != i2 and 1 <= i1 <= len(product_options) and 1 <= i2 <= len(product_options):
                name1 = product_options[i1 - 1].get("name")
                name2 = product_options[i2 - 1].get("name")
                if name1 and name2:
                    print(f"\n[Parser] Parsing raw query: '{query}'")
                    print(f"  - Deterministic position compare -> #{i1} ({name1!r}) vs #{i2} ({name2!r})")
                    return ShoppingContext(intent="COMPARE", compare_targets=[name1, name2])

        # 1.5a-bis Range pick off the zero-result subcategory menu ("từ 1 đến
        # 4") - inherently ambiguous whether the user means "search across
        # exactly these 4" or "show me more broadly, don't make me pick just
        # one", so resolved to the safer/simpler reading: broaden to the
        # WHOLE top-level category (no specific `subcategory` filter) rather
        # than guessing a multi-subcategory combination. Without this, the
        # range phrase fell through to the AI parser, which had no better
        # answer than re-showing the identical menu - the exact "not found ->
        # menu -> pick -> still not found -> same menu" loop the single-
        # ordinal shortcut above was built to prevent, just for a new input
        # shape the AI parser doesn't reliably resolve either.
        range_match = _ORDINAL_RANGE_RE.search(normalized)
        if range_match and subcategory_options:
            lo, hi = int(range_match.group(1)), int(range_match.group(2))
            if lo > hi:
                lo, hi = hi, lo
            if 1 <= lo and hi <= len(subcategory_options):
                print(f"\n[Parser] Parsing raw query: '{query}'")
                print(f"  - Deterministic range pick -> subcategories #{lo}-#{hi}, broadening to top-level category")
                ctx = ShoppingContext(intent="SEARCH", category=subcategory_category_slug, query_q=None)
                ctx._no_text_search = True
                return ctx

        # 1.5b Ordinal reference to a just-shown list ("phòng số 1", "sản
        # phẩm số 3", a bare "2" answering a numbered menu, or "số 10" picking
        # a subcategory off the zero-result menu) - resolve directly against
        # the cached list instead of paying for an AI Parser call to reason
        # about which item "số N"/a bare number means. Scoped to short
        # queries only (mirrors intent_classifier's own length guard below)
        # and to an in-range index, so a coincidental "số N" inside a
        # longer/unrelated sentence (a phone number, a price) never misfires -
        # out-of-range just falls through to normal parsing. subcategory_options
        # checked FIRST: it's only ever non-empty right after we just showed
        # that exact menu (orchestrator clears it the moment a real product
        # search succeeds), so it's the more recent context whenever both
        # happen to be present.
        if len(query.split()) <= 6:
            ordinal_match = _ORDINAL_REF_RE.search(normalized) or _BARE_ORDINAL_RE.fullmatch(normalized)
            if ordinal_match:
                ordinal = int(ordinal_match.group(1))
                if subcategory_options and 1 <= ordinal <= len(subcategory_options):
                    target = subcategory_options[ordinal - 1]
                    print(f"\n[Parser] Parsing raw query: '{query}'")
                    print(f"  - Deterministic ordinal reference -> subcategory #{ordinal}: '{target.get('name')}'")
                    ctx = ShoppingContext(
                        intent="SEARCH",
                        category=subcategory_category_slug,
                        subcategory=target.get("name"),
                        query_q=None,
                    )
                    ctx._no_text_search = True
                    return ctx
                if product_options and 1 <= ordinal <= len(product_options):
                    target = product_options[ordinal - 1]
                    print(f"\n[Parser] Parsing raw query: '{query}'")
                    print(f"  - Deterministic ordinal reference -> #{ordinal}: '{target.get('name')}'")
                    return ShoppingContext(
                        intent="PRODUCT_INFO",
                        product=target.get("slug"),
                        query_q=target.get("name"),
                    )

        # 2. Classify intent deterministically
        classify_res = intent_classifier.classify(normalized)
        intent = None
        sub_intent = None
        if classify_res is not None:
            intent, sub_intent = classify_res
        
        # 3. Extract entities
        entities = entity_extractor.extract(normalized)

        print(f"\n[Parser] Parsing raw query: '{query}'")
        print(f"  - Normalized  : '{normalized}'")
        print(f"  - Intent Rule : {intent}")
        print(f"  - Entities    : Brand={entities['brand']}, Category={entities['category']} (ID={entities['category_id']}), PriceMin={entities['price_min']}, PriceMax={entities['price_max']}")

        # A deterministic COMPARE needs its two targets split out - without
        # this, compare_targets stayed empty (only query_q was ever set here)
        # and search_engine.compare() iterates `context.compare_targets`, so
        # it silently did NOTHING (no backend lookup for either side at all)
        # and fell through to an ungrounded LLM answer. Confirmed live: "so
        # sánh sữa bột và vớ" ran zero product searches, straight to the
        # Response Formatter on history alone.
        compare_targets: List[str] = []
        if intent == "COMPARE":
            parts = [entity_extractor.clean_query_keywords(p) for p in _COMPARE_TARGET_SPLIT_RE.split(normalized, maxsplit=1)]
            compare_targets = [p for p in parts if p]
            if len(compare_targets) != 2:
                # Couldn't cleanly resolve exactly two sides (e.g. cleaning
                # emptied one out) - let the AI parser take a real look
                # instead of returning a COMPARE with unusable targets.
                intent = None

        if intent is not None:
            cleaned_q = entity_extractor.clean_query_keywords(normalized)
            # Only SEARCH carries a consultation_level - and only "none" vs
            # "expert" is reachable here: reaching this deterministic branch
            # at all requires an explicit verb match (_SEARCH_RE), so a bare
            # ambiguous noun phrase ("Laptop Dell") never lands here - it has
            # no matching verb, so classify() already returned None for it
            # and it falls through to the AI parser below, which is where
            # "assist" actually gets decided.
            consultation_level = ("expert" if is_advisory_query(query) else "none") if intent == "SEARCH" else None
            print(f"  - Deterministic Parse Result -> Intent: {intent}, Sub Intent: {sub_intent}, Consultation: {consultation_level}, Core Query q: '{cleaned_q}'"
                  + (f", Compare Targets: {compare_targets}" if intent == "COMPARE" else ""))
            ctx = ShoppingContext(
                intent=intent,
                sub_intent=sub_intent,
                consultation_level=consultation_level,
                category=entities["category"],
                subcategory=entities["subcategory"],
                brand=entities["brand"],
                price_min=entities["price_min"],
                price_max=entities["price_max"],
                query_q=cleaned_q,
                compare_targets=compare_targets,
            )
            if intent == "SEARCH" and not entities["category"] and entities["weak_category"]:
                ctx._category_confirm_candidate = _weak_candidate_payload(entities["weak_category"])
            return ctx

        # 4. Semantic parse cache - skip the Gemini parse entirely when a
        # sufficiently similar PAST query was already parsed AND led to a
        # confirmed successful search (see parse_cache_repository + the
        # orchestrator write site). Reuses the orchestrator's already-computed
        # query_vector, so a MISS costs one Mongo scan, not a second embedding.
        # Reference queries ("cái đó", "thứ 2"...) are excluded: they depend on
        # THIS session's shown products, not a global concept, so they must go
        # to the AI parser (which gets conversation history) instead of matching
        # some unrelated cached concept.
        #
        # A query with NO content of its own beyond price/quantity/stopword
        # phrasing ("dưới 500k", "dưới 100k") is equally unsafe to match
        # against the (global, cross-session) cache: its embedding is
        # dominated by the generic price phrasing, not product intent, so two
        # completely unrelated bare-price queries can score falsely high
        # similarity - observed live: "dưới 500k" matched a cached "dưới
        # 100k" parse at 0.88 (above the 0.86 floor) and silently injected
        # that OTHER session's "áo"/"thời trang nữ" into a turn that never
        # mentioned clothing, discarding whatever this session was actually
        # about. Reuses the same clean_query_keywords() the deterministic
        # path already uses for cleaned_q (step 3) - no new heuristic, and
        # this session's own query_q/category is what memory_resolver.resolve()
        # correctly carries forward instead (see its query_q backfill).
        has_own_content = bool(entity_extractor.clean_query_keywords(normalized).strip())
        is_reference = any(marker in f" {normalized} " for marker in REFERENCE_MARKERS)
        # A no-preference reply ("nào cũng được", "không quan tâm"...) is the
        # SAME failure shape as a bare-price phrase above: its embedding is
        # dominated by the generic indifference wording, not real product
        # intent, so it can score falsely high similarity against an
        # unrelated cached concept. Confirmed live: "nào cũng được" (a
        # skincare Consultation Flow's own no-preference answer) matched an
        # unrelated cached "sức khỏe & làm đẹp" health concept and silently
        # replaced the live sunscreen topic with it. This is meant as
        # defense-in-depth - a live Consultation Flow reply should normally
        # be caught earlier by orchestrator._resolve_gap_fill_answer and
        # never even reach here - but a reply that DOES fall through this far
        # must still never touch the global cache.
        skip_semantic_cache = is_reference or not has_own_content or is_no_preference_reply(normalized)
        query_vector = await query_vector_lazy.get() if query_vector_lazy and not skip_semantic_cache else None

        # 4.5 Embedding fast-path for CHITCHAT/SOCIAL phrasing classify()'s
        # regex list doesn't cover (paraphrases of a joke/off-topic ask/social
        # nicety) - matches against the same example pool via the local
        # (free) Nomic embedding, gated by the SAME skip_semantic_cache guard
        # above: a short/reference/no-preference message has too little
        # embedding signal to trust against ANY global pool, chitchat
        # examples included (see the "dưới 500k" false-match precedent right
        # above). A confident match returns a full ShoppingContext straight
        # from that example's own output - response_formatter already renders
        # CHITCHAT/SOCIAL/GREETING as a $0 deterministic reply, so this skips
        # the ~4000-token AI Parser call entirely with no other change needed.
        if query_vector and not skip_semantic_cache:
            fastpath_ctx = try_embedding_fastpath(query_vector)
            if fastpath_ctx:
                print(f"  - Embedding fast-path -> Intent: {fastpath_ctx.intent}, Sub Intent: {fastpath_ctx.sub_intent}")
                return fastpath_ctx

        if query_vector and not skip_semantic_cache:
            cached = await parse_cache_repo.lookup(query_vector)
            if cached:
                cp = cached["parse"]
                # Safety Guard: If both current and cached queries have different categories, reject the cache hit
                cache_cat = cp.get("category")
                curr_cat = entities.get("category")
                if cache_cat and curr_cat and cache_cat.strip().lower() != curr_cat.strip().lower():
                    print(f"  - [Parser] Rejecting Semantic cache HIT due to category mismatch: cache={cache_cat!r}, current={curr_cat!r}")
                    cached = None
            if cached:
                cp = cached["parse"]
                print(f"  - [Parser] Semantic cache HIT - reusing prior parse "
                      f"(similarity={cached['similarity']:.2f}, cached {cached['age_days']}d ago, "
                      f"orig={cached['query_text']!r}) -> skipping Gemini parse call.")
                # Reuse the cached SEMANTIC parse (intent/category/query_q/
                # expanded/purpose), but apply THIS turn's own deterministically-
                # extracted brand/price - the cached turn's brand/price came from
                # different wording and must never leak in. category mirrors the
                # AI-path overlay below: cached concept wins, this turn's
                # deterministic category only fills a gap the cache left empty.
                # subcategory only means anything WITHIN the category it was
                # resolved from - never pair the cache's own category with
                # entities["subcategory"] (or vice versa), or a coincidental
                # entity_extractor category misfire (e.g. "tủ lạnh" wording
                # scoring highest against an unrelated "sách" subcategory)
                # silently attaches a subcategory from a DIFFERENT category
                # than the one actually being searched.
                cache_category = cp.get("category")
                
                # Prevent brand drop during cache hits: if the deterministic extractor failed to
                # detect the brand, but the cached parse contains a brand, we can safely fall
                # back to it ONLY if the brand name is explicitly mentioned in the query text.
                brand = entities["brand"]
                if not brand and cp.get("brand"):
                    cached_brand = cp["brand"].strip().lower()
                    if re.search(rf"\b{re.escape(cached_brand)}\b", normalized):
                        brand = cp["brand"]

                ctx = ShoppingContext(
                    intent=cp.get("intent", "SEARCH"),
                    sub_intent=cp.get("sub_intent"),
                    consultation_level=cp.get("consultation_level"),
                    category=cache_category or entities["category"],
                    subcategory=cp.get("subcategory") if cache_category else entities["subcategory"],
                    query_q=cp.get("query_q"),
                    expanded_queries=list(cp.get("expanded_queries") or []),
                    purpose=cp.get("purpose"),
                    brand=brand,
                    price_min=entities["price_min"],
                    price_max=entities["price_max"],
                )
                ctx._parse_source = "cache"

                print(f"  - Cache-hit Parse Result -> Intent: {ctx.intent}, Brand: {ctx.brand}, Category: {ctx.category}, PriceMin: {ctx.price_min}, PriceMax: {ctx.price_max}, Core Query q: '{ctx.query_q}', Expanded: {ctx.expanded_queries}")
                return ctx

        # 5. Fallback to Gemini AI Parse
        print("  - Intent ambiguous. Falling back to AI Parser...")
        history_str = await history_lazy.get()
        # Dynamic Few-Shot Selection: parser_prompt.txt's fixed few-shot
        # block used to embed all 21 examples on EVERY AI-parser call
        # (~1,700 fixed tokens, the actual biggest single line item in this
        # prompt - see few_shot_selector.py's own docstring for the full
        # breakdown). Reuses THIS turn's own query embedding (already
        # computed for the semantic parse cache check above, or computed
        # fresh here if that check was skipped - query_vector_lazy memoizes,
        # so this is never a second embedding call) to pick the few pool
        # examples most relevant to THIS message, on top of a fixed anchor
        # set covering every major decision boundary regardless of
        # similarity (see few_shot_selector.select_examples).
        message_vector = await query_vector_lazy.get() if query_vector_lazy else None
        examples = select_examples(message_vector)
        ai_context = await llm_client_wrapper.parse_query(
            query, history_str, product_options=product_options, examples=examples,
        )

        # Overlay deterministic entities if AI missed them. subcategory is
        # ONLY ever overlaid alongside category (both from entity_extractor
        # together, guaranteed consistent) - never mixing the AI's OWN
        # resolved category with entity_extractor's subcategory guess, which
        # can come from a COMPLETELY different (mis-resolved) category. Bug
        # confirmed live: AI correctly resolved "tủ lạnh", but entity_extractor's
        # own category/subcategory guess for that exact message was "sách"/
        # "sách văn học trong nước" (a coincidental word-overlap misfire) -
        # unconditionally attaching that subcategory poisoned
        # _has_new_search_signal's subcategory check (any truthy subcategory
        # is treated as an automatic new-topic signal), which in turn
        # defeated the advisory-follow-up-grounds-in-cache path.
        if not ai_context.brand and entities["brand"]:
            ai_context.brand = entities["brand"]
        # Category/subcategory only mean anything for a product-bearing intent
        # (SEARCH/COMPARE/PRODUCT_INFO). entity_extractor.extract() runs
        # find_category() on the raw text with zero intent-awareness, so for a
        # GREETING/SOCIAL/CHITCHAT/FAQ turn its guess is often a coincidental
        # single-word misfire that only LOOKS trustworthy (find_category()'s
        # rare-word tie-break exists precisely to let real rare nouns like
        # "áo"/"quần" resolve on their own - see ontology.py - but that same
        # rule also lets a token like "trẻ" resolve confidently off ITS rare
        # vocabulary even when the actual word was "trẻ trung", unrelated to
        # "trẻ em"). Confirmed live: "trẻ trung" correctly parsed as
        # CHITCHAT/out_of_scope with no category from the AI, then this overlay
        # stamped category="me-be" onto it anyway, purely because "trẻ" ties
        # to the mẹ & bé vocabulary.
        if ai_context.intent in ("SEARCH", "COMPARE", "PRODUCT_INFO"):
            if not ai_context.category and entities["category"]:
                ai_context.category = entities["category"]
                if not ai_context.subcategory and entities["subcategory"]:
                    ai_context.subcategory = entities["subcategory"]
            elif ai_context.intent == "SEARCH" and not ai_context.category and entities["weak_category"]:
                # AI ALSO found no confident category (same gate reasoning as
                # the deterministic branch above - see there) - surface the
                # weak guess for a confirm question instead of just accepting
                # a category-less search.
                ai_context._category_confirm_candidate = _weak_candidate_payload(entities["weak_category"])

        # Tag as a fresh AI parse and snapshot its SESSION-INDEPENDENT semantic
        # fields (pre memory-merge) so the orchestrator can cache it verbatim if
        # the search succeeds. brand/price are omitted on purpose (turn-specific).
        ai_context._parse_source = "ai"
        ai_context._ai_parse = {
            "intent": ai_context.intent,
            "sub_intent": ai_context.sub_intent,
            "consultation_level": ai_context.consultation_level,
            "category": ai_context.category,
            "subcategory": ai_context.subcategory,
            "query_q": ai_context.query_q,
            "expanded_queries": list(ai_context.expanded_queries or []),
            "purpose": ai_context.purpose,
        }

        print(f"  - AI Parse Result -> Intent: {ai_context.intent}, Consultation: {ai_context.consultation_level}, Brand: {ai_context.brand}, Category: {ai_context.category}, PriceMax: {ai_context.price_max}, Core Query q: '{ai_context.query_q}', Expanded: {ai_context.expanded_queries}")
        return ai_context

query_parser = QueryParser()
