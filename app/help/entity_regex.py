import re
from typing import Dict, Optional

from app.knowledge.ontology import _strip_diacritics

# ── Regex entity extraction ───────────────────────────────────────────────────
# Ported from v1's app/help/rule_engine.py verbatim (same patterns, same
# rationale) - these extract entity VALUES only, they never decide a Business
# Object/case by themselves. Kept as a small shared module because both
# conversation_state resume (deterministic slot-filling) and step1_understand
# (merging into the LLM's own entities output) need the exact same
# extraction, and fastpath.py needs the yes/no parser for nothing else but
# this stays the single source of truth for "what does an order code/phone/
# email look like" across the whole /help pipeline.
_ORDER_CODE_RE = re.compile(r"\bDEL[0-9A-Z]{6,}\b", re.IGNORECASE)
_ORDER_CODE_FALLBACK_RE = re.compile(r"\b(?=[A-Z0-9]{8,20}\b)(?=[A-Z0-9]*\d)[A-Z0-9]{8,20}\b", re.IGNORECASE)
_PHONE_RE = re.compile(r"\b(?:\+84|0)(?:3|5|7|8|9)\d{8}\b")
_EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")


def extract_regex_entities(message: str) -> Dict[str, str]:
    entities: Dict[str, str] = {}
    order_match = _ORDER_CODE_RE.search(message) or _ORDER_CODE_FALLBACK_RE.search(message)
    if order_match:
        entities["ma_don_hang"] = order_match.group(0).upper()
    phone_match = _PHONE_RE.search(message)
    if phone_match:
        entities["so_dien_thoai"] = phone_match.group(0)
        entities["so_dien_thoai_hoac_email"] = phone_match.group(0)
    email_match = _EMAIL_RE.search(message)
    if email_match:
        entities["email"] = email_match.group(0)
        entities["so_dien_thoai_hoac_email"] = email_match.group(0)
    return entities


# A free-text entity slot (ly_do_*, dia_chi_*, san_pham_can_doi_tra...) has no
# format to validate against, so nothing mechanical rejects a message that
# ISN'T actually answering the pending question - "any non-empty reply
# counts" swallowed a genuinely new, unrelated question whole (confirmed
# live: "Đơn này X đang ở đâu?" got silently accepted as the answer to
# "which product do you want to return", instead of falling through to a
# fresh Step 1 call that would have recognized it as a shipping-tracking
# question). A question mark or a WH-question particle is a strong signal
# the message is asking something, not answering - treat that as
# unresolved so the caller (orchestrator) drops the pending state and lets
# Step 1 re-classify the message properly instead of misfiling it.
_QUESTION_MARKERS = (
    "?", "o dau", "khi nao", "bao lau", "the nao", "nhu the nao",
    "tai sao", "vi sao", "sao vay", "lam sao", "the a", "phai khong",
)


def _looks_like_a_question(text: str) -> bool:
    if "?" in text:
        return True
    folded = f" {_strip_diacritics(text.lower())} "
    return any(f" {marker} " in folded or folded.startswith(f" {marker} ") for marker in _QUESTION_MARKERS[1:])


def extract_entity_value(entity_name: Optional[str], message: str) -> Optional[str]:
    """Used when resuming a COLLECTING_ENTITY state - extraction scoped to
    exactly the one entity the business object is waiting on."""
    if not entity_name:
        return message.strip() or None
    if entity_name == "ma_don_hang":
        m = _ORDER_CODE_RE.search(message) or _ORDER_CODE_FALLBACK_RE.search(message)
        if m:
            return m.group(0).upper()
        # Our known order-code shapes aren't exhaustive (real codes may use a
        # different prefix/length/separator than DEL.../8-20 alnum) - treating
        # a non-matching reply as "didn't answer" used to wipe the whole
        # pending cancel/return flow (case + business_object_ids) and restart
        # Step 1 from scratch on just this one message, losing the customer's
        # original intent entirely. A single-token reply with a digit in it
        # that isn't a question is still the customer answering "what's the
        # order code" - accept it best-effort and let Step 2's real lookup
        # validate/404 it (that path already degrades gracefully via
        # ErrorGroup.NOT_FOUND without escalating or dropping context).
        text = message.strip()
        if (
            text and not _looks_like_a_question(text) and " " not in text
            and 4 <= len(text) <= 30 and any(c.isdigit() for c in text)
        ):
            return text.upper()
        return None
    if entity_name in ("so_dien_thoai", "so_dien_thoai_hoac_email"):
        m = _PHONE_RE.search(message) or _EMAIL_RE.search(message)
        return m.group(0) if m else None
    if entity_name == "email":
        m = _EMAIL_RE.search(message)
        return m.group(0) if m else None
    # Free-text entity - accept anything EXCEPT something that reads like the
    # customer asking a new question instead of answering this one.
    text = message.strip()
    if not text or _looks_like_a_question(text):
        return None
    return text


# Whole-TOKEN membership (not raw substring) - deliberately excludes "huy"
# ("huỷ"/cancel) from both sets: it's the action noun itself, not a yes/no
# signal (a raw substring check on it wrongly read "vâng, huỷ giúp mình luôn"
# as a refusal - confirmed live in v1). Short, diacritic-collision-prone
# syllables ("dùng"/"đừng"/"đúng" all fold to "dung") are deliberately left
# out of both sets too - an unrecognized reply returns None (ambiguous)
# rather than guessing wrong.
_YES_TOKENS = {"co", "duoc", "vang", "ok", "yes", "u"}
_NO_PHRASES_FOLDED = ("thoi khoi", "khong can", "khong muon", "khong dong y")
_NO_TOKENS = {"khong"}


def parse_yes_no(message: str) -> Optional[bool]:
    folded = _strip_diacritics(message.lower()).strip()
    tokens = {w for w in re.split(r"[^\w]+", folded, flags=re.UNICODE) if w}
    if any(p in folded for p in _NO_PHRASES_FOLDED):
        return False
    if _NO_TOKENS & tokens:
        return False
    if _YES_TOKENS & tokens:
        return True
    return None
