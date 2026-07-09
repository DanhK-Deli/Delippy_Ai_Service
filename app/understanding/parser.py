import re
from typing import Any, Dict, List, Optional
from app.understanding.query_normalizer import query_normalizer
from app.understanding.intent_classifier import intent_classifier
from app.understanding.entity_extractor import entity_extractor
from app.chat.lazy import Lazy
from app.client.llm_client import llm_client_wrapper
from app.models.shopping_context import ShoppingContext

# Matches "số 1", "phòng số 2", "sản phẩm số 3"... Deliberately NOT "thứ N" -
# "thứ 2"/"thứ 4"/"thứ 7" etc. are also the standard Vietnamese way to write
# weekdays (Monday/Wednesday/Saturday), so that pattern is left to the AI
# Parser (which has conversation context to disambiguate) rather than risking
# a wrong deterministic guess. "số N" carries no such calendar ambiguity.
_ORDINAL_REF_RE = re.compile(r"\bsố\s*(\d{1,2})\b")

class QueryParser:
    async def parse(
        self,
        query: str,
        history_lazy: Lazy,
        product_options: Optional[List[Dict[str, Any]]] = None,
        subcategory_options: Optional[List[Dict[str, Any]]] = None,
        subcategory_category_slug: Optional[str] = None,
    ) -> ShoppingContext:
        # 1. Normalize
        normalized = query_normalizer.normalize(query)

        # 1.5 Ordinal reference to a just-shown list ("phòng số 1", "sản
        # phẩm số 3", or "số 10" picking a subcategory off the zero-result
        # menu) - resolve directly against the cached list instead of paying
        # for an AI Parser call to reason about which item "số N" means.
        # Scoped to short queries only (mirrors intent_classifier's own
        # length guard below) and to an in-range index, so a coincidental
        # "số N" inside a longer/unrelated sentence (a phone number, a price)
        # never misfires - out-of-range just falls through to normal parsing.
        # subcategory_options checked FIRST: it's only ever non-empty right
        # after we just showed that exact menu (orchestrator clears it the
        # moment a real product search succeeds), so it's the more recent
        # context whenever both happen to be present.
        if len(query.split()) <= 6:
            ordinal_match = _ORDINAL_REF_RE.search(normalized)
            if ordinal_match:
                ordinal = int(ordinal_match.group(1))
                if subcategory_options and 1 <= ordinal <= len(subcategory_options):
                    target = subcategory_options[ordinal - 1]
                    print(f"\n[Parser] Parsing raw query: '{query}'")
                    print(f"  - Deterministic ordinal reference -> subcategory #{ordinal}: '{target.get('name')}'")
                    return ShoppingContext(
                        intent="SEARCH",
                        category=subcategory_category_slug,
                        subcategory=target.get("name"),
                        query_q=None,
                    )
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
        intent = intent_classifier.classify(normalized)
        
        # 3. Extract entities
        entities = entity_extractor.extract(normalized)

        print(f"\n[Parser] Parsing raw query: '{query}'")
        print(f"  - Normalized  : '{normalized}'")
        print(f"  - Intent Rule : {intent}")
        print(f"  - Entities    : Brand={entities['brand']}, Category={entities['category']} (ID={entities['category_id']}), PriceMin={entities['price_min']}, PriceMax={entities['price_max']}")

        if intent is not None:
            cleaned_q = entity_extractor.clean_query_keywords(normalized)
            print(f"  - Deterministic Parse Result -> Intent: {intent}, Core Query q: '{cleaned_q}'")
            return ShoppingContext(
                intent=intent,
                category=entities["category"],
                subcategory=entities["subcategory"],
                brand=entities["brand"],
                price_min=entities["price_min"],
                price_max=entities["price_max"],
                query_q=cleaned_q
            )

        # 4. Fallback to Gemini AI Parse
        print("  - Intent ambiguous. Falling back to AI Parser...")
        history_str = await history_lazy.get()
        ai_context = await llm_client_wrapper.parse_query(query, history_str, product_options=product_options)
        
        # Overlay deterministic entities if AI missed them
        if not ai_context.brand and entities["brand"]:
            ai_context.brand = entities["brand"]
        if not ai_context.category and entities["category"]:
            ai_context.category = entities["category"]
            
        print(f"  - AI Parse Result -> Intent: {ai_context.intent}, Brand: {ai_context.brand}, Category: {ai_context.category}, PriceMax: {ai_context.price_max}, Core Query q: '{ai_context.query_q}', Expanded: {ai_context.expanded_queries}")
        return ai_context

query_parser = QueryParser()
