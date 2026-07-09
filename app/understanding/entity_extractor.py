import re
from typing import Dict, Any, Optional
from app.knowledge.ontology import ontology

# Currency/quantity unit words - also present in the shared stopwords.json
# (kept there for ontology.find_category(), which is safe to leave as-is:
# it only screens candidate CATEGORY-matching words, not the text a user
# actually searches for). clean_query_keywords() must NOT blindly strip
# these as freestanding words too - "đồng" is also the first syllable of
# "đồng hồ"/"đồng phục" - so it skips them when reusing that shared list
# and only removes them via the attached-number regex below.
_CURRENCY_UNIT_WORDS = {"triệu", "trieu", "tr", "ngàn", "nghìn", "k", "đ", "vnd", "đồng", "dong", "vđ"}


class EntityExtractor:
    def extract(self, query: str) -> Dict[str, Any]:
        text = query.lower()
        entities = {
            "brand": ontology.find_brand(text),
            "category": None,
            "category_id": None,
            "subcategory": None,
            "price_min": None,
            "price_max": None
        }

        # Check Category
        cat_info = ontology.find_category(text)
        if cat_info:
            entities["category"] = cat_info["slug"]
            entities["category_id"] = cat_info["id"]
            # Captured here (from the RAW query text) because it can't be
            # recovered later - search_engine.search() re-resolves category_id
            # by calling find_category() again on this already-resolved slug,
            # which short-circuits find_category()'s step 1 (exact slug match)
            # and never reaches the subcategory-scoring step.
            entities["subcategory"] = cat_info.get("subcategory")

        # Parse Prices (e.g., dưới 20 triệu, trên 5 tr, < 10tr, > 2 triệu)
        # Normalize million representation
        clean_text = text.replace("triệu", "tr").replace("trieu", "tr").replace("m", "tr")
        clean_text = clean_text.replace("ngàn", "k").replace("nghìn", "k")

        # Under/less than (dưới, nhỏ hơn, <)
        under_match = re.search(r"(?:dưới|nhỏ hơn|<|dưói)\s*(\d+(?:\.\d+)?)\s*(tr|k|đ|vnd|đồng)?", clean_text)
        if under_match:
            value = float(under_match.group(1))
            unit = under_match.group(2)
            if unit == "tr" or not unit: # default to tr for numbers like "dưới 20"
                if value < 1000: value *= 1_000_000
            elif unit == "k":
                value *= 1000
            entities["price_max"] = int(value)

        # Over/more than (trên, lớn hơn, >)
        over_match = re.search(r"(?:trên|lớn hơn|>|từ)\s*(\d+(?:\.\d+)?)\s*(tr|k|đ|vnd|đồng)?", clean_text)
        if over_match:
            value = float(over_match.group(1))
            unit = over_match.group(2)
            if unit == "tr" or not unit:
                if value < 1000: value *= 1_000_000
            elif unit == "k":
                value *= 1000
            entities["price_min"] = int(value)

        # Bare budget with a currency unit but NO qualifier word ("mua đồ 500k",
        # "laptop 15tr") - a very common way to state a budget that the
        # under/over patterns above miss because nothing like "dưới"/"trên"
        # precedes the number. Treated as price_max (an approximate ceiling).
        # Only fires when no explicit bound was already found, and the currency
        # unit is REQUIRED: a number with no unit ("mua 2 cái", "iphone 15",
        # "sách lớp 5") is a quantity/model/grade, never a price. The "k" case
        # additionally requires value >= 10 so a screen resolution ("màn hình
        # 2k/4k") isn't mistaken for a 2.000đ/4.000đ budget - real "k" budgets
        # start much higher, while "tr" is a plausible budget at any size (1tr).
        if entities["price_min"] is None and entities["price_max"] is None:
            bare_match = re.search(r"\b(\d+(?:\.\d+)?)\s*(tr|k)\b", clean_text)
            if bare_match:
                value = float(bare_match.group(1))
                unit = bare_match.group(2)
                if unit == "tr":
                    if value < 1000: value *= 1_000_000
                    entities["price_max"] = int(value)
                elif unit == "k" and value >= 10:
                    entities["price_max"] = int(value * 1000)

        return entities

    def clean_query_keywords(self, query: str) -> str:
        text = re.sub(r"\s+", " ", query.lower()).strip()

        # Stopwords to remove. Currency/quantity units (tr, k, đ, đồng...)
        # are deliberately NOT here: they are also real Vietnamese words/
        # syllables ("đồng" in "đồng hồ", "đồng phục") and must only be
        # stripped when actually attached to a price number (handled below),
        # never as a freestanding word - stripping "đồng" unconditionally
        # turned "tìm đồng hồ" into a bare "hồ" search, matching completely
        # unrelated products like "hồ ly" / "hồ Thác Bà".
        stopwords = [
            "tìm kiếm", "tìm", "tim", "kiếm", "kiem", "mua", "tư vấn", "tu van", "gợi ý", "goi y", "so sánh", "so sanh",
            "dưới", "dưói", "trên", "nhỏ hơn", "lớn hơn", "khoảng", "tầm", "giá", "từ",
        ]

        for word in stopwords:
            text = re.sub(r"\b" + re.escape(word) + r"\b", "", text)

        # Marketing filler ("chính hãng", "giá rẻ", "hàng mới"...) doesn't help
        # the backend's free-text match and can push a real product out of a
        # narrow keyword search - strip it too (shared list with category
        # resolution in ontology.py, so both stay in sync).
        for word in ontology.stopwords:
            if word in _CURRENCY_UNIT_WORDS:
                continue
            text = re.sub(r"\b" + re.escape(word) + r"\b", "", text)

        # Remove a number ONLY when a currency/quantity unit is glued right
        # after it (e.g. "20 triệu", "500k", "500 đồng") - this is the only
        # way to tell a price number apart from any other meaningful number
        # in the query. The previous version made the unit optional, so it
        # erased EVERY bare number - "sách lớp 5" -> "sách lớp", "iphone 15"
        # -> "iphone", "áo size 6" -> "áo size" - silently losing the exact
        # detail that made the search specific.
        text = re.sub(r"\b\d+(?:\.\d+)?\s*(?:triệu|trieu|tr|ngàn|nghìn|k|đ|vnd|đồng|dong|vđ)\b", "", text)

        text = re.sub(r"\s+", " ", text).strip()
        return text

entity_extractor = EntityExtractor()
