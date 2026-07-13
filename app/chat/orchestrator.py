import asyncio
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from app.chat.session_manager import session_manager
from app.understanding.parser import query_parser
from app.understanding.intent_classifier import is_advisory_query, is_too_vague_for_results, classify_faq_topic, is_no_preference_reply, is_tech_explain_query, is_deep_consult_query
from app.understanding.entity_extractor import entity_extractor
from app.chat.memory_resolver import memory_resolver, _shares_a_word
from app.chat.lazy import Lazy
from app.retrieval.search_engine import search_engine
from app.retrieval.evidence_builder import evidence_builder
from app.chat.response_formatter import response_formatter
from app.chat.response_planner import response_planner
from app.chat.compare_builder import compare_builder
from app.chat.recommendation_builder import recommendation_builder
from app.models.shopping_context import ShoppingContext
from app.models.evidence import Evidence
from app.client.llm_client import llm_client_wrapper
from app.database.conversation_repository import conversation_repo
from app.database.parse_cache_repository import parse_cache_repo
from app.knowledge.ontology import ontology
import json
import random
import re

# Frontend renders this as a "Xem thêm" button; clicking it re-sends the
# label as a chat message, which the "xem thêm" keyword check below matches.
SEE_MORE_ACTION = {"action": "see_more", "label": "Xem thêm", "message": "Xem thêm"}

def _tokens(text: str) -> List[str]:
    """Whole-word tokens, lowercased, splitting on any non-word char so
    punctuation in product names ("i5*5300U/", "Áo-Thun") never fuses or
    blocks a token. \\w is Unicode here, so Vietnamese diacritics stay intact."""
    return re.findall(r"\w+", text.lower(), flags=re.UNICODE)

def _filter_cached_products(products: List[Dict[str, Any]], context: ShoppingContext) -> List[Dict[str, Any]]:
    """Zero-cost fast path for follow-ups like "tìm thêm laptop cũ" /
    "còn loại nào khác không" that are really just asking about products
    already fetched this session. Matches query_q/expanded_queries (as
    AND-within-a-phrase, OR-across-phrases) against cached product names -
    no API call, no LLM call. Only ever a subset of what's cached (max 20
    items, see evidence_builder), so an empty match here just means "fall
    through to a real search", never "nothing exists".

    Must also honor brand/price - the cached list was true for the PREVIOUS
    turn's constraints, not this turn's. Without checking brand, asking for
    "asus" right after browsing a cached list of non-Asus laptops falsely
    matched on the word "laptop" alone and reported "no Asus in stock" even
    though the real catalog has one - the cache never got a chance to be
    refreshed with a search that actually filters by brand."""
    if not products or not context.query_q:
        return []
    phrases = [context.query_q, *context.expanded_queries]
    # Each phrase becomes its list of >1-char word tokens; a product matches a
    # phrase only when those tokens appear as a CONTIGUOUS whole-word run in the
    # name (AND-within-a-phrase-in-order, OR-across-phrases). The old
    # `all(w in name)` check accepted the words scattered anywhere as bare
    # substrings, which produced two false-positive classes: (1) scattered
    # words - "đồ ăn" (food) matched "SET ĐỒ CHƠI NẤU ĂN" (a toy) because "đồ"
    # sat in "đồ chơi" and "ăn" in "nấu ăn", two unrelated parts of the name;
    # (2) the classic substring collision this codebase keeps getting bitten by
    # - "áo" matching "cháo". Whole-word contiguous matching kills both. Erring
    # strict is safe here: a false negative just falls through to a real search
    # (see docstring), whereas a false positive silently answers from the wrong
    # cached products. Word order is treated as fixed - Vietnamese product nouns
    # are order-stable ("bánh tráng", "laptop cũ"), and the expanded_queries
    # already supply phrasing variants as separate OR-groups if one is needed.
    keyword_groups: List[List[str]] = []
    for p in phrases:
        if not p:
            continue
        toks = [w for w in _tokens(p) if len(w) > 1]
        if toks:
            keyword_groups.append(toks)
    if not keyword_groups:
        return []

    def _contiguous(group: List[str], name_tokens: List[str]) -> bool:
        span = len(group)
        return any(name_tokens[i:i + span] == group for i in range(len(name_tokens) - span + 1))

    def _matches(p: Dict[str, Any]) -> bool:
        name = (p.get("name") or "").lower()
        name_tokens = _tokens(name)
        if not any(_contiguous(group, name_tokens) for group in keyword_groups):
            return False
        if context.brand and context.brand.lower() not in name:
            return False
        price = p.get("price")
        if context.price_min is not None and (price is None or price < context.price_min):
            return False
        if context.price_max is not None and (price is None or price > context.price_max):
            return False
        return True

    return [p for p in products if _matches(p)]

def _has_new_search_signal(context: ShoppingContext, prev: Dict[str, Any]) -> bool:
    """True when THIS turn introduced a distinguishing constraint the cached
    list wasn't built for, so an advisory follow-up should trigger a fresh
    search instead of reusing the cache. `prev` is the pre-resolve snapshot of
    memory's constraints; memory_resolver has already merged this turn into
    context, so a value that differs from `prev` is genuinely new this turn
    (a value equal to `prev` was merely carried forward - not a new signal).
    Category uses shared-word comparison, matching how memory_resolver decides
    a topic change, so consistent re-phrasing of the same topic isn't treated
    as new."""
    if context.subcategory:
        return True
    if context.brand and context.brand != prev.get("brand"):
        return True
    if context.price_min is not None and context.price_min != prev.get("price_min"):
        return True
    if context.price_max is not None and context.price_max != prev.get("price_max"):
        return True
    if context.category and not _shares_a_word(context.category, prev.get("category")):
        return True
    # query_q is the actual product noun. Only a CONCRETE new noun counts as a
    # new signal: both this turn's and the prior query_q must be non-empty and
    # share no word. The non-empty guards are the whole point - advisory
    # phrasing ("cái nào rẻ nhất") deliberately strips query_q to near-empty/
    # generic (that's WHY cache-grounding exists), so a missing/emptied query_q
    # this turn, or no prior noun to compare against, must NOT trigger a
    # re-search. Shared-word tolerance (same as category) keeps a re-phrasing of
    # the same product ("bánh" vs "bánh tráng") grounded in cache, while a
    # genuinely different noun (cached snacks, now asking about "bánh") re-searches.
    prev_query_q = prev.get("query_q")
    if context.query_q and prev_query_q and not _shares_a_word(context.query_q, prev_query_q):
        return True
    return False

# "the OTHER / remaining one" - only meaningful right after a COMPARE, where it
# refers to whichever of the two just-compared items the user did NOT just drill
# into. Word-boundary-padded phrases so they fire as standalone references.
_OTHER_COMPARED_MARKERS = [
    "còn lại", "con lai", "cái còn lại", "cai con lai", "sản phẩm còn lại", "san pham con lai",
    "cái kia", "cai kia", "sản phẩm kia", "san pham kia", "món kia", "mon kia", " kia ",
]

def _resolve_other_compared_item(message: str, memory: Dict[str, Any]) -> Optional[str]:
    """Resolve "còn sản phẩm kia thì sao" / "cái còn lại" to the OTHER item of
    the last comparison - the one the user did NOT just look at. The AI parser
    has no notion of "the last comparison's two items" and returned an empty
    query for this, dead-ending on the ambiguous-reference error path. Scoped
    tightly: only fires when a recent COMPARE stored >=2 targets AND we can tell
    which one was just discussed (last_product_name), so "the other" is
    unambiguous; otherwise returns None and the message parses normally (no
    regression). Returns the other item's stored name, routed as PRODUCT_INFO by
    the caller (get_detail self-heals a name -> slug via search)."""
    text = f" {(message or '').lower().strip()} "
    if not any(m in text for m in _OTHER_COMPARED_MARKERS):
        return None
    items = memory.get("last_compare") or []
    if len(items) < 2:
        return None
    last_viewed = (memory.get("last_product_name") or "")
    if not last_viewed:
        return None
    others = [it for it in items if it and not _shares_a_word(it, last_viewed)]
    return others[0] if others else None

# --- Consultation Flow: multi-turn requirement gathering ------------------
# An "expert"-level ask ("tư vấn máy giặt") with genuinely open requirements
# gets asked about each still-missing attribute from its category's
# requirement_schema.json, one per turn, instead of either a single generic
# question (the old behavior) or a blind search. See app/knowledge/
# requirement_schema.json + ontology.requirement_schema_for().

# A no-preference reply ("không biết", "tùy", "nào cũng được") means "don't
# ask me this again, I have no answer" - distinct from an unparseable reply,
# which instead falls through to the real parser (see _resolve_gap_fill_answer).
# Moved to intent_classifier.py so parser.py's semantic-cache gate can reuse
# the SAME check (see its skip_semantic_cache) - an indifferent reply must
# never be allowed to hit the global parse cache even if it somehow reaches
# the AI-parser path, since its embedding carries no real topic signal.
_is_no_preference = is_no_preference_reply

# Requirement Resolver v0 - regex/dictionary only, no AI. Only "family_size"/
# "age" have a real structured shape (a headcount) worth normalizing this
# pass; every other freeform attribute (camera_need, occasion...) keeps its
# raw text only - see requirement_schema.json's Round 3 scope note.
_NUMERIC_REQUIREMENT_FIELDS = {"family_size", "age"}
_WORD_NUMBER_MARKERS = [
    (re.compile(r"một mình|độc thân|doc than|mot minh"), 1),
    (re.compile(r"vợ chồng|cặp đôi|vo chong|cap doi"), 2),
]

def _normalize_numeric(field: str, text: str) -> Optional[int]:
    if field not in _NUMERIC_REQUIREMENT_FIELDS:
        return None
    lowered = (text or "").lower()
    for pattern, value in _WORD_NUMBER_MARKERS:
        if pattern.search(lowered):
            return value
    digit_match = re.search(r"\d+", lowered)
    return int(digit_match.group()) if digit_match else None

def _missing_requirement_fields(context: ShoppingContext, resolved: Dict[str, Any]) -> List[str]:
    """Still-unanswered required attributes for context.category, in schema
    priority order. `resolved` is conversation.memory["shopping_requirement"] -
    a field counts as resolved once it's a key there (real answer or the
    "__skipped__" sentinel), regardless of what ShoppingContext itself carries
    this exact turn. "budget"/"purpose" ALSO count as resolved when the
    ORIGINAL message already supplied them (context.price_min/price_max/
    purpose), covering the case where a gap-fill loop never needed to start
    at all - e.g. "tư vấn laptop cho lập trình khoảng 20 triệu" gives both in
    one message."""
    missing = []
    for field in ontology.requirement_schema_for(context.category):
        if field in resolved:
            continue
        if field == "budget" and (context.price_min is not None or context.price_max is not None):
            continue
        if field == "purpose" and context.purpose:
            continue
        missing.append(field)
    return missing

def _resolve_gap_fill_answer(message: str, memory: Dict[str, Any]) -> Optional[ShoppingContext]:
    """Resolves a reply to a live Consultation Flow question directly to the
    ONE attribute it was asking about (memory["awaiting"]["pending_field"]),
    instead of re-parsing from scratch - the AI Parser has no notion of "this
    reply answers my own pending question" (see parser_prompt.txt), so a bare
    "4 người" or "khoảng 15 triệu" would otherwise have nothing to anchor it
    to the right attribute.

    Falls through to normal parsing (returns None) when: no GAP_FILL is
    live/unexpired, or the reply reads as a new/unrelated ask rather than a
    short direct answer (see the word-count guard below) - forcing a wrong
    assignment is worse than letting the real parser take a fresh look."""
    awaiting = memory.get("awaiting")
    if not awaiting or awaiting.get("action") != "GAP_FILL":
        return None
    expires_at = awaiting.get("expires_at")
    if expires_at:
        try:
            if datetime.fromisoformat(expires_at) < datetime.utcnow():
                return None
        except ValueError:
            pass
    pending_field = awaiting.get("pending_field")
    if not pending_field:
        return None

    # A "tại sao"/technical-explain question ("tại sao cần RAM 16GB thế?")
    # reads as a short, direct reply (often <=8 words) and would otherwise be
    # captured below as a literal ANSWER to pending_field (e.g. stored as the
    # budget value!) - it's a SIDE question, not an answer, so let it fall
    # through to the real parser/Tech Explain check instead (see
    # orchestrator's own 5.5 step).
    if is_tech_explain_query(message):
        return None

    entities = entity_extractor.extract(message)
    incidental_price_min, incidental_price_max = entities.get("price_min"), entities.get("price_max")
    incidental_brand = entities.get("brand")
    has_incidental_price = incidental_price_min is not None or incidental_price_max is not None

    resolved = dict(memory.get("shopping_requirement") or {})

    if pending_field == "budget":
        if has_incidental_price:
            resolved["budget"] = {"value": message.strip(), "normalized": incidental_price_max or incidental_price_min}
        elif _is_no_preference(message):
            resolved["budget"] = "__skipped__"
        else:
            # No usable price and no explicit "no preference" - ambiguous,
            # safer to let the real parser take a fresh look.
            return None
    elif _is_no_preference(message):
        resolved[pending_field] = "__skipped__"
    elif has_incidental_price or incidental_brand:
        # Answered a DIFFERENT field spontaneously (e.g. gave budget while
        # asked about family size) - leave pending_field unresolved this
        # turn; the incidental price/brand still gets merged in below, and
        # pending_field will be asked again next turn since it's still
        # missing from `resolved`.
        pass
    elif len(message.split()) <= 8:
        resolved[pending_field] = {
            "value": message.strip(),
            "normalized": _normalize_numeric(pending_field, message),
        }
    else:
        # A long reply reads like a fresh, unrelated ask rather than a direct
        # answer - don't force it into this field.
        return None

    memory["shopping_requirement"] = resolved

    def _answer_text(field: str) -> Optional[str]:
        entry = resolved.get(field)
        return entry.get("value") if isinstance(entry, dict) else None

    ctx = ShoppingContext(
        intent="SEARCH",
        consultation_level="expert",
        category=memory.get("category"),
        query_q=memory.get("query_q"),
        brand=incidental_brand or memory.get("brand"),
        price_min=incidental_price_min if incidental_price_min is not None else memory.get("price_min"),
        price_max=incidental_price_max if incidental_price_max is not None else memory.get("price_max"),
        purpose=_answer_text("purpose") or memory.get("purpose"),
    )
    ctx._requirement_answers = {
        f: e["value"] for f, e in resolved.items() if isinstance(e, dict) and f != "purpose"
    }
    return ctx

# Explicit rejections of DETAIL's compare-suggestion outro ("Bạn muốn Delippy
# so sánh sản phẩm này với X không?") - anything else short is treated as a
# confirmation (see _resolve_compare_suggestion_answer below).
_COMPARE_SUGGESTION_REJECTION_MARKERS = ["không", "khong", "thôi", "thoi", "khỏi", "khoi", "chưa", "chua"]

def _resolve_compare_suggestion_answer(message: str, memory: Dict[str, Any]) -> Optional[ShoppingContext]:
    """Resolves a reply confirming (or rejecting) DETAIL's compare-suggestion
    outro (memory["awaiting"] = {"action": "COMPARE", "target": {"product",
    "candidate"}}, set by response_planner._next_action_and_target) directly
    - a pre-parse deterministic override, same pattern as
    _resolve_gap_fill_answer/_resolve_other_compared_item.

    This exists because depending on the Parser to classify the reply as
    SOCIAL first (see memory_resolver.py's target-aware resume) isn't
    reliable: a short "tôi có" can get classified DIRECTLY as intent=COMPARE
    by the AI parser using conversation history to infer a target - but only
    the SUGGESTED candidate, silently dropping the product actually being
    viewed, so search_engine.compare() then reports the candidate "not
    found" instead of comparing both. Resolving here, before the parser ever
    runs, avoids depending on the AI parser to reconstruct BOTH sides of a
    pending yes/no question correctly.

    Falls through to normal parsing (returns None) on an explicit rejection
    or a long/unrelated reply - a genuinely new ask should still reach the
    real parser rather than being forced into a compare."""
    awaiting = memory.get("awaiting")
    if not awaiting or awaiting.get("action") != "COMPARE":
        return None
    target = awaiting.get("target") or {}
    product, candidate = target.get("product"), target.get("candidate")
    if not product or not candidate or not product.get("name") or not candidate.get("name"):
        return None
    expires_at = awaiting.get("expires_at")
    if expires_at:
        try:
            if datetime.fromisoformat(expires_at) < datetime.utcnow():
                return None
        except ValueError:
            pass
    text = (message or "").lower()
    if any(marker in text for marker in _COMPARE_SUGGESTION_REJECTION_MARKERS):
        return None
    if len(message.split()) > 6:
        return None

    # Never re-resolve either product by free-text name search (names
    # drift/alias) - seed both into the cached-products list so
    # search_engine.compare()'s OWN existing cached_by_name -> slug ->
    # get_details(slug) path (unchanged) does an exact slug fetch for both.
    cached = list(memory.get("search_results") or [])
    known = {(p.get("name") or "").strip().lower() for p in cached if p.get("name")}
    for p in (product, candidate):
        if p["name"].strip().lower() not in known:
            cached.append({"name": p["name"], "slug": p.get("slug")})
    memory["search_results"] = cached
    memory.pop("awaiting", None)
    return ShoppingContext(intent="COMPARE", compare_targets=[product["name"], candidate["name"]])

class Orchestrator:
    async def process_message(self, message: str, session_id: Optional[str] = None) -> dict:
        # 1. Load Session
        conversation = await session_manager.load_session(session_id)
        
        # 1.5 Check if user requests pagination / "xem thêm"
        is_see_more = any(kw in message.lower() for kw in ["xem thêm", "xem them", "tải thêm", "tai them", "đề xuất thêm", "de xuat them"])
        if is_see_more and "search_results" in conversation.memory:
            results = conversation.memory.get("search_results", [])
            pointer = conversation.memory.get("search_pointer", 5)
            next_products = results[pointer : pointer + 5]
            if next_products:
                conversation.memory["search_pointer"] = pointer + 5

                intro = random.choice(ontology.pagination_intros) if ontology.pagination_intros else \
                    "Delippy gợi ý thêm cho bạn các sản phẩm tiếp theo:"
                answer = f"{intro}\n\n"
                for p in next_products:
                    rating_str = f"({p.get('rating')}⭐)" if p.get("rating") else ""
                    sold_str = f"| Đã bán {p.get('sold_count')}" if p.get("sold_count") else ""
                    answer += f"- **{p.get('name')}** - Giá: **{p.get('price'):,.0f}đ** {rating_str} {sold_str}\n"
                outro = random.choice(ontology.pagination_outros) if ontology.pagination_outros else \
                    "Bạn có muốn xem thêm nữa không?"
                answer += f"\n{outro}"

                has_more = (pointer + 5) < len(results)

                # Save session history
                await session_manager.add_message(conversation, "user", message)
                await session_manager.add_message(conversation, "assistant", answer)
                await session_manager.save_session(conversation)

                return {
                    "summary": "SEARCH_PAGINATION",
                    "answer": answer,
                    "intent": "SEARCH",
                    "mode": "search",
                    "confidence": 1.0,
                    "highlights": [],
                    "follow_up_actions": [SEE_MORE_ACTION] if has_more else [],
                    "warnings": [],
                    "source_list": [],
                    "data": {
                        "session_id": conversation.session_id,
                        "memory": conversation.memory,
                        "products": next_products
                    }
                }
            else:
                answer = random.choice(ontology.pagination_end_responses) if ontology.pagination_end_responses else \
                    "Delippy đã hiển thị hết toàn bộ sản phẩm tìm thấy rồi đó ạ!"
                await session_manager.add_message(conversation, "user", message)
                await session_manager.add_message(conversation, "assistant", answer)
                await session_manager.save_session(conversation)
                return {
                    "summary": "SEARCH_PAGINATION_END",
                    "answer": answer,
                    "intent": "SEARCH",
                    "mode": "search",
                    "confidence": 1.0,
                    "highlights": [],
                    "follow_up_actions": [],
                    "warnings": [],
                    "source_list": [],
                    "data": {
                        "session_id": conversation.session_id,
                        "memory": conversation.memory,
                        "products": []
                    }
                }

        # 3. Query embedding - lazy AND backgrounded. Only two things ever
        # need the actual vector: the parser's semantic-cache lookup (only
        # reached when deterministic rules don't resolve intent - see
        # parser.py step 4) and the history-RAG lookup below (only reached on
        # an LLM-fallback formatter call). Greeting/FAQ/rule-based
        # SEARCH-COMPARE-PRODUCT_INFO turns - the majority - never touch it.
        # Wrapped in Lazy (now Task-memoized, see lazy.py) so whichever of the
        # two call sites - or the background save below - resolves it first,
        # the others just await that same in-flight computation.
        query_vector_lazy = Lazy(lambda: asyncio.to_thread(llm_client_wrapper.get_embedding, message))

        async def _save_user_message() -> None:
            vector = await query_vector_lazy.get()
            await conversation_repo.save_message(conversation.session_id, "user", message, vector)
        asyncio.create_task(_save_user_message())

        # 4. History RAG - lazy: a Mongo scan + cosine-similarity pass over
        # the whole session just to maybe use 3 lines of it. Deterministic
        # intent parsing and deterministic response formatting (greeting,
        # already-found products, product details...) never touch this -
        # only wrap it in work when an LLM fallback call actually needs it.
        async def _build_history_str() -> str:
            print("\n[Orchestrator] LLM fallback needs history - running RAG lookup now (lazy, was skipped until this point).")
            relevant_history = []
            query_vector = await query_vector_lazy.get()
            if query_vector:
                relevant_history = await conversation_repo.get_relevant_history(conversation.session_id, query_vector, limit=3)

            # Pure semantic-similarity retrieval can miss the ONE turn a
            # short reply ("có", "không", "ok", "được") actually depends on:
            # the assistant's own immediately preceding question. "tôi có"
            # answering "bạn có muốn xem chi tiết sản phẩm rẻ nhất này
            # không?" has a generic embedding that isn't reliably similar to
            # that specific product question, so RAG can return 3
            # semantically-close-but-stale messages instead - the AI Parser
            # then has no idea what "có" is affirming and guesses CHITCHAT.
            # conversation.history (in-memory, already loaded, no DB
            # round-trip) is chronological and doesn't yet include THIS
            # turn's user message (only appended after formatting - see
            # step 9 below), so splicing its last 2 entries in front always
            # keeps the true most-recent exchange visible regardless of what
            # RAG did or didn't retrieve.
            recent = conversation.history[-2:]
            seen = {(m["role"], m["content"]) for m in recent}
            combined = recent + [m for m in relevant_history if (m.get("role"), m.get("content")) not in seen]
            def clean_msg(msg):
                role = msg.get("role")
                content = msg.get("content") or ""
                if role == "assistant":
                    # Remove markdown tables, bullet points, and numbered product lists to save tokens
                    lines = content.split("\n")
                    cleaned = []
                    for l in lines:
                        ls = l.strip()
                        if ls.startswith("|") or ls.startswith("•") or ls.startswith("-") or re.match(r"^\d+\.\s+", ls):
                            continue
                        cleaned.append(l)
                    content = "\n".join(cleaned).strip()
                return f"{role}: {content}"

            return "\n".join(clean_msg(msg) for msg in combined)

        history_lazy = Lazy(_build_history_str)

        # 5. Parse Query & Resolve Memory
        # Pass previously shown products so the parser can resolve demonstrative
        # references ("cái ở Hà Nội đó") back to a specific product slug.
        # subcategory_options is the numbered menu from a PRIOR zero-result
        # turn (see step 6 below) - lets a follow-up "số N" resolve to an
        # actual subcategory_id instead of the AI re-guessing a free-text
        # category label from history alone.
        product_options = conversation.memory.get("search_results")
        subcategory_options = conversation.memory.get("subcategory_menu")
        subcategory_category_slug = conversation.memory.get("subcategory_menu_category_slug")

        # Deterministic pre-check: a live Consultation Flow question
        # (memory["awaiting"]["action"]=="GAP_FILL") means this reply likely
        # answers that ONE pending requirement attribute - resolve it directly
        # instead of paying for an AI parse that has no notion of "this
        # answers my own pending question" (see _resolve_gap_fill_answer).
        # Falls through to normal parsing when the reply doesn't read as a
        # direct answer (long/unrelated message).
        gap_fill_ctx = _resolve_gap_fill_answer(message, conversation.memory)
        # Deterministic pre-check: a live DETAIL compare-suggestion outro
        # ("Bạn muốn Delippy so sánh sản phẩm này với X không?") means a short
        # non-rejecting reply confirms it - resolve directly instead of
        # trusting the AI parser to reconstruct BOTH sides of the pending
        # question (see _resolve_compare_suggestion_answer).
        compare_suggestion_ctx = (
            _resolve_compare_suggestion_answer(message, conversation.memory) if not gap_fill_ctx else None
        )
        # Deterministic pre-check: "còn sản phẩm kia thì sao" after a COMPARE
        # means the OTHER just-compared item. Resolve it here (into a
        # PRODUCT_INFO context for the other item's name) instead of paying for
        # an AI parse that has no notion of "the last comparison" and returns an
        # empty query for it. Falls through to the normal parser when it can't
        # unambiguously identify the other item.
        other_compared = (
            _resolve_other_compared_item(message, conversation.memory)
            if not gap_fill_ctx and not compare_suggestion_ctx else None
        )
        if gap_fill_ctx:
            print(f"\n[Orchestrator] '{message}' -> resolved as a Consultation Flow answer "
                  f"for '{conversation.memory.get('awaiting', {}).get('pending_field')}'.")
            context = gap_fill_ctx
        elif compare_suggestion_ctx:
            print(f"\n[Orchestrator] '{message}' -> resolved as a compare-suggestion confirmation: "
                  f"{compare_suggestion_ctx.compare_targets}.")
            context = compare_suggestion_ctx
        elif other_compared:
            print(f"\n[Orchestrator] '{message}' -> resolved to the OTHER compared item: '{other_compared}' (PRODUCT_INFO).")
            context = ShoppingContext(intent="PRODUCT_INFO", query_q=other_compared)
        else:
            context = await query_parser.parse(
                message, history_lazy,
                product_options=product_options,
                subcategory_options=subcategory_options,
                subcategory_category_slug=subcategory_category_slug,
                query_vector_lazy=query_vector_lazy,
            )
        # Snapshot memory's search constraints BEFORE resolve merges this turn
        # into them - needed to tell a genuinely-new constraint from one merely
        # carried forward (see _has_new_search_signal / the advisory branch below).
        prev_constraints = {
            "query_q": conversation.memory.get("query_q"),
            "category": conversation.memory.get("category"),
            "brand": conversation.memory.get("brand"),
            "price_min": conversation.memory.get("price_min"),
            "price_max": conversation.memory.get("price_max"),
        }
        # Answering the bot's OWN pending Consultation Flow question is never a
        # "new topic", even when the reply incidentally mentions a brand that
        # memory_resolver's topic-change heuristic (step 3) would otherwise
        # treat as a shift and memory.clear() away - snapshot/restore across
        # that call so a just-resolved requirement is never silently lost.
        gap_fill_snapshot = dict(conversation.memory.get("shopping_requirement") or {}) if gap_fill_ctx else None
        context = memory_resolver.resolve(conversation, context, message)
        if gap_fill_snapshot is not None:
            conversation.memory["shopping_requirement"] = gap_fill_snapshot

        # 5.5 Tech Explain (Sprint 4): a "tại sao/vì sao/... hay ..." technical
        # question ("tại sao lập trình cần RAM 16GB", "nên chọn truyền động
        # trực tiếp hay gián tiếp") grounded in a category ALREADY being
        # discussed (context.category from this turn, or memory's if this
        # turn didn't re-specify one) - answered as a SIDE question, without
        # touching the normal SEARCH/Consultation Flow pipeline or
        # `awaiting` state below. Tries guide_rule.json's own "education"
        # text first (0 tokens, see recommendation_builder.match_spec_education) -
        # only falls back to a neutral LLM explainer (tech_explain_prompt.txt)
        # when nothing there matches (e.g. "trực tiếp hay gián tiếp" - a
        # washing-machine motor technology guide_rule.json has no spec for).
        # A question with no active category to ground it in is deliberately
        # left unanswered here (falls through to the normal pipeline instead)
        # - answering ungrounded "tại sao" trivia would turn this into a
        # generic Q&A bot, not a shopping assistant.
        tech_explain_answer = None
        if context.intent == "SEARCH" and is_tech_explain_query(message):
            active_category = context.category or conversation.memory.get("category")
            if active_category:
                bucket_info = recommendation_builder.resolve_bucket_for(
                    active_category,
                    conversation.memory.get("shopping_requirement") or {},
                    context.purpose or conversation.memory.get("purpose"),
                )
                if bucket_info:
                    _, _, tech_bucket = bucket_info
                    tech_explain_answer = recommendation_builder.match_spec_education(message, tech_bucket)
                if not tech_explain_answer:
                    tech_explain_answer = await llm_client_wrapper.format_tech_explain_response(active_category, message)

        # 6. Search Pipeline (zero-result SEARCH retries with expanded queries
        # instead of asking the user to teach the system - see search_engine.search_or_expand)
        evidence = Evidence()
        gap_fill_question = None
        if tech_explain_answer:
            print(f"\n[Orchestrator] Tech Explain - '{message}' answered as a technical "
                  f"question grounded in '{active_category}' (no search/gap-fill state touched).")
            evidence = Evidence(error=tech_explain_answer)
        elif context.intent == "SEARCH":
            # Consultation Flow: an "expert"-level ask (explicitly wants to be
            # advised - "tư vấn", "nên mua", "laptop nào tốt"...) gets asked
            # about each still-missing required attribute from its category's
            # requirement_schema.json (e.g. family_size then budget for a
            # washing machine), one per turn, instead of either a single
            # generic question or a blind search - a real salesperson asks
            # "dùng để làm gì?" AND "ngân sách bao nhiêu?" before grabbing
            # random stock off the shelf. `missing` is recomputed fresh every
            # turn from conversation.memory["shopping_requirement"], so this
            # naturally asks the NEXT field once the previous one resolves
            # (see _resolve_gap_fill_answer) and naturally stops once every
            # required field is answered or explicitly skipped -
            # _force_advisory means resolve_followup already decided this is a
            # SOCIAL continuation of a pending topic (see memory_resolver.py),
            # not a fresh advisory ask, so it's excluded here.
            #
            # ALSO excluded: an advisory follow-up about products already
            # shown ("cái nào ngon nhất, tư vấn tôi") - computed here (not
            # just in the advisory-grounding branch below) because this turn
            # may ALSO read as a fresh "expert"-level ask (it likely has "tư
            # vấn" too) with shopping_requirement already cleared from the
            # previous successful search, which would otherwise re-trigger
            # the WHOLE gap-fill sequence from scratch instead of reasoning
            # over the products already cached - confirmed live: this exact
            # case re-asked "gia đình mấy người" after 3 tủ lạnh were already
            # shown, instead of answering "cái nào ngon nhất".
            cached_products = conversation.memory.get("search_results") or []
            is_advisory_followup_on_cache = (
                bool(cached_products)
                and (is_advisory_query(message) or context._force_advisory)
                and not _has_new_search_signal(context, prev_constraints)
            )
            missing_fields: List[str] = []
            if context.consultation_level == "expert" and not context._force_advisory and not is_advisory_followup_on_cache:
                missing_fields = _missing_requirement_fields(
                    context, conversation.memory.get("shopping_requirement", {})
                )

            if missing_fields:
                term = context.query_q or context.category or "sản phẩm này"
                # Market Education (Sprint 3): a "tư vấn X" ask this WIDE OPEN
                # (nothing answered yet - missing_fields is still the FULL
                # schema, not just the tail end of an already-started
                # sequence) gets a short explainer of the real buying choices
                # for this DECISION SCENARIO before the first bare clarifying
                # question - see app/knowledge/education_rule.json. Resolved
                # via education_domain_for(term), deliberately NOT
                # context.category - "kem chống nắng" and "thuốc say xe" sit
                # under the SAME catalog category ("sức khỏe & sắc đẹp") but
                # need completely different educational content, so content
                # selection is keyed by the actual buying need instead (see
                # ontology.py's own note on this). The gate condition below
                # (missing_fields == full schema) still uses the catalog's
                # requirement_schema.json unchanged - that's a separate
                # concern (when has search-filtering info gathering not
                # started yet), orthogonal to which content to show.
                #
                # Shown once per flow (education_shown, popped alongside
                # shopping_requirement below once the flow completes) so a
                # later reply in the SAME sequence never repeats it. A
                # partially-answered ask ("tư vấn laptop cho lập trình" -
                # purpose already given) skips straight to the plain
                # remaining-field question instead, since there's nothing
                # left to help the user decide between.
                domain = ontology.education_domain_for(term)
                education = ontology.education_rule_for(domain)
                if (
                    education
                    and missing_fields == ontology.requirement_schema_for(context.category)
                    and not conversation.memory.get("education_shown")
                ):
                    education_text = await llm_client_wrapper.format_education_response(term, education["choices"])
                    if education_text:
                        conversation.memory["education_shown"] = True
                        gap_fill_question = education_text
                        print(f"\n[Orchestrator] Market Education - '{message}' is a wide-open "
                              f"'tư vấn' ask (domain='{domain}'); showing buying-choices explainer "
                              f"before the first gap-fill question.")

                # Bucket Education: the OPPOSITE case from Market Education
                # above - a SPECIFIC bucket already resolved (e.g. "tư vấn
                # laptop học code" gives purpose=coding straight away, or the
                # user just answered Market Education's own question), but
                # the flow isn't done yet (budget still missing). Surfaces
                # guide_rule.json's own "education" text for THAT bucket - 0
                # LLM tokens, pure data concatenation - explaining WHY those
                # specs matter, before asking the next question. Shown once
                # per flow (bucket_education_shown, popped alongside
                # shopping_requirement below) - doesn't repeat on every
                # follow-up reply in the same sequence.
                bucket_education_text = None
                if (
                    not gap_fill_question
                    and missing_fields != ontology.requirement_schema_for(context.category)
                    and not conversation.memory.get("bucket_education_shown")
                ):
                    bucket_info = recommendation_builder.resolve_bucket_for(
                        context.category, conversation.memory.get("shopping_requirement", {}), context.purpose,
                    )
                    if bucket_info:
                        _, bucket_key, bucket = bucket_info
                        bucket_education_text = recommendation_builder.bucket_education_text(bucket)
                        if bucket_education_text:
                            conversation.memory["bucket_education_shown"] = True
                            print(f"\n[Orchestrator] Bucket Education - '{message}' resolved bucket "
                                  f"'{bucket_key}'; showing why-it-matters explainer before the next question.")

                if not gap_fill_question:
                    next_field = missing_fields[0]
                    field_templates = ontology.clarifying_questions_for_field(context.category, next_field)
                    if field_templates:
                        next_question = random.choice(field_templates).format(term=term)
                        # Bucket Education is pure explanation (no question of
                        # its own, unlike Market Education's LLM text, which
                        # already ends on one) - append the actual remaining
                        # question so the turn doesn't end on a lecture with
                        # nothing to answer.
                        gap_fill_question = f"{bucket_education_text}\n\n{next_question}" if bucket_education_text \
                            else next_question

            if gap_fill_question:
                print(f"\n[Orchestrator] Consultation Flow - '{message}' wants to be advised; "
                      f"asking about '{missing_fields[0]}' next (still missing: {missing_fields}).")
                evidence = Evidence(error=gap_fill_question)
                now = datetime.utcnow()
                conversation.memory["awaiting"] = {
                    "action": "GAP_FILL",
                    "pending_field": missing_fields[0],
                    "created_at": now.isoformat(),
                    "expires_at": (now + timedelta(minutes=10)).isoformat(),
                }
            else:
                # This need's Consultation Flow sequence is done (every
                # required field answered/skipped, or this wasn't an
                # "expert"-level ask at all) - clear it so a LATER, unrelated
                # advisory ask starts its own sequence fresh. Snapshotted
                # BEFORE the pop for the Recommendation Engine hook below
                # (see recommendation_builder.build() call further down) -
                # by the time evidence is ready, memory's own copy is already
                # gone, so this turn's only surviving copy of what the user
                # actually answered (e.g. family_size=4) is this local var.
                requirement_snapshot = dict(conversation.memory.get("shopping_requirement") or {})
                conversation.memory.pop("shopping_requirement", None)
                conversation.memory.pop("education_shown", None)
                conversation.memory.pop("bucket_education_shown", None)
                # Advisory follow-up about the products just shown ("tư vấn cái nào
                # hợp", "cái nào ngon nhất") - advisory phrasing strips down to a
                # near-empty/generic query_q, so a fresh search would drift to a
                # different (or mixed) product set. Ground the advice in the SAME
                # cached list instead (is_advisory_followup_on_cache, computed
                # above - same source of truth the gap-fill gate just used, so
                # the two can't drift). The downstream is_advisory path in
                # response_formatter then reasons over these exact products.
                if is_advisory_followup_on_cache:
                    print(f"\n[Orchestrator] Advisory follow-up - grounding advice in "
                          f"{len(cached_products)} cached product(s) already shown, skipped re-search.")
                    evidence = evidence_builder.build_search_evidence(cached_products)
                elif (local_matches := _filter_cached_products(cached_products, context)):
                    print(f"\n[Orchestrator] Answered from {len(cached_products)} cached product(s) already in memory "
                          f"({len(local_matches)} matched) - skipped API/LLM call.")
                    evidence = evidence_builder.build_search_evidence(local_matches)
                else:
                    # search_or_expand already retried with category dropped and
                    # every expanded synonym (see search_engine.search_or_expand)
                    # before giving up - leave a genuine miss as an empty
                    # Evidence rather than stuffing in unrelated cached products
                    # from an earlier, different search. response_formatter's
                    # deterministic zero-result path then gives the MORE useful
                    # answer on its own: the category's real subcategory menu
                    # when a category resolved, or the out-of-scope/capability
                    # list when it never did - both $0 and more actionable than
                    # "here's something else you looked at before".
                    evidence = await search_engine.search_or_expand(context)

                    # Semantic parse cache WRITE: this is the one place we KNOW a
                    # fresh search actually succeeded with real, live-verified
                    # products. Cache the AI parse for global reuse so a future
                    # similar query skips the Gemini parse. Gated on _parse_source
                    # == "ai" (never a cache hit / deterministic / reference parse)
                    # and on evidence.products - a wrong parse finds nothing, so it
                    # can never be cached (structural anti-poisoning). Reuses THIS
                    # turn's query_vector; no extra embedding. TTL'd, not permanent.
                    #
                    # ALSO excludes a generic indifference reply ("bao nhiêu cũng
                    # được", "không biết"...) even when it happened to resolve to
                    # real products - that resolution only worked because the AI
                    # parser leaned on THIS conversation's history (a pending
                    # question it was answering), not because the bare text itself
                    # stably means that concept. Caching it under the message's own
                    # embedding would silently apply THIS conversation's answer to
                    # any unrelated future conversation that happens to say
                    # something similarly generic - confirmed live: a past "bao
                    # nhiêu cũng được" cached as "máy giặt" (washing machine) later
                    # hijacked an unrelated "tư vấn mỹ phẩm" (cosmetics) session's
                    # own budget answer via a 1.00 similarity match.
                    if (
                        evidence.products
                        and getattr(context, "_parse_source", None) == "ai"
                        and context._ai_parse
                        and not _is_no_preference(message)
                    ):
                        await parse_cache_repo.store(message, await query_vector_lazy.get(), context._ai_parse)
                        print(f"\n[Orchestrator] Semantic parse cached for global reuse "
                              f"(concept q='{context._ai_parse.get('query_q')}', category={context._ai_parse.get('category')}, "
                              f"{len(evidence.products)} product(s) confirmed).")

                # Recommendation Engine (Sprint 2): an "expert"-level ask with
                # a real category/spec rule (see guide_rule.json) gets its
                # candidates re-sorted by suitability - not raw search
                # relevance - with each one carrying WHY (success/warning
                # bullets, see recommendation_builder.py). Re-attached to
                # evidence itself (like compare_builder's comparison_table)
                # so conversation.memory["search_results"] below and a later
                # "số N" both see the SAME sorted order as what's rendered.
                if context.consultation_level == "expert" and evidence.products:
                    scored_products = await recommendation_builder.build(
                        evidence.products, context.category, requirement_snapshot, context.purpose,
                        price_min=context.price_min, price_max=context.price_max,
                    )
                    if scored_products:
                        evidence = evidence.copy(update={"products": scored_products})

                if not evidence.products and not evidence.related_products and context.category:
                    # Genuine miss with a real category resolved - offer that
                    # category's own subcategory menu (see ontology.subcategories_for)
                    # instead of a dead-end message. Persist it (with real
                    # subcategory ids, not just display names) so a follow-up
                    # "chọn số N"/"số 10" resolves deterministically next turn -
                    # see parser.py's ordinal-reference shortcut. Without this,
                    # picking a menu option had NOTHING to resolve against: the
                    # AI Parser could only guess a free-text category label from
                    # history, which search_engine then had to re-derive a
                    # category_id from and still had no query_q to search with -
                    # that's what turned "not found -> show menu -> pick one ->
                    # still not found -> show the SAME menu again" into a loop.
                    menu = ontology.subcategories_for(context.category)
                    if menu:
                        evidence = evidence.copy(update={"subcategory_menu": menu})
                        conversation.memory["subcategory_menu"] = menu["subcategories"]
                        conversation.memory["subcategory_menu_category_slug"] = menu["slug"]
                elif evidence.products:
                    # A real result came back this turn - any subcategory menu
                    # from an earlier miss is stale now; clear it so a later
                    # "số N" isn't misresolved against a menu that's no longer
                    # what's being discussed.
                    conversation.memory.pop("subcategory_menu", None)
                    conversation.memory.pop("subcategory_menu_category_slug", None)

                conversation.memory["search_results"] = evidence.products or evidence.related_products
                conversation.memory["search_pointer"] = 5
        elif context.intent == "COMPARE":
            evidence = await search_engine.compare(context, cached_products=conversation.memory.get("search_results"))
            # Structured, zero-LLM comparison (winners/value/difference per
            # criterion) - only meaningful with >=2 resolved products; stays
            # None otherwise, and response_formatter falls back to the
            # existing generic LLM path unchanged (e.g. mostly-not-found compare).
            comparison_table = compare_builder.build(evidence.comparison_results, context.category)
            if comparison_table:
                evidence = evidence.copy(update={"comparison_table": comparison_table})
            # Remember what was compared so a later "còn cái kia thì sao" can
            # resolve to the OTHER item (see _resolve_other_compared_item).
            # Stored regardless of whether the targets were found in-catalog -
            # the reference is to what the USER compared, not to the results.
            if context.compare_targets:
                conversation.memory["last_compare"] = list(context.compare_targets[:3])
            if evidence.related_products:
                # So a follow-up like "cho tôi xem chi tiết [cái vừa gợi ý]"
                # has something to resolve against - related_products is the
                # only product data a COMPARE turn produces when the targets
                # themselves aren't in the catalog (see search_engine.compare).
                conversation.memory["search_results"] = evidence.related_products
                conversation.memory["search_pointer"] = len(evidence.related_products)
        elif context.intent == "PRODUCT_INFO":
            slug = context.product or (context.query_q.replace(" ", "-") if context.query_q else "")
            if not slug:
                # Genuinely ambiguous reference (e.g. "nó" among 20 products
                # just shown) - ask instead of guessing. Deterministic, no
                # LLM/API call, and avoids the old failure mode of sending
                # an empty slug into search_engine.get_detail().
                evidence = Evidence(error=(
                    "Bạn muốn xem chi tiết sản phẩm nào trong danh sách vừa rồi ạ? "
                    "Bạn có thể nói tên hoặc số thứ tự sản phẩm giúp mình nhé."
                ))
            else:
                evidence = await search_engine.get_detail(slug)
                # Track the product just viewed so a follow-up "cái còn lại"
                # after a comparison knows which of the two to exclude.
                if evidence.details and evidence.details.get("name"):
                    conversation.memory["last_product_name"] = evidence.details["name"]

                # Product Deep-Dive: "tư vấn kỹ hơn về X" on an already-
                # resolved product - the seller's own `details` text is
                # frequently too sparse to actually consult from (just a
                # hotline number/warranty terms - confirmed live: a real
                # Yadea S3 listing's whole "description" was two phone
                # numbers), so draw on the LLM's real market knowledge about
                # that product/model instead (see llm_client's own honesty
                # guard - declines rather than invents if it doesn't
                # recognize the model). response_formatter's DETAIL branch
                # renders this IN PLACE OF the raw description snippet.
                if evidence.details and is_deep_consult_query(message):
                    deep_dive_text = await llm_client_wrapper.format_product_deep_dive(
                        evidence.details.get("name"),
                        evidence.details.get("details"),
                        evidence.details.get("price"),
                    )
                    if deep_dive_text:
                        evidence = evidence.copy(update={"deep_dive_text": deep_dive_text})
                        print(f"\n[Orchestrator] Product Deep-Dive - '{message}' asked for a deeper look "
                              f"at '{evidence.details.get('name')}'; using market knowledge instead of "
                              f"the seller's own (often sparse) description.")
        elif context.intent == "FAQ":
            # Different policy questions (đổi trả/giao hàng/thanh toán) used to
            # all get the same hardcoded đổi trả answer regardless of what was
            # actually asked - classify_faq_topic() picks the right bucket from
            # faq_answers.json instead.
            topic = classify_faq_topic(message)
            evidence = Evidence(faq_answer=ontology.faq_answers.get(topic) or ontology.faq_answers.get("chung"))

        # 7.5 Response Planner decides WHAT this turn's reply is (type/
        # next_action/warnings) from (message, evidence, context) alone -
        # response_formatter only renders that decision, it doesn't re-derive
        # it. next_action mirrors the old awaiting_action computation exactly
        # (see response_planner.py), used below to track a pending follow-up
        # so a bare "có"/"ok"/"ừ" NEXT turn can resume this exact topic
        # instead of being misclassified as SOCIAL/CHITCHAT and wiping memory
        # (see memory_resolver.resolve_followup). Only set when this turn
        # actually produced something to follow up on; TTL'd so a stale
        # confirm long after the fact can't resurrect a dead thread. Skipped
        # entirely when this turn already set its own GAP_FILL awaiting above
        # - that one must survive this turn untouched, not get overwritten/
        # cleared here.
        plan = response_planner.plan(message, evidence, context)

        if gap_fill_question:
            pass
        elif plan.next_action:
            now = datetime.utcnow()
            conversation.memory["awaiting"] = {
                "action": plan.next_action,
                "target": plan.target,
                "reason": plan.reason,
                "created_at": now.isoformat(),
                "expires_at": (now + timedelta(minutes=10)).isoformat(),
            }
        else:
            conversation.memory.pop("awaiting", None)

        # 8. Format Response
        answer = await response_formatter.format(message, history_lazy, evidence, context, plan)

        # 9. Save assistant response with embedding to DB - backgrounded like
        # the user message (step 3): the caller doesn't need this write to
        # get their answer, only future turns' RAG lookup does.
        async def _save_assistant_message() -> None:
            vector = await asyncio.to_thread(llm_client_wrapper.get_embedding, answer)
            await conversation_repo.save_message(conversation.session_id, "assistant", answer, vector)
        asyncio.create_task(_save_assistant_message())

        # Update Session
        await session_manager.add_message(conversation, "assistant", answer)
        await session_manager.save_session(conversation)

        # evidence.products holds up to 20 (kept in conversation.memory for
        # "xem thêm" pagination) but the API response itself should only
        # surface the current 5-item page, same as the answer text - the rest
        # is fetched on demand via the see_more follow-up action.
        response_products = evidence.products
        follow_up_actions = []
        # response_formatter's too-vague-to-show path (is_too_vague_for_results)
        # asks a clarifying question INSTEAD of listing products for this
        # exact turn - if the API response still put product cards in `data`,
        # the frontend would render them right under a text that never
        # mentioned them, looking like a contradiction. Same guards as that
        # path (not advisory, products exist) so the two can't drift.
        skip_products_this_turn = (
            context.intent == "SEARCH"
            and not is_advisory_query(message)
            and is_too_vague_for_results(context)
        )
        if context.intent == "SEARCH" and evidence.products and not skip_products_this_turn:
            response_products = evidence.products[:5]
            if len(evidence.products) > 5:
                follow_up_actions = [SEE_MORE_ACTION]
        elif skip_products_this_turn:
            response_products = []

        return {
            "summary": context.intent,
            "answer": answer,
            "intent": context.intent,
            "mode": context.intent.lower(),
            "confidence": 1.0,
            "highlights": [],
            "follow_up_actions": follow_up_actions,
            "warnings": [],
            "source_list": [],
            "data": {
                "session_id": conversation.session_id,
                "memory": conversation.memory,
                "products": response_products
            }
        }

orchestrator = Orchestrator()
