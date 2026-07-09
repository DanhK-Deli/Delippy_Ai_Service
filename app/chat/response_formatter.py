import json
import random
from typing import Dict, Any, List
from app.models.evidence import Evidence
from app.models.shopping_context import ShoppingContext
from app.chat.lazy import Lazy
from app.client.llm_client import llm_client_wrapper
from app.knowledge.ontology import ontology
from app.understanding.intent_classifier import is_too_vague_for_results, is_prompt_probe_query, needs_consultation

class ResponseFormatter:
    async def format(self, query: str, history_lazy: Lazy, evidence: Evidence, context: ShoppingContext) -> str:
        intent = context.intent

        # 1. Greeting
        if intent == "GREETING":
            print("\n[Formatter] Skipped LLM Formatting: GREETING matches deterministic response (Tokens: 0, Cost: $0.00)\n")
            if ontology.greeting_responses:
                return random.choice(ontology.greeting_responses)
            return "Xin chào! Mình là trợ lý mua sắm thông minh của Delippy. Bạn cần mình giúp gì hôm nay? (Tìm sản phẩm, so sánh sản phẩm, tư vấn mua hàng...)"

        # 1.5 Social niceties (thanks, well-wishes, farewells) - the user being
        # polite, not asking an off-topic question. Reciprocate warmly (thank
        # you / wish back) before the soft product redirect, distinct from
        # CHITCHAT's decline-and-redirect tone.
        if intent == "SOCIAL":
            print("\n[Formatter] Skipped LLM Formatting: SOCIAL matches deterministic response (Tokens: 0, Cost: $0.00)\n")
            if ontology.social_responses:
                return random.choice(ontology.social_responses)
            return "Cảm ơn bạn nhiều nha! Khi nào cần tìm sản phẩm gì thì cứ nhắn Delippy nhé!"

        # 1.6 Chitchat / out-of-scope (jokes, small talk, anything not shopping-related).
        # Distinct from GREETING - reusing the shop-welcome text for "kể chuyện cười"
        # read as a robotic non-sequitur. Still deterministic ($0) - a small pool of
        # varied warm decline-and-redirect lines instead of one canned paragraph.
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
            print("\n[Formatter] Skipped LLM Formatting: CHITCHAT matches deterministic response (Tokens: 0, Cost: $0.00)\n")
            if ontology.chitchat_responses:
                return random.choice(ontology.chitchat_responses)
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
            # 3.5a A real category matched but even the expanded query
            # variants (search_engine.search_or_expand) came up empty - offer
            # that category's own subcategory menu instead of a dead-end
            # "try other keywords" message. Still $0: menu is computed once
            # by orchestrator (ontology.subcategories_for) and attached to
            # evidence - reading it from there (not recomputing here) keeps
            # the text on screen and what's persisted to conversation.memory
            # for a later "số N" guaranteed identical.
            menu = evidence.subcategory_menu
            if menu and menu["subcategories"]:
                listed = "\n".join(f"{i}. {s['name'].capitalize()}" for i, s in enumerate(menu["subcategories"][:10], start=1))
                print("\n[Formatter] Skipped LLM Formatting: SEARCH empty matches deterministic subcategory menu (Tokens: 0, Cost: $0.00)\n")
                return (
                    f"Delippy chưa tìm thấy sản phẩm khớp với yêu cầu của bạn trong nhóm **{menu['name']}**. "
                    f"Bạn có thể chọn cụ thể hơn một trong các mục sau:\n\n{listed}\n\n"
                    "Bạn muốn tìm ở mục nào trong số này không?"
                )
            if not context.category:
                # 3.5b category never resolved at all - this is very likely
                # outside Delippy's catalog entirely (jobs, food delivery,
                # weather...), not just a bad keyword within a real category.
                # State current coverage instead of paying for an LLM call to
                # guess/decline. See orchestrator.py: the cached-related-
                # products fallback is deliberately skipped in this exact
                # case so it lands here instead of the LLM branch below.
                names = ontology.top_level_category_names()
                if names:
                    listed = ", ".join(n.capitalize() for n in names)
                    print("\n[Formatter] Skipped LLM Formatting: SEARCH empty + unresolved category matches deterministic scope response (Tokens: 0, Cost: $0.00)\n")
                    return (
                        "Delippy hiện chưa hỗ trợ tìm kiếm với nội dung này trên nền tảng. "
                        f"Hiện tại Delippy có các nhóm ngành: {listed}.\n\n"
                        "Bạn cần tìm sản phẩm/dịch vụ nào trong số này không?"
                    )

            print("\n[Formatter] Skipped LLM Formatting: SEARCH matches deterministic empty result (Tokens: 0, Cost: $0.00)\n")
            if ontology.search_empty_responses:
                return random.choice(ontology.search_empty_responses)
            return "Delippy hiện chưa tìm thấy sản phẩm nào khớp với yêu cầu của bạn. Bạn thử tìm với từ khoá khác xem sao nhé!"

        # 4. Fallback to the configured LLM provider for Consultation, Comparison and FAQ Answers
        # evidence.products can hold up to 20 (kept for "xem thêm" pagination) -
        # cap what actually goes into the prompt so pagination storage doesn't
        # inflate LLM token cost.
        evidence_for_llm = evidence.copy(update={"products": evidence.products[:5]}) if evidence.products else evidence

        # Strip empty/None fields and use compact separators to keep the prompt
        # small even when evidence carries a lot of data (e.g. 3-way comparisons).
        evidence_payload = {
            k: v for k, v in evidence_for_llm.dict(exclude_none=True).items()
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
