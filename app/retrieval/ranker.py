import re
from typing import List, Dict, Any, Optional
from app.models.shopping_context import ShoppingContext
from app.knowledge.ontology import ontology

def _query_words(query_q: Optional[str]) -> List[str]:
    if not query_q:
        return []
    return [w for w in query_q.lower().split() if len(w) > 1 or w.isdigit()]

def top_match_confidence(product_name: str, query_q: Optional[str]) -> Optional[float]:
    """Fraction of query_q's meaningful words that literally appear (word-
    boundary, not substring) in product_name - same tokenization Ranker.rank()
    uses for its own keyword-match scoring, factored out so search_engine can
    flag a weak top result (see Evidence.low_confidence) without duplicating
    the regex. None when there's nothing to compare (no query text)."""
    q_words = _query_words(query_q)
    if not q_words:
        return None
    name_lower = (product_name or "").lower()
    matched = sum(1 for w in q_words if re.search(rf"\b{re.escape(w)}\b", name_lower))
    return matched / len(q_words)

class Ranker:
    def rank(self, products: List[Dict[str, Any]], context: ShoppingContext, intended_subcategory: Optional[str] = None) -> List[Dict[str, Any]]:
        if not products:
            return []

        # NOTE: search results are ProductCard objects, which carry no
        # "category" field at all (only ProductDetail does - see product_api.md).
        # There is nothing here to re-verify a product's category against, so
        # we don't try - the backend's own category_id filter (passed in
        # search_engine.search) is the single source of truth for category
        # correctness. Re-deriving it here from a field that doesn't exist on
        # this data used to hard-zero every single search result whenever a
        # category was known.
        scored_list = []
        for p in products:
            score = 0.0
            p_name = p.get("name", "").lower()
            brand_match = False
            keyword_match_count = 0

            # Penalize accessories cluttering a main-device search
            if ontology.is_accessory(p_name, context.category):
                score -= 0.6

            # 1. Brand Matching (40%)
            if context.brand:
                if context.brand.lower() in p_name:
                    brand_match = True
                    score += 0.4

            # 2. Price Proximity (30%)
            price = p.get("price")
            if price is not None:
                in_range = True
                if context.price_min is not None and price < context.price_min:
                    in_range = False
                if context.price_max is not None and price > context.price_max:
                    in_range = False
                if in_range:
                    score += 0.3

            # 3. Keyword Word Match (30%) - word-boundary, not substring:
            # a plain `w in p_name` check let short query words false-match
            # inside unrelated words in the product name (e.g. query "máy in"
            # (printer) counted "in" as matched against a washing machine
            # named "... LG Inverter 10.5kg", since "in" is literally the
            # first two letters of "inverter"). Same class of bug already
            # fixed in ontology.find_brand()'s word-boundary regex.
            if context.query_q:
                # len(w) > 1 drops single-char filler, but a bare digit is a
                # single char too - it excluded grade/size numbers ("lớp 5",
                # "size 6") from scoring entirely, so e.g. "lớp 1" and "lớp
                # 5" books tied on "sách"+"lớp" and the actual grade never
                # broke the tie.
                q_words = _query_words(context.query_q)
                if q_words:
                    keyword_match_count = sum(1 for w in q_words if re.search(rf"\b{re.escape(w)}\b", p_name))
                    score += 0.3 * (keyword_match_count / len(q_words))

            # 4. Subcategory mismatch check - catches what keyword overlap
            # alone can't: "máy in" (printer, subcategory "nạp mực in") and
            # "máy tính xách tay" (laptop, subcategory "laptop theo nhãn
            # hiệu") share the top-level category AND the generic word "máy",
            # so a laptop/monitor used to pass the keyword-overlap check
            # above purely on that shared word. Only fires when there's
            # enough signal on BOTH sides to compare (a confidently resolved
            # intended_subcategory, and a product name specific enough to
            # confidently resolve its own) - absence of a product-side match
            # is not evidence of mismatch, so it does not penalize.
            category_mismatch = False
            if intended_subcategory and context.query_q:
                product_subcategory = ontology.best_subcategory_for_product(p_name)
                category_mismatch = bool(product_subcategory) and product_subcategory != intended_subcategory
                if category_mismatch:
                    score -= 0.6

            # Relevance gate, most authoritative signal first.
            # - Brand has no backend filter param, so it's the one thing we
            #   MUST verify client-side (or fall back to keyword overlap).
            # - If a category resolved AND the user also gave free-text
            #   keywords, still require at least one keyword hit AND no
            #   confident subcategory mismatch, rather than trusting
            #   category_id alone: the backend's own text search inside that
            #   category is approximate, not exact, and let a query like
            #   "máy in" (printer) return a laptop/monitor whose name shares
            #   nothing with "máy in" except the category scope and the
            #   generic word "máy".
            # - If a category resolved but the user gave NO free-text (pure
            #   category browse), there's nothing to check keywords against,
            #   so category_id scoping alone is trusted.
            if context.brand:
                is_relevant = brand_match or keyword_match_count > 0
            elif context.category and context.query_q:
                is_relevant = keyword_match_count > 0 and not category_mismatch
            elif context.category:
                is_relevant = True
            elif context.query_q:
                is_relevant = keyword_match_count > 0
            else:
                is_relevant = True

            scored_list.append((score, is_relevant, p))

        scored_list = [item for item in scored_list if item[1]]
        scored_list.sort(key=lambda x: x[0], reverse=True)
        return [p for _, _, p in scored_list]

ranker = Ranker()
