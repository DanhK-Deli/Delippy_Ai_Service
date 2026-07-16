from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from app.client.llm_client import load_prompt_template, log_usage
from app.core.llm import llm_provider
from app.help import fact_manifest, grounding
from app.help.fact_manifest import Fact


class Step3Claim(BaseModel):
    text: str
    fact_id: str


class Step3LLMResult(BaseModel):
    answer: str
    claims: List[Step3Claim] = Field(default_factory=list)


@dataclass
class Step3Response:
    answer: str
    grounded: bool
    warnings: List[str] = field(default_factory=list)


def _format_history(history: List[Dict[str, str]], limit: int = 6) -> str:
    recent = history[-limit:] if history else []
    lines = [f"{turn.get('role', '?')}: {turn.get('content', '')}" for turn in recent]
    return "\n".join(lines) if lines else "(không có)"


async def _call_llm(message: str, history: List[Dict[str, str]], facts: List[Fact], emotion: str) -> Optional[Step3LLMResult]:
    if not llm_provider.is_available():
        return None
    template = load_prompt_template("help_step3_respond_prompt.txt")
    prompt = template.format(
        emotion=emotion,
        facts_json=fact_manifest.to_json(facts),
        history=_format_history(history),
        message=message,
    )
    try:
        result = await llm_provider.generate_structured(prompt=prompt, response_schema=Step3LLMResult, model_tier="cheap")
        log_usage("Help Step3 Respond", result.prompt_tokens, result.completion_tokens)
        return result.value
    except Exception as e:
        print(f"\n[{llm_provider.name} - Error in Help Step3 Respond] {e}.\n")
        return None


async def respond(message: str, history: List[Dict[str, str]], facts: List[Fact], emotion: str) -> Step3Response:
    """Step 3 (LLM #2) + grounding verifier (plan §A). One retry with an
    explicit correction note on the first grounding failure; if the retry
    also fails to ground, the caller (orchestrator) must escalate rather
    than show unverified text - see grounding.py's own docstring on why this
    isn't just a prompt instruction."""
    llm_result = await _call_llm(message, history, facts, emotion)
    if llm_result is None:
        return Step3Response(answer="", grounded=False, warnings=["step3 llm unavailable or failed"])

    claims = [c.model_dump() for c in llm_result.claims]
    check = grounding.verify(llm_result.answer, claims, facts)
    if check.ok:
        return Step3Response(answer=llm_result.answer, grounded=True)

    correction_note = (
        "\n\n(Câu trả lời trước của bạn vi phạm quy tắc grounding: "
        + "; ".join(check.violations)
        + ". Hãy trả lời lại CHỈ dựa trên facts đã cho, bỏ hẳn phần thông tin không có nguồn.)"
    )
    retry_result = await _call_llm(message + correction_note, history, facts, emotion)
    if retry_result is not None:
        retry_claims = [c.model_dump() for c in retry_result.claims]
        retry_check = grounding.verify(retry_result.answer, retry_claims, facts)
        if retry_check.ok:
            return Step3Response(answer=retry_result.answer, grounded=True)
        return Step3Response(answer="", grounded=False, warnings=retry_check.violations)

    return Step3Response(answer="", grounded=False, warnings=check.violations)
