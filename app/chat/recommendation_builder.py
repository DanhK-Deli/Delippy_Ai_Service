from typing import Any, Dict, List, Optional
from app.knowledge.ontology import ontology
from app.chat.spec_extractor import spec_extractor
from app.client.llm_client import llm_client_wrapper

_STAR_MAX = 5

# Tier B (long-tail AI Scorer) cost bound - matches response_formatter's own
# "only the first 5 are ever shown" convention, so nothing is scored (and
# paid for) beyond what actually gets rendered this turn.
_AI_SCORER_MAX_PRODUCTS = 5

# Requirement Resolver-style keyword buckets (regex/dictionary, no AI) for
# resolving context.purpose free text into a guide_rule.json "purpose" bucket
# key - same v0 scope as orchestrator.py's _normalize_numeric, covering only
# the buckets guide_rule.json actually defines this sprint.
_PURPOSE_BUCKET_KEYWORDS = {
    "coding": ["lập trình", "lap trinh", "code", "coding", "dev"],
    "office": ["văn phòng", "van phong", "học tập", "hoc tap", "office"],
    "gaming": ["gaming", "game", "chơi game", "choi game", "chiến game", "chien game"],
}

# Weight for the budget pseudo-spec (see _score_product) - not part of
# guide_rule.json since price/price_max are already real, reliable fields
# (no spec_extractor guesswork needed), but scored alongside the rest so
# "trong ngân sách" carries comparable influence to a spec like RAM.
_BUDGET_WEIGHT = 3

_SPEC_DISPLAY = {
    "ram": lambda v: f"RAM {v}GB",
    "ssd": lambda v: f"SSD {v}GB",
    "capacity": lambda v: f"Dung tích {v}kg",
    "weight_kg": lambda v: f"Trọng lượng {v}kg",
}

# Human labels for trade-off phrasing (see _build_trade_off) - the only
# place spec_name ever needs to read as a noun phrase instead of a full
# sentence fragment.
_SPEC_TRADE_OFF_LABEL = {
    "ram": "RAM",
    "ssd": "ổ cứng",
    "gpu": "card đồ họa",
    "weight_kg": "độ gọn nhẹ",
    "capacity": "dung tích",
    "inverter": "tiết kiệm điện",
    "budget": "ngân sách",
}

# Keywords for recognizing when a free-text "tại sao"-style question is
# asking about ONE OF the specs guide_rule.json already has an "education"
# text for (see match_spec_education) - so that question can be answered at
# 0 tokens instead of always falling back to an LLM call. v0/keyword-only,
# same philosophy as _PURPOSE_BUCKET_KEYWORDS.
_SPEC_MENTION_KEYWORDS = {
    "ram": ["ram"],
    "ssd": ["ssd", "ổ cứng", "o cung"],
    "gpu": ["gpu", "card đồ họa", "card do hoa", "vga"],
    "weight_kg": ["trọng lượng", "trong luong", "cân nặng", "can nang", "nhẹ", "nhe"],
    "capacity": ["dung tích", "dung tich"],
    "inverter": ["inverter"],
}

class RecommendationBuilder:
    """Hybrid Recommendation Engine, two tiers over the SAME output shape
    (`suitability_score` 1-5 + `recommend_reasons` [{status,text}]) so
    response_formatter's ⭐/✓/⚠ rendering never needs to know which tier
    produced it:

    Tier A (core categories - laptop, washing machine...): deterministic,
    zero-LLM. Reads app/knowledge/guide_rule.json thresholds+weights for
    whichever requirement (purpose, family_size...) the Consultation Flow
    already resolved (see requirement_schema.json), extracts the matching
    spec attributes from each candidate via spec_extractor, and produces a
    WEIGHTED score plus reasoning bullets with a real consequence (not just
    "chưa đạt chuẩn X"). Also flags a trade-off between the top 2 candidates
    when they win on different specs.

    Tier B (long-tail - everything else): a category with NO guide_rule.json
    entry would otherwise get NO suitability info at all (a marketplace has
    thousands of categories; hand-authoring Tier A rules for every one of
    them isn't tractable). Falls back to ONE cheap structured-output LLM
    call (see llm_client.score_products_ai) that reads the raw product name/
    description text directly and scores+reasons the same shape Tier A
    produces - auto-scaling the ⭐/✓/⚠ consult experience to any category
    without a line of new rule code, at the cost of one real LLM call
    instead of $0. Scores only the first _AI_SCORER_MAX_PRODUCTS candidates
    (cost-bounded, matches what's actually shown) - any further pagination
    candidates stay unscored, appended after.
    """

    async def build(
        self,
        products: List[Dict[str, Any]],
        category: Optional[str],
        requirement_answers: Dict[str, Any],
        purpose: Optional[str],
        price_min: Optional[int] = None,
        price_max: Optional[int] = None,
    ) -> Optional[List[Dict[str, Any]]]:
        if not products:
            return None
        resolved = self.resolve_bucket_for(category, requirement_answers, purpose)
        if resolved:
            group_key, _bucket_key, bucket = resolved
            scored = [self._score_product(p, group_key, bucket, price_max) for p in products]
            scored.sort(key=lambda item: item["suitability_score"], reverse=True)

            trade_off = self._build_trade_off(scored)
            if trade_off:
                scored[0]["trade_off_summary"] = trade_off
            return scored

        return await self._ai_score(products, requirement_answers, purpose, price_min, price_max)

    async def _ai_score(
        self,
        products: List[Dict[str, Any]],
        requirement_answers: Dict[str, Any],
        purpose: Optional[str],
        price_min: Optional[int],
        price_max: Optional[int],
    ) -> Optional[List[Dict[str, Any]]]:
        candidates = products[:_AI_SCORER_MAX_PRODUCTS]
        need_text = self._describe_need(requirement_answers, purpose, price_min, price_max)
        scored_items = await llm_client_wrapper.score_products_ai(need_text, candidates)
        if not scored_items:
            return None

        by_key = {item["slug"]: item for item in scored_items}
        merged = []
        for p in candidates:
            key = p.get("slug") or p.get("name")
            match = by_key.get(key)
            item = dict(p)
            if match:
                item["suitability_score"] = max(1, min(_STAR_MAX, match["suitability_score"]))
                item["recommend_reasons"] = match["recommend_reasons"]
            else:
                # The LLM dropped this product from its response (shouldn't
                # happen per the prompt's own "don't skip any" rule, but a
                # partial/malformed response must never crash the turn) - a
                # neutral middle score, no fabricated reasons.
                item["suitability_score"] = 3
                item["recommend_reasons"] = []
            merged.append(item)
        merged.sort(key=lambda it: it["suitability_score"], reverse=True)

        # Anything beyond the scored top N (kept for "xem thêm" pagination)
        # stays unscored/unsorted, appended after - same "don't touch what
        # wasn't shown" boundary as the cost cap itself.
        remaining = [dict(p) for p in products[len(candidates):]]
        return merged + remaining

    def _describe_need(
        self, requirement_answers: Dict[str, Any], purpose: Optional[str],
        price_min: Optional[int], price_max: Optional[int],
    ) -> str:
        parts = []
        if purpose:
            parts.append(f"Mục đích/nhu cầu: {purpose}")
        for field, entry in (requirement_answers or {}).items():
            if field == "purpose" or entry == "__skipped__":
                continue
            value = entry.get("value") if isinstance(entry, dict) else entry
            if value:
                parts.append(f"{field}: {value}")
        if price_max is not None:
            parts.append(f"Ngân sách tối đa: {price_max:,.0f}đ")
        if price_min is not None:
            parts.append(f"Ngân sách tối thiểu: {price_min:,.0f}đ")
        return "; ".join(parts) if parts else "Chưa nêu yêu cầu cụ thể - tư vấn dựa trên đánh giá/giá bán chung."

    def _score_product(
        self, product: Dict[str, Any], group_key: str, bucket: Dict[str, Any], price_max: Optional[int],
    ) -> Dict[str, Any]:
        text = f"{product.get('name') or ''} {product.get('details') or ''}"
        specs = spec_extractor.extract(group_key, text)

        reasons = []
        weighted_hits = 0.0
        total_weight = 0.0

        price = product.get("price")
        if price_max is not None and price is not None:
            weight = _BUDGET_WEIGHT
            total_weight += weight
            if price <= price_max:
                weighted_hits += weight
                reasons.append({"spec": "budget", "status": "success", "text": "Đúng ngân sách bạn đưa ra"})
            else:
                over = price - price_max
                reasons.append({
                    "spec": "budget", "status": "warning",
                    "text": f"Giá vượt ngân sách bạn đưa ra khoảng {over:,.0f}đ",
                })

        for spec_name, condition in bucket.items():
            value = specs.get(spec_name)
            if value is None:
                continue
            weight = condition.get("weight", 1)
            total_weight += weight
            ok = self._meets(value, condition)
            # Numeric conditions (min/max) get "<spec value> <label>" (e.g.
            # "RAM 16GB đủ lập trình mượt mà") - the number IS the evidence.
            # Boolean conditions (gpu/inverter - see _meets) have no
            # meaningful "value" to show, so their label/warning is already
            # a complete sentence (see guide_rule.json's own phrasing).
            is_numeric = "min" in condition or "max" in condition
            if ok:
                weighted_hits += weight
                label = condition.get("label", spec_name)
                text = f"{self._spec_display(spec_name, value)} {label}" if is_numeric else label
                reasons.append({"spec": spec_name, "status": "success", "text": text})
            else:
                warning_template = condition.get("warning")
                if warning_template:
                    warning_text = warning_template.format(value=value)
                else:
                    label = condition.get("label", spec_name)
                    warning_text = f"{self._spec_display(spec_name, value)} (chưa đạt chuẩn {label})" if is_numeric else f"Chưa đạt: {label}"
                reasons.append({"spec": spec_name, "status": "warning", "text": warning_text})

        # No spec (or budget) could be evaluated at all - a neutral middle
        # score, not a penalty for missing data.
        score = round((weighted_hits / total_weight) * _STAR_MAX) if total_weight else 3
        score = max(1, min(_STAR_MAX, score))

        item = dict(product)
        item["suitability_score"] = score
        item["recommend_reasons"] = reasons
        return item

    def _build_trade_off(self, scored: List[Dict[str, Any]]) -> Optional[str]:
        """A real trade-off note between the top 2 candidates - only when the
        runner-up actually WINS on some spec the leader lost on (not always;
        a leader that wins outright has nothing to trade off). Deterministic
        and template-based - the alternative to a bare star ranking that
        hides the fact two products can suit two different priorities."""
        if len(scored) < 2:
            return None
        top, second = scored[0], scored[1]
        if second["suitability_score"] > top["suitability_score"]:
            top, second = second, top  # shouldn't happen given the sort, but keep the note's "top" honest

        top_status = {r["spec"]: r["status"] for r in top.get("recommend_reasons", [])}
        second_status = {r["spec"]: r["status"] for r in second.get("recommend_reasons", [])}
        second_wins = [
            spec for spec, status in second_status.items()
            if status == "success" and top_status.get(spec) == "warning"
        ]
        if not second_wins:
            return None

        labels = ", ".join(_SPEC_TRADE_OFF_LABEL.get(s, s) for s in second_wins)
        return (
            f"Nếu ưu tiên {labels} thì **{second.get('name')}** đáng cân nhắc hơn, "
            f"còn **{top.get('name')}** vẫn là lựa chọn cân bằng nhất trong nhóm này."
        )

    def resolve_bucket_for(
        self, category: Optional[str], requirement_answers: Dict[str, Any], purpose: Optional[str],
    ) -> Optional[tuple]:
        """(group_key, bucket_key, bucket_dict) for whichever guide_rule.json
        bucket the already-resolved requirement (purpose/family_size/...)
        maps to, or None. Public entry point for callers that need to know
        WHICH bucket applies without running the full scoring pipeline - see
        orchestrator.py's Bucket Education (shows guide_rule.json's own
        "education" text once a bucket is known, before the flow's next
        gap-fill question) and its 0-token tech-explain short-circuit
        (match_spec_education)."""
        resolved = ontology.guide_rule_for(category)
        if not resolved:
            return None
        group_key, rule = resolved

        # guide_rule.json's group is keyed by exactly ONE requirement field
        # this sprint ("purpose" for tech, "family_size" for appliance) - a
        # future sprint adding a second scored field per group would need a
        # real priority rule here, not just "first one wins".
        field_name, buckets = next(iter(rule.items()), (None, None))
        if not field_name or not buckets:
            return None

        bucket_key, bucket = self._resolve_bucket(field_name, buckets, requirement_answers, purpose)
        if not bucket:
            return None
        return group_key, bucket_key, bucket

    def bucket_education_text(self, bucket: Dict[str, Any]) -> Optional[str]:
        """Concatenates every spec's "education" sentence in `bucket` (see
        guide_rule.json) into one 0-token explainer - the deterministic
        counterpart to recommend_reasons' short "✓ RAM 16GB đủ lập trình"
        bullets, meant to actually teach WHY those specs matter. None when
        the bucket has no education text authored yet."""
        lines = [condition["education"] for condition in bucket.values() if condition.get("education")]
        if not lines:
            return None
        return " ".join(lines)

    def match_spec_education(self, message: str, bucket: Dict[str, Any]) -> Optional[str]:
        """0-token short-circuit for an explicit "tại sao"-style question
        (see intent_classifier.is_tech_explain_query): if `message` mentions
        a spec `bucket` already has authored "education" text for (e.g.
        "ram", "inverter"), return that text directly - no LLM call needed.
        None when nothing in `bucket` matches, so the caller falls back to
        the LLM explainer instead (see llm_client.format_tech_explain_response)."""
        text = (message or "").lower()
        for spec_name, condition in bucket.items():
            if not condition.get("education"):
                continue
            keywords = _SPEC_MENTION_KEYWORDS.get(spec_name, [spec_name])
            if any(keyword in text for keyword in keywords):
                return condition["education"]
        return None

    def _resolve_bucket(
        self, field_name: str, buckets: Dict[str, Any],
        requirement_answers: Dict[str, Any], purpose: Optional[str],
    ) -> tuple:
        if field_name == "purpose":
            entry = requirement_answers.get("purpose")
            answer_text = entry.get("value") if isinstance(entry, dict) else entry
            text = (purpose or answer_text or "").lower()
            if not text:
                return None, None
            for bucket_key in buckets:
                keywords = _PURPOSE_BUCKET_KEYWORDS.get(bucket_key, [bucket_key])
                if any(keyword in text for keyword in keywords):
                    return bucket_key, buckets[bucket_key]
            return None, None

        # Numeric requirement fields (e.g. "family_size") - nearest bucket by
        # absolute distance, since real answers don't fall neatly onto the
        # exact sample sizes in guide_rule.json ("1"/"2"/"4").
        entry = requirement_answers.get(field_name)
        normalized = entry.get("normalized") if isinstance(entry, dict) else None
        if normalized is None:
            return None, None
        best_key = min(buckets, key=lambda key: abs(int(key) - normalized))
        return best_key, buckets[best_key]

    def _meets(self, value: Any, condition: Dict[str, Any]) -> bool:
        if "min" in condition or "max" in condition:
            if "min" in condition and value < condition["min"]:
                return False
            if "max" in condition and value > condition["max"]:
                return False
            return True
        # No min/max - a presence/boolean condition (e.g. gpu, inverter).
        return bool(value)

    def _spec_display(self, spec_name: str, value: Any) -> str:
        formatter = _SPEC_DISPLAY.get(spec_name)
        return formatter(value) if formatter else f"{spec_name} {value}"

recommendation_builder = RecommendationBuilder()
