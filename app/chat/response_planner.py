from typing import Any, Dict, List, Optional, Tuple
from app.models.evidence import Evidence
from app.models.shopping_context import ShoppingContext
from app.models.response_plan import ResponsePlan
from app.knowledge.ontology import ontology
from app.understanding.intent_classifier import is_too_vague_for_results, needs_consultation

class ResponsePlanner:
    """Sits between retrieval and response_formatter. Decides WHAT kind of
    reply this turn gets (type/next_action/show_products/show_menu/warnings)
    from (query, evidence, context) alone - response_formatter should never
    need to re-derive these from evidence/context itself, only render them.

    Deliberately does NOT run for GREETING/SOCIAL/CHITCHAT - those never
    reach retrieval (response_formatter's own early sections 1/1.5/1.6
    short-circuit before evidence exists), so there is nothing for a
    post-retrieval planner to plan for them.
    """

    def plan(
        self, query: str, evidence: Evidence, context: ShoppingContext,
        already_nudged: bool = False, already_category_confirmed: bool = False,
    ) -> ResponsePlan:
        intent = context.intent
        next_action, target, reason = self._next_action_and_target(intent, evidence)

        # PRODUCT_INFO: a deterministic detail card, a deterministic
        # ambiguous-reference error, or (neither) falls through to the
        # generic LLM formatter same as COMPARE/FAQ below.
        if intent == "PRODUCT_INFO":
            if evidence.details:
                return ResponsePlan(type="DETAIL", next_action=next_action, target=target, reason=reason)
            if evidence.error:
                return ResponsePlan(type="CLARIFICATION", next_action=next_action, target=target, reason=reason)
            return ResponsePlan(type="CONSULT", next_action=next_action, target=target, reason=reason)

        # SEARCH's own requirement-gap question - evidence.error was set by
        # orchestrator BEFORE retrieval even ran (see orchestrator.py's
        # gap_fill_question check), so this is always a fresh, complete
        # question with nothing else to decide.
        if intent == "SEARCH" and evidence.error:
            return ResponsePlan(type="CLARIFICATION", next_action=next_action, target=target, reason=reason)

        if intent == "COMPARE":
            return ResponsePlan(type="COMPARE", next_action=next_action, target=target, reason=reason)

        if intent == "FAQ":
            return ResponsePlan(type="FAQ", next_action=next_action, target=target, reason=reason)

        if intent == "SEARCH":
            # entity_extractor found no CONFIDENT category, only a weak
            # single-word guess it declined to trust on its own (see
            # ontology.find_category_weak()'s docstring / parser.py's
            # _category_confirm_candidate) - ask instead of silently
            # searching category-less. `already_category_confirmed` stops
            # this from looping forever if the same weak guess keeps coming
            # back turn after turn (mirrors already_nudged below).
            if context._category_confirm_candidate and not already_category_confirmed:
                return ResponsePlan(
                    type="CLARIFICATION",
                    next_action="CONFIRM_CATEGORY",
                    target={"candidate": context._category_confirm_candidate},
                    reason="category_confirm",
                )

            consultative = self._is_consultative(query, context)

            if not consultative and evidence.products:
                is_broad_query = (
                    not context.brand and context.price_min is None
                    and context.price_max is None and not context.purpose
                )
                clarify_templates = ontology.clarifying_questions_for(context.category)
                # Two guards on TOP of is_too_vague_for_results, both there to
                # stop this nudge from looping forever: (1) `_no_text_search` -
                # the user just picked a specific subcategory off a menu
                # (deterministic ordinal/range pick, see parser.py) - that's
                # already a deliberate narrowing action, asking a generic
                # clarifying question right after feels redundant. (2)
                # `already_nudged` - this category's nudge already fired once
                # this session (see orchestrator.py, keyed on
                # memory["vague_nudge_shown_category"]). Necessary because
                # is_too_vague_for_results only ever clears via
                # brand/price/purpose - a pooled question about an attribute
                # with NO dedicated ShoppingContext field (age, occasion,
                # skin_need...) relies on the AI parser guessing it into
                # `purpose`, which it often won't (e.g. "bé trai" answering a
                # gender question isn't semantically a "purpose") - without
                # this guard that reply is silently dropped and the identical
                # question re-fires every turn, forever. Asking once and then
                # showing whatever results exist beats an infinite loop.
                if not context._no_text_search and not already_nudged and is_too_vague_for_results(context) and clarify_templates:
                    return ResponsePlan(type="CLARIFICATION", next_action=next_action, target=target, reason=reason)

                warnings = self._search_result_warnings(evidence)
                return ResponsePlan(
                    type="SEARCH_RESULT",
                    next_action=next_action,
                    target=target,
                    reason=reason,
                    show_products=min(5, len(evidence.products)),
                    is_broad_query=is_broad_query or context.consultation_level == "assist",
                    warnings=warnings,
                )

            if not evidence.products and not evidence.related_products:
                return ResponsePlan(
                    type="ZERO_RESULT",
                    next_action=next_action,
                    target=target,
                    reason=reason,
                    show_menu=bool(evidence.subcategory_menu),
                )

            # Consultative SEARCH with results, or a zero-direct-match SEARCH
            # that still has related_products to offer warmly - both already
            # routed to the same generic LLM formatter call.
            plan_type = "FOLLOWUP" if context._force_advisory else "CONSULT"
            return ResponsePlan(type=plan_type, next_action=next_action, target=target, reason=reason, consultative=True)

        # Any other intent (shouldn't normally reach here) - generic LLM fallback.
        return ResponsePlan(type="CONSULT", next_action=next_action, target=target, reason=reason)

    def _next_action_and_target(
        self, intent: str, evidence: Evidence
    ) -> Tuple[Optional[str], Optional[Dict[str, Any]], Optional[str]]:
        """Returns (next_action, target, reason). `next_action` mirrors
        orchestrator.py's pre-refactor awaiting_action computation
        (intentionally independent of consultative/type above, so a
        consultative SEARCH-with-products still yields SELECT_PRODUCT exactly
        as it always did) - EXTENDED to make one concrete decision explicit:
        a DETAIL view with a real related product becomes next_action
        "COMPARE" (not the generic "PRODUCT_INFO" label), carrying both
        products' name+slug as `target` so a later bare "có" can resolve
        deterministically into a real comparison (see
        memory_resolver.resolve_followup()'s caller) instead of a generic
        advisory resume. This is the ONE place that decision is made - a
        future sprint adding another real next-action (once it has real
        backing data, e.g. accessories/reviews) only extends this dispatch."""
        if intent == "SEARCH" and evidence.products:
            return "SELECT_PRODUCT", None, None

        if intent == "PRODUCT_INFO" and evidence.details:
            product = {"name": evidence.details.get("name"), "slug": evidence.details.get("slug")}
            if evidence.related_products:
                candidate = evidence.related_products[0]
                # Safeguard: only suggest comparing if they belong to the same top-level category
                prod_cat_id = evidence.details.get("category", {}).get("id") if isinstance(evidence.details.get("category"), dict) else None
                cand_cat_group = ontology.find_category(candidate.get("name") or "")
                cand_cat_id = cand_cat_group.get("id") if cand_cat_group else None
                if prod_cat_id and cand_cat_id and prod_cat_id == cand_cat_id:
                    target = {
                        "product": product,
                        "candidate": {"name": candidate.get("name"), "slug": candidate.get("slug")},
                    }
                    return "COMPARE", target, "related_product"
            return "PRODUCT_INFO", {"product": product}, None

        if intent in ("SEARCH", "PRODUCT_INFO", "COMPARE") and (
            evidence.related_products or evidence.details or evidence.comparison_results
        ):
            return intent, None, None
        return None, None, None

    def _is_consultative(self, query: str, context: ShoppingContext) -> bool:
        if context.consultation_level == "expert" or context.purpose:
            consultative = True
        elif context.consultation_level in ("none", "assist"):
            consultative = False
        else:
            consultative = needs_consultation(query, context)
        return consultative or context._force_advisory

    def _search_result_warnings(self, evidence: Evidence) -> List[str]:
        warnings = []
        if any(int(p.get("stock") or 0) <= 0 for p in evidence.products[:5]):
            warnings.append("out_of_stock")
        if evidence.low_confidence:
            warnings.append("low_confidence")
        return warnings

response_planner = ResponsePlanner()
