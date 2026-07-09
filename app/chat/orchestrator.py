from typing import Any, Dict, List, Optional
from app.chat.session_manager import session_manager
from app.understanding.parser import query_parser
from app.understanding.intent_classifier import is_advisory_query, is_too_vague_for_results, classify_faq_topic
from app.chat.memory_resolver import memory_resolver, _shares_a_word
from app.chat.lazy import Lazy
from app.retrieval.search_engine import search_engine
from app.retrieval.evidence_builder import evidence_builder
from app.chat.response_formatter import response_formatter
from app.models.shopping_context import ShoppingContext
from app.models.evidence import Evidence
from app.client.llm_client import llm_client_wrapper
from app.database.conversation_repository import conversation_repo
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

        # 3. Generate user query embedding and save to history DB (needed
        # regardless of this turn's path, so future turns can retrieve it)
        query_vector = llm_client_wrapper.get_embedding(message)
        await conversation_repo.save_message(conversation.session_id, "user", message, query_vector)

        # 4. History RAG - lazy: a Mongo scan + cosine-similarity pass over
        # the whole session just to maybe use 3 lines of it. Deterministic
        # intent parsing and deterministic response formatting (greeting,
        # already-found products, product details...) never touch this -
        # only wrap it in work when an LLM fallback call actually needs it.
        async def _build_history_str() -> str:
            print("\n[Orchestrator] LLM fallback needs history - running RAG lookup now (lazy, was skipped until this point).")
            relevant_history = []
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
            return "\n".join(f"{msg['role']}: {msg['content']}" for msg in combined)

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

        # Deterministic pre-check: "còn sản phẩm kia thì sao" after a COMPARE
        # means the OTHER just-compared item. Resolve it here (into a
        # PRODUCT_INFO context for the other item's name) instead of paying for
        # an AI parse that has no notion of "the last comparison" and returns an
        # empty query for it. Falls through to the normal parser when it can't
        # unambiguously identify the other item.
        other_compared = _resolve_other_compared_item(message, conversation.memory)
        if other_compared:
            print(f"\n[Orchestrator] '{message}' -> resolved to the OTHER compared item: '{other_compared}' (PRODUCT_INFO).")
            context = ShoppingContext(intent="PRODUCT_INFO", query_q=other_compared)
        else:
            context = await query_parser.parse(
                message, history_lazy,
                product_options=product_options,
                subcategory_options=subcategory_options,
                subcategory_category_slug=subcategory_category_slug,
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
        context = memory_resolver.resolve(conversation, context)

        # 6. Search Pipeline (zero-result SEARCH retries with expanded queries
        # instead of asking the user to teach the system - see search_engine.search_or_expand)
        evidence = Evidence()
        if context.intent == "SEARCH":
            cached_products = conversation.memory.get("search_results") or []
            # Advisory follow-up about the products just shown ("tư vấn cái nào
            # hợp", "cái nào ngon nhất") - advisory phrasing strips down to a
            # near-empty/generic query_q, so a fresh search would drift to a
            # different (or mixed) product set. Ground the advice in the SAME
            # cached list instead, UNLESS this turn adds a new distinguishing
            # constraint (brand/price/category/subcategory) that means the user
            # actually wants a different search. The downstream is_advisory path
            # in response_formatter then reasons over these exact products.
            if cached_products and is_advisory_query(message) and not _has_new_search_signal(context, prev_constraints):
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
        elif context.intent == "FAQ":
            # Different policy questions (đổi trả/giao hàng/thanh toán) used to
            # all get the same hardcoded đổi trả answer regardless of what was
            # actually asked - classify_faq_topic() picks the right bucket from
            # faq_answers.json instead.
            topic = classify_faq_topic(message)
            evidence = Evidence(faq_answer=ontology.faq_answers.get(topic) or ontology.faq_answers.get("chung"))

        # 8. Format Response
        answer = await response_formatter.format(message, history_lazy, evidence, context)

        # 9. Save assistant response with embedding to DB
        response_vector = llm_client_wrapper.get_embedding(answer)
        await conversation_repo.save_message(conversation.session_id, "assistant", answer, response_vector)

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
