import re
from typing import Dict, Optional
from app.models.shopping_context import ShoppingContext

REFERENCE_MARKERS = [
    "cái đó", "cái này", "cái ở", "sản phẩm đó", "sản phẩm này",
    " đó ", " đó?", " này ", " này?", " nó ", " nó?",
    "vừa rồi", "vừa nãy", "ở trên", "đầu tiên", "cuối cùng",
    "thứ nhất", "thứ hai", "thứ 2", "thứ ba", "thứ 3",
    "món này", "món đó", "món kia", "chiếc này", "chiếc đó",
    "bộ này", "bộ đó", "cái kia", "bên trái", "bên phải",
    "hình trên", "ảnh trên", "ảnh vừa gửi", "vừa xem", "cái vừa coi",
    "shop vừa gửi", "đang hiển thị", "bé này", "bé đó", "mã này",
    "mã đó", "mã sp này", "link này", "hình này", "ảnh này",
    "phiên bản này", "bản này", "mẫu kia", "kiểu này", "dòng này",
    "bên trên", "bên dưới", "cái kế tiếp", "món đầu", "món cuối", "kế cuối",
    "sản phẩm kia", "mẫu này", "mẫu đó", "hàng này", "hàng đó", "loại này", "loại đó"
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
    "đáng mua không", "đáng tiền không", "có đáng không", "chính hãng không",
    "hàng thật không", "auth không", "fake không", "hợp size nào", "hợp da nào",
    "hợp dáng nào", "bán chạy nhất", "review sao", "đánh giá thế nào",
    "nên mua loại nào", "loại nào tốt hơn", "giúp mình chọn", "tư vấn giúp",
    "review", "đánh giá", "có tốt không", "xài êm không", "dùng được không",
    "nên mua không", "nen mua khong", "tính năng nào", "đặc điểm", "ưu điểm",
    "nhược điểm", "chất lượng sao", "bền không", "mịn không", "xịn nhất",
    "cao cấp nhất", "rẻ hơn", "mắc hơn", "tốt hơn", "đáng tiền", "đáng mua",
    "best seller", "mới nhất", "moi nhat", "đời mới", "trend", "hot trend",
    "review tốt không", "được ưa chuộng", "đánh giá tốt", "có nên mua"
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

# A no-preference reply ("không biết", "tùy") means "don't ask me this again,
# I have no answer" - distinct from an unparseable reply. Moved here (from
# orchestrator.py, its original home) so parser.py can ALSO use it: a bare
# "nào cũng được" carries no real product intent, so its embedding is
# dominated by the generic indifference phrasing, not the topic - the SAME
# failure shape as the already-fixed bare-price-phrase case (see parser.py's
# skip_semantic_cache), and confirmed live to cause the same kind of
# cross-session hijack (an unrelated cached "health/beauty" concept overwrote
# a live skincare consultation's own topic).
_NO_PREFERENCE_MARKERS = [
    "không biết", "khong biet", "chưa biết", "chua biet",
    "tùy", "tuy", "không quan tâm", "khong quan tam",
    "bất kỳ", "bat ky", "không rành", "khong ranh",
    "không quan trọng", "khong quan trong", "chưa rõ", "chua ro",
]

# "[interrogative] + cũng được/đc/ok" is a productive Vietnamese construction
# for "whichever/whatever - no preference" ("bao nhiêu cũng được", "cái nào
# cũng được", "gì cũng được", "sao cũng được", "lúc nào cũng được", "ở đâu
# cũng được"...) - a STRUCTURAL pattern, not a fixed set of phrases, so this
# regex generalizes across every question-word variant instead of needing a
# new literal entry in _NO_PREFERENCE_MARKERS each time a new one shows up.
_INDIFFERENCE_RE = re.compile(r"cũng (được|đc|dc|ok|okay)\b")

def is_no_preference_reply(message: str) -> bool:
    text = (message or "").lower()
    return any(marker in text for marker in _NO_PREFERENCE_MARKERS) or bool(_INDIFFERENCE_RE.search(text))

# Same "[interrogative] + cũng được" construction as _INDIFFERENCE_RE, but
# capturing the interrogative too so the WHOLE clause can be stripped, not
# just "cũng được" - removing only the suffix left "gì" dangling in front of
# the real subject (e.g. "sách gì cũng được" -> "sách gì"), which still isn't
# a clean search term.
_INDIFFERENCE_PHRASE_RE = re.compile(
    r"\b(?:gì|nào|sao|ai|bao nhiêu|lúc nào|ở đâu)\s+cũng\s*(?:được|đc|dc|ok|okay)\b"
)

def strip_no_preference_phrasing(message: str) -> str:
    """Strips an indifference clause ("sách gì cũng được" -> "sách") from a
    query. Used by llm_client's deterministic fallback (provider unavailable
    or errored) - unlike the normal AI/deterministic parser paths, that
    fallback has no LLM to separate the real subject from this filler, so a
    query like "sách gì cũng được" was sent to the backend verbatim and
    matched zero products."""
    text = message or ""
    text = _INDIFFERENCE_PHRASE_RE.sub("", text)
    for marker in _NO_PREFERENCE_MARKERS:
        text = re.sub(re.escape(marker), "", text, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", text).strip()

# A "why does this matter" / "which technology is better" question (Sprint 4's
# Tech Explain) - "tại sao"/"vì sao" cover an explicit why-ask; the rest cover
# an implicit "explain this choice" ask ("nên chọn ... hay ...", "... hay ...
# cái nào tốt hơn", "khác nhau như thế nào", "loại nào tốt hơn") without the
# word "tại sao" itself (e.g. "nên chọn truyền động trực tiếp hay gián tiếp").
# v0/regex-only - shares this codebase's usual "Requirement Resolver v0"
# scope, not an AI classifier.
_TECH_EXPLAIN_RE = re.compile(
    r"tại sao|vì sao|tai sao|vi sao|"
    r"sao (lại )?(cần|nên)|"
    r"nên chọn .+ hay .+|nen chon .+ hay .+|"
    r".+ hay .+ (cái nào|loại nào|cai nao|loai nao) tốt hơn|"
    r"khác nhau (như thế nào|ra sao)|khac nhau (nhu the nao|ra sao)|"
    r"loại nào tốt hơn|loai nao tot hon|nên dùng loại nào|nen dung loai nao",
    re.IGNORECASE,
)

def is_tech_explain_query(message: str) -> bool:
    return bool(_TECH_EXPLAIN_RE.search((message or "").lower()))

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

# A PRODUCT_INFO turn that only asks about ONE narrow field of an
# already-resolved product (giá / size-màu / hình) rather than a full
# consult - "giá bao nhiêu", "còn size nào", "cho xem hình" don't need the
# whole detail card + Product Deep-Dive market analysis that every
# PRODUCT_INFO turn otherwise gets (see orchestrator.py's PRODUCT_INFO
# branch), that's needlessly expensive AND reads as over-answering a
# one-line question. Deliberately keyed off flags (not a single enum) so a
# compound ask ("giá và size thế nào") answers both fields in one reply
# instead of only the first match.
#
# A genuine opinion-ask ("có đáng mua không", "chất lượng sao") should still
# win and get the full consult - but that CANNOT reuse is_advisory_query:
# ADVISORY_MARKERS includes bare "nào"/"nhất", tuned for SEARCH's "which
# product among many" ranking questions, and "size nào"/"màu nào"/"giá...
# thế nào" are exactly the everyday narrow phrasings this feature exists to
# catch - gating on the SEARCH-tuned list swallowed almost every real-world
# narrow ask (confirmed by hand-testing before this list existed). This is
# its own, deliberately smaller set of markers that actually ask for an
# opinion/recommendation on THIS product, not "which value/variant".
_FULL_CONSULT_MARKERS = [
    "có nên mua", "co nen mua", "có đáng mua", "co dang mua",
    "đáng mua không", "dang mua khong", "đáng tiền không", "dang tien khong",
    "có tốt không", "co tot khong", "chất lượng sao", "chat luong sao",
    "review", "tư vấn", "tu van", "khuyên", "nên chọn", "nen chon",
    "xài êm không", "xai em khong", "dùng được không", "dung duoc khong",
    "có nên không", "co nen khong", "bền không", "ben khong",
]
_FULL_CONSULT_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(kw) for kw in _FULL_CONSULT_MARKERS) + r")\b"
)
_PRICE_FOCUS_MARKERS = [
    "giá bao nhiêu", "gia bao nhieu", "giá cả", "gia ca", "giá bán", "gia ban",
    "giá tiền", "gia tien", "bao nhiêu tiền", "bao nhieu tien", "nhiêu tiền", "nhieu tien",
    "mấy tiền", "may tien", "giá nhiêu", "gia nhieu",
]
# The "(?<!đánh )(?<!danh )" guard applies to the WHOLE alternation (not
# just the bare fallback below) - "đánh giá bao nhiêu sao" (how many stars
# rated) contains "giá bao nhiêu" as a literal substring and would otherwise
# false-positive on the phrase list too, not just on a bare "giá".
_PRICE_FOCUS_RE = re.compile(
    r"(?<!đánh )(?<!danh )\b(?:" + "|".join(re.escape(kw) for kw in _PRICE_FOCUS_MARKERS) + r")\b"
)
# Bare "giá"/"gia" as a fallback for short asks like "giá?" alone - same
# "đánh giá"/"danh gia" (rating/review) exclusion as above.
_BARE_PRICE_RE = re.compile(r"(?<!đánh )(?<!danh )\bgiá\b|(?<!đánh )(?<!danh )\bgia\b")

_VARIANT_FOCUS_MARKERS = [
    "còn size", "con size", "còn màu", "con mau", "size nào", "size gi", "size gì",
    "màu nào", "mau nao", "màu gì", "mau gi", "màu sắc", "mau sac", "kích cỡ", "kich co",
    "kích thước", "kich thuoc", "mẫu mã", "mau ma", "phối màu", "phoi mau",
    "tùy chọn màu", "tuy chon mau", "có size", "co size", "có màu", "co mau",
]
_VARIANT_FOCUS_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(kw) for kw in _VARIANT_FOCUS_MARKERS) + r")\b"
)
_BARE_VARIANT_RE = re.compile(r"\bsize\b|\bcỡ\b|\bmàu\b|\bmau\b")

# Excludes "hình như" ("seems like") - an unrelated filler phrase that
# happens to contain the bare word "hình".
_IMAGE_FOCUS_MARKERS = [
    "hình ảnh", "hinh anh", "xem hình", "xem hinh", "xem ảnh", "xem anh",
    "coi hình", "coi hinh", "coi ảnh", "coi anh", "cho xem hình", "cho xem ảnh",
    "ảnh thật", "anh that", "hình thật", "hinh that", "ảnh sản phẩm", "hình sản phẩm",
]
_IMAGE_FOCUS_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(kw) for kw in _IMAGE_FOCUS_MARKERS) + r")\b"
)
_BARE_IMAGE_RE = re.compile(r"\bảnh\b|\bhình\b(?!\s*như)")

def classify_product_focus(query: str) -> Dict[str, bool]:
    text = (query or "").lower()
    if _FULL_CONSULT_RE.search(text):
        return {"price": False, "variant": False, "image": False}
    return {
        "price": bool(_PRICE_FOCUS_RE.search(text) or _BARE_PRICE_RE.search(text)),
        "variant": bool(_VARIANT_FOCUS_RE.search(text) or _BARE_VARIANT_RE.search(text)),
        "image": bool(_IMAGE_FOCUS_RE.search(text) or _BARE_IMAGE_RE.search(text)),
    }

def is_narrow_product_query(focus: Dict[str, bool]) -> bool:
    return any(focus.values())

# A bare ordinal-position reference ("thứ 2", "thứ hai") to an item in the
# just-shown product list. parser.py deliberately leaves "thứ N" to the AI
# Parser rather than a deterministic shortcut (see parser.py's own comment -
# "thứ 2"/"thứ 4"/"thứ 7" are also how Vietnamese writes weekdays, so a
# blind regex risks misreading a genuine weekday mention as a position
# pick). The AI Parser is instructed to resolve this strictly against
# {product_options} (see parser_prompt.txt's reference-resolution rule),
# but an LLM can still occasionally return a real-looking slug for the
# WRONG item - confirmed live: "cái áo dài thứ 2 có size không" resolved to
# a product from a completely unrelated much-earlier turn instead of the
# actual 2nd item just shown. Used by orchestrator.py's PRODUCT_INFO branch
# as a safety-net cross-check: when this marker is present, the resolved
# slug must actually be IN conversation.memory["search_results"] before
# being trusted, rather than confidently displaying a wrong product.
_ORDINAL_POSITION_RE = re.compile(r"\bthứ\s*\d{1,2}\b|\bthu\s*\d{1,2}\b")

def is_ordinal_position_query(message: str) -> bool:
    return bool(_ORDINAL_POSITION_RE.search((message or "").lower()))

# "I don't like the shown product(s), show me something else" - e.g. "còn
# cái nào khác không", "không ưng", "cái khác đi". This is easy to confuse
# with ADVISORY_MARKERS (both often contain "nào"/"khác"), but the two mean
# OPPOSITE things: an advisory ask ("cái nào ngon nhất") wants the assistant
# to REASON about the SAME already-shown products, while this wants
# DIFFERENT products entirely - grounding it in the same cached list (see
# orchestrator.py's is_advisory_followup_on_cache) just re-shows the exact
# same rejected item(s) again. Confirmed live: "còn cái nào khác không"
# right after a single-result search re-displayed that SAME product twice
# in a row instead of broadening the search for alternatives. Checked
# separately from ADVISORY_MARKERS (not merged into it) since the two need
# to route to opposite behaviors in orchestrator.py, not just share a
# "this is about the shown products" signal.
_ALTERNATIVE_REQUEST_MARKERS = [
    # Bare "[noun] khác" ("cho xem mẫu khác", "đổi sản phẩm khác") - no
    # interrogative word, so kept as an explicit list. Unlike "nào khác"/"gì
    # khác" below, a bare "khác" alone is too ambiguous to safely generalize
    # without anchoring to one of these specific nouns ("khác với..." is a
    # normal comparison, not a rejection).
    "cái khác", "cai khac", "món khác", "mon khac", "sản phẩm khác", "san pham khac",
    "mẫu khác", "mau khac", "loại khác", "loai khac", "đồ khác", "do khac",
    # Explicit dissatisfaction phrasing - not a "[noun] khác" shape at all.
    "không ưng", "khong ung", "chưa ưng", "chua ung",
    "không thích cái này", "khong thich cai nay", "chưa thích cái này", "chua thich cai nay",
    "không hợp", "khong hop", "chưa phù hợp", "chua phu hop", "không phù hợp", "khong phu hop",
]
_ALTERNATIVE_REQUEST_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(kw) for kw in _ALTERNATIVE_REQUEST_MARKERS) + r")\b"
)
# Structural, NOT enumerated - same "productive Vietnamese construction"
# lesson as _INDIFFERENCE_RE above. An earlier literal-phrase-list version
# of this marker had "mẫu nào khác"/"còn mẫu nào khác" as its own entries
# but no "loại nào khác" entry, and silently missed the real live query
# "còn loại nào khác không bạn" - the enumeration approach can never keep up
# with every classifier noun ("cái"/"loại"/"mẫu"/"sản phẩm"/"món"/"đồ"...).
# "[interrogative] khác" ("nào khác"/"gì khác") covers ALL of them at once,
# since "nào"/"gì" already carry the "which/what" signal unambiguously
# regardless of what noun precedes them. "khác đi"/"khác không" catches the
# bare suffix form ("cho xem cái khác đi").
_ALTERNATIVE_REQUEST_STRUCTURAL_RE = re.compile(
    r"\b(?:nào|nao|gì|gi)\s+(?:khác|khac)\b|\b(?:khác|khac)\s+(?:đi|di|không|khong)\b"
)

def is_alternative_request_query(message: str) -> bool:
    text = (message or "").lower()
    return bool(_ALTERNATIVE_REQUEST_RE.search(text) or _ALTERNATIVE_REQUEST_STRUCTURAL_RE.search(text))

# A customer signaling they're DONE consulting and ready to order - often
# fired right after a PRODUCT_INFO turn, and often NOT phrased as a full
# sentence ("chốt đơn", "lấy cái này", "vậy chốt nha"). Deliberately
# CONFIRMATORY phrasings only (referring back to something already being
# discussed), not generic shopping verbs like bare "mua"/"đặt" - those
# already mean "start a new search" elsewhere (_SEARCH_RE / _BUSINESS_SIGNAL_RE),
# and reusing them here would hijack a fresh "mình muốn mua áo thun" search
# as if it were a checkout confirmation for whatever product happened to be
# in memory. orchestrator.py only acts on this when a last-viewed product
# actually exists in conversation.memory - otherwise there's nothing to
# confirm an order for, so it falls through to the normal pipeline unchanged.
CHECKOUT_INTENT_MARKERS = [
    "chốt đơn", "chot don", "chốt luôn", "chot luon", "chốt nha", "chot nha",
    "chốt giúp", "chot giup", "chốt liền", "chot lien", "vậy chốt", "vay chot",
    "đặt hàng cái này", "dat hang cai nay", "đặt hàng con này", "dat hang con nay",
    "đặt đơn", "dat don", "đặt liền", "dat lien",
    "mua cái này", "mua con này", "lấy cái này", "lay cai nay",
    "lấy con này", "lay con nay", "mình lấy cái này", "minh lay cai nay",
    "mình lấy con này", "minh lay con nay", "mình mua cái này", "minh mua cai nay",
    "cho mình đặt", "cho minh dat", "quyết định mua", "quyet dinh mua",
    "vậy lấy nha", "vay lay nha", "vậy mua nha", "vay mua nha",
    "ok mua", "oke mua", "ok lấy", "oke lấy", "oke lay",
]
_CHECKOUT_INTENT_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(kw) for kw in CHECKOUT_INTENT_MARKERS) + r")\b"
)

def is_checkout_intent_query(message: str) -> bool:
    return bool(_CHECKOUT_INTENT_RE.search((message or "").lower()))

# Sub-topic within the FAQ intent - the FAQ keyword check below only knows
# "this is a policy question", not WHICH policy, so every FAQ used to get the
# same hardcoded "đổi trả" answer regardless of what was actually asked.
# Checked in this order (đổi trả before giao hàng) because "đổi trả và giao
# lại hàng" contains both "đổi trả" and "giao" - đổi trả is the more specific ask.
FAQ_TOPIC_KEYWORDS = {
    "doi_tra": [
        "đổi trả", "doi tra", "trả hàng", "tra hang", "hoàn tiền", "hoan tien", "bảo hành", "bao hanh",
        "hàng giả", "hàng nhái", "không đúng mô tả", "khác hình", "sai mẫu", "thiếu phụ kiện", "đổi ý", "không ưng",
        "đổi mẫu", "đổi hàng", "trả lại", "hoàn trả", "hoan tra", "back tiền", "bảo hành bao lâu", "rách", "hư hỏng",
        "lỗi kỹ thuật", "đổi sang", "chật quá", "rộng quá", "sai màu", "giao sai", "không giống hình"
    ],
    "giao_hang": [
        "giao hàng", "giao hang", "ship", "vận chuyển", "van chuyen", "phí giao", "phi giao",
        "giao ngoài giờ", "giao tận nơi", "đổi địa chỉ giao", "hủy đơn giao", "theo dõi đơn", "tra cứu vận đơn", "shipper gọi",
        "giao nhanh", "phí ship", "tiền ship", "mien phi ship", "miễn ship", "chừng nào tới", "đang ở đâu", "lấy hàng",
        "gửi hàng", "chành xe", "giao trong ngày", "nowship", "grab", "nhận hàng", "check đơn", "tình trạng đơn",
        "đơn hàng sao rồi", "hành trình đơn"
    ],
    "thanh_toan": [
        "thanh toán", "thanh toan", "trả góp", "tra gop", "cod", "chuyển khoản", "chuyen khoan",
        "trả sau", "mua trước trả sau", "kredivo", "fundiin", "thanh toán quốc tế", "paypal", "trả bằng thẻ",
        "nhận hàng đưa tiền", "chuyển tiền", "ck", "banking", "tiền mặt", "quét mã", "qr code", "cà thẻ",
        "phí thanh toán", "cọc", "đặt cọc", "trả trước", "lãi suất"
    ],
    "bao_mat": [
        "bảo mật", "bao mat", "riêng tư", "rieng tu", "thông tin cá nhân", "thong tin ca nhan", "quyền riêng tư", "quyen rieng tu",
        "chính sách bảo mật", "chinh sach bao mat", "xóa tài khoản", "yêu cầu xóa dữ liệu", "rò rỉ thông tin", "lộ thông tin",
        "bán data", "bảo vệ dữ liệu", "an toàn không", "chính sách", "điều khoản", "cam kết bảo mật"
    ],
    "khuyen_mai": [
        "mã freeship", "ưu đãi thành viên", "tích điểm", "đổi điểm", "hạng thành viên", "quà tặng kèm", "xu thưởng",
        "ưu đãi", "uu dai", "tặng kèm", "quà tặng", "mua 1 tặng 1", "combo", "chiết khấu", "săn sale", "deal", "xu"
    ],
    "ton_kho": [
        "còn hàng", "con hang", "hết hàng", "het hang", "còn size", "con size", "còn màu", "con mau", "sold out",
        "khi nào có hàng lại", "restock"
    ],
    "tai_khoan": [
        "đăng nhập", "quên mật khẩu", "tạo tài khoản", "đổi mật khẩu", "xác thực otp", "liên kết số điện thoại"
    ],
    "hoa_don": [
        "xuất hóa đơn", "hóa đơn đỏ", "hóa đơn vat", "invoice", "xuất hóa đơn công ty"
    ]
}

TOXICITY_MARKERS = [
    "dở quá", "dở ẹc", "ngu quá", "ngu vậy", "tệ quá", "tệ thế", "vớ vẩn", "vo van",
    "lừa đảo", "lua dao", "bậy bạ", "bay ba", "điên à", "dien a", "ngáo", "ngao", "dở vậy", "do vay",
    "hàng đểu", "shop lừa", "seller dở", "chặt chém", "vô trách nhiệm", "report shop", "báo cáo shop",
    "bùng hàng", "bom hàng", "óc chó", "ngu như bò", "dcm", "vloz", "clgt", "đồ dỏm", "hàng fake",
    "hàng giả", "hàng nhái", "scam", "phế", "hãm", "vãi", "đkm", "đmm", "cc", "cl", "như lồn",
    "như cặc", "bot ngu", "bố láo", "trả lời ngu", "thằng điên", "con điên", "biến đi", "cút",
    "dẹp", "đừng làm phiền", "im đi"
]
SOCIAL_COMPLIMENT_MARKERS = [
    "cảm ơn", "cam on", "thank", "tuyệt vời", "tuyet voi", "tốt quá", "tot qua",
    "dễ thương", "de thuong", "ok nha", "được nha", "duc nha", "tạm biệt", "tam biet",
    "bye", "chúc bạn", "chúc bn", "quá xịn", "chuẩn không cần chỉnh", "đóng gói kỹ",
    "ship nhanh ghê", "5 sao", "shop uy tín", "sẽ ủng hộ tiếp", "quay lại ủng hộ",
    "auth ngon", "thanks", "tks", "tk", "cám ơn", "đẹp nha", "xịn nha", "rất thích",
    "good", "nice", "quá đã", "xuất sắc", "rep nhanh", "bot xịn", "đỉnh", "10 đ",
    "ưng ý", "chấm", "gút chóp", "đã nhận hàng", "hài lòng"
]
OUT_OF_SCOPE_MARKERS = [
    "kể chuyện cười", "ke chuyen cuoi", "kể chuyện", "ke chuyen", "thời tiết", "thoi tiet",
    "sửa ống nước", "sua ong nuoc", "sửa điện", "sua dien", "sửa nhà", "sua nha",
    "tuyển dụng", "tuyen dung", "tìm việc", "tim viec", "giao trà sữa", "giao tra sua",
    "sửa xe", "sua xe", "sửa máy", "sua may", "dịch giúp", "dịch sang tiếng anh",
    "làm bài tập", "giải toán", "viết code", "tư vấn sức khỏe", "khám bệnh",
    "tư vấn pháp luật", "luật sư", "làm thơ", "xem bói", "tử vi", "phong thủy",
    "số đề", "vay tiền", "chuyển tiền hộ", "đặt taxi", "gọi grab", "mua vé xem phim",
    "hát đi", "dịch tiếng", "chứng khoán", "bitcoin", "bóng đá", "kết quả xổ số",
    "xổ số", "đánh lô", "chính trị", "tôn giáo", "đặt xe", "gọi taxi", "mua vé số",
    "vé máy bay", "đặt đồ ăn", "mua thẻ cào", "nạp game",
    "giá vàng", "gia vang", "giá xăng", "gia xang", "tỷ giá", "ty gia",
    "giá đô", "gia do", "giá chứng khoán", "gia chung khoan",
    "lãi suất ngân hàng", "lai suat ngan hang",
    "gợi ý phim", "goi y phim", "gợi ý bài hát", "goi y bai hat",
    "gợi ý địa điểm", "goi y dia diem", "gợi ý tên cho con", "goi y ten cho con",
    "gợi ý quán ăn", "goi y quan an", "tìm quán ăn", "tim quan an",
    "tìm phòng trọ", "tim phong tro", "tìm việc làm", "tim viec lam",
    "tìm bạn gái", "tìm bạn trai", "tìm người yêu",
    "mua vé số", "mua bảo hiểm",
    "mua vàng", "mua ngoại tệ", "đặt vé máy bay", "đặt vé xem phim",
    "đặt bàn nhà hàng", "gọi taxi", "gọi grab", "chuyển tiền hộ", "vay tiền",
    "mua vui", "mua chuộc", "mua thời gian", "mua danh",
    "thuê người", "thue nguoi", "tìm giúp việc", "giup viec",
    "dọn nhà", "don nha", "sửa khóa", "sua khoa", "thông bồn cầu", "thong bon cau",
    "thuê thợ", "thue tho", "chuyển nhà", "chuyen nha", "gọi xe ôm", "xe om", "dat xe",
    "vape", "pod", "thuốc lá điện tử", "thuoc la dien tu", "shisha", "thuốc lá",
    "mua súng", "dao găm", "dao gam", "mã tấu", "ma túy", "cỏ mỹ", "co my",
    "gái gọi", "gai goi", "phò", "sugar baby", "thuốc kích dục", "mua acc",
    "bán nick", "cày thuê", "cay thue", "tăng like", "tang like", "hack xu",
    "hack nick", "mua follow", "tải game", "tai game", "crack", "vay tiền",
    "vay tien", "cầm đồ", "cam do", "bốc họ", "boc ho", "tín dụng đen", "mua cổ phiếu",
    "co phieu", "đầu tư", "dau tu", "chứng khoán", "chung khoan", "tìm xưởng",
    "nhập sỉ", "nhap si", "mua chó", "mua cho", "bán mèo", "ban meo", "mua gà",
    "mua ga", "bán chim", "ban chim", "thú cưng", "thu cung"
]

_TOXICITY_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(kw) for kw in TOXICITY_MARKERS) + r")\b"
)
_SOCIAL_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(kw) for kw in SOCIAL_COMPLIMENT_MARKERS) + r")\b"
)
_OUT_OF_SCOPE_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(kw) for kw in OUT_OF_SCOPE_MARKERS) + r")\b"
)
_SEARCH_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(kw) for kw in ["tìm", "tim", "kiếm", "kiem", "mua", "tư vấn", "tu van", "gợi ý", "goi y"]) + r")\b"
)

# A concrete shopping ask ("...tìm cho anh nồi cơm", "...mua giúp mình đôi giày")
# sharing a sentence with a social nicety ("cảm ơn nha", "chúc bạn") used to lose
# the ask entirely: the Social/toxicity-style checks below ran unconditionally
# on the WHOLE message with no notion that a real business request was also
# present, so "cảm ơn nha tìm cho anh nồi cơm" matched "cảm ơn" and returned
# SOCIAL before the shopping verb ever got a chance to matter. Deliberately
# bare verbs/nouns (not compound phrases) - broad recall is safe HERE because
# it only gates the Social/help-capabilities checks (politeness words that
# never describe a subject, so they can't legitimately co-occur with a real
# shopping ask), unlike Out-of-scope markers below (which describe the actual
# subject, e.g. "tìm việc làm" - gating THOSE on a bare verb would wrongly let
# "tìm" alone override a specific non-retail phrase; that's a marker-precision
# problem instead, not a gating one).
_BUSINESS_SIGNAL_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(kw) for kw in [
        "tìm", "tim", "kiếm", "kiem", "mua", "đặt", "dat", "xem",
        "tư vấn", "tu van", "gợi ý", "goi y", "so sánh", "so sanh",
        "review", "đánh giá", "danh gia", "còn hàng", "con hang",
        "còn size", "con size", "còn màu", "con mau",
        "chi tiết", "chi tiet", "thông tin", "thong tin", "cấu hình", "cau hinh",
    ]) + r")\b"
)

def has_business_signal(query: str) -> bool:
    return bool(_BUSINESS_SIGNAL_RE.search((query or "").lower()))

def classify_faq_topic(query: str) -> str:
    text = query.lower()
    for topic, keywords in FAQ_TOPIC_KEYWORDS.items():
        if any(kw in text for kw in keywords):
            return topic
    return "chung"

class IntentClassifier:
    def classify(self, query: str) -> Optional[tuple[str, Optional[str]]]:
        text = query.lower().strip()
        padded = f" {text} "

        # 1. Chitchat/Social/Out-of-scope/Greeting checks (no 6-word limit needed)
        
        # Greeting Check
        if (
            re.search(r"^(xin chào|chào bạn|chào|hi|hello|alo|hey|chao)\b", text)
            or re.search(r"\b(bạn|cậu|mày|bot|delippy|ban|cau|may)\s+l[àa]\s+(ai|gì|gi)\b", text)
            or re.search(r"^(ai\s+(đây|đấy|day)|đây\s+l[àa]\s+ai|day\s+la\s+ai|ai\s+vậy|ai\s+vay|ai\s+thế|ai\s+the)$", text)
        ):
            return "GREETING", "greeting"



            
        # Toxicity check - always first, unconditional: an insult must never
        # be swallowed just because the same message also names a product
        # ("dở quá, tìm hoài không ra" stays toxicity regardless).
        if _TOXICITY_RE.search(text):
            return "CHITCHAT", "toxicity"

        # A real shopping ask sharing the message with a social nicety
        # ("cảm ơn nha, tìm giúp mình nồi cơm") must win over the nicety -
        # see _BUSINESS_SIGNAL_RE. Only gates Social/help-capabilities
        # (politeness words with no subject of their own); Out-of-scope below
        # stays unconditional on purpose - it describes an actual (non-retail)
        # subject, and "tìm việc làm" containing the verb "tìm" must NOT be
        # allowed to override that specific marker.
        business_signal = has_business_signal(text)

        # Social check
        if not business_signal and _SOCIAL_RE.search(text):
            return "SOCIAL", "compliment"

        # Out-of-scope check
        if _OUT_OF_SCOPE_RE.search(text):
            return "CHITCHAT", "out_of_scope"

        # Help capabilities check
        if not business_signal and any(kw in text for kw in ["làm được gì", "giúp được gì", "tính năng", "chức năng", "capabilities", "lam duoc gi", "giup duoc gi"]):
            return "CHITCHAT", "help_capabilities"

        # 2. Limit check for Search/Compare/FAQ/Product Info
        if len(text.split()) > 6:
            return None

        # Reference queries
        if any(marker in padded for marker in REFERENCE_MARKERS):
            return None

        # Compare Check
        if any(kw in text for kw in ["so sánh", "so sanh", "khác gì", "khac gi", " vs ", " so với ", " so voi "]):
            return "COMPARE", None

        # FAQ Check
        if any(kw in text for kw in ["faq", "chính sách", "chinh sach", "đổi trả", "doi tra", "giao hàng", "giao hang", "ship", "vận chuyển", "van chuyen", "thanh toán", "thanh toan", "bảo mật", "bao mat", "riêng tư", "rieng tu"]):
            return "FAQ", None

        # Product Info Check
        if any(kw in text for kw in ["chi tiết", "chi tiet", "thông tin", "thong tin", "cấu hình", "cau hinh", "mô tả", "mo ta"]):
            return "PRODUCT_INFO", None
            
        # Search Check (Explicit search words with word boundary)
        if _SEARCH_RE.search(text):
            return "SEARCH", None
            
        return None

CSKH_KEYWORDS = [
    r"\btheo\s+(dõi|dỏi|doi)\b",
    r"\bđơn\s+hàng\b", r"\bdon\s+hang\b",
    r"\btra\s+cứu\s+đơn\b", r"\btra\s+cuu\s+don\b",
    r"\bkiểm\s+tra\s+đơn\b", r"\bkiem\s+tra\s+don\b",
    r"\bhành\s+trình\s+đơn\b", r"\bhành\s+trình\s+don\b",
    r"\blịch\s+trình\s+đơn\b", r"\blich\s+trinh\s+don\b",
    r"\btrạng\s+thái\s+đơn\b", r"\btrang\s+thai\s+don\b",
    r"\bhủy\s+đơn\b", r"\bhuy\s+don\b", r"\bhuỷ\s+đơn\b",
    r"\bđổi\s+trả\s+đơn\b", r"\bđổi\s+trả\s+hàng\b", r"\bdoi\s+tra\s+don\b", r"\bdoi\s+tra\s+hang\b",
    r"\bđiểm\s+dp\b", r"\bdiem\s+dp\b", r"\btích\s+điểm\b", r"\btich\s+diem\b", r"\bđổi\s+điểm\b", r"\bdoi\s+diem\b",
    r"\bgiới thiệu\s+(về\s+)?delippy\b", r"\bgioi thieu\s+(ve\s+)?delippy\b",
    r"\bdelippy\s+là\s+(gì|ai|app gì)\b", r"\bdelippy\s+la\s+(gi|ai|app gi)\b",
    r"\bđăng nhập\b", r"\bdang nhap\b", r"\bđăng ký\b", r"\bdang ky\b",
    r"\bkhóa tài khoản\b", r"\bxóa tài khoản\b",
    r"\blỗi\s+app\b", r"\bloi\s+app\b", r"\bapp\s+bị\s+lỗi\b", r"\bapp\s+bi\s+loi\b"
]


CSKH_RE = re.compile("|".join(CSKH_KEYWORDS), re.IGNORECASE)

VOUCHER_KEYWORDS = [
    r"\báp\s+mã\b", r"\bap\s+ma\b", r"\bnhập\s+mã\b", r"\bnhap\s+ma\b",
    r"\bsử dụng\s+(mã|voucher)\b", r"\bsudung\s+(mã|voucher)\b",
    r"\bnhận\s+(mã|voucher)\b", r"\bnhan\s+(mã|voucher)\b",
    r"\blấy\s+(mã|voucher)\b", r"\blay\s+(mã|voucher)\b",
    r"\bvoucher\s+giảm\b", r"\bvoucher\s+giam\b", r"\bmã\s+giảm\s*giá\b", r"\bma\s+giam\s*gia\b"
]
VOUCHER_RE = re.compile("|".join(VOUCHER_KEYWORDS), re.IGNORECASE)

def is_cskh_support_query(message: str) -> bool:
    text = (message or "").lower().strip()
    # Direct short keywords
    if text in ["voucher", "mã giảm giá", "ma giam gia", "điểm dp", "diem dp", "tích điểm", "tich diem", "đổi điểm", "doi diem", "delippy", "deligroup"]:
        return True
    # Check general CSKH keywords
    if CSKH_RE.search(text):
        return True
    # Check voucher specific keywords
    if VOUCHER_RE.search(text):
        return True
    return False

intent_classifier = IntentClassifier()

