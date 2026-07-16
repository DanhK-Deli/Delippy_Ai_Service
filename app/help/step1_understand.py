import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from app.client.llm_client import load_prompt_template, log_usage
from app.core.llm import llm_provider
from app.knowledge.help.loader import help_knowledge

_CASES = {"GENERAL", "ORDER", "PROMOTION", "ACCOUNT", "APP_ISSUE", "OUT_OF_SCOPE"}
_EMOTIONS = {"NEUTRAL", "FRUSTRATED", "ANGRY", "CONFUSED", "HAPPY"}
_DEFAULT_CONFIDENCE_THRESHOLD = 0.6


class Step1LLMResult(BaseModel):
    case: str = "OUT_OF_SCOPE"
    business_objects_needed: List[str] = Field(default_factory=list)
    confidence: float = 0.0
    emotion: str = "NEUTRAL"
    entities: Dict[str, str] = Field(default_factory=dict)
    alternative_candidates: List[str] = Field(default_factory=list)


@dataclass
class Step1Understanding:
    """Validated output of Step 1 - never trusts the raw LLM result as-is,
    same discipline v1's llm_fallback.classify_ambiguous applied to a single
    intent id, now applied to a whole list of business_objects_needed (the
    'Case -> Business Object -> Document' design's closed vocabulary, see
    business_objects.json's own docstring)."""

    case: str
    business_objects_needed: List[str] = field(default_factory=list)
    confidence: float = 0.0
    emotion: str = "NEUTRAL"
    entities: Dict[str, Any] = field(default_factory=dict)
    alternative_candidates: List[str] = field(default_factory=list)
    resolved: bool = False  # False -> orchestrator must enter CLARIFYING, never guess


def _format_history(history: List[Dict[str, str]], limit: int = 6) -> str:
    recent = history[-limit:] if history else []
    lines = [f"{turn.get('role', '?')}: {turn.get('content', '')}" for turn in recent]
    return "\n".join(lines) if lines else "(không có)"


def _registry_json() -> str:
    compact = [
        {"id": bo["id"], "case": bo["case"], "description": bo.get("description")}
        for bo in help_knowledge.all_business_objects()
    ]
    return json.dumps(compact, ensure_ascii=False)


def _confidence_threshold_for(bo_id: str) -> float:
    bo = help_knowledge.get_business_object(bo_id)
    value = (bo or {}).get("confidence_threshold")
    return float(value) if isinstance(value, (int, float)) else _DEFAULT_CONFIDENCE_THRESHOLD


def _validate(raw: Step1LLMResult) -> Step1Understanding:
    case = raw.case if raw.case in _CASES else "OUT_OF_SCOPE"
    emotion = raw.emotion if raw.emotion in _EMOTIONS else "NEUTRAL"

    # A business_objects_needed id is only usable if it's a REAL registry id
    # AND declares the same case the model itself chose - anything else is
    # dropped rather than trusted, mirroring how classify_ambiguous() treats
    # an intent not in `by_id` as unresolved instead of guessing.
    valid_ids: List[str] = []
    for bo_id in raw.business_objects_needed:
        bo = help_knowledge.get_business_object(bo_id)
        if bo and bo.get("case") == case:
            valid_ids.append(bo_id)

    alt_valid = [bo_id for bo_id in raw.alternative_candidates if help_knowledge.get_business_object(bo_id)]

    confidence = max(0.0, min(1.0, raw.confidence))
    threshold = min((_confidence_threshold_for(bo_id) for bo_id in valid_ids), default=_DEFAULT_CONFIDENCE_THRESHOLD)
    resolved = bool(valid_ids) and case not in ("OUT_OF_SCOPE",) and confidence >= threshold

    return Step1Understanding(
        case=case,
        business_objects_needed=valid_ids,
        confidence=confidence,
        emotion=emotion,
        entities=dict(raw.entities or {}),
        alternative_candidates=alt_valid,
        resolved=resolved,
    )


async def understand(
    message: str,
    history: List[Dict[str, str]],
    *,
    active_business_object: Optional[Dict[str, str]] = None,
) -> Step1Understanding:
    """Step 1 (LLM #1) - see the agreed AI Customer Care v2 plan §6. Exactly
    one LLM call; never renders customer-facing text itself."""
    if not llm_provider.is_available():
        return Step1Understanding(case="OUT_OF_SCOPE", resolved=False)

    template = load_prompt_template("help_step1_understand_prompt.txt")
    prompt = template.format(
        active_business_object=json.dumps(active_business_object, ensure_ascii=False) if active_business_object else "(không có)",
        history=_format_history(history),
        registry_json=_registry_json(),
        message=message,
    )
    try:
        result = await llm_provider.generate_structured(prompt=prompt, response_schema=Step1LLMResult, model_tier="cheap")
        log_usage("Help Step1 Understand", result.prompt_tokens, result.completion_tokens)
        return _validate(result.value)
    except Exception as e:
        print(f"\n[{llm_provider.name} - Error in Help Step1 Understand] {e}.\n")
        return Step1Understanding(case="OUT_OF_SCOPE", resolved=False)
