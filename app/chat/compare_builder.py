from typing import Any, Dict, List, Optional
from app.knowledge.ontology import ontology

# Criteria whose lower value wins (everything else in compare_rule.json is
# "higher is better": rating, sold_count). "stock" is handled separately
# below (boolean in-stock/out-of-stock, not a numeric min/max).
_LOWER_IS_BETTER = {"price"}

# Shown in the table (still useful reference info), but never given a "✓
# winner" claim - a price difference is self-evident from the raw numbers
# sitting right next to each other; a bare "✓ rẻ hơn X" reads like a hard
# sell for something the user can already see themselves.
_NO_HIGHLIGHT_CRITERIA = {"price"}

# Below this, "đã bán 2" / "đã bán 0" reads as noise, not a real popularity
# signal - starting calibration (not measured against real traffic; revisit
# once real compare volume accumulates - see the parse-cache similarity
# floor for the same kind of "reasoned starting point" precedent).
_SOLD_COUNT_MIN_TO_SHOW = 20

class CompareBuilder:
    """Deterministic, zero-LLM comparison: computes which product(s) win each
    criterion in app/knowledge/compare_rule.json (resolved per category) and
    by how much, so response_formatter can render a real comparison table
    instead of handing two product blobs to an LLM to improvise over. Never
    reads/derives spec fields (RAM, camera, capacity...) - those don't exist
    in the catalog yet (no Spec Extractor this sprint); only price/stock/
    rating/sold_count, which are reliably real API fields.

    Deliberately does NOT attempt a "which is better for you" use-case
    comparison (the highest-value ask, per the user) - that needs a
    category/keyword -> use-case tagging rule (a real Attribute Ontology),
    which is Sprint 2 scope, not something to bolt onto Compare alone ahead
    of that broader design. What this DOES do: never present metadata noise
    (a 0 rating, a single-digit sold_count) as if it were a meaningful
    "winner", so what's shown is at least honest.
    """

    def build(self, comparison_results: List[Dict[str, Any]], category: Optional[str]) -> Optional[Dict[str, Any]]:
        if len(comparison_results) < 2:
            return None

        items = [{
            "name": p.get("name"),
            "price": p.get("price"),
            "in_stock": int(p.get("stock") or 0) > 0,
            # 0 and None both mean "no ratings yet", never a real quality
            # signal - normalizing to None here means the generic missing-
            # data handling in _highlight() already does the right thing,
            # with no separate "rating" special case needed there.
            "rating": p.get("rating") or None,
            "sold_count": p.get("sold_count"),
            # Brand is never a real API field (see search_engine.py's own
            # brand filtering) - only ever derived from the name, same
            # resolver the rest of the codebase already relies on. Shown as
            # an identity label only, never scored as "better/worse".
            "brand": ontology.find_brand((p.get("name") or "").lower()),
        } for p in comparison_results]

        criteria = [c for c in ontology.compare_criteria_for(category) if self._is_visible(c, items)]
        highlights = [h for h in (self._highlight(c, items) for c in criteria) if h]
        return {"items": items, "criteria": criteria, "highlights": highlights}

    def _is_visible(self, criterion: str, items: List[Dict[str, Any]]) -> bool:
        """Whether this criterion has anything worth SHOWING as a table row
        at all, before even asking whether it produces a highlight - e.g. no
        point rendering a "Đánh giá" row when nobody has a real rating yet."""
        if criterion == "rating":
            return any(it["rating"] is not None for it in items)
        if criterion == "sold_count":
            return any((it.get("sold_count") or 0) >= _SOLD_COUNT_MIN_TO_SHOW for it in items)
        return True

    def _highlight(self, criterion: str, items: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if criterion in _NO_HIGHLIGHT_CRITERIA:
            return None

        if criterion == "stock":
            in_stock = [it["name"] for it in items if it["in_stock"]]
            if not in_stock or len(in_stock) == len(items):
                # Nobody in stock, or everybody - no differentiator to flag.
                return None
            return {"criterion": "stock", "winners": in_stock, "value": True, "difference": None}

        # Numeric criteria (rating/sold_count) - missing data on ANY side
        # means this criterion isn't fairly comparable this round; a product
        # with no rating never gets marked as "losing" on rating.
        if not all(it.get(criterion) is not None for it in items):
            return None
        values = [it[criterion] for it in items]
        if len(set(values)) < 2:
            return None  # tied - nothing to flag

        lower_is_better = criterion in _LOWER_IS_BETTER
        best = min(values) if lower_is_better else max(values)
        if criterion == "sold_count" and best < _SOLD_COUNT_MIN_TO_SHOW:
            return None  # even the "winner" isn't a meaningful sales signal
        worst = max(values) if lower_is_better else min(values)
        return {
            "criterion": criterion,
            "winners": [it["name"] for it in items if it[criterion] == best],
            "value": best,
            "difference": abs(best - worst),
        }

compare_builder = CompareBuilder()
