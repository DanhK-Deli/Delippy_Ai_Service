import re
from typing import Optional, Tuple

from app.knowledge.ontology import _strip_diacritics

# ── Fast-path whitelist (plan §E) ─────────────────────────────────────────────
# A SMALL, CLOSED set of trivial GENERAL-case replies that skip Step 1
# entirely - 0 LLM calls, same cheapest-path guarantee v1's rule engine gave
# the common case. This is NOT a return to "rule engine decides everything":
# the whitelist only ever fires when the ENTIRE message (after stripping
# filler words) is nothing but a greeting/thanks/goodbye - any real business
# content in the same message falls through to the full Step 1 pipeline, so
# grounding/confidence/auth gates always apply to anything that could
# actually be wrong. Matching-and-not-firing is always the safe failure mode
# here, never the reverse.
_FILLER_TOKENS = {"ban", "oi", "nhe", "a", "shop", "delippy", "admin", "ad", "nha", "nhi", "xin", "vay"}
_GREETING_TOKENS = {"chao", "hello", "hi", "alo", "helo"}
_THANKS_TOKENS = {"cam", "on", "thanks", "thank", "you", "tks", "thx"}
_GOODBYE_TOKENS = {"tam", "biet", "bye", "byebye", "hen", "gap", "lai"}

# (business_object_id, response_template_id) - the two canned replies already
# vetted in response_template.json; see business_objects.json's
# BO_GENERAL_GREETING/THANKS/GOODBYE entries (THANKS/GOODBYE have no KO of
# their own in v1's KB, they reuse the generic close template).
_GREETING_RESULT = ("BO_GENERAL_GREETING", "RT_HELP_GREETING")
_THANKS_RESULT = ("BO_GENERAL_THANKS", "RT_GREETING_CLOSE")
_GOODBYE_RESULT = ("BO_GENERAL_GOODBYE", "RT_GREETING_CLOSE")


def _tokenize(message: str) -> list:
    folded = _strip_diacritics(message.lower())
    folded = re.sub(r"[^\w\s]", " ", folded)
    return [w for w in folded.split() if w]


def match_fast_path(message: str) -> Optional[Tuple[str, str]]:
    """Returns (business_object_id, response_template_id) if the WHOLE
    message is a trivial greeting/thanks/goodbye, else None (meaning: fall
    through to the full Step 1 -> ... pipeline)."""
    tokens = _tokenize(message)
    filtered = [w for w in tokens if w not in _FILLER_TOKENS]
    if not filtered:
        return None
    if all(w in _GREETING_TOKENS for w in filtered):
        return _GREETING_RESULT
    if all(w in _THANKS_TOKENS for w in filtered):
        return _THANKS_RESULT
    if all(w in _GOODBYE_TOKENS for w in filtered):
        return _GOODBYE_RESULT
    return None
