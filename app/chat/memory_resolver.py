from typing import Optional
from app.models.conversation import Conversation
from app.models.shopping_context import ShoppingContext

def _shares_a_word(a: Optional[str], b: Optional[str]) -> bool:
    if not a or not b:
        return False
    return bool(set(a.lower().split()) & set(b.lower().split()))

class MemoryResolver:
    def resolve(self, conversation: Conversation, current_context: ShoppingContext) -> ShoppingContext:
        memory = conversation.memory
        
        # 1. Reset memory if user queries a brand-new intent or says greetings/faq/chitchat/social
        if current_context.intent in ["GREETING", "FAQ", "CHITCHAT", "SOCIAL"]:
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

        # Save current query keywords in memory for turn tracking
        if current_context.query_q:
            memory["query_q"] = current_context.query_q

        return current_context

memory_resolver = MemoryResolver()
