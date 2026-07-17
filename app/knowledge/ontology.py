import difflib
import json
import math
import os
import re
import unicodedata
from typing import Dict, List, Optional, Any

def _strip_diacritics(text: str) -> str:
    """ASCII-fold Vietnamese text (điện thoại -> dien thoai) so it can be
    compared against slugs, which the backend always returns as ASCII/
    hyphenated (e.g. "dien-thoai-tablet")."""
    text = text.replace("đ", "d").replace("Đ", "D")
    normalized = unicodedata.normalize("NFD", text)
    return "".join(c for c in normalized if unicodedata.category(c) != "Mn")

# Typo-tolerance tier (find_category()/find_brand()'s last-resort fallback,
# AFTER the exact and no-diacritics attempts both find nothing) - snaps an
# unrecognized query word to its closest known vocabulary word via
# difflib's stdlib SequenceMatcher ratio, no external dependency/model call.
# Deliberately NOT applied to entity_extractor.clean_query_keywords's
# stopword stripping: stopwords are mostly short (<=4 chars), and a short
# word has many equally-close neighbors ("mua" is 0.8-similar to "mưa"/"múa"/
# "mùa"/"mụa"...), so fuzzy-matching THOSE would misfire constantly. Scoped
# to category/brand vocabulary words only, which are long enough (>=4 chars)
# for a close match to be a genuine, low-ambiguity typo instead of a
# coincidence, and are only ever used for internal category_id/brand
# resolution - never rewritten into the actual backend search text (same
# boundary the no-diacritics fallback above already keeps).
_MIN_FUZZY_WORD_LEN = 4
# 0.75, not difflib's usual 0.8+ default: a single wrong Vietnamese tone mark
# ("điẹn" for "điện", "thoai" for "thoại") already lands at ratio ~0.75-0.8,
# since each vowel+tone combination is its own Unicode codepoint - one wrong
# tone is a whole-character diff, not a small edit, on an already-short
# word. Verified against a batch of unrelated English filler words (table,
# pizza, coffee, hello...) at this cutoff + the length-similarity
# pre-filter: no spurious matches beyond one defensible case (table->tablet,
# an actual product-relevant near-miss, not a false positive).
_FUZZY_CUTOFF = 0.75

def _fuzzy_correct_words(words: set, vocab: List[str]) -> set:
    vocab_set = set(vocab)
    corrected = set()
    for w in words:
        if w in vocab_set or len(w) < _MIN_FUZZY_WORD_LEN:
            corrected.add(w)
            continue
        # Pre-filter to similar-length candidates before scoring - cuts
        # difflib's comparison set down from the whole vocabulary (hundreds
        # of words) to a handful, keeping this fallback cheap even though
        # it's O(vocab) in the worst case.
        candidates = [v for v in vocab if abs(len(v) - len(w)) <= 2]
        match = difflib.get_close_matches(w, candidates, n=1, cutoff=_FUZZY_CUTOFF)
        corrected.add(match[0] if match else w)
    return corrected

class Ontology:
    _instance = None

    # Words that must be ignored ONLY for category scoring, never for the
    # backend free-text query. Two kinds:
    #  - Generic "product/item" filler ("sản phẩm", "đồ", "xem") that shows up
    #    as fragments inside many unrelated subcategory names (e.g. "phẩm"
    #    inside "thực phẩm") and would otherwise falsely win the overlap
    #    scoring for ANY query that just says "product"/"item".
    #  - Grammatical particles ("không" = negation/"có...không?", "đã" = past
    #    marker, "bị" = passive-voice/affliction marker) that carry no category
    #    intent but happen to be a literal token inside a compound synonym
    #    phrase ("nồi chiên KHÔNG dầu" = air fryer, "máy lọc KHÔNG khí" = air
    #    purifier; "máy ĐÃ qua sử dụng" = used goods; "thiết BỊ mạng/y tế/âm
    #    thanh..." = network/medical/audio EQUIPMENT), so the word-splitter
    #    turns them into a spurious rare-word signal. "bị" is especially risky:
    #    it's near-universal in Vietnamese symptom complaints ("bị đau", "bị
    #    sốt", "bị ho") - exactly the health queries where a wrong category
    #    hurts most - and since the other words in such a query match nothing,
    #    "bị" wins outright with no tie forming for the tie-safeguards to catch.
    # Kept separate from self.stopwords (stopwords.json) ON PURPOSE: that list
    # is ALSO iterated by entity_extractor.clean_query_keywords() to strip words
    # from the actual backend query, where removing "không" would INVERT meaning
    # ("sạc không dây" wireless -> "sạc dây" wired) and removing "đồ" would break
    # "đồ chơi trẻ em". These words must be dropped from category matching only.
    _CATEGORY_NOISE_WORDS = {"sản", "phẩm", "đồ", "xem", "không", "đã", "bị"}
    # ASCII-folded mirror, for _category_query_words()'s no-diacritics
    # fallback (see there) - computed here since _strip_diacritics is
    # already defined above at module scope by the time this class body runs.
    _CATEGORY_NOISE_WORDS_STRIPPED = {_strip_diacritics(w) for w in _CATEGORY_NOISE_WORDS}

    # Minimum IDF-weighted single-word score to trust as a category signal -
    # see _score_subcategories() for the calibration (df/N distribution of
    # "máy" vs "giày"/"áo"/"quần"). Also reused by is_generic_word() so
    # ranker.py can flag the SAME genericity concept at the product-relevance
    # layer, not just the category layer.
    _MIN_SINGLE_WORD_WEIGHT = 2.5

    # Which category-flavored clarifying-question group (keys in
    # clarifying_questions.json) applies to each top-level category id (ids
    # from categories.json). A group only fires for categories where its
    # phrasing genuinely fits - e.g. the "đời mới / dùng để học-làm-giải trí"
    # (tech) questions make no sense for a food snack or a fridge, which is the
    # exact mismatch this mapping exists to prevent. Categories NOT listed here
    # (industrial, services, art, building materials, real estate...) fall back
    # to the universal brand/price questions only - never a wrong-flavored one.
    # "điện dân dụng - điện lạnh" (85) is deliberately its OWN "appliance" group,
    # not lumped with phones/computers, because "dùng để học tập/làm việc/giải
    # trí?" fits a laptop but not a máy giặt or tủ lạnh.
    # Also reused as the SAME group-key resolution for requirement_schema.json
    # (see requirement_schema_for()) - one mapping, two consumers, so a
    # category can never resolve to a different "flavor" for its clarifying
    # questions than for its required-attribute schema.
    _CLARIFY_GROUP_BY_CATEGORY_ID = {
        79: "phone_tablet",  # điện thoại & tablet - split out from "tech" so
                             # phones ask about budget/camera_need, not "purpose"
                             # (which fits laptops, not phones).
        80: "tech",       # máy tính-máy ảnh máy quay
        85: "appliance",  # điện dân dụng - điện lạnh
        81: "vehicle",    # ô tô - xe máy - xe đạp
        78: "food",       # siêu thị bách hóa
        77: "fashion",    # thời trang & phụ kiện
        76: "beauty",     # sức khỏe & sắc đẹp
        86: "baby",       # mẹ & bé
        87: "book",       # sách & ebook
        89: "construction_furniture",  # vật liệu xây dựng
        82: "real_estate",             # đăng tin-quảng cáo bđs
        84: "service_travel",          # dịch vụ & du lịch
        83: "art_music",               # nghệ thuật & mỹ thuật
        88: "industrial_agricultural", # công nghiệp - nông nghiệp
    }

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super(Ontology, cls).__new__(cls, *args, **kwargs)
            cls._instance.reload()
        return cls._instance

    def reload(self):
        base_dir = os.path.dirname(__file__)
        self.aliases: Dict[str, str] = self._load_json(os.path.join(base_dir, "aliases.json"))
        self.synonyms: Dict[str, List[str]] = self._load_json(os.path.join(base_dir, "synonyms.json"))
        # Category-resolution phrase hints: subcategory name -> multi-word
        # phrases that should resolve to it via find_category()'s step-2 LITERAL
        # phrase match ONLY. Deliberately kept OUT of synonyms.json (and thus
        # out of _subcategory_words / the step-3 IDF word scorer): synonyms feed
        # BOTH step 2 and step 3, so adding a multi-word product name there
        # ("kem chống nắng") leaks its individual words ("chống", "nắng") into
        # the scorer's vocabulary, where a single incidental one then wins for
        # an unrelated query ("áo chống nắng" -> skincare instead of clothing).
        # These hints only ADD strong, unambiguous literal-phrase resolutions
        # (the exact whole product name); they never influence single-word
        # overlap scoring. Multi-word only, which also keeps them safe for
        # normalize_term() (it matches whole words, never multi-word phrases).
        self.category_phrases: Dict[str, List[str]] = self._load_json(os.path.join(base_dir, "category_phrases.json"))
        self.categories: Dict[str, Any] = self._load_json(os.path.join(base_dir, "categories.json"))
        self._subcat_word_df, self._subcat_count = self._build_word_doc_freq()
        # ASCII-folded mirror of the same table, for find_category()'s
        # no-diacritics fallback (see its own docstring note) - a query typed
        # without dấu ("nuoc giat") can never overlap this vocabulary's
        # accented words, so scoring needs its own stripped word-space to
        # match against. Built once here (load time), not per-request.
        self._subcat_word_df_stripped, _ = self._build_word_doc_freq(stripped=True)
        # Typo-tolerance vocabulary (find_category()'s tier-3 fallback, see
        # _fuzzy_correct_words) - just the keys of the two doc-freq tables
        # above, already built, filtered to words long enough for a fuzzy
        # match to mean anything (see _MIN_FUZZY_WORD_LEN).
        self._category_vocab: List[str] = [w for w in self._subcat_word_df if len(w) >= _MIN_FUZZY_WORD_LEN]
        self._category_vocab_stripped: List[str] = [w for w in self._subcat_word_df_stripped if len(w) >= _MIN_FUZZY_WORD_LEN]
        self.brands: Dict[str, List[str]] = self._load_json(os.path.join(base_dir, "brands.json"))
        self.accessory_rules: Dict[str, List[str]] = self._load_json(os.path.join(base_dir, "accessories.json"))
        # Flat, attribute-keyed (e.g. "budget", "purpose", "family_size") -
        # NOT category-keyed. Shared across every category that needs a given
        # attribute; requirement_schema.json is what decides WHICH attributes
        # apply to which category (see requirement_schema_for()).
        self.clarifying_questions: Dict[str, List[str]] = self._load_json(os.path.join(base_dir, "clarifying_questions.json"))
        # category-group -> ordered (by "priority") required attribute names -
        # the Consultation Flow's single source of truth for which questions
        # to ask, and in what order, before searching an "expert"-level ask.
        # See app/chat/orchestrator.py's _missing_requirement_fields().
        self.requirement_schema: Dict[str, Any] = self._load_json(os.path.join(base_dir, "requirement_schema.json"))
        # category-group -> ordered comparison criteria (e.g. ["price", "stock",
        # "rating", "sold_count"]) - Compare Builder's single source of truth for
        # WHAT to compare, so adding a criterion later (once real spec data
        # exists) is a data change, not a code change. See app/chat/compare_builder.py.
        self.compare_rule: Dict[str, Any] = self._load_json(os.path.join(base_dir, "compare_rule.json"))
        # category-group -> requirement field -> value bucket -> spec
        # thresholds ({"min"/"max", "label"}) - the Recommendation Engine's
        # single source of truth for what counts as "suitable" for a given
        # answered requirement. Unlike requirement_schema.json/compare_rule.json,
        # deliberately has NO "_default" bucket: a category with no dedicated
        # rule here has no spec_extractor support either, so
        # recommendation_builder.build() must leave its products unscored
        # rather than invent thresholds for specs it can't read. See
        # app/chat/recommendation_builder.py + app/chat/spec_extractor.py.
        self.guide_rule: Dict[str, Any] = self._load_json(os.path.join(base_dir, "guide_rule.json"))
        # education_domain -> {"choices": [{"group","desc"}]} - the
        # market-education content shown BEFORE the Consultation Flow's first
        # gap-fill question, when the ask is still genuinely wide open (see
        # orchestrator.py's education gate). Same "no entry, no feature" stance
        # as guide_rule.json - a domain without one just keeps the old plain
        # clarifying-question behavior.
        #
        # Deliberately keyed by "education_domain" (see education_domain_for()
        # below), NOT by catalog category/group - a real buying decision
        # ("laptop", "thuốc say xe") doesn't line up with the catalog's own
        # taxonomy (both "kem chống nắng" and "thuốc say xe" sit under the
        # SAME broad "sức khỏe & sắc đẹp" category, but need completely
        # different educational content). Coupling Education to category
        # would mean either sharing one group's content across unrelated
        # decisions, or an ever-growing pile of category-specific requirement
        # fields (skin_need, medicine_need, ...) just to tell them apart.
        # education_domains.json resolves the free-text query DIRECTLY to a
        # domain instead, independent of how the catalog itself is organized.
        self.education_rule: Dict[str, Any] = self._load_json(os.path.join(base_dir, "education_rule.json"))
        self.education_domains: Dict[str, List[str]] = self._load_json(os.path.join(base_dir, "education_domains.json"))
        # Hand-written, per-domain replacement for education_prompt.txt's LLM
        # call - education_rule.json's choices are 100% static (10 fixed
        # domains, hand-authored groups/descriptions), so the explainer text
        # never actually varies turn to turn except for {term}. Keyed by the
        # same domain string as education_rule_for(); a domain with no entry
        # here falls back to the LLM call (see llm_client.format_education_response).
        self.education_templates: Dict[str, str] = self._load_json(os.path.join(base_dir, "education_templates.json"))
        self.faq_answers: Dict[str, str] = self._load_json(os.path.join(base_dir, "faq_answers.json"))
        # Keyed by sub_intent (see ShoppingContext.sub_intent):
        # "greeting"/"compliment"/"no_intent"/"out_of_scope"/"toxicity"/
        # "help_capabilities" - each GREETING/SOCIAL/CHITCHAT reply picks
        # randomly from its own bucket instead of one pool per top-level
        # intent, so a bare "ok" doesn't get the same reply as "cảm ơn nha",
        # and a complaint doesn't get the same reply as "kể chuyện cười đi".
        self.chitchat_responses: Dict[str, List[str]] = self._load_json(os.path.join(base_dir, "chitchat_responses.json"))
        # Kept separate from chitchat_responses: those are a warm decline for
        # genuinely off-topic chat (jokes, weather...), these specifically
        # defend against probing for the system prompt/internal config. Both
        # classify as CHITCHAT upstream, so mixing them in one random.choice
        # pool meant an innocent joke had ~1/3 odds of getting "mình không
        # tiết lộ prompt..." - a non-sequitur that reads as accusing the user
        # of trying to jailbreak the bot. See intent_classifier.is_prompt_probe_query.
        self.prompt_probe_responses: List[str] = self._load_json(os.path.join(base_dir, "prompt_probe_responses.json"))
        self.stopwords: set = set(self._load_json(os.path.join(base_dir, "stopwords.json")) or [])
        # No-diacritics mirrors of every dictionary find_category()/find_brand()/
        # normalize_term()/entity_extractor.clean_query_keywords() match
        # against - all built ONCE here (service load, not per-request) so the
        # no-diacritics fallback each of those adds is just another O(1) dict
        # lookup, identical cost to the existing accented one. Only ever
        # consulted when the INPUT text itself has no diacritic marks (see
        # each call site's own `_strip_diacritics(text) == text` guard) - a
        # normal, properly-accented query never reaches these and pays
        # nothing extra. A collision where two different accented words fold
        # to the same stripped form (e.g. "ga"/"gà") is an accepted, inherent
        # ambiguity of typing without dấu in the first place - the same
        # tie-break safeguards find_category() already has for the accented
        # path (reject an unresolvable cross-category tie rather than guess)
        # cover this fallback too, since it reuses _score_subcategories().
        self.stopwords_stripped: set = {_strip_diacritics(w) for w in self.stopwords}
        self._aliases_stripped: Dict[str, str] = {_strip_diacritics(k): v for k, v in self.aliases.items()}
        self._synonym_lookup_stripped: Dict[str, str] = {
            _strip_diacritics(syn): canonical
            for canonical, syn_list in self.synonyms.items()
            for syn in syn_list
        }
        self._brands_stripped: Dict[str, str] = {}
        for _brand, _models in self.brands.items():
            self._brands_stripped[_strip_diacritics(_brand)] = _brand
            for _model in _models:
                self._brands_stripped[_strip_diacritics(_model)] = _brand

        # Warm response pools - deterministic (LLM-free) paths pick randomly
        # from these instead of a single fixed string, so SEARCH/PRODUCT_INFO/
        # pagination replies stay varied and friendly without spending an LLM
        # call. (GREETING/SOCIAL/CHITCHAT now live in chitchat_responses above.)
        self.search_found_intros: List[str] = self._load_json(os.path.join(base_dir, "search_found_intros.json"))
        self.search_empty_responses: List[str] = self._load_json(os.path.join(base_dir, "search_empty_responses.json"))
        self.product_info_intros: List[str] = self._load_json(os.path.join(base_dir, "product_info_intros.json"))
        self.product_info_outros: List[str] = self._load_json(os.path.join(base_dir, "product_info_outros.json"))
        self.pagination_intros: List[str] = self._load_json(os.path.join(base_dir, "pagination_intros.json"))
        self.pagination_outros: List[str] = self._load_json(os.path.join(base_dir, "pagination_outros.json"))
        self.pagination_end_responses: List[str] = self._load_json(os.path.join(base_dir, "pagination_end_responses.json"))
        # Recommendation Engine (Sprint 2) closing line - the only part of
        # that turn formatter_prompt.txt's LLM call used to add on top of the
        # fully-deterministic star ratings/reasons/trade-off block (see
        # response_formatter.py); templated instead since it only ever
        # varies by the top product's name.
        self.recommendation_closings: List[str] = self._load_json(os.path.join(base_dir, "recommendation_closings.json"))

    def _load_json(self, path: str) -> Any:
        try:
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
            return {}
        except Exception:
            return {}

    def _subcategory_words(self, cat_name: str, sub_name: str, stripped: bool = False) -> set:
        """All words identifying a subcategory: its own name, its synonym
        phrases, AND its top-level category's name. Folding in the top-level
        name lets a generic word ("máy") still tip the balance toward the
        right category when the real subcategory match is otherwise a tie -
        e.g. "máy tính-máy ảnh máy quay" reinforces "máy" for its "nạp mực
        in" subcategory, breaking a tie against an unrelated "in ấn, dịch
        thuật" (printing SERVICES, not hardware) subcategory that only
        shares the word "in".

        `stripped` returns the ASCII-folded form of the same word set
        instead (for the no-diacritics fallback - see find_category()) -
        same words, just diacritics-insensitive, so a caller never needs to
        fold this set itself."""
        words = set(w for w in re.split(r"[^\w]+", cat_name.lower(), flags=re.UNICODE) if w)
        words |= set(w for w in re.split(r"[^\w]+", sub_name, flags=re.UNICODE) if w)
        for syn_phrase in self.synonyms.get(sub_name, []):
            words |= set(w for w in re.split(r"[^\w]+", syn_phrase.lower(), flags=re.UNICODE) if w)
        if stripped:
            return {_strip_diacritics(w) for w in words}
        return words

    def _build_word_doc_freq(self, stripped: bool = False):
        """Document frequency of each word across all subcategories - how
        many distinct subcategories a word shows up in. Powers the IDF
        weighting in find_category(): a word shared by many subcategories
        ("máy" - appears in ~18) is a much weaker signal than one nearly
        unique to a handful ("giặt"/"in" - appear in ~2), so a rare word
        should outrank a common one even when it's the only word matched.

        `stripped` builds the same table in ASCII-folded word-space, for the
        no-diacritics fallback (see find_category())."""
        df: Dict[str, int] = {}
        count = 0
        for cat_name, cat_data in self.categories.items():
            for sub_name in cat_data.get("subcategories", {}).keys():
                count += 1
                for w in self._subcategory_words(cat_name, sub_name, stripped=stripped):
                    df[w] = df.get(w, 0) + 1
        return df, count

    def normalize_term(self, term: str) -> str:
        term_clean = term.lower().strip()
        # Direct alias lookup
        if term_clean in self.aliases:
            return self.aliases[term_clean]
        # Synonym lookup - rewrite colloquial/foreign terms (e.g. "smartphone")
        # to the canonical subcategory name so search actually finds it,
        # the same way aliases do. Without this, a synonym-recognized term
        # would still be sent to the backend verbatim and legitimately return
        # zero results.
        #
        # Skips synonyms.json keys formatted as a CATALOG LABEL rather than a
        # natural search phrase (containing " - ", e.g. "ăn vặt - bánh kẹo",
        # "sữa - tả - bình sữa" - a UI tab name, not product wording).
        # Substituting one of THOSE defeats this function's own stated
        # purpose ("so search actually finds it"): no real product title
        # contains that literal dash-joined label either, so the rewrite
        # guarantees zero results instead of preventing them. Confirmed
        # live: query_normalizer.normalize() turned "banh snack" into "banh
        # ăn vặt - bánh kẹo" (per-word substitution, "snack" -> its
        # subcategory's own label), corrupting the actual search text sent
        # downstream. A natural-phrase canonical ("điện thoại di động" for
        # "smartphone") is unaffected - it has no such separator.
        for canonical, syn_list in self.synonyms.items():
            if term_clean in syn_list and " - " not in canonical:
                return canonical
        # No-diacritics fallback ("dien thoai" -> "điện thoại") - only tried
        # when the term itself has no dấu to begin with (a term that already
        # carries dấu and still matched nothing is a genuine unknown term,
        # not a diacritics problem), against dictionaries built once at
        # reload() (see there) so this costs one more O(1) dict lookup, same
        # as the accented attempts above.
        if _strip_diacritics(term_clean) == term_clean:
            stripped = self._aliases_stripped.get(term_clean)
            if not stripped:
                syn_stripped = self._synonym_lookup_stripped.get(term_clean)
                if syn_stripped and " - " not in syn_stripped:
                    stripped = syn_stripped
            if stripped:
                return stripped
        return term_clean

    def find_brand(self, text: str) -> Optional[str]:
        text_lower = text.lower()
        # Word-boundary match - a raw substring check let short model keywords
        # (e.g. honda's "sh") false-match inside unrelated words (e.g. "ship").
        for brand in self.brands.keys():
            if re.search(rf"\b{re.escape(brand)}\b", text_lower):
                return brand
        for brand, models in self.brands.items():
            for model in models:
                if re.search(rf"\b{re.escape(model)}\b", text_lower):
                    return brand
        # No-diacritics fallback - same guard/rationale as normalize_term()
        # above. Brand names/models are mostly already ASCII (Samsung, Sony,
        # Honda...) so this mainly helps the handful with Vietnamese spelling.
        if _strip_diacritics(text_lower) == text_lower:
            for stripped_key, brand in self._brands_stripped.items():
                if re.search(rf"\b{re.escape(stripped_key)}\b", text_lower):
                    return brand
        # Typo tolerance - last resort, single-word brand NAMES only (not
        # multi-word models: too structurally varied to fuzzy-match safely,
        # e.g. "iphone 15 pro max" has no single close neighbor to snap to).
        words = [w for w in re.split(r"[^\w]+", text_lower, flags=re.UNICODE) if len(w) >= _MIN_FUZZY_WORD_LEN]
        if words:
            brand_vocab = list(self.brands.keys())
            for w in words:
                if w in self.brands:
                    continue
                candidates = [b for b in brand_vocab if abs(len(b) - len(w)) <= 2]
                match = difflib.get_close_matches(w, candidates, n=1, cutoff=_FUZZY_CUTOFF)
                if match:
                    return match[0]
        return None

    def _category_query_words(self, text_lower: str, stripped: bool = False) -> set:
        """Tokenize + strip filler for the IDF subcategory scorer - shared by
        find_category() (resolving a user query) and best_subcategory_for_product()
        (resolving a PRODUCT NAME, to check it actually belongs to the
        subcategory the query resolved to - see ranker.py).

        `stripped` ASCII-folds both the input AND the stopword/noise-word
        filter (self.stopwords_stripped / _CATEGORY_NOISE_WORDS_STRIPPED) -
        an earlier version filtered against the ACCENTED lists even here,
        on the assumption an unaccented token could never match an accented
        stopword and would just "fall through harmlessly". That assumption
        was wrong: it meant NO stopword filtering happened at all for a
        no-diacritics query, letting filler words leak into the scorer as
        real candidate words - confirmed live: "toi can tim banh canh cu de
        an" left "can" (từ "cần" - filler "need") in as a query word, which
        then collided with "căn" (từ "căn hộ" - apartment, a real vocab
        word: both fold to the SAME stripped "can") and confidently
        resolved the whole query to bất động sản instead of food."""
        stopwords = self.stopwords_stripped if stripped else self.stopwords
        noise_words = self._CATEGORY_NOISE_WORDS_STRIPPED if stripped else self._CATEGORY_NOISE_WORDS
        words = {
            w for w in re.split(r"[^\w]+", text_lower, flags=re.UNICODE)
            if len(w) > 1 and w not in stopwords and w not in noise_words
        }
        if stripped:
            return {_strip_diacritics(w) for w in words}
        return words

    def _score_subcategories(self, query_words: set, stripped: bool = False, min_overlap: int = 1) -> Optional[Dict[str, Any]]:
        """Core IDF-weighted subcategory scorer - see find_category() step 3
        for the full rationale. Factored out so best_subcategory_for_product()
        can reuse the exact same scoring against a product name instead of a
        user query.

        `stripped` scores against the ASCII-folded vocabulary/doc-freq table
        instead (both built once at reload() - see there) - same algorithm,
        same tie-break safeguards below, just a different word-space; callers
        must pass `query_words` already folded to match (see find_category()).

        `min_overlap` demands at least that many overlapping words before
        trusting ANY result, bypassing the single-word weight-threshold trust
        below entirely - used by find_category()'s no-diacritics/typo
        fallback tiers (min_overlap=2), which don't get to rely on that
        threshold the way the primary accented tier does: it was calibrated
        against the real, curated accented vocabulary ("áo"/"quần" are
        genuinely rare there), but accent-folding or typo-correction can
        make an UNRELATED word land on the same rare slot by coincidence -
        confirmed live twice over (see find_category()'s own notes on "nam"
        and "cần"->"căn"). Requiring a second corroborating word is a much
        safer bar for a fallback tier to clear than trusting any single
        lucky-weight word."""
        if not query_words:
            return None
        word_df = self._subcat_word_df_stripped if stripped else self._subcat_word_df
        scored = []  # (score_tuple, overlap_set, result_dict) - first-encountered order
        for cat_name, cat_data in self.categories.items():
            for sub_name in cat_data.get("subcategories", {}).keys():
                sub_words = self._subcategory_words(cat_name, sub_name, stripped=stripped)
                if not sub_words:
                    continue
                overlap = query_words & sub_words
                if not overlap:
                    continue
                weighted = sum(math.log(self._subcat_count / word_df.get(w, 1)) for w in overlap)
                score = (weighted, len(overlap))
                result = {"id": cat_data.get("id"), "slug": cat_data.get("slug"), "level": 1, "subcategory": sub_name}
                scored.append((score, overlap, result))
        if not scored:
            return None

        # Confidence gate. Take every candidate tied at the top score. If they
        # matched on DIFFERENT words (no single word common to all of them), the
        # query has no dominant category signal - it's a coin-flip between
        # unrelated meanings, and the old code picked one purely by dict-iteration
        # order. E.g. "bánh in" ties "bánh"->food against "in"->printing across
        # four unrelated top-level categories; guessing is worse than admitting
        # we don't know, so return None ("undetermined"). A tie whose candidates
        # DO share a common word is a real single-term match with several
        # sub-flavors (e.g. "giày" -> men's/women's/kids' shoes, all keyed on
        # "giày") and still resolves - we just keep the first-encountered one,
        # exactly as before.
        best_score = max(s for s, _, _ in scored)
        if best_score[1] < min_overlap:
            return None
        top = [(overlap, result) for score, overlap, result in scored if score == best_score]
        if len(top) > 1 and not set.intersection(*(overlap for overlap, _ in top)):
            return None

        # Same-word tie across DIFFERENT top-level categories is a second,
        # distinct kind of ambiguity the check above doesn't catch: a common
        # filler word ties with ITSELF across several unrelated categories,
        # so the "different words" check above (which compares overlap SETS)
        # never fires, and the old code just picked whichever candidate
        # happened to be first in categories.json regardless of whether that
        # pick meant anything. Two real examples show this needs BOTH an
        # absolute-genericity signal and a cross-category signal, not either
        # alone:
        #  - "máy" (weight~1.6, df=27/134): ties across công nghiệp/điện
        #    thoại/ô tô/... - genuinely no dominant category, and picking
        #    "công nghiệp" (first in the dict) confidently locked a bare
        #    "máy i" query into a category that has nothing to do with it.
        #  - "áo"/"quần" (weight~3.8, df=3/134): ALSO tie across 2 different
        #    top-level ids ("thời trang" + "vật liệu xây dựng", the latter
        #    only because its "tủ quần áo"/wardrobe synonym happens to
        #    contain that word) - but a word this rare is still a strong
        #    signal for its true category; rejecting it on cross-category
        #    ties alone would break bare "áo"/"quần" search, which used to
        #    work (by luck of dict order, not by design).
        # Requiring the word to ALSO be low-weight (genuinely common, not
        # just incidentally shared with one contaminated synonym) before the
        # cross-category tie counts as real ambiguity keeps "máy" rejected
        # and "áo"/"quần"/"giày" resolving. "sách" (weight~2.3, ties 13 ways
        # but all under ONE id) is unaffected either way - single-id ties
        # were never the concern.
        # A third kind of tie the two checks above don't catch: DIFFERENT
        # subcategories WITHIN THE SAME top-level category tying on exactly
        # the same overlap set. This happens because _subcategory_words()
        # folds the top-level category's own name into every subcategory's
        # vocabulary (see its own docstring) - so for a category whose
        # subcategories don't otherwise share distinguishing words, a query
        # matching only that shared top-level vocabulary ties ALL of them
        # identically. Confirmed live: "xe đạp điện GIANT I NIKKO" (a real
        # bicycle) tied "ôtô"/"xe máy"/"xe đạp" (all under category 81) at
        # the exact same overlap {"xe","đạp"} and score, and the old code
        # picked "ôtô" purely because it's declared first in categories.json
        # - confidently mislabeling a bicycle as a car. Same
        # weight/word-count threshold as the cross-category check: a 2+-word
        # tie is unambiguous enough to always reject (no legitimate single
        # compound noun ties this way in practice), a low-weight single word
        # is genuinely too generic to trust, but a rare, high-weight single
        # word tie (kept - e.g. "giày" tying its own men's/women's/kids'
        # sub-flavors) still resolves as before.
        spans_multiple_categories = len({result["id"] for _, result in top}) > 1
        spans_multiple_subcategories = len({result["subcategory"] for _, result in top}) > 1
        if spans_multiple_categories or spans_multiple_subcategories:
            # 1-word ties additionally need the low-weight check (protects
            # "áo"/"quần"/"giày" - see above). A 2+-word tie across DIFFERENT
            # top-level categories has no equivalent false-positive class to
            # protect: a genuinely specific compound noun ("tủ lạnh", "máy
            # giặt") never ties across unrelated categories in practice -
            # only a generic VERB phrase does, e.g. "chăm sóc" (care/tend to,
            # written as 2 space-separated syllables, tokenized into
            # {"chăm","sóc"}) ties at equal weight across "chăm sóc và bảo
            # dưỡng" (car care), "chăm sóc thú cưng" (pet care), "chăm sóc da
            # nữ" (skincare)... an AI-Parser free-text label like "chăm sóc
            # nhà cửa" (home care) for a "bột giặt" (detergent) query
            # confidently but wrongly resolved to id=81 (ô tô - xe máy - xe
            # đạp) this way - picking whichever of those five was first in
            # the dict, same failure shape as "máy", just with 2 words
            # instead of 1. So reject outright regardless of weight here.
            if best_score[1] >= 2 or best_score[0] < self._MIN_SINGLE_WORD_WEIGHT:
                if spans_multiple_categories:
                    # Genuinely don't know WHICH top-level category either -
                    # no signal at all is trustworthy here.
                    return None
                # All tied candidates agree on the SAME top-level category -
                # that part isn't ambiguous, only which specific subcategory
                # is. Discarding category_id along with the subcategory guess
                # was a real regression (confirmed live: "bất động sản" ties
                # 4-ways across its own subcategories - "dự án bất động sản
                # lớn", "sàn bất động sản"... - which used to at least
                # resolve category_id=82 via first-in-dict order; returning
                # None here lost that correct, unambiguous id too, on top of
                # the subcategory guess this check is actually meant to
                # refuse). Degrade to a category-only match instead - same
                # shape find_category() step 1 already returns.
                return {"id": top[0][1]["id"], "slug": top[0][1]["slug"], "level": 1, "subcategory": None}
        return top[0][1]

    def is_generic_word(self, word: str) -> bool:
        """True for a word too common across the catalog's own vocabulary to
        carry any real product-search signal on its own (e.g. "máy" - present
        in 27 of 134 subcategories). Same IDF weight/threshold as the
        single-word category-tie gate in _score_subcategories(), exposed here
        so ranker.py/search_engine.py can flag the analogous case at the
        product-relevance layer: a query that reduces to just this one word
        (its other tokens were noise/typos) shouldn't be presented with full
        confidence just because SOME product happens to contain it."""
        df = self._subcat_word_df.get(word.lower())
        if not df:
            return False
        weight = math.log(self._subcat_count / df)
        return weight < self._MIN_SINGLE_WORD_WEIGHT

    def best_subcategory_for_product(self, product_name: str) -> Optional[str]:
        """Which subcategory a PRODUCT's own name best matches, via the same
        scoring find_category() uses for a user query. Lets ranker.py check a
        product actually belongs to the subcategory the query resolved to,
        not just the same top-level category: "máy in" (printer, subcategory
        "nạp mực in") and "máy tính xách tay" (laptop, subcategory "laptop
        theo nhãn hiệu") share the top-level category "máy tính-máy ảnh máy
        quay" - category_id scoping alone can't tell them apart, which is
        exactly how a laptop/monitor used to leak into a "máy in" search."""
        result = self._score_subcategories(self._category_query_words(product_name.lower()))
        return result["subcategory"] if result else None

    def query_restates_subcategory(self, query_q: Optional[str], subcategory: Optional[str]) -> bool:
        """True when query_q, resolved on its own via find_category(), lands
        on the EXACT SAME subcategory already known (`subcategory`) - i.e.
        query_q is just a restatement of the category/subcategory itself
        ("ô tô"/"ôtô" for the "ôtô" subcategory), not a more specific
        distinguishing term (a brand, model, or spec word). Shared by two
        callers that both need this same fact for different reasons:
        - search_engine.py: prefer a category/subcategory BROWSE
          (/products, subcategory_id filter) over a keyword search
          (/products/search?q=...) in that case - confirmed live, real
          listings (brand+model titles like "Toyota Camry 2019", "BMW")
          almost never contain the bare category noun, so the keyword
          index misses them entirely while a subcategory browse lists them
          all regardless of title text.
        - ranker.py: trust category_id/subcategory_id scoping over
          requiring a literal keyword hit in the product's own name, for
          the same reason.
        False whenever query_q carries anything beyond the bare category
        restatement (a brand, a different/no subcategory) - those cases are
        real distinguishing signal and must go through the normal keyword
        path unchanged.

        Normalizes query_q the same way query_normalizer.normalize() does
        (per-word alias/synonym substitution) before resolving it - on the
        AI-parser path, query_q is Gemini's own free-text guess and can be
        an unaccented ASCII spelling ("oto") that never went through that
        normalization (only the deterministic parser's own pipeline does),
        so find_category() would otherwise never recognize it as the same
        concept as its accented catalog counterpart ("ôtô").

        Resolving to the same subcategory is NOT sufficient on its own: the
        IDF scorer in find_category() simply ignores any word it doesn't
        recognize (a brand like "toyota" contributes nothing to the score
        either way), so "ôtô toyota" would "restate" the "ôtô" subcategory
        here too even though "toyota" is a real, meaningful distinguisher a
        keyword search COULD act on - browsing would silently drop it
        (confirmed live: "tìm oto toyota" returned BMW/Mazda6 alongside the
        real Toyota once browse ignored the brand word entirely). Also
        requires every meaningful word in query_q to already be part of the
        subcategory's own vocabulary (its name + top-level category name +
        synonyms) - nothing left over.

        No-diacritics gap fixed: normalize_term() only rewrites whole KNOWN
        alias/synonym terms ("oto"->"ô tô"), not arbitrary bare syllables
        ("dien"/"thoai" have no such entry, so they pass through unchanged) -
        so find_category() above already resolves a no-dấu query correctly
        (via its own fallback tiers), but the subset check below used to
        compare those still-unaccented words against the ACCENTED-only
        subcategory vocabulary and always fail. Confirmed live: "dien thoai"
        correctly resolved to "điện thoại di động" above, yet this returned
        False, so ranker.py's category_id-trust branch never fired and every
        genuine phone got rejected for "0 keyword match"."""
        if not subcategory or not query_q:
            return False
        normalized_q = " ".join(self.normalize_term(w) for w in query_q.lower().split())
        cat_info = self.find_category(normalized_q)
        if not cat_info or cat_info.get("subcategory") != subcategory:
            return False
        is_no_diacritics = bool(normalized_q) and _strip_diacritics(normalized_q) == normalized_q
        query_words = self._category_query_words(normalized_q, stripped=is_no_diacritics)
        for cat_name, cat_data in self.categories.items():
            if cat_data.get("id") != cat_info["id"]:
                continue
            sub_words = self._subcategory_words(cat_name, subcategory, stripped=is_no_diacritics)
            return query_words.issubset(sub_words)
        return False

    def strip_category_noun(self, query_q: Optional[str], subcategory: Optional[str]) -> str:
        """Removes any word from query_q that's already part of
        `subcategory`'s own vocabulary (its name + top-level category name +
        synonyms) - generic set-difference, e.g. "ôtô toyota" -> "toyota",
        "ôtô honda" -> "honda", equally for ANY leftover word, not a specific
        brand. /products/search's own AND-token match requires EVERY word in
        `q` to appear in the product's title - confirmed live, this backend
        genuinely returns 0 for q="ôtô toyota" but 1 real match for
        q="toyota" alone, because "ôtô" (the bare category noun) almost
        never appears literally in a real brand+model title. Leaving it in
        the query silently defeats the search for whatever real
        distinguishing term (brand, model...) is left over. Returns query_q
        unchanged if subcategory/category can't be resolved, or if stripping
        would remove EVERYTHING (that all-restated case belongs to
        query_restates_subcategory()'s browse path instead, not here).

        No-diacritics gap fixed - same as query_restates_subcategory()'s own
        note: a no-dấu query_q ("dien thoai toyota") never matched the
        ACCENTED-only subcategory vocabulary this compared against, so the
        bare category noun never got stripped and "toyota" stayed buried
        behind "dien thoai", which the backend's AND-token match then failed
        on entirely."""
        if not subcategory or not query_q:
            return query_q or ""
        cat_info = self.find_category(query_q)
        if not cat_info:
            return query_q
        is_no_diacritics = _strip_diacritics(query_q.lower()) == query_q.lower()
        sub_words = None
        for cat_name, cat_data in self.categories.items():
            if cat_data.get("id") == cat_info["id"]:
                sub_words = self._subcategory_words(cat_name, subcategory, stripped=is_no_diacritics)
                break
        if not sub_words:
            return query_q
        if is_no_diacritics:
            kept = [w for w in query_q.split() if _strip_diacritics(w.lower()) not in sub_words]
        else:
            kept = [w for w in query_q.split() if w.lower() not in sub_words]
        return " ".join(kept) if kept else query_q

    def product_has_category_signal(self, product_name: str, category_id: int) -> bool:
        """True iff product_name shares ANY vocabulary overlap with ANY
        subcategory under `category_id` - even if _score_subcategories
        couldn't confidently resolve to ONE of them (an ambiguous tie among
        that category's own sibling subcategories - see the same-category
        tie rejection in _score_subcategories()). Distinguishes the two
        different reasons best_subcategory_for_product() can return None:
        genuinely NO keyword signal at all (a foreign brand/model name like
        "Toyota Camry 2019" - safe to trust category_id filtering alone) vs.
        a real signal that's just ambiguous WITHIN this category's own
        subcategory family (a bicycle matching generic words shared with
        car/motorbike subcategories under the same parent - should NOT get
        the same free pass, since it might belong to a genuinely different
        sibling subcategory the tie couldn't distinguish). Used by ranker.py
        right where that distinction actually matters, instead of collapsing
        both into an equally-permissive bare None."""
        words = self._category_query_words(product_name.lower())
        if not words:
            return False
        for cat_name, cat_data in self.categories.items():
            if cat_data.get("id") != category_id:
                continue
            for sub_name in cat_data.get("subcategories", {}).keys():
                if words & self._subcategory_words(cat_name, sub_name):
                    return True
        return False

    def find_category(self, text: str) -> Optional[Dict[str, Any]]:
        text_lower = text.lower()
        # Whole-string no-diacritics guard, reused by steps 1-3's fallback
        # below: True only when text_lower carries NO Vietnamese diacritic
        # marks at all ("nuoc giat"), never for a normal accented query that
        # simply didn't match anything ("nước giặt" alone still resolves via
        # the accented path below, unaffected). A text that already has dấu
        # and still matches nothing is a genuine unknown term, not a
        # diacritics problem - so this fallback only ever fires for the
        # currently-100%-broken no-dấu case, at zero extra cost for every
        # normal query (one string comparison, done once here).
        is_no_diacritics = bool(text_lower) and _strip_diacritics(text_lower) == text_lower

        # 1. Exact match on a main category's own name/slug - rare but strongest signal
        for cat_name, cat_data in self.categories.items():
            slug = cat_data.get("slug") or ""
            if cat_name in text_lower or (slug and slug in text_lower):
                return {"id": cat_data.get("id"), "slug": cat_data.get("slug"), "level": 1, "subcategory": None}
        if is_no_diacritics:
            for cat_name, cat_data in self.categories.items():
                slug = cat_data.get("slug") or ""
                stripped_name = _strip_diacritics(cat_name)
                if stripped_name in text_lower or (slug and slug in text_lower):
                    return {"id": cat_data.get("id"), "slug": cat_data.get("slug"), "level": 1, "subcategory": None}

        # 2. Literal multi-word phrase match. A subcategory's own name or one
        # of its synonym phrases (2+ words) appearing verbatim in the query is
        # a far stronger, unambiguous signal than the fragment-overlap ratio
        # in step 3 below - which it needs to preempt, because that ratio can
        # be fooled by a single generic word. E.g. "máy" (shared by "xe máy",
        # "máy tính bàn", "máy văn phòng"...) was beating a real 2-word match
        # "máy giặt" for a washing-machine query, purely because "máy giặt"
        # only lives inside "điện lạnh"'s long synonym list, which dilutes
        # its ratio far below "xe máy"'s short, undiluted one. Picks the
        # longest verbatim phrase match across all subcategories for
        # specificity (e.g. prefer a 3-word hit over a 2-word one).
        best_phrase = None
        for cat_name, cat_data in self.categories.items():
            for sub_name in cat_data.get("subcategories", {}).keys():
                for phrase in [sub_name] + self.synonyms.get(sub_name, []) + self.category_phrases.get(sub_name, []):
                    phrase = phrase.lower()
                    candidate = _strip_diacritics(phrase) if is_no_diacritics else phrase
                    if len(phrase.split()) < 2 or candidate not in text_lower:
                        continue
                    if not best_phrase or len(phrase) > len(best_phrase[0]):
                        best_phrase = (phrase, {"id": cat_data.get("id"), "slug": cat_data.get("slug"), "level": 1, "subcategory": sub_name})
        if best_phrase:
            return best_phrase[1]

        # 3. Score every subcategory by IDF-weighted word overlap and keep the
        # single best (most specific) match. An earlier version scored by
        # raw overlap-ratio (matched words / total words in the subcategory +
        # its synonyms), which had two failure modes now fixed by IDF:
        # - A short, fully-matched subcategory could hijack resolution purely
        #   by having fewer words in its denominator, even when the matched
        #   word was a generic one shared by a dozen other subcategories
        #   ("máy" matching "xe máy" beat a real "máy giặt" match inside
        #   "điện lạnh", purely because "điện lạnh" has a longer synonym list
        #   diluting its ratio - see git history for the exact repro).
        # - A subcategory with MORE synonyms scored WORSE for an otherwise
        #   perfect match, since every synonym word added to the denominator
        #   without the query needing to mention it.
        # IDF fixes both: a word's weight is log(N / how many subcategories
        # contain it), so "máy" (~18 subcategories) contributes far less than
        # "giặt"/"in" (~2 subcategories each) regardless of how long any
        # subcategory's synonym list is.
        #
        # Generic verbs/particles/marketing filler ("mua", "chính hãng", "giá
        # rẻ"...) are stripped first - otherwise they coincidentally match
        # unrelated subcategories too (e.g. "mua" literally appears inside
        # "cần mua nhà đất"). Also pulls in words from any colloquial synonym
        # phrases mapped to a subcategory (synonyms.json is keyed by the
        # exact subcategory name) - e.g. "áo" only appears in synonyms.json's
        # "áo nữ"/"áo nam", never in the subcategory name "thời trang nữ"
        # itself, so a bare "áo" query would otherwise never match. This only
        # widens what find_category() can resolve; it does NOT touch
        # normalize_term()/query_q, so backend search text stays exactly
        # what the user typed.
        #
        # For a genuinely no-dấu query, go straight to the ASCII-folded
        # scorer instead of trying the accented one first: several common
        # Vietnamese words carry no diacritics even when properly spelled
        # ("nam", "cho", "ba"...), so the accented attempt can still find a
        # coincidental PARTIAL match on those alone (e.g. "ao thun nam" ->
        # "nam" alone matching "chăm sóc cho nam giới") and return it before
        # the fuller stripped comparison (which also catches "ao"->"áo",
        # correctly winning "thời trang nam" with a stronger 2-word overlap)
        # ever gets a chance to run. The stripped table is a strict superset
        # of what the accented one can match here, so there's no case where
        # trying accented first would find something stripped would miss.
        # Both fallback tiers below (no-diacritics AND typo-correction) require
        # a 2+-word overlap to trust a result - the primary accented tier
        # right below keeps its normal min_overlap=1 (default), since ITS
        # single-word trust threshold (_MIN_SINGLE_WORD_WEIGHT) was
        # calibrated against the real, curated accented vocabulary where a
        # rare word genuinely means something ("áo"/"quần" alone). Accent-
        # folding or typo-correction can land an UNRELATED word on that same
        # rare slot purely by coincidence - confirmed live twice: "nam" (a
        # naturally-unaccented word) and "cần"->"can" colliding with "căn"
        # (apartment) both produced a confident but wrong single-word
        # resolution before this gate existed. A 2nd corroborating word is a
        # much safer bar for a tier that's already guessing.
        if is_no_diacritics:
            words = self._category_query_words(text_lower, stripped=True)
            result = self._score_subcategories(words, stripped=True, min_overlap=2)
            if result:
                return result
            # 4. Typo tolerance - last resort, only reached when steps 1-3
            # above found NOTHING at all. Snaps each unrecognized word to its
            # closest known vocabulary neighbor (see _fuzzy_correct_words)
            # and retries the exact same scorer/tie-break logic - so a typo'd
            # word gets exactly as much scrutiny as a correctly-spelled one,
            # it's just been substituted first.
            fuzzy_words = _fuzzy_correct_words(words, self._category_vocab_stripped)
            return self._score_subcategories(fuzzy_words, stripped=True, min_overlap=2) if fuzzy_words != words else None
        words = self._category_query_words(text_lower)
        result = self._score_subcategories(words)
        if result:
            return result
        fuzzy_words = _fuzzy_correct_words(words, self._category_vocab)
        return self._score_subcategories(fuzzy_words, min_overlap=2) if fuzzy_words != words else None

    def find_category_weak(self, text: str) -> Optional[Dict[str, Any]]:
        """The single-word guess find_category()'s no-diacritics/typo
        fallback tiers found but rejected for being below their min_overlap=2
        confidence bar (see find_category()) - for callers that want to
        SUGGEST it to the user ("bạn có muốn tìm loại {X} cụ thể không?")
        instead of either trusting it outright or discarding it. Never used
        to filter a search directly - only find_category()'s confident
        result is. Recomputes the exact same tiers WITHOUT the 2-word
        requirement; returns None if even a single word doesn't match
        anything (nothing to suggest)."""
        text_lower = text.lower()
        is_no_diacritics = bool(text_lower) and _strip_diacritics(text_lower) == text_lower
        if is_no_diacritics:
            words = self._category_query_words(text_lower, stripped=True)
            result = self._score_subcategories(words, stripped=True)
            if result:
                return result
            fuzzy_words = _fuzzy_correct_words(words, self._category_vocab_stripped)
            return self._score_subcategories(fuzzy_words, stripped=True) if fuzzy_words != words else None
        words = self._category_query_words(text_lower)
        result = self._score_subcategories(words)
        if result:
            return result
        fuzzy_words = _fuzzy_correct_words(words, self._category_vocab)
        return self._score_subcategories(fuzzy_words) if fuzzy_words != words else None

    def subcategories_for(self, category: str) -> Optional[Dict[str, Any]]:
        """Display name + id + subcategory list (each with its own real
        numeric id) for the top-level category a (possibly loose, AI-
        generated) category label resolves to. Re-resolves via
        find_category() the same way search_engine.search() derives
        category_id from context.category, so it works whether `category` is
        already a slug (deterministic parser path) or free-text (AI parser
        path). Used by response_formatter's zero-result fallback to offer a
        concrete subcategory menu instead of a dead-end "try other keywords"
        message - $0 cost, pure ontology lookup. The ids are what make a
        later "chọn số N" from that menu resolvable to an ACTUAL
        subcategory_id filter (see subcategory_id_for) instead of just a
        free-text name the AI has to re-guess."""
        cat_info = self.find_category(category)
        if not cat_info:
            return None
        for cat_name, cat_data in self.categories.items():
            if cat_data.get("id") == cat_info["id"]:
                return {
                    "name": cat_name,
                    "slug": cat_data.get("slug"),
                    "category_id": cat_data.get("id"),
                    "subcategories": [
                        {"name": sub_name, "id": sub_id}
                        for sub_name, sub_id in cat_data.get("subcategories", {}).items()
                    ],
                }
        return None

    def _requirement_group_for(self, category: Optional[str]) -> Optional[str]:
        """Resolves `category` (slug or free text, same as subcategories_for())
        to its requirement_schema.json / clarifying_questions.json group key,
        or None if it's unresolved / outside the catalog (callers fall back to
        "_default" as appropriate)."""
        if not category:
            return None
        cat_info = self.find_category(category)
        if not cat_info:
            return None
        return self._CLARIFY_GROUP_BY_CATEGORY_ID.get(cat_info["id"])

    def requirement_schema_for(self, category: Optional[str]) -> List[str]:
        """Ordered required attribute names (e.g. ["family_size", "budget"])
        for whichever requirement_schema.json group `category` resolves to,
        sorted by each entry's "priority" - lowest asked first. Falls back to
        the "_default" group when category is None/unresolved or has no
        dedicated group of its own. Used by the Consultation Flow's gap-fill
        loop (see orchestrator.py's _missing_requirement_fields()) to decide
        WHICH attribute to ask about next, never by response_formatter/
        response_planner directly."""
        schema = self.requirement_schema if isinstance(self.requirement_schema, dict) else {}
        group_key = self._requirement_group_for(category)
        bucket = schema.get(group_key) if group_key else None
        if not bucket:
            bucket = schema.get("_default") or {}
        entries = sorted(bucket.get("required", []), key=lambda e: e.get("priority", 0))
        return [e["field"] for e in entries if e.get("field")]

    def compare_criteria_for(self, category: Optional[str]) -> List[str]:
        """Ordered comparison criteria (e.g. ["price", "stock", "rating",
        "sold_count"]) for whichever compare_rule.json group `category`
        resolves to - same group resolution as requirement_schema_for(),
        falling back to "_default". Used by compare_builder.build()."""
        rules = self.compare_rule if isinstance(self.compare_rule, dict) else {}
        group_key = self._requirement_group_for(category)
        criteria = rules.get(group_key) if group_key else None
        return list(criteria or rules.get("_default") or [])

    def guide_rule_for(self, category: Optional[str]) -> Optional[Any]:
        """(group_key, rule_dict) for whichever guide_rule.json group
        `category` resolves to - same group resolution as
        requirement_schema_for()/compare_criteria_for(). Returns None (no
        "_default" fallback) when the group has no dedicated scoring rule -
        callers must treat that as "can't score this category", not "score
        it generically". Used by app/chat/recommendation_builder.py."""
        rules = self.guide_rule if isinstance(self.guide_rule, dict) else {}
        group_key = self._requirement_group_for(category)
        if not group_key or group_key not in rules:
            return None
        return group_key, rules[group_key]

    def education_domain_for(self, text: Optional[str]) -> Optional[str]:
        """Resolves free text (normally context.query_q - the actual buying
        need, e.g. "laptop", "thuốc say xe") to an education_domains.json
        domain key via plain keyword containment - deliberately independent
        of find_category()/the catalog taxonomy (see education_rule's own
        note on why). v0 scope: first matching domain wins; a query matching
        no domain's keywords returns None, and callers must treat that as
        "no Education content available", never fall back to a category-based
        guess."""
        if not text:
            return None
        domains = self.education_domains if isinstance(self.education_domains, dict) else {}
        lowered = text.lower()
        for domain, keywords in domains.items():
            if any(keyword in lowered for keyword in keywords):
                return domain
        return None

    def education_rule_for(self, domain: Optional[str]) -> Optional[Dict[str, Any]]:
        """{"choices": [{"group","desc"}]} for `domain` (see
        education_domain_for()), or None when there's no authored content for
        it yet - callers must skip Education entirely rather than invent
        generic filler. Used by orchestrator.py's Consultation Flow to decide
        WHAT to show before its first gap-fill question."""
        rules = self.education_rule if isinstance(self.education_rule, dict) else {}
        if not domain or domain not in rules:
            return None
        return rules[domain]

    def category_display_name(self, category: Optional[str]) -> Optional[str]:
        """Human-readable Vietnamese category name for `category`, whether
        it's already a slug (deterministic parser path - see
        entity_extractor.py's entities["category"] = cat_info["slug"]) or
        free text (AI parser path). Anywhere a category is the last-resort
        fallback for a user-facing {term} (clarifying questions, Market
        Education), reading context.category directly risks leaking a raw
        slug straight into the reply - confirmed live: "Bạn dùng
        suc-khoe-sac-dep cho loại da..." on the deterministic parser path,
        where category is never anything BUT a slug. Falls back to the input
        unchanged if it doesn't resolve to a known category at all (already
        whatever text the AI parser guessed, safe to show as-is)."""
        if not category:
            return None
        cat_info = self.find_category(category)
        if not cat_info:
            return category
        for cat_name, cat_data in self.categories.items():
            if cat_data.get("id") == cat_info["id"]:
                return cat_name
        return category

    def clarifying_questions_for_field(self, category: Optional[str], field: str) -> List[str]:
        """Question templates for ONE specific requirement attribute (e.g.
        "budget", "family_size") - clarifying_questions.json is flat/attribute-
        keyed (shared across every category that needs that attribute), so
        `category` isn't actually needed for the lookup itself; kept in the
        signature for symmetry with requirement_schema_for() and in case a
        future category-specific override is ever needed. Caller does
        random.choice() over the result, matching every other call site's
        existing convention (see orchestrator.py)."""
        cq = self.clarifying_questions if isinstance(self.clarifying_questions, dict) else {}
        return list(cq.get(field, []))

    def clarifying_questions_for(self, category: Optional[str]) -> List[str]:
        """Every clarifying-question template that fits `category` - i.e. the
        templates for every attribute in its requirement schema, plus
        "budget" always (every category can be asked about price). Re-
        resolves via requirement_schema_for()/find_category() the same way
        subcategories_for() does, so it works whether `category` is a slug
        (deterministic parser path) or free text (AI parser path). Used by
        response_formatter's broad-query nudge and response_planner's
        too-vague-to-show check - callers that just want SOME reasonable
        narrowing question, not a specific attribute (see
        clarifying_questions_for_field() for that)."""
        fields = set(self.requirement_schema_for(category)) | {"budget"}
        cq = self.clarifying_questions if isinstance(self.clarifying_questions, dict) else {}
        templates = []
        for field in fields:
            templates += cq.get(field, [])
        return templates

    def subcategory_id_for(self, category: str, subcategory_name: str) -> Optional[int]:
        """Numeric subcategory_id (cấp 2) for a specific subcategory name
        within `category` - e.g. 595 for "máy ảnh - máy quay - phụ kiện"
        under "máy tính-máy ảnh máy quay". Needed because /products/search
        has no subcategory_id param at all (only category_id) - only the
        /products LIST endpoint supports it (see api-docs/product_api.md) -
        so subcategory-level filtering only works via search_engine's
        no-query-text browse path, never via a text search."""
        cat_info = self.find_category(category)
        if not cat_info:
            return None
        for cat_name, cat_data in self.categories.items():
            if cat_data.get("id") == cat_info["id"]:
                return cat_data.get("subcategories", {}).get(subcategory_name)
        return None

    def top_level_category_names(self) -> List[str]:
        """All top-level category display names - used for the deterministic
        out-of-scope fallback (a query whose category never resolved at all,
        e.g. asking for jobs or restaurants, isn't a bad keyword within a
        real category, it's outside the catalog entirely)."""
        return list(self.categories.keys())

    def is_accessory(self, product_name: str, category: Optional[str]) -> bool:
        """True if product_name looks like an accessory (case/charger/screen
        protector/...) while the user is searching within a main-device
        category (laptop/phone/etc) - used to penalize accessories cluttering
        a main-device search."""
        if not category:
            return False
        device_categories = self.accessory_rules.get("device_categories", [])
        accessory_keywords = self.accessory_rules.get("accessory_keywords", [])
        name_lower = product_name.lower()
        # category can be a Vietnamese display name ("điện thoại") or an ASCII
        # slug ("dien-thoai-tablet") depending which parse path produced it -
        # ASCII-fold both sides (and de-hyphenate) so either form matches the
        # same device_categories entries.
        category_folded = _strip_diacritics(category.lower()).replace("-", " ")
        if not any(_strip_diacritics(dc) in category_folded for dc in device_categories):
            return False
        return any(ak in name_lower for ak in accessory_keywords)

ontology = Ontology()
