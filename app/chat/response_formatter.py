import json
import random
import re
from typing import Dict, Any, List
from app.models.evidence import Evidence
from app.models.shopping_context import ShoppingContext
from app.models.response_plan import ResponsePlan
from app.chat.lazy import Lazy
from app.client.llm_client import llm_client_wrapper
from app.knowledge.ontology import ontology
from app.understanding.intent_classifier import is_prompt_probe_query

# Rendering vocabulary for Compare Builder's structured output (see
# app/chat/compare_builder.py) - the builder only ever produces criterion
# ids/values/differences, never display text; that stays here.
_COMPARE_CRITERION_LABELS = {
    "price": "Giá",
    "stock": "Tình trạng",
    "rating": "Đánh giá",
    "sold_count": "Đã bán",
}

def _format_compare_value(criterion: str, item: Dict[str, Any]) -> str:
    if criterion == "price":
        price = item.get("price")
        return f"{price:,.0f}đ" if price is not None else "-"
    if criterion == "stock":
        return "Còn hàng" if item.get("in_stock") else "Hết hàng"
    if criterion == "rating":
        rating = item.get("rating")
        return f"{rating}⭐" if rating is not None else "Chưa có đánh giá"
    if criterion == "sold_count":
        sold = item.get("sold_count")
        return f"{sold:,}" if sold is not None else "-"
    return "-"

def _format_highlight_sentence(highlight: Dict[str, Any]) -> str:
    # "price" never reaches here - compare_builder.py deliberately never
    # highlights it (a price difference is self-evident from the table's own
    # numbers; a bare "✓ rẻ hơn X" reads like an unnecessary hard sell).
    winners = ", ".join(highlight["winners"])
    criterion = highlight["criterion"]
    difference = highlight.get("difference")
    if criterion == "stock":
        return f"{winners} còn hàng."
    if criterion == "rating":
        return f"{winners} được đánh giá cao hơn {round(difference, 1)}⭐."
    if criterion == "sold_count":
        return f"{winners} bán chạy hơn {difference:,} lượt."
    return f"{winners} vượt trội hơn ở {criterion}."

# Rendering vocabulary for the Planner's warning tags (see
# response_planner.py._search_result_warnings) - the planner only ever
# produces symbolic tags, never Vietnamese text; that stays here.
_WARNING_LINES = {
    "out_of_stock": "Có một vài sản phẩm hiện đã hết hàng sẵn trong kho.",
    "low_confidence": (
        "Các sản phẩm trên chỉ khớp một phần với mô tả của bạn, có thể chưa đúng ý lắm "
        "- bạn xem thử hoặc thử mô tả rõ hơn giúp Delippy nhé!"
    ),
}

# Recommendation Engine (Sprint 2) - matches recommendation_builder.py's own
# 1-5 scale (see _STAR_MAX there).
_REC_STAR_MAX = 5

def _render_warnings(warnings: List[str]) -> str:
    lines = [_WARNING_LINES[w] for w in warnings if w in _WARNING_LINES]
    if not lines:
        return ""
    if len(lines) == 1:
        return f"\n_Lưu ý: {lines[0]}_\n"
    bullets = "\n".join(f"• {line}" for line in lines)
    return f"\nDelippy có vài lưu ý:\n{bullets}\n"

def _minimize_product(p: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(p, dict):
        return p
    min_p = {}
    for field in ["name", "price", "rating", "sold_count", "slug", "stock"]:
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
    async def format(self, query: str, history_lazy: Lazy, evidence: Evidence, context: ShoppingContext, plan: ResponsePlan) -> str:
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
        if plan.type == "DETAIL":
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
            
            # Product Deep-Dive (see orchestrator.py) - a "tư vấn kỹ hơn"
            # ask replaces the raw seller description with a genuine
            # analysis drawn from the LLM's real market knowledge, since the
            # seller's own text is often too sparse to consult from at all
            # (confirmed live - a real listing's whole description was two
            # phone numbers). Falls back to the plain snippet unchanged when
            # no deep-dive was requested/succeeded this turn.
            if evidence.deep_dive_text:
                resp += f"\n**Tư vấn chi tiết** (kiến thức thị trường chung, không phải cam kết từ người bán):\n{evidence.deep_dive_text}\n"
            elif d.get("details"):
                clean_desc = re.sub(r"<[^>]*>", "", str(d.get("details", "")))
                desc = " ".join(clean_desc.split())[:300]
                resp += f"\n**Mô tả**: {desc}...\n"

            # Planner already decided WHETHER there's a specific product worth
            # suggesting a compare against (see response_planner.py's
            # _next_action_and_target) - one clear question naming it beats a
            # random vague "so sánh HAY xem thêm?" pick. Falls back to the
            # random pool only when there's genuinely nothing to suggest.
            if plan.next_action == "COMPARE" and plan.target:
                candidate_name = plan.target.get("candidate", {}).get("name")
                outro = f"Bạn muốn Delippy so sánh sản phẩm này với **{candidate_name}** không?"
            else:
                outro = random.choice(ontology.product_info_outros) if ontology.product_info_outros else \
                    "Bạn muốn Delippy so sánh sản phẩm này với sản phẩm khác, hay xem thêm sản phẩm tương tự không?"
            resp += f"\n{outro}"

            if ontology.product_info_intros:
                resp = f"{random.choice(ontology.product_info_intros)}\n\n{resp}"

            print("\n[Formatter] Skipped LLM Formatting: PRODUCT_INFO matches deterministic response (Tokens: 0, Cost: $0.00)\n")
            return resp

        # 2.5 Clarification question - either a complete error message already
        # written upstream (PRODUCT_INFO ambiguous reference, or SEARCH's
        # requirement-gap question - see orchestrator.py) or a too-vague-to-
        # show-results nudge the Planner decided on (see response_planner.py).
        # Either way the Planner already decided THIS turn is a clarification;
        # the formatter just picks which text source to render.
        if plan.type == "CLARIFICATION":
            if evidence.error:
                print("\n[Formatter] Skipped LLM Formatting: CLARIFICATION matches upstream error message (Tokens: 0, Cost: $0.00)\n")
                return evidence.error
            clarify_templates = ontology.clarifying_questions_for(context.category)
            term = context.query_q or context.category or "sản phẩm này"
            question = random.choice(clarify_templates).format(term=term)
            print("\n[Formatter] Skipped LLM Formatting: SEARCH too-vague-to-show matches deterministic clarifying question (Tokens: 0, Cost: $0.00)\n")
            return question

        # 3. Search Result Deterministic Formatting - Planner already decided
        # this turn is a plain product list (not consultative, not too vague -
        # see response_planner.py), so the formatter only renders it.
        if plan.type == "SEARCH_RESULT":
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

            # Warning notes - tags decided by the Planner (see
            # response_planner.py._search_result_warnings), formatter just
            # renders them. Combined into ONE "Delippy có vài lưu ý:" bullet
            # block instead of stacking separate "_Lưu ý: ..._" lines, which
            # read as mechanical/AI-generated when 2+ applied at once.
            resp += _render_warnings(plan.warnings)

            # A bare category/keyword search with no brand, price range or
            # purpose is under-specified - ask a narrowing question instead of
            # the generic prompt. Phrasing lives in knowledge/clarifying_questions.json
            # (never hardcoded here) and one is picked at random. Also nudge
            # this way whenever the Parser judged consultation_level="assist"
            # (a general brand/category ask - "Laptop Dell", "Máy giặt LG" -
            # that already HAS a brand, so is_broad_query alone would miss it
            # and fall to the generic outro below) - the "Hybrid" UX: show
            # results now, but invite narrowing instead of a bland close.
            clarify_templates = ontology.clarifying_questions_for(context.category)
            if plan.is_broad_query and clarify_templates:
                term = context.query_q or context.category or "sản phẩm này"
                question = random.choice(clarify_templates).format(term=term)
                resp += f"\n{question}"
            else:
                # A structured, numbered menu instead of an open multi-choice
                # question ("...xem chi tiết hơn hay so sánh sản phẩm nào
                # không?"). That phrasing offers 2+ actions with no way to
                # tell which one a bare "có" answers - a real gap even with
                # memory/follow-up resolution working correctly, since
                # nothing here ever committed to ONE specific next action.
                # Naming the exact reply shape (a number, "so sánh X và Y",
                # "xem thêm") gives parser.py's deterministic ordinal/compare
                # shortcuts something unambiguous to catch - $0, no AI call,
                # and easier for Delippy's older user base to answer than an
                # open question they have to phrase themselves.
                shown_count = min(5, len(evidence.products))
                resp += "\nBạn có thể:\n"
                resp += f"• Nhập số 1-{shown_count} để xem chi tiết sản phẩm.\n"
                if shown_count >= 2:
                    resp += '• Nhập "so sánh 1 và 2" (đổi số tương ứng) để so sánh 2 sản phẩm.\n'
                if len(evidence.products) > 5:
                    resp += '• Nhập "xem thêm" để xem các sản phẩm còn lại.\n'

            print("\n[Formatter] Skipped LLM Formatting: SEARCH matches deterministic product list (Tokens: 0, Cost: $0.00)\n")
            return resp

        # A relaxed fallback set (see orchestrator.py) means there IS
        # something to offer instead of a bare dead-end - fall through to
        # the LLM formatter below, which already knows how to present
        # not_found + related_products warmly (formatter_prompt.txt rule 5).
        if plan.type == "ZERO_RESULT":
            # Warm, personalized zero-result reply (zero_result_prompt.txt) -
            # replaces 3 formerly-canned texts that read as robotic ("không
            # có ý nghĩa gì hết" per live user feedback). The LLM only writes
            # ONE intro sentence (acknowledge + pivot) - it never sees or
            # invents the actual subcategory/category names list, which is
            # still built deterministically below exactly as before, so
            # nothing here can hallucinate a menu option that doesn't exist.
            #
            # render_context tells the LLM WHAT is about to render right
            # after its sentence (so it can word the pivot accordingly)
            # without ever handing it the actual list to describe/enumerate -
            # that stays 100% backend-owned. A bare bool (is_category_menu)
            # would need a new bool per future render type (related_products,
            # brands, keyword_suggestions...); a {"type", "count"} dict is the
            # one shape every future type reuses. Computed BEFORE the LLM
            # call and reused as-is for the deterministic list append below,
            # so what's described and what's actually rendered can't drift.
            menu = evidence.subcategory_menu
            names = ontology.top_level_category_names() if not context.category else []
            if menu and menu["subcategories"]:
                render_context = {"type": "subcategory_menu", "count": min(len(menu["subcategories"]), 10)}
            elif names:
                render_context = {"type": "top_level_categories", "count": len(names)}
            else:
                render_context = {"type": "none", "count": 0}

            search_term = context.query_q or context.purpose or context.category or "sản phẩm này"
            intro = await llm_client_wrapper.format_zero_result_response(search_term, render_context)

            # A real category matched but even the expanded query variants
            # (search_engine.search_or_expand) came up empty - offer that
            # category's own subcategory menu instead of a dead-end "try
            # other keywords" message. menu is computed once by orchestrator
            # (ontology.subcategories_for) and attached to evidence - reading
            # it from there (not recomputing here) keeps what's shown and
            # what's persisted to conversation.memory for a later "số N"
            # guaranteed identical.
            if render_context["type"] == "subcategory_menu":
                listed = "\n".join(f"{i}. {s['name'].capitalize()}" for i, s in enumerate(menu["subcategories"][:10], start=1))
                return f"{intro}\n\n{listed}\n\nBạn muốn tìm ở mục nào trong số này không?"

            if render_context["type"] == "top_level_categories":
                # category never resolved at all - this is very likely
                # outside Delippy's catalog entirely (jobs, food delivery,
                # weather...), not just a bad keyword within a real category.
                # See orchestrator.py: the cached-related-products fallback is
                # deliberately skipped in this exact case so it lands here
                # instead of the LLM branch below.
                listed = ", ".join(n.capitalize() for n in names)
                return (
                    f"{intro}\n\nHiện tại Delippy có các nhóm ngành: {listed}.\n\n"
                    "Bạn cần tìm sản phẩm/dịch vụ nào trong số này không?"
                )

            return intro

        # 3.5 Compare Builder result - a real field-by-field comparison
        # (winners/value/difference per criterion, see compare_builder.py),
        # rendered as a markdown table + summary bullets with ZERO LLM calls.
        # Only present when >=2 products actually resolved (see
        # orchestrator.py); otherwise comparison_table is None and this falls
        # through to the generic LLM comparison below unchanged (e.g. a
        # mostly-not-found "so sánh samsung và lg" brand-level ask).
        if plan.type == "COMPARE" and evidence.comparison_table:
            table = evidence.comparison_table
            items = table["items"]

            resp = ""
            if evidence.not_found:
                resp += f"_Delippy chưa tìm thấy: {', '.join(evidence.not_found)}._\n\n"

            resp += "**So sánh nhanh**\n\n"
            header = "| Tiêu chí | " + " | ".join(it["name"] for it in items) + " |"
            resp += header + "\n"
            resp += "|" + "---|" * (len(items) + 1) + "\n"
            for criterion in table["criteria"]:
                row = [_COMPARE_CRITERION_LABELS.get(criterion, criterion)]
                for it in items:
                    row.append(_format_compare_value(criterion, it))
                resp += "| " + " | ".join(row) + " |\n"

            if table["highlights"]:
                resp += "\nDelippy nhận thấy:\n"
                for h in table["highlights"]:
                    resp += f"✓ {_format_highlight_sentence(h)}\n"

            # Call LLM comparison analysis to provide human-like advice on top of raw table data
            if evidence.comparison_results:
                analysis = await llm_client_wrapper.format_comparison_analysis(
                    query=query,
                    products=[
                        {
                            "name": p.get("name"),
                            "description": p.get("description") or p.get("details") or "",
                            "price": p.get("price"),
                            "brand": p.get("brand_name")
                        } for p in evidence.comparison_results
                    ]
                )
                if analysis:
                    resp += f"\n\n**Gợi ý lựa chọn:**\n{analysis}"

            print("\n[Formatter] Rendered hybrid comparison: deterministic table + LLM semantic analysis.\n")
            return resp.rstrip()


        # 3.6 Recommendation Engine (Sprint 2) - deterministic star ratings +
        # Vietnamese success/warning bullets from recommendation_builder.py
        # (orchestrator.py already sorted evidence.products by suitability
        # before this runs - see its own comment there). Detected purely from
        # evidence's own enriched fields (same pattern as COMPARE checking
        # evidence.comparison_table above), not plan.type, since CONSULT and
        # FOLLOWUP both fall through to the same LLM path below unchanged.
        # Rendered here, in FULL, so the LLM call below never needs to
        # re-list products/specs - it only adds a short closing sentence (see
        # formatter_prompt.txt's already_rendered_recommendations rule and
        # the evidence_payload flag set right before that call).
        recommendation_block = ""
        if evidence.products and evidence.products[0].get("suitability_score") is not None:
            lines = []
            for p in evidence.products[:5]:
                score = p.get("suitability_score") or 0
                stars = "⭐" * score + "☆" * (_REC_STAR_MAX - score)
                lines.append(f"**{p.get('name')}** - {p.get('price'):,.0f}đ {stars}")
                for reason in p.get("recommend_reasons") or []:
                    icon = "✓" if reason.get("status") == "success" else "⚠"
                    lines.append(f"{icon} {reason.get('text')}")
            recommendation_block = "\n".join(lines)
            # Only ever set on the (now top-ranked) products[0] - see
            # recommendation_builder._build_trade_off() - a genuine
            # complementary-strength note between the top 2 candidates, not
            # forced when one strictly dominates the other.
            trade_off = evidence.products[0].get("trade_off_summary")
            if trade_off:
                recommendation_block += f"\n\n{trade_off}"
            print("\n[Formatter] Recommendation Engine: deterministic star ratings + reasoning bullets rendered (Tokens: 0, Cost: $0.00)\n")

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

        # Tells the LLM (via formatter_prompt.txt's own rule) that
        # recommendation_block above already lists every product's name/
        # price/star rating/reasons - without this flag the LLM has no way
        # to know that block exists (it's rendered in pure Python, never
        # part of the prompt itself) and would re-list specs it just saw.
        if recommendation_block:
            evidence_payload["already_rendered_recommendations"] = True

        evidence_str = json.dumps(evidence_payload, ensure_ascii=False, separators=(",", ":"))
        history_str = await history_lazy.get()
        llm_response = await llm_client_wrapper.format_response(query, history_str, evidence_str)

        # Append warning note to LLM response if any product is out of stock (and not already warned)
        if intent == "SEARCH" and evidence.products:
            has_out_of_stock = any(int(p.get("stock") or 0) <= 0 for p in evidence.products[:5])
            if has_out_of_stock and "hết hàng" not in llm_response.lower() and "không còn số lượng" not in llm_response.lower():
                llm_response += "\n\n_Lưu ý: Có một vài sản phẩm hiện đã hết hàng sẵn trong kho._"

        if recommendation_block:
            return f"{recommendation_block}\n\n{llm_response}"
        return llm_response

response_formatter = ResponseFormatter()
