from datetime import datetime
from typing import Any, Dict, Optional
from app.models.conversation import Conversation
from app.models.shopping_context import ShoppingContext

def _shares_a_word(a: Optional[str], b: Optional[str]) -> bool:
    if not a or not b:
        return False
    return bool(set(a.lower().split()) & set(b.lower().split()))

# A reply this long, classified SOCIAL, sitting right after a live pending
# question is unusual enough to more likely be a genuinely new (mis-tagged)
# aside than an answer to that question - don't force-resume past this
# length. Deliberately generous: real "no preference" answers ("cái nào cũng
# được", "thì cái nào cũng được trong thương hiệu đó") run several words.
_FOLLOWUP_MAX_WORDS = 10

def resolve_followup(message: str, memory: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Returns the popped `awaiting` dict when a still-live pending question
    (memory["awaiting"], set by the orchestrator after any turn that ended on
    a follow-up question) should be resumed instead of trusting the Parser's
    SOCIAL classification - None otherwise. The caller inspects the returned
    dict's `action`/`target` to decide HOW to resume (see MemoryResolver.resolve()) -
    this used to just return a bare bool, which meant every awaiting type
    resumed the exact same generic way regardless of what was actually pending.

    Deliberately does NOT try to enumerate what counts as "answering" the
    question (an exact-phrase allowlist for "có"/"ok"/"ừ" caught the literal
    yes-cases but missed equally valid answers like "cái nào cũng được" -
    "whichever, don't care" - and every future rephrasing of the same idea
    would need its own new entry). Instead it trusts the Parser's OWN
    classification contract: SOCIAL means "no real subject matter of its own"
    (see parser_prompt.txt - compliment or content-free filler), which is
    exactly the population of replies with nothing better to do than
    continue whatever's already pending. CHITCHAT/FAQ/GREETING are NOT
    treated this way - those DO carry real signal (toxicity, an actual
    out-of-scope ask, a real FAQ topic) that must never be silently
    overridden just because a question happens to be pending; the caller
    only invokes this for intent == "SOCIAL".

    Expired awaiting state (TTL set by the orchestrator) is dropped so a
    reply minutes/hours later doesn't resurrect a dead conversation thread.
    Consumes (pops) the awaiting state on a successful match - it answers
    THIS one pending question, not every future SOCIAL reply in the session."""
    awaiting = memory.get("awaiting")
    if not awaiting:
        return None
    expires_at = awaiting.get("expires_at")
    if expires_at:
        try:
            if datetime.fromisoformat(expires_at) < datetime.utcnow():
                memory.pop("awaiting", None)
                return None
        except ValueError:
            pass
    if len((message or "").split()) > _FOLLOWUP_MAX_WORDS:
        return None
    memory.pop("awaiting", None)
    return awaiting

class MemoryResolver:
    def resolve(self, conversation: Conversation, current_context: ShoppingContext, message: str = "") -> ShoppingContext:
        memory = conversation.memory

        # 1. Reset memory if user queries a brand-new intent or says greetings/faq/chitchat/social
        if current_context.intent in ["GREETING", "FAQ", "CHITCHAT", "SOCIAL"]:
            resumed = resolve_followup(message, memory) if current_context.intent == "SOCIAL" else None
            if resumed:
                # The Parser has no notion of "what pending question is this
                # answering" and a content-free reply defaults to SOCIAL (see
                # parser_prompt.txt) regardless of how it's phrased - that's
                # the exact bug that made the assistant "forget" mid-
                # conversation. Only SOCIAL is eligible here - GREETING/FAQ/
                # CHITCHAT fall through to `return current_context` below
                # unconditionally, since those DO carry real signal that must
                # win over a pending question.
                target = resumed.get("target") or {}
                if resumed.get("action") == "COMPARE" and target.get("candidate"):
                    # DETAIL's outro suggested comparing against a specific
                    # related product (see response_planner.py's
                    # _next_action_and_target) - resolve straight into that
                    # COMPARE instead of a generic advisory resume. Seed BOTH
                    # products into the cached-products list so
                    # search_engine.compare()'s OWN existing
                    # cached_by_name -> slug -> get_details(slug) path (see
                    # search_engine.py, unchanged) does an exact slug fetch
                    # for both - names drift/alias ("Galaxy A36" vs "Galaxy
                    # A36 5G"), so a fresh free-text re-search on a stored
                    # name risks matching the wrong variant.
                    product, candidate = target["product"], target["candidate"]
                    cached = list(memory.get("search_results") or [])
                    known = {(p.get("name") or "").strip().lower() for p in cached if p.get("name")}
                    for p in (product, candidate):
                        if p.get("name") and p["name"].strip().lower() not in known:
                            cached.append({"name": p["name"], "slug": p.get("slug")})
                    memory["search_results"] = cached
                    current_context.intent = "COMPARE"
                    current_context.compare_targets = [product["name"], candidate["name"]]
                else:
                    # Resume as an advisory continuation of whatever's
                    # already in memory (cached products/category/etc,
                    # merged below) instead of wiping it and replying with a
                    # canned social message.
                    current_context.intent = "SEARCH"
                    current_context._force_advisory = True
            else:
                return current_context

        # 2. Check query keyword shift (e.g. user changes search topic from 'laptop' to 'áo')
        old_query_q = memory.get("query_q")
        new_query_q = current_context.query_q
        if new_query_q and old_query_q and new_query_q != old_query_q:
            # If the new query keyword does not overlap with the old query keyword,
            # clear the old category, brand and price constraints.
            if old_query_q not in new_query_q and new_query_q not in old_query_q:
                memory.pop("category", None)
                memory.pop("brand", None)
                memory.pop("price_min", None)
                memory.pop("price_max", None)

        # 3. If user provides a new category/brand that genuinely conflicts
        # with memory, reset the rest of the search memory. Two guards
        # against false "topic changed" resets that were wiping
        # search_results/history mid-conversation:
        #   - PRODUCT_INFO/COMPARE never signal a new topic - they're always
        #     about something already in context (e.g. "xem chi tiết của nó").
        #   - category is raw AI-generated text, re-phrased inconsistently
        #     turn to turn for the SAME topic ("laptop" / "laptop theo nhãn
        #     hiệu" / "laptop cũ" all came from one real laptop-shopping
        #     thread) - comparing for ANY shared word instead of exact
        #     string equality avoids treating that wording noise as a
        #     brand-new search.
        is_reference_intent = current_context.intent in ("PRODUCT_INFO", "COMPARE")
        old_category = memory.get("category")
        if (
            not is_reference_intent
            and current_context.category
            and old_category
            and not _shares_a_word(old_category, current_context.category)
        ):
            memory.clear()
        elif (
            not is_reference_intent
            and current_context.brand
            and memory.get("brand") != current_context.brand
        ):
            brand = current_context.brand
            memory.clear()
            memory["brand"] = brand

        # 4. Merge Turn Context into Memory
        if current_context.price_min is not None or current_context.price_max is not None:
            memory.pop("price_min", None)
            memory.pop("price_max", None)

        if current_context.category:
            memory["category"] = current_context.category
        else:
            current_context.category = memory.get("category")

        if current_context.brand:
            memory["brand"] = current_context.brand
        else:
            current_context.brand = memory.get("brand")

        if current_context.price_min is not None:
            memory["price_min"] = current_context.price_min
        else:
            current_context.price_min = memory.get("price_min")

        if current_context.price_max is not None:
            memory["price_max"] = current_context.price_max
        else:
            current_context.price_max = memory.get("price_max")

        if current_context.purpose:
            memory["purpose"] = current_context.purpose
        else:
            current_context.purpose = memory.get("purpose")

        new_level = current_context.consultation_level
        old_level = memory.get("consultation_level")
        if new_level and new_level != "none":
            memory["consultation_level"] = new_level
            current_context.consultation_level = new_level
        else:
            # Only carry the OLD "expert" forward while its Consultation Flow
            # is still actually live (a pending GAP_FILL question, or an
            # unresolved shopping_requirement) - never indefinitely. Without
            # this guard, "expert" from an EARLIER, already-finished
            # tư vấn ("tư vấn laptop" -> flow completed and search_results
            # returned) stuck in memory forever and got applied to a LATER,
            # completely unrelated plain search ("tìm dây sạc") whose own
            # deterministic parse correctly said consultation_level="none" -
            # step 3's topic-conflict memory.clear() doesn't catch this case
            # because a plain "tìm X" query often has category=None from the
            # deterministic entity extractor, so the clear-guard
            # (current_context.category truthy) never fires. Confirmed live:
            # this exact leak forced an unrelated "purpose"/"budget" gap-fill
            # onto a simple "tìm dây sạc" search.
            still_in_flow = bool(memory.get("shopping_requirement")) or \
                (memory.get("awaiting") or {}).get("action") == "GAP_FILL"
            current_context.consultation_level = (old_level if still_in_flow else None) or "none"
            memory["consultation_level"] = current_context.consultation_level

        # Save current query keywords in memory for turn tracking - and, like
        # category/brand/price/purpose above, carry the EXISTING one forward
        # when this turn didn't supply its own (a bare "dưới 500k" narrowing
        # reply has no product noun of its own; without this, nothing kept
        # this session's real query_q, which is exactly the gap a wrongly-
        # matched semantic parse-cache hit from an unrelated session used to
        # paper over - see parser.py step 4's skip_semantic_cache).
        if current_context.query_q:
            memory["query_q"] = current_context.query_q
        elif not current_context._no_text_search:
            current_context.query_q = memory.get("query_q")

        return current_context

memory_resolver = MemoryResolver()
