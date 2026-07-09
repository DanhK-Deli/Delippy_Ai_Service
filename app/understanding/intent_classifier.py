import re
from typing import Optional
from app.models.shopping_context import ShoppingContext

REFERENCE_MARKERS = [
    "cái đó", "cái này", "cái ở", "sản phẩm đó", "sản phẩm này",
    " đó ", " đó?", " này ", " này?", " nó ", " nó?",
    "vừa rồi", "vừa nãy", "ở trên", "đầu tiên", "cuối cùng",
    "thứ nhất", "thứ hai", "thứ 2", "thứ ba", "thứ 3",
]

# An advisory SEARCH turn asks the assistant to reason/recommend over products
# (which one is best/cheapest/most suitable) rather than just list matches.
# Shared between response_formatter (routes these past the deterministic bullet
# list into the LLM formatter) and orchestrator (grounds the advice in the
# already-shown cached products instead of re-searching) so the two can't drift.
ADVISORY_MARKERS = [
    "tư vấn", "tu van", "khuyên", "nên chọn", "gợi ý", "giải thích",
    "rẻ nhất", "re nhat", "ngon nhất", "ngon nhat", "tốt nhất", "tot nhat",
    "mắc nhất", "mac nhat", "đắt nhất", "dat nhat", "nào", "nao", "nhất", "nhat",
]

# Word-boundary match (not naive substring) so short markers like "nào"/"nhất"
# only fire as standalone words, never as a fragment of a longer token.
_ADVISORY_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(kw) for kw in ADVISORY_MARKERS) + r")\b"
)

def is_advisory_query(query: str) -> bool:
    return bool(_ADVISORY_RE.search((query or "").lower()))

def needs_consultation(query: str, context: ShoppingContext) -> bool:
    """True for a SEARCH turn that should get the LLM's narrative/consultative
    reply instead of the deterministic bullet list - either an ADVISORY_MARKERS
    hit (existing signal), OR context.purpose is set. purpose is filled by
    the AI parser whenever it translates a NEED into a concrete product noun
    ("quà cho mẹ tầm 500k" -> query_q="nước hoa", purpose="quà tặng" - see
    parser_prompt.txt rule 1) - a query like that has NO advisory marker
    word at all, yet is exactly the case a chatbot exists to handle well: the
    user doesn't know what to search for, only what they need. Before this,
    such a query got the same dry "đây là N sản phẩm" list as a crisp
    keyword search, which defeats the point of asking a chatbot instead of
    just using the search bar.

    Deliberately NOT used to broaden orchestrator's two narrower
    is_advisory_query call sites (advisory-grounding-in-cache,
    product-suppression-when-too-vague) - those want the marker's specific
    "query_q stripped to near-nothing" semantics, not "purpose is set" (a
    purpose query gets a REAL query_q from the parser, so a fresh search is
    exactly what's wanted there, not reusing a stale cached list)."""
    return is_advisory_query(query) or bool(context.purpose)

# A CHITCHAT turn that's specifically probing for the system prompt/internal
# config/instructions, as opposed to genuinely off-topic chat (jokes, weather,
# small talk). Both classify as CHITCHAT upstream (parser_prompt.txt has no
# separate category for this), but they need very different replies -
# response_formatter picks ontology.prompt_probe_responses only when this
# fires, otherwise ontology.chitchat_responses (see response_formatter.py).
PROMPT_PROBE_MARKERS = [
    "system prompt", "prompt của bạn", "prompt gốc", "câu lệnh gốc",
    "hướng dẫn hệ thống", "hướng dẫn nội bộ", "cấu hình hệ thống",
    "cấu hình của bạn", "instructions", "system message",
    "được train như nào", "được lập trình như nào", "training data",
    "bỏ qua hướng dẫn", "bỏ qua các hướng dẫn", "ignore previous",
    "ignore all previous", "jailbreak", "mã nguồn", "source code",
    "cách bạn vận hành", "cách bạn hoạt động", "tiết lộ prompt",
]

_PROMPT_PROBE_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(kw) for kw in PROMPT_PROBE_MARKERS) + r")\b"
)

def is_prompt_probe_query(query: str) -> bool:
    return bool(_PROMPT_PROBE_RE.search((query or "").lower()))

def is_too_vague_for_results(context: ShoppingContext) -> bool:
    """True when a SEARCH turn gave no brand/price/purpose AND query_q
    reduces to at most one meaningful word (single-char, non-digit tokens
    dropped - same filter ranker.py/search_engine.py already apply). A
    category can resolve to exactly one place ("áo" -> thời trang & phụ
    kiện) and still be too vague to search ON: "áo" alone, or "áo t" where
    "t" is noise, names nothing beyond the category itself. Shared between
    response_formatter (skips the product list and asks instead) and
    orchestrator (must skip putting products in the API response's `data`
    too, or the frontend renders product cards under a text that asked a
    clarifying question instead of presenting them) so the two can't drift."""
    is_broad = not context.brand and context.price_min is None and context.price_max is None and not context.purpose
    kept_words = [w for w in (context.query_q or "").lower().split() if len(w) > 1 or w.isdigit()]
    return is_broad and len(kept_words) <= 1

# Sub-topic within the FAQ intent - the FAQ keyword check below only knows
# "this is a policy question", not WHICH policy, so every FAQ used to get the
# same hardcoded "đổi trả" answer regardless of what was actually asked.
# Checked in this order (đổi trả before giao hàng) because "đổi trả và giao
# lại hàng" contains both "đổi trả" and "giao" - đổi trả is the more specific ask.
FAQ_TOPIC_KEYWORDS = {
    "doi_tra": ["đổi trả", "doi tra", "trả hàng", "tra hang", "hoàn tiền", "hoan tien", "bảo hành", "bao hanh"],
    "giao_hang": ["giao hàng", "giao hang", "ship", "vận chuyển", "van chuyen", "phí giao", "phi giao"],
    "thanh_toan": ["thanh toán", "thanh toan", "trả góp", "tra gop", "cod", "chuyển khoản", "chuyen khoan"],
    "bao_mat": ["bảo mật", "bao mat", "riêng tư", "rieng tu", "thông tin cá nhân", "thong tin ca nhan", "quyền riêng tư", "quyen rieng tu", "chính sách bảo mật", "chinh sach bao mat"],
}

def classify_faq_topic(query: str) -> str:
    text = query.lower()
    for topic, keywords in FAQ_TOPIC_KEYWORDS.items():
        if any(kw in text for kw in keywords):
            return topic
    return "chung"

class IntentClassifier:
    def classify(self, query: str) -> Optional[str]:
        text = query.lower().strip()
        padded = f" {text} "

        # If query is long/complex, skip deterministic rules and fallback to LLM parser
        if len(text.split()) > 6:
            return None

        # Demonstrative/reference queries ("cái đó", "2 loại đầu tiên", "thứ
        # hai") need conversation memory to resolve what they point to -
        # this must run BEFORE every other rule below (not just before
        # PRODUCT_INFO/SEARCH), because a reference-based COMPARE ("so sánh
        # 2 loại đầu tiên") also contains the "so sánh" keyword and used to
        # get locked into COMPARE right here with no way to ever fill
        # compare_targets: the deterministic path never consults history, so
        # it permanently returned "chưa có thông tin sản phẩm nào để so
        # sánh" instead of giving the AI parser (which does get history) a
        # chance to resolve the reference into real product names.
        if any(marker in padded for marker in REFERENCE_MARKERS):
            return None

        # Greeting Check
        if re.search(r"^(xin chào|chào bạn|chào|hi|hello|alo|hey|chao)\b", text):
            return "GREETING"

        # Compare Check
        if any(kw in text for kw in ["so sánh", "so sanh", "khác gì", "khac gi", " vs ", " so với ", " so voi "]):
            return "COMPARE"

        # FAQ Check
        if any(kw in text for kw in ["faq", "chính sách", "chinh sach", "đổi trả", "doi tra", "giao hàng", "giao hang", "ship", "vận chuyển", "van chuyen", "thanh toán", "thanh toan", "bảo mật", "bao mat", "riêng tư", "rieng tu"]):
            return "FAQ"

        # Product Info Check
        if any(kw in text for kw in ["chi tiết", "chi tiet", "thông tin", "thong tin", "cấu hình", "cau hinh", "mô tả", "mo ta"]):
            # Only classify as PRODUCT_INFO if it looks like they are asking about a single product
            return "PRODUCT_INFO"
            
        # Search Check (Explicit search words)
        if any(kw in text for kw in ["tìm", "tim", "kiếm", "kiem", "mua", "tư vấn", "tu van", "gợi ý", "goi y"]):
            return "SEARCH"
            
        return None  # Let parser resolve if ambiguous

intent_classifier = IntentClassifier()
