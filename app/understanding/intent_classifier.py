import re
from typing import Optional
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
    "mua vé số", "mua bảo hiểm", "mua đất", "mua dat", "mua nhà", "mua chung cư",
    "mua vàng", "mua ngoại tệ", "đặt vé máy bay", "đặt vé xem phim",
    "đặt bàn nhà hàng", "gọi taxi", "gọi grab", "chuyển tiền hộ", "vay tiền",
    "mua vui", "mua chuộc", "mua thời gian", "mua danh",
    "thuê nhà", "thue nha", "phong tro", "chung cu", "thuê mặt bằng", "mat bang",
    "nhà đất", "nha dat", "thuê người", "thue nguoi", "tìm giúp việc", "giup viec",
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
        if re.search(r"^(xin chào|chào bạn|chào|hi|hello|alo|hey|chao)\b", text):
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

intent_classifier = IntentClassifier()
