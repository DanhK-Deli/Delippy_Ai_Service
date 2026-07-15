import time
from typing import Optional

from app.client.llm_client import request_tokens
from app.help import llm_fallback, rule_engine
from app.help import state as help_state
from app.help.flow_executor import execute as execute_flow
from app.help.session import help_session_manager
from app.help.templates import render_or_fallback
from app.knowledge.help.loader import help_knowledge
from app.models.help import HelpResponse



def _clarification_prompt(shortlist) -> str:
    options = "\n".join(f"{i + 1}. {c.get('description') or c['id']}" for i, c in enumerate(shortlist))
    return f"Bạn đang muốn hỏi về điều nào dưới đây?\n{options}"


async def process_help_message(
    message: str,
    session_id: Optional[str],
    *,
    token: Optional[str] = None,
    user_id: Optional[str] = None,
) -> HelpResponse:
    """The /help pipeline's single entry point - see the approved plan:
    Rule Engine (0 LLM calls in the common case) -> LLM fallback (exactly 1
    cheap-tier call, only on genuine ambiguity) -> Flow Executor (data-driven
    off the Knowledge Base JSON) -> persisted session state for the next
    turn's slot-filling/clarification."""
    t0 = time.perf_counter()
    request_tokens.set(0)

    help_knowledge.maybe_reload()  # cheap mtime check - picks up any KB edit made since the last turn

    conversation = await help_session_manager.load_session(session_id)
    memory = conversation.memory

    rule_result = rule_engine.classify(message, memory)
    mode = "rule"

    if not rule_result.resolved and rule_result.shortlist:
        rule_result = await llm_fallback.classify_ambiguous(
            message, conversation.history, rule_result.shortlist, rule_result.entities
        )
        mode = "llm_fallback"

    await help_session_manager.add_message(conversation, "user", message)

    if not rule_result.resolved:
        if rule_result.shortlist:
            answer = _clarification_prompt(rule_result.shortlist)
            memory["awaiting"] = help_state.make_awaiting(
                help_state.HelpAwaitAction.AWAITING_CLARIFICATION,
                rule_result.shortlist[0]["id"],
                pending_options=[c["id"] for c in rule_result.shortlist],
                collected_entities=rule_result.entities,
            )
            response = HelpResponse(
                answer=answer, 
                mode="ask_clarification", 
                follow_up_questions=[answer],
                response_time_ms=(time.perf_counter() - t0) * 1000,
                tokens_used=request_tokens.get(),
            )
        else:
            answer = render_or_fallback("RT_ERROR_GENERIC_FALLBACK", {})
            help_state.clear_awaiting(memory)
            response = HelpResponse(
                answer=answer, 
                mode="unresolved",
                response_time_ms=(time.perf_counter() - t0) * 1000,
                tokens_used=request_tokens.get(),
            )
        await help_session_manager.add_message(conversation, "assistant", response.answer)
        await help_session_manager.save_session(conversation)
        return response

    retry_key = f"_retry_{rule_result.ko_id}"
    retry_already_attempted = bool(memory.get(retry_key))

    flow_result = await execute_flow(
        rule_result.domain_attr,
        rule_result.intent,
        rule_result.entities,
        token=token,
        session_id=conversation.session_id,
        user_id=user_id,
        history=conversation.history,
        retry_already_attempted=retry_already_attempted,
    )

    if flow_result.awaiting is not None:
        memory["awaiting"] = flow_result.awaiting
    else:
        help_state.clear_awaiting(memory)
        memory.pop(retry_key, None)

    if not flow_result.escalated and any("failed" in w or "skipped" in w for w in flow_result.warnings):
        memory[retry_key] = True

    await help_session_manager.add_message(conversation, "assistant", flow_result.answer)
    await help_session_manager.save_session(conversation)

    return HelpResponse(
        answer=flow_result.answer,
        intent=rule_result.intent,
        domain=rule_result.domain_attr,
        mode=mode,
        confidence=rule_result.confidence,
        escalated=flow_result.escalated,
        ticket_id=flow_result.ticket_id,
        follow_up_questions=flow_result.follow_up_questions,
        warnings=flow_result.warnings,
        data=flow_result.data or None,
        response_time_ms=(time.perf_counter() - t0) * 1000,
        tokens_used=request_tokens.get(),
    )

