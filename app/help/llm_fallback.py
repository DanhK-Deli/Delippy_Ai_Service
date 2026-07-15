import json
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from app.client.llm_client import load_prompt_template, log_usage
from app.core.llm import llm_provider
from app.database.conversation_repository import cosine_similarity
from app.database.mongodb import get_db
from app.help.rule_engine import RuleEngineResult
from app.knowledge.help.loader import help_knowledge

# Hardcoded until the business fills in real per-Knowledge-Object values -
# every KO's confidence_threshold is currently the literal string "TODO"
# (see the approved plan §3). Prefer the JSON value the moment it's a real
# number instead of that placeholder.
_CONFIDENCE_DEFAULT = 0.6

_PARSE_CACHE_TTL_DAYS = 14
_PARSE_CACHE_MIN_SIMILARITY = 0.92


class HelpParseResult(BaseModel):
    intent: str
    entities: Dict[str, str] = Field(default_factory=dict)
    confidence: float = 0.0


class HelpParseCacheRepository:
    """A dedicated cache, NOT a reused ParseCacheRepository instance as the
    plan originally sketched: app/database/parse_cache_repository.py's own
    store() silently no-ops unless parse.get("query_q") is truthy (a
    /chat-specific product-search gate - confirmed by reading it, not
    assumed) - a HelpParseResult has no such field, so reusing that class
    verbatim would look like it caches but never actually persist anything.
    Same shape/TTL/similarity-floor otherwise, own "help_parse_cache"
    collection so it can never collide with chat's cache."""

    def __init__(self, collection_name: str = "help_parse_cache"):
        self.collection_name = collection_name

    async def store(self, message: str, embedding: List[float], parse: Dict[str, Any]) -> None:
        if not embedding or not parse:
            return
        db = await get_db()
        now = datetime.utcnow()
        await db[self.collection_name].insert_one({
            "message": message,
            "embedding": embedding,
            "parse": parse,
            "created_at": now,
            "expires_at": now + timedelta(days=_PARSE_CACHE_TTL_DAYS),
        })

    async def lookup(self, embedding: List[float]) -> Optional[Dict[str, Any]]:
        if not embedding:
            return None
        db = await get_db()
        now = datetime.utcnow()
        best: Optional[tuple] = None
        cursor = db[self.collection_name].find({"expires_at": {"$gt": now}})
        async for doc in cursor:
            emb = doc.get("embedding")
            sim = cosine_similarity(embedding, emb) if emb else 0.0
            if best is None or sim > best[0]:
                best = (sim, doc)
        if best and best[0] >= _PARSE_CACHE_MIN_SIMILARITY:
            return best[1].get("parse")
        return None


help_parse_cache = HelpParseCacheRepository()


def _confidence_threshold_for(ko: Optional[Dict[str, Any]]) -> float:
    if ko:
        value = ko.get("confidence_threshold")
        if isinstance(value, (int, float)):
            return float(value)
    return _CONFIDENCE_DEFAULT


def _format_history(history: List[Dict[str, str]], limit: int = 2) -> str:
    recent = history[-limit:] if history else []
    lines = [f"{turn.get('role', '?')}: {turn.get('content', '')}" for turn in recent]
    return "\n".join(lines) if lines else "(không có)"


def _shortlist_json(shortlist: List[Dict[str, Any]]) -> str:
    compact = [
        {"id": c["id"], "description": c.get("description"), "sample_questions": c.get("sample_questions", [])}
        for c in shortlist
    ]
    return json.dumps(compact, ensure_ascii=False)


async def classify_ambiguous(
    message: str,
    history: List[Dict[str, str]],
    shortlist: List[Dict[str, Any]],
    prior_entities: Optional[Dict[str, Any]] = None,
) -> RuleEngineResult:
    """Single cheap-tier call, only invoked when rule_engine.classify()
    returns resolved=False - see the approved plan §3. The prompt only ever
    lists the tied shortlist rule_engine already computed (2-8 items), never
    all 63 Knowledge Objects - what keeps this token-critical path small.
    Still returns a RuleEngineResult (resolved=False + the same/refined
    shortlist) when the model itself can't confidently pick one, so the
    orchestrator's next step is always the same: AWAITING_CLARIFICATION."""
    prior_entities = prior_entities or {}
    if not shortlist:
        return RuleEngineResult(resolved=False, entities=prior_entities, shortlist=[])

    by_id = {c["id"]: c for c in shortlist}

    embedding: List[float] = []
    if llm_provider.is_available():
        try:
            embedding = llm_provider.embed(message, task_type="RETRIEVAL_QUERY")
        except Exception:
            embedding = []
        if embedding:
            cached = await help_parse_cache.lookup(embedding)
            if cached and cached.get("intent") in by_id:
                ko = help_knowledge.get_knowledge_object(by_id[cached["intent"]]["domain_attr"], by_id[cached["intent"]]["intent"])
                threshold = _confidence_threshold_for(ko)
                if float(cached.get("confidence", 0.0)) >= threshold:
                    entities = {**prior_entities, **(cached.get("entities") or {})}
                    candidate = by_id[cached["intent"]]
                    return RuleEngineResult(
                        resolved=True, ko_id=candidate["id"], domain_attr=candidate["domain_attr"],
                        intent=candidate["intent"], entities=entities, confidence=float(cached.get("confidence", 0.0)),
                    )

    if not llm_provider.is_available():
        # No LLM reachable - degrade to asking the user to pick from the
        # shortlist directly rather than guessing.
        return RuleEngineResult(resolved=False, entities=prior_entities, shortlist=shortlist)

    template = load_prompt_template("help_parser_prompt.txt")
    prompt = template.format(
        history=_format_history(history), shortlist_json=_shortlist_json(shortlist), message=message
    )

    try:
        result = await llm_provider.generate_structured(prompt=prompt, response_schema=HelpParseResult, model_tier="cheap")
        log_usage("Help Intent Fallback", result.prompt_tokens, result.completion_tokens)
        parsed = result.value
    except Exception:
        return RuleEngineResult(resolved=False, entities=prior_entities, shortlist=shortlist)

    if parsed.intent == "UNRESOLVED" or parsed.intent not in by_id:
        return RuleEngineResult(resolved=False, entities=prior_entities, shortlist=shortlist)

    candidate = by_id[parsed.intent]
    ko = help_knowledge.get_knowledge_object(candidate["domain_attr"], candidate["intent"])
    threshold = _confidence_threshold_for(ko)
    entities = {**prior_entities, **parsed.entities}

    if parsed.confidence < threshold:
        return RuleEngineResult(resolved=False, entities=entities, shortlist=shortlist)

    if embedding:
        await help_parse_cache.store(
            message, embedding, {"intent": parsed.intent, "entities": parsed.entities, "confidence": parsed.confidence}
        )

    return RuleEngineResult(
        resolved=True, ko_id=candidate["id"], domain_attr=candidate["domain_attr"], intent=candidate["intent"],
        entities=entities, confidence=parsed.confidence,
    )
