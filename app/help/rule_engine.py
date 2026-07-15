import math
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from app.help import state as help_state
from app.knowledge.help.loader import help_knowledge
from app.knowledge.ontology import _strip_diacritics

# ── Regex entity extraction ───────────────────────────────────────────────────
# The exact backend order-code format isn't confirmed in the Business Document
# (its own example is the illustrative "DELXXXXXXXX" -
# docs/chatbot-cskh-knowledge-base-design.md#0.2). Primary pattern matches
# that prefix; a looser fallback still catches a bare alphanumeric code if the
# real prefix differs, so extraction degrades gracefully instead of silently
# missing a pasted order code.
_ORDER_CODE_RE = re.compile(r"\bDEL[0-9A-Z]{6,}\b", re.IGNORECASE)
_ORDER_CODE_FALLBACK_RE = re.compile(r"\b(?=[A-Z0-9]{8,20}\b)(?=[A-Z0-9]*\d)[A-Z0-9]{8,20}\b", re.IGNORECASE)
_PHONE_RE = re.compile(r"\b(?:\+84|0)(?:3|5|7|8|9)\d{8}\b")
_EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")


def extract_regex_entities(message: str) -> Dict[str, str]:
    """Regex entities only EXTRACT values - they never pick the intent by
    themselves (see classify()'s step 1 / the approved plan §1)."""
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


def _extract_entity_value(entity_name: Optional[str], message: str) -> Optional[str]:
    """Used only when resuming an AWAITING_ENTITY state (see _try_resume) -
    extraction scoped to exactly the one entity the flow is waiting on."""
    if not entity_name:
        return message.strip() or None
    if entity_name == "ma_don_hang":
        m = _ORDER_CODE_RE.search(message) or _ORDER_CODE_FALLBACK_RE.search(message)
        return m.group(0).upper() if m else None
    if entity_name in ("so_dien_thoai", "so_dien_thoai_hoac_email"):
        m = _PHONE_RE.search(message) or _EMAIL_RE.search(message)
        return m.group(0) if m else None
    if entity_name == "email":
        m = _EMAIL_RE.search(message)
        return m.group(0) if m else None
    # Free-text entity (ly_do_*, dia_chi_*, mo_ta_loi...) - any non-empty
    # reply counts; these fields are inherently free-form in the KB.
    return message.strip() or None


# Whole-TOKEN membership (not raw substring) - deliberately excludes "huy"
# ("huỷ"/cancel) from both sets: it's the action noun itself, not a yes/no
# signal, and a raw substring check on it wrongly read "vâng, huỷ giúp mình
# luôn" (yes, please cancel) as a refusal (confirmed live while testing this
# module). Short, diacritic-collision-prone syllables ("dùng"/"đừng"/"đúng"
# all fold to "dung") are deliberately left out of both sets too - an
# unrecognized reply returns None (ambiguous) rather than guessing wrong,
# which is the correct failure mode here (falls through to full
# classification / eventually the LLM fallback, never silently misfires).
_YES_TOKENS = {"co", "duoc", "vang", "ok", "yes", "u"}
_NO_PHRASES_FOLDED = ("thoi khoi", "khong can", "khong muon", "khong dong y")
_NO_TOKENS = {"khong"}


def _parse_yes_no(message: str) -> Optional[bool]:
    folded = _strip_diacritics(message.lower()).strip()
    tokens = {w for w in re.split(r"[^\w]+", folded, flags=re.UNICODE) if w}
    if any(p in folded for p in _NO_PHRASES_FOLDED):
        return False
    if _NO_TOKENS & tokens:
        return False
    if _YES_TOKENS & tokens:
        return True
    return None


# ── Tokenization (diacritic-folded, per mục 0.3's "gõ tắt/không dấu" note) ────
# Same rationale as Ontology._CATEGORY_NOISE_WORDS (app/knowledge/ontology.py):
# IDF alone isn't enough in a small corpus (63 Knowledge Objects, short
# keyword/synonym lists) - a grammatical particle that happens to appear in
# only 1-2 KOs' phrase text looks deceptively "rare" by document frequency
# even though it carries zero domain signal (confirmed live: "chưa" alone
# tied an unrelated payment KO against a real shipping match on "Mã đơn
# DEL1234567 giao chưa?" purely because both KOs' phrase text happened to
# contain "chưa"). Folded forms (no diacritics) since _tokenize folds too.
_HELP_NOISE_WORDS = {
    "chua", "roi", "da", "khong", "ma", "la", "thi", "duoc", "cho", "cua", "va", "hay",
    "nay", "do", "vay", "nhe", "a", "nhi", "sao", "vi", "nen", "neu", "de", "khi", "luc",
    "lai", "cung", "rat", "qua", "con", "nua", "gi", "van", "dang", "se", "di", "ve", "ra",
    "vao", "len", "xuong", "toi", "ban", "minh", "voi", "tu", "den", "sau", "truoc",
}


def _tokenize(text: str) -> Set[str]:
    folded = _strip_diacritics(text.lower())
    return {
        w for w in re.split(r"[^\w]+", folded, flags=re.UNICODE)
        if len(w) > 1 and w not in _HELP_NOISE_WORDS
    }


def _phrases_for_ko(ko: Dict[str, Any]) -> List[str]:
    phrases: List[str] = list(ko.get("keywords") or [])
    for syn in (ko.get("synonyms") or []):
        if syn.get("canonical"):
            phrases.append(syn["canonical"])
        phrases.extend(syn.get("variants") or [])
    return [p for p in phrases if p]


# ── Constants - calibrated against the reviewer's own examples (see verification) ──
# A candidate must clear this weighted score to be considered a real match at
# all (belt-and-suspenders on top of the tie check below - a razor-thin,
# low-confidence winner still shouldn't auto-resolve in a domain where the
# wrong guess can trigger a real action, e.g. order cancellation).
MIN_CONFIDENCE_SCORE = 1.0
# Ties are EXACT score equality, same as Ontology._score_subcategories() -
# not a fuzzy percentage margin. A percentage margin was tried and rejected:
# when the best score itself is low (a message built entirely from common
# words), a wide percentage window pulls in many barely-related KOs as
# "tied", producing a shortlist too broad to be useful to the LLM fallback.
# Exact equality only fires when two-plus Knowledge Objects are GENUINELY
# equally supported by the message text.

# A KO's own domain_attr -> the intent to fall back to when multiple KOs in
# that SAME domain tie with no dominant winner (plan §1, step 3 second
# bullet) - "check status" is always a safe, non-committal default. Only
# domains where such a safe default genuinely exists are listed; a tie in an
# unlisted domain is ambiguous (goes to the LLM fallback).
_DEFAULT_INTENT_BY_DOMAIN = {
    "order": "kiem_tra_trang_thai_don",              # ORDER_STATUS_CHECK
    "payment": "kiem_tra_trang_thai_thanh_toan",       # PAYMENT_STATUS_CHECK
    "shipping": "tra_cuu_van_don",                     # SHIPPING_TRACKING_LOOKUP
}


@dataclass
class RuleEngineResult:
    """Always returned by classify() - resolved=False means "call
    llm_fallback with this shortlist", never a bare None. Keeps the
    orchestrator's branch trivial (see approved plan)."""

    resolved: bool
    ko_id: Optional[str] = None
    domain_attr: Optional[str] = None
    intent: Optional[str] = None
    entities: Dict[str, Any] = field(default_factory=dict)
    confidence: float = 1.0
    shortlist: List[Dict[str, Any]] = field(default_factory=list)
    resumed_awaiting: bool = False


def _all_kos() -> List[Tuple[str, Dict[str, Any]]]:
    """(domain_attr, knowledge_object) for every Knowledge Object across all
    13 business-domain files."""
    out: List[Tuple[str, Dict[str, Any]]] = []
    for attr in help_knowledge.domain_attrs():
        data = getattr(help_knowledge, attr, None) or {}
        for ko in data.get("knowledge_objects", []):
            out.append((attr, ko))
    return out


def _find_ko_by_id(ko_id: Optional[str]) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    if not ko_id:
        return None, None
    for attr, ko in _all_kos():
        if ko.get("id") == ko_id:
            return attr, ko
    return None, None


def _build_doc_freq(kos: List[Tuple[str, Dict[str, Any]]]) -> Tuple[Dict[str, int], int]:
    df: Dict[str, int] = {}
    for _, ko in kos:
        words: Set[str] = set()
        for phrase in _phrases_for_ko(ko):
            words |= _tokenize(phrase)
        for w in words:
            df[w] = df.get(w, 0) + 1
    return df, len(kos)


def _literal_phrase_matches(message_folded: str, kos: List[Tuple[str, Dict[str, Any]]]) -> List[Tuple[str, Dict[str, Any]]]:
    """Step 2: exact 2+-word phrase matches, longest wins - same precedence
    as Ontology.find_category()'s own step 2. Returns EVERY Knowledge Object
    tied at that longest length (a single generic 2-word phrase like "thanh
    toán" can legitimately appear in more than one sibling KO's own
    keywords/synonyms within the same domain - confirmed live - so this must
    detect that tie instead of picking whichever happens to iterate first)."""
    best_len = 0
    tied: List[Tuple[str, Dict[str, Any]]] = []
    seen_ids: Set[str] = set()
    for attr, ko in kos:
        for phrase in _phrases_for_ko(ko):
            folded_phrase = _strip_diacritics(phrase.lower())
            word_count = len(folded_phrase.split())
            if word_count < 2 or folded_phrase not in message_folded:
                continue
            if len(folded_phrase) > best_len:
                best_len = len(folded_phrase)
                tied = []
                seen_ids = set()
            if len(folded_phrase) == best_len and ko["id"] not in seen_ids:
                seen_ids.add(ko["id"])
                tied.append((attr, ko))
    return tied


def _score_kos(
    message_words: Set[str], kos: List[Tuple[str, Dict[str, Any]]], df: Dict[str, int], n: int
) -> List[Tuple[Tuple[float, int], str, Dict[str, Any]]]:
    """Step 3: IDF-weighted word-overlap score per Knowledge Object - same
    log(N/df(word)) weighting as Ontology._score_subcategories(), ported from
    subcategories to Knowledge Objects."""
    scored = []
    for attr, ko in kos:
        ko_words: Set[str] = set()
        for phrase in _phrases_for_ko(ko):
            ko_words |= _tokenize(phrase)
        overlap = message_words & ko_words
        if not overlap:
            continue
        weighted = sum(math.log(n / df.get(w, 1)) for w in overlap)
        scored.append(((weighted, len(overlap)), attr, ko))
    return scored


def _shortlist(tied: List[Tuple[str, Dict[str, Any]]]) -> List[Dict[str, Any]]:
    return [
        {
            "id": ko["id"],
            "domain_attr": attr,
            "intent": ko["intent"],
            "description": ko.get("description"),
            "sample_questions": ko.get("sample_questions", []),
        }
        for attr, ko in tied
    ]


def _resolve_tied(tied: List[Tuple[str, Dict[str, Any]]], regex_entities: Dict[str, Any]) -> RuleEngineResult:
    """Shared resolution rule for a tied candidate set - used identically
    after step 2 (phrase match) and step 3 (score match) ties, since both
    kinds of tie mean the same thing: 'more than one Knowledge Object is
    equally supported by the message text' (plan §1's ambiguity definition)."""
    if len(tied) == 1:
        attr, ko = tied[0]
        return RuleEngineResult(
            resolved=True, ko_id=ko["id"], domain_attr=attr, intent=ko["intent"], entities=regex_entities, confidence=1.0
        )
    domains_involved = {attr for attr, _ in tied}
    if len(domains_involved) == 1:
        only_domain = next(iter(domains_involved))
        default_intent = _DEFAULT_INTENT_BY_DOMAIN.get(only_domain)
        if default_intent:
            ko = help_knowledge.get_knowledge_object(only_domain, default_intent)
            if ko:
                return RuleEngineResult(
                    resolved=True, ko_id=ko["id"], domain_attr=only_domain, intent=default_intent,
                    entities=regex_entities, confidence=0.8,
                )
    # Ambiguous: tied across different domains, or tied in a domain with no
    # registered default - call the LLM fallback with exactly this shortlist.
    return RuleEngineResult(resolved=False, entities=regex_entities, shortlist=_shortlist(tied))


def _resolve_by_score(message: str, regex_entities: Dict[str, str]) -> RuleEngineResult:
    kos = _all_kos()
    message_folded = _strip_diacritics(message.lower())

    phrase_ties = _literal_phrase_matches(message_folded, kos)
    if phrase_ties:
        return _resolve_tied(phrase_ties, regex_entities)

    message_words = _tokenize(message)
    df, n = _build_doc_freq(kos)
    scored = _score_kos(message_words, kos, df, n)

    if not scored:
        if regex_entities:
            # Bare code / contact info with no other verb - the code decides
            # the DOMAIN FAMILY is order-related, the default-intent map
            # decides the actual intent (plan §1, step 1).
            default_intent = _DEFAULT_INTENT_BY_DOMAIN["order"]
            ko = help_knowledge.get_knowledge_object("order", default_intent)
            if ko:
                return RuleEngineResult(
                    resolved=True, ko_id=ko["id"], domain_attr="order", intent=default_intent,
                    entities=regex_entities, confidence=0.7,
                )
        return RuleEngineResult(resolved=False, entities=regex_entities, shortlist=[])

    best_score = max(s for s, _, _ in scored)
    tied_raw = [(attr, ko) for score, attr, ko in scored if score == best_score]
    if best_score[0] < MIN_CONFIDENCE_SCORE:
        return RuleEngineResult(resolved=False, entities=regex_entities, shortlist=_shortlist(_dedup(tied_raw)))

    return _resolve_tied(_dedup(tied_raw), regex_entities)


def _dedup(tied: List[Tuple[str, Dict[str, Any]]]) -> List[Tuple[str, Dict[str, Any]]]:
    seen_ids: Set[str] = set()
    out: List[Tuple[str, Dict[str, Any]]] = []
    for attr, ko in tied:
        if ko["id"] not in seen_ids:
            seen_ids.add(ko["id"])
            out.append((attr, ko))
    return out


def _match_clarification_choice(message: str, options: List[str]) -> Optional[str]:
    """User was shown a numbered menu of tied candidates (AWAITING_CLARIFICATION)
    - accept either a number ("1", "2") or a keyword re-score restricted to
    just those options."""
    m = re.search(r"\d+", message)
    if m:
        idx = int(m.group(0)) - 1
        if 0 <= idx < len(options):
            return options[idx]
    subset = [(attr, ko) for attr, ko in (_find_ko_by_id(kid) for kid in options) if ko]
    if not subset:
        return None
    message_words = _tokenize(message)
    df, n = _build_doc_freq(subset)
    scored = _score_kos(message_words, subset, df, n)
    if not scored:
        return None
    best = max(scored, key=lambda s: s[0])
    return best[2]["id"]


def _try_resume(message: str, awaiting: Dict[str, Any]) -> Optional[RuleEngineResult]:
    """One resume handler per HelpAwaitAction state - see the approved plan §2.
    Returns None (not a RuleEngineResult) when the reply can't be resolved
    against the pending state, telling classify() to fall through to normal
    steps 1-3 instead of getting stuck."""
    state_value = awaiting.get("state")
    collected = dict(awaiting.get("collected_entities") or {})

    # AWAITING_CLARIFICATION is handled first and separately: the "current"
    # Knowledge Object isn't a single resolved id yet in this state (the
    # whole point is the user is picking ONE from pending_options), so it
    # must not be gated on _find_ko_by_id(awaiting["ko_id"]) succeeding like
    # every other state below.
    if state_value == help_state.HelpAwaitAction.AWAITING_CLARIFICATION.value:
        picked_id = _match_clarification_choice(message, awaiting.get("pending_options") or [])
        if not picked_id:
            return None
        picked_attr, picked_ko = _find_ko_by_id(picked_id)
        if not picked_ko:
            return None
        return RuleEngineResult(
            resolved=True, ko_id=picked_id, domain_attr=picked_attr, intent=picked_ko["intent"],
            entities=collected, confidence=1.0, resumed_awaiting=True,
        )

    ko_id = awaiting.get("ko_id")
    domain_attr, ko = _find_ko_by_id(ko_id)
    if not ko:
        return None
    intent = ko["intent"]

    if state_value == help_state.HelpAwaitAction.AWAITING_ENTITY.value:
        value = _extract_entity_value(awaiting.get("pending_entity"), message)
        if value is None:
            return None
        collected[awaiting["pending_entity"]] = value
        return RuleEngineResult(
            resolved=True, ko_id=ko_id, domain_attr=domain_attr, intent=intent,
            entities=collected, confidence=1.0, resumed_awaiting=True,
        )

    if state_value == help_state.HelpAwaitAction.AWAITING_CONFIRMATION.value:
        confirmed = _parse_yes_no(message)
        if confirmed is None:
            return None
        collected["_confirmed"] = confirmed
        return RuleEngineResult(
            resolved=True, ko_id=ko_id, domain_attr=domain_attr, intent=intent,
            entities=collected, confidence=1.0, resumed_awaiting=True,
        )

    if state_value == help_state.HelpAwaitAction.AWAITING_EVIDENCE.value:
        # Attachment upload is a transport-layer concern the current
        # text-only /help request schema doesn't carry yet
        # (MISSING_FROM_DOCUMENT) - accept any non-empty reply as "provided"
        # for now so the flow can still proceed.
        text = message.strip()
        if not text:
            return None
        collected["hinh_anh_minh_chung"] = text
        return RuleEngineResult(
            resolved=True, ko_id=ko_id, domain_attr=domain_attr, intent=intent,
            entities=collected, confidence=1.0, resumed_awaiting=True,
        )

    return None


def classify(message: str, memory: Dict[str, Any]) -> RuleEngineResult:
    """Entry point - see the approved plan §1/§2/§4:
    1. Continuation check (cheapest path) - resumes memory["awaiting"] if set.
    2. Literal multi-word phrase match wins outright.
    3. IDF-weighted overlap score + explicit tie/ambiguity resolution.
    Regex entities are extracted up front and merged into whatever the
    winning path returns - they inform entities, never the intent choice by
    themselves (except the bare-code default-domain fallback in
    _resolve_by_score)."""
    awaiting = help_state.get_active_awaiting(memory)
    if awaiting:
        resumed = _try_resume(message, awaiting)
        if resumed:
            return resumed

    regex_entities = extract_regex_entities(message)
    return _resolve_by_score(message, regex_entities)
