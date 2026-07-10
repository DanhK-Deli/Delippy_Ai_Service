import json
import random
import re
from typing import Dict, Any, List
from app.models.evidence import Evidence
from app.models.shopping_context import ShoppingContext
from app.chat.lazy import Lazy
from app.client.llm_client import llm_client_wrapper
from app.knowledge.ontology import ontology
from app.understanding.intent_classifier import is_too_vague_for_results, is_prompt_probe_query, needs_consultation

def _minimize_product(p: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(p, dict):
        return p
    min_p = {}
    for field in ["name", "price", "rating", "sold_count", "slug"]:
        if p.get(field) is not None:
            min_p[field] = p[field]
    details = p.get("details")
    if details:
        # Simple HTML tag stripping
        clean_desc = re.sub(r"<[^>]*>", "", str(details))
        clean_desc = " ".join(clean_desc.split())
        min_p["details"] = clean_desc[:120] + "..." if len(clean_desc) > 120 else clean_desc
    return min_p

class ResponseFormatter:
    async def format(self, query: str, history_lazy: Lazy, evidence: Evidence, context: ShoppingContext) -> str:
        intent = context.intent

        # 1. Greeting
        if intent == "GREETING":
            responses = ontology.chitchat_responses.get("greeting", [])
            print("\n[Formatter] Skipped LLM Formatting: GREETING matches deterministic response (Tokens: 0, Cost: $0.00)\n")
            if responses:
                return random.choice(responses)
            return "Xin chào! Mình là trợ lý mua sắm thông minh của Delippy. Bạn cần mình giúp gì hôm nay? (Tìm sản phẩm, so sánh sản phẩm, tư vấn mua hàng...)"

        # 1.5 Social niceties - the user being polite, not asking an off-topic
        # question. sub_intent (parser_prompt.txt) splits this further:
        # "compliment" (thanks, well-wishes, farewells - reciprocate warmly)
        # vs "no_intent" (a bare filler ack like "ok"/"vâng" with no real ask -
        # a thanks-reply here would read as a non-sequitur). Defaults to
        # "compliment" when sub_intent is missing/unrecognized (old cached
        # parses, or the model returning something unexpected) - matches
        # exactly what this branch always did before sub_intent existed.
        if intent == "SOCIAL":
            bucket = context.sub_intent if context.sub_intent in ("compliment", "no_intent") else "compliment"
            responses = ontology.chitchat_responses.get(bucket, [])
            print(f"\n[Formatter] Skipped LLM Formatting: SOCIAL/{bucket} matches deterministic response (Tokens: 0, Cost: $0.00)\n")
            if responses:
                return random.choice(responses)
            return "Cảm ơn bạn nhiều nha! Khi nào cần tìm sản phẩm gì thì cứ nhắn Delippy nhé!"

        # 1.6 Chitchat / out-of-scope (jokes, small talk, anything not
        # shopping-related) - distinct from GREETING, reusing the shop-welcome
        # text for "kể chuyện cười" read as a robotic non-sequitur. sub_intent
        # splits this into "toxicity" (complaints/insults - de-escalate,
        # don't get defensive), "help_capabilities" ("bạn làm được gì" - state
        # real capabilities), or "out_of_scope" (everything else off-topic -
        # the default whenever sub_intent is missing/unrecognized, matching
        # this branch's original single-pool behavior). Still deterministic
        # ($0) - each bucket is its own small pool of varied warm lines.
        # A user probing for the system prompt/internal config is ALSO
        # CHITCHAT upstream (no separate intent for it), but needs a very
        # different reply than an innocent joke gets - picking from one mixed
        # pool meant a joke like "nước mắt em rơi, trò chơi kết thúc" had real
        # odds of getting "mình không tiết lộ prompt đâu nha", which reads as
        # accusing the user of trying to jailbreak the bot. Check the
        # narrower, specific case first.
        if intent == "CHITCHAT":
            if is_prompt_probe_query(query) and ontology.prompt_probe_responses:
                print("\n[Formatter] Skipped LLM Formatting: CHITCHAT prompt-probe matches deterministic response (Tokens: 0, Cost: $0.00)\n")
                return random.choice(ontology.prompt_probe_responses)
            bucket = context.sub_intent if context.sub_intent in ("out_of_scope", "toxicity", "help_capabilities") else "out_of_scope"
            responses = ontology.chitchat_responses.get(bucket, [])
            print(f"\n[Formatter] Skipped LLM Formatting: CHITCHAT/{bucket} matches deterministic response (Tokens: 0, Cost: $0.00)\n")
            if responses:
                return random.choice(responses)
            return "Mình là trợ lý mua sắm của Delippy nên chưa hỗ trợ được việc này. Bạn cần tìm sản phẩm gì thì cứ nói mình nghe nhé!"

        # 2. Detail / Product Info (Deterministic format if we just want a simple description)
        if intent == "PRODUCT_INFO" and evidence.details:
            d = evidence.details
            sizes_str = ", ".join([s.get("name") for s in d.get("sizes", []) if s.get("name")])
            colors_str = ", ".join(d.get("colors", []))
            
            resp = f"### Thông tin chi tiết sản phẩm: **{d.get('name')}**\n"
            resp += f"- **Giá**: {d.get('price'):,.0f}đ\n"
            resp += f"- **Trạng thái**: {'Còn hàng' if d.get('stock', 0) > 0 else 'Hết hàng'}\n"
            resp += f"- **Đánh giá**: {d.get('rating')} ⭐ ({d.get('sold_count')} đã bán)\n"
            if sizes_str:
                resp += f"- **Kích cỡ**: {sizes_str}\n"
            if colors_str:
                resp += f"- **Màu sắc**: {colors_str}\n"
            
            # Simple detail content
            if d.get("details"):
                desc = d.get("details", "").replace("<p>", "").replace("</p>", "\n").replace("<br>", "\n")[:300]
                resp += f"\n**Mô tả**: {desc}...\n"

            outro = random.choice(ontology.product_info_outros) if ontology.product_info_outros else \
                "Bạn muốn Delippy so sánh sản phẩm này với sản phẩm khác, hay xem thêm sản phẩm tương tự không?"
            resp += f"\n{outro}"

            if ontology.product_info_intros:
                resp = f"{random.choice(ontology.product_info_intros)}\n\n{resp}"

            print("\n[Formatter] Skipped LLM Formatting: PRODUCT_INFO matches deterministic response (Tokens: 0, Cost: $0.00)\n")
            return resp

        # 2.5 Product not found / genuinely ambiguous reference - the error
        # text is already a complete, user-facing message (see orchestrator.py),
        # no need to spend an LLM call rephrasing it.
        if intent == "PRODUCT_INFO" and evidence.error:
            print("\n[Formatter] Skipped LLM Formatting: PRODUCT_INFO error matches deterministic response (Tokens: 0, Cost: $0.00)\n")
            return evidence.error

        # 3. Search Result Deterministic Formatting (if no complex query/advisory/need)
        consultative = needs_consultation(query, context)
        if intent == "SEARCH" and not consultative and evidence.products:
            is_broad_query = not context.brand and context.price_min is None and context.price_max is None and not context.purpose

            # A query that reduces to at most one meaningful word beyond the
            # category itself ("áo" alone, or "áo t" where "t" is the same
            # single-char noise ranker.py/search_engine.py already strip)
            # gives nothing concrete to match ON - the category resolved to
            # exactly one place, so this ISN'T the earlier
            # ambiguous-category bug, but the product ask itself is still
            # too vague to search confidently. Showing 20 assorted "áo"
            # results and THEN asking "cụ thể loại nào?" already told the
            # user we knew we were guessing - ask first instead of guessing
            # first. A query with 2+ real words ("áo thun nam") is specific
            # enough that showing results is genuinely helpful, so only this
            # <=1-meaningful-word case skips straight to the question. See
            # is_too_vague_for_results - orchestrator uses the SAME check to
            # keep product cards out of the API response's `data` too.
            clarify_templates = ontology.clarifying_questions_for(context.category)
            if is_too_vague_for_results(context) and clarify_templates:
                term = context.query_q or context.category or "sản phẩm này"
                question = random.choice(clarify_templates).format(term=term)
                print("\n[Formatter] Skipped LLM Formatting: SEARCH too-vague-to-show matches deterministic clarifying question (Tokens: 0, Cost: $0.00)\n")
                return question

            intro = random.choice(ontology.search_found_intros).format(count=len(evidence.products)) if ontology.search_found_intros \
                else f"Delippy tìm thấy {len(evidence.products)} sản phẩm nổi bật:"
            resp = f"{intro}\n\n"
            # Numbered (not bulleted) so a follow-up like "cho tôi xem số 1"
            # can be resolved deterministically against this exact order -
            # see parser.py's ordinal-reference shortcut, which indexes into
            # conversation.memory["search_results"] (same list, same order).
            for i, p in enumerate(evidence.products[:5], start=1):
                rating_str = f"({p.get('rating')}⭐)" if p.get("rating") else ""
                sold_str = f"| Đã bán {p.get('sold_count')}" if p.get("sold_count") else ""
                resp += f"{i}. **{p.get('name')}** - Giá: **{p.get('price'):,.0f}đ** {rating_str} {sold_str}\n"

            # Weak keyword-overlap top match (see search_engine.search) - say so
            # instead of presenting a coincidental hit as a confident answer.
            if evidence.low_confidence:
                resp += (
                    "\n_Lưu ý: các sản phẩm trên chỉ khớp một phần với mô tả của bạn, "
                    "có thể chưa đúng ý lắm - bạn xem thử hoặc thử mô tả rõ hơn giúp Delippy nhé!_\n"
                )

            # A bare category/keyword search with no brand, price range or
            # purpose is under-specified - ask a narrowing question instead of
            # the generic prompt. Phrasing lives in knowledge/clarifying_questions.json
            # (never hardcoded here) and one is picked at random.
            clarify_templates = ontology.clarifying_questions_for(context.category)
            if is_broad_query and clarify_templates:
                term = context.query_q or context.category or "sản phẩm này"
                question = random.choice(clarify_templates).format(term=term)
                resp += f"\n{question}"
            else:
                outro = random.choice(ontology.search_found_outros) if ontology.search_found_outros else \
                    "Bạn muốn mình tư vấn chi tiết hơn hay so sánh sản phẩm nào không?"
                resp += f"\n{outro}"

            print("\n[Formatter] Skipped LLM Formatting: SEARCH matches deterministic product list (Tokens: 0, Cost: $0.00)\n")
            return resp

        # A relaxed fallback set (see orchestrator.py) means there IS
        # something to offer instead of a bare dead-end - fall through to
        # the LLM formatter below, which already knows how to present
        # not_found + related_products warmly (formatter_prompt.txt rule 5).
        if intent == "SEARCH" and not evidence.products and not evidence.related_products:
            # Warm, personalized zero-result reply (zero_result_prompt.txt) -
            # replaces 3 formerly-canned texts that read as robotic ("không
            # có ý nghĩa gì hết" per live user feedback). The LLM only writes
            # the empathetic paragraph (acknowledge + excuse + pivot) - it
            # never sees or invents the actual subcategory/category names
            # list, which is still built deterministically below exactly as
            # before, so nothing here can hallucinate a menu option that
            # doesn't exist.
            category_display = None
            if context.category:
                info = evidence.subcategory_menu or ontology.subcategories_for(context.category)
                if info:
                    category_display = info.get("name")

            search_term = context.query_q or context.purpose or context.category or "sản phẩm này"
            intro = await llm_client_wrapper.format_zero_result_response(search_term, category_display)

            # A real category matched but even the expanded query variants
            # (search_engine.search_or_expand) came up empty - offer that
            # category's own subcategory menu instead of a dead-end "try
            # other keywords" message. menu is computed once by orchestrator
            # (ontology.subcategories_for) and attached to evidence - reading
            # it from there (not recomputing here) keeps what's shown and
            # what's persisted to conversation.memory for a later "số N"
            # guaranteed identical.
            menu = evidence.subcategory_menu
            if menu and menu["subcategories"]:
                listed = "\n".join(f"{i}. {s['name'].capitalize()}" for i, s in enumerate(menu["subcategories"][:10], start=1))
                return f"{intro}\n\n{listed}\n\nBạn muốn tìm ở mục nào trong số này không?"

            if not context.category:
                # category never resolved at all - this is very likely
                # outside Delippy's catalog entirely (jobs, food delivery,
                # weather...), not just a bad keyword within a real category.
                # See orchestrator.py: the cached-related-products fallback is
                # deliberately skipped in this exact case so it lands here
                # instead of the LLM branch below.
                names = ontology.top_level_category_names()
                if names:
                    listed = ", ".join(n.capitalize() for n in names)
                    return (
                        f"{intro}\n\nHiện tại Delippy có các nhóm ngành: {listed}.\n\n"
                        "Bạn cần tìm sản phẩm/dịch vụ nào trong số này không?"
                    )

            return intro

        # 4. Fallback to the configured LLM provider for Consultation, Comparison and FAQ Answers
        # evidence.products can hold up to 20 (kept for "xem thêm" pagination) -
        # cap what actually goes into the prompt so pagination storage doesn't
        # inflate LLM token cost.
        evidence_for_llm = evidence.copy(update={"products": evidence.products[:5]}) if evidence.products else evidence

        # Minimize product data payloads to save input tokens
        minimized_products = [_minimize_product(p) for p in (evidence_for_llm.products or [])]
        minimized_related = [_minimize_product(p) for p in (evidence_for_llm.related_products or [])]
        minimized_details = _minimize_product(evidence_for_llm.details) if evidence_for_llm.details else None
        minimized_comparisons = [_minimize_product(p) for p in (evidence_for_llm.comparison_results or [])]

        # Re-build evidence dict with minimized values
        evidence_dict = evidence_for_llm.dict(exclude_none=True)
        if "products" in evidence_dict and evidence_dict["products"]:
            evidence_dict["products"] = minimized_products
        if "related_products" in evidence_dict and evidence_dict["related_products"]:
            evidence_dict["related_products"] = minimized_related
        if "details" in evidence_dict and evidence_dict["details"]:
            evidence_dict["details"] = minimized_details
        if "comparison_results" in evidence_dict and evidence_dict["comparison_results"]:
            evidence_dict["comparison_results"] = minimized_comparisons

        # Strip empty/None fields and use compact separators to keep the prompt
        # small even when evidence carries a lot of data (e.g. 3-way comparisons).
        evidence_payload = {
            k: v for k, v in evidence_dict.items()
            if v != [] and v != {} and v != ""
        }

        # context.purpose/price_min/price_max never reached the LLM before -
        # it had to infer "what does this user actually need" from the raw
        # query text alone, even though the parser had ALREADY extracted it.
        # Without this, formatter_prompt.txt's consultative rule (see below)
        # has nothing concrete to reason from.
        user_need = {
            k: v for k, v in {
                "purpose": context.purpose,
                "price_min": context.price_min,
                "price_max": context.price_max,
            }.items() if v is not None
        }
        if user_need:
            evidence_payload["user_need"] = user_need

        evidence_str = json.dumps(evidence_payload, ensure_ascii=False, separators=(",", ":"))
        history_str = await history_lazy.get()
        return await llm_client_wrapper.format_response(query, history_str, evidence_str)

response_formatter = ResponseFormatter()
