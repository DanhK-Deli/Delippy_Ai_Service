import re
import time
from typing import Any, Dict, List, Optional, Tuple

from app.client.llm_client import request_tokens
from app.help import business_object_executor, entity_regex, fact_manifest, fastpath, step1_understand, step3_respond
from app.help import conversation_state as cs
from app.help.conversation_state import ConversationState
from app.help.errors import ErrorGroup, handle_exception
from app.help.escalation import EscalationAction, escalation_actions_for, help_ticket_repo
from app.help.session import help_session_manager
from app.help.templates import render_or_fallback
from app.knowledge.help.loader import help_knowledge
from app.models.help import HelpResponse

_OUT_OF_SCOPE_TEXT = (
    "Mình xin lỗi, đây là vấn đề nằm ngoài phạm vi mình có thể hỗ trợ trực tiếp qua chat. "
    "Bạn vui lòng liên hệ kênh CSKH khác của Delippy để được hỗ trợ chính xác hơn nhé!"
)

_SYSTEM_FIELDS = {"user_id", "session_id"}


def _finalize_metrics(t0: float, mode: str) -> Tuple[float, int]:
    response_time_ms = (time.perf_counter() - t0) * 1000
    tokens_used = request_tokens.get()
    print(f"[Help v2] mode={mode} response_time_ms={response_time_ms:.0f} tokens_used={tokens_used}")
    return response_time_ms, tokens_used


_MAX_CLARIFICATION_OPTIONS = 6

_CASE_LABELS = {
    "GENERAL": "Thông tin chung / chính sách / công ty Delippy",
    "ORDER": "Đơn hàng của bạn (trạng thái, vận chuyển, huỷ, đổi trả...)",
    "PROMOTION": "Khuyến mãi / voucher",
    "ACCOUNT": "Tài khoản của bạn",
    "APP_ISSUE": "Vấn đề kỹ thuật khi dùng app",
}


def _case_fallback_candidates(case: str) -> List[str]:
    """When Step 1 is confident about the CASE but couldn't pin down a
    specific Business Object (and gave no alternative_candidates itself),
    offer every Business Object registered under that case as the menu -
    this is what actually fixes 'tôi thắc mắc về'/'chính sách của công ty'
    falling into a flat decline: the model already told us GENERAL, we just
    widen to everything GENERAL offers instead of giving up."""
    return [
        bo["id"] for bo in help_knowledge.all_business_objects()
        if bo.get("case") == case and not bo.get("fast_path")
    ][:_MAX_CLARIFICATION_OPTIONS]


def _clarification_prompt(candidate_ids: List[str]) -> str:
    options = []
    for bo_id in candidate_ids[:_MAX_CLARIFICATION_OPTIONS]:
        bo = help_knowledge.get_business_object(bo_id) or {}
        options.append(bo.get("description") or bo_id)
    lines = "\n".join(f"{i + 1}. {desc}" for i, desc in enumerate(options))
    return f"Bạn có thể đang muốn hỏi về:\n{lines}\n\nBạn cho mình biết cụ thể hơn nhé?"


def _match_clarification_choice(message: str, candidate_ids: List[str]) -> Optional[str]:
    m = re.search(r"\d+", message)
    if m:
        idx = int(m.group(0)) - 1
        if 0 <= idx < len(candidate_ids):
            return candidate_ids[idx]
    folded = message.lower()
    for bo_id in candidate_ids:
        bo = help_knowledge.get_business_object(bo_id) or {}
        desc = (bo.get("description") or "").lower()
        if desc and any(word in folded for word in desc.split() if len(word) > 3):
            return bo_id
    return None


# A KO's own follow_up_questions[] is a flat list, NOT positionally aligned
# with required_entities (e.g. RETURN_REQUEST_CREATE's 3 follow-up questions
# cover san_pham/ly_do/hinh_anh in that order but require ma_don_hang too,
# assumed already known from the UI's order-selection context per plan §8) -
# picking follow_up_questions[0] whenever pending_entity merely APPEARED in
# that KO's required_entities asked the wrong question outright (confirmed:
# it would ask "which product?" while still waiting on the order code).
# A direct, deterministic entity -> question map sidesteps that entirely.
_ENTITY_QUESTIONS = {
    "ma_don_hang": "Bạn cho mình xin mã đơn hàng được không ạ?",
    "ma_yeu_cau_doi_tra": "Bạn cho mình xin mã yêu cầu đổi trả nhé?",
    "san_pham_can_doi_tra": "Bạn muốn đổi trả sản phẩm nào trong đơn vậy ạ?",
    "ly_do_doi_tra": "Bạn cho mình biết lý do muốn đổi trả được không?",
    "hinh_anh_minh_chung": "Bạn gửi giúp mình hình ảnh/video sản phẩm nhé?",
    "dia_chi_giao_moi": "Bạn cho mình xin địa chỉ giao hàng mới nhé?",
    "ma_voucher": "Bạn cho mình xin mã voucher được không?",
    "so_dien_thoai_hoac_email": "Bạn dùng số điện thoại hay email để đăng ký tài khoản?",
    "kenh_dang_nhap": "Bạn đang nói đến kênh nào (Google/Facebook/Apple)?",
    "kenh_nghi_ngo_lua_dao": "Bạn nhận được tin nhắn/cuộc gọi nghi ngờ này qua kênh nào?",
    "san_pham": "Bạn cho mình biết tên sản phẩm cần kiểm tra nhé?",
}


def _ask_for_entity(pending_entity: str) -> str:
    if pending_entity in _ENTITY_QUESTIONS:
        return _ENTITY_QUESTIONS[pending_entity]
    return render_or_fallback("RT_ASK_MORE_INFO_GENERIC", {"ten_entity_con_thieu": pending_entity})


_CONFIRMATION_QUESTIONS = {
    # Wording matches the real in-app confirmation dialog exactly - see
    # docs/chatbot-cskh-knowledge-base-design.md ORD-03 - so the chat channel
    # doesn't ask something subtly different from what the app itself says.
    "BO_ORDER_CANCEL": "Bạn có chắc chắn muốn huỷ đơn hàng này không?",
    "BO_ACCOUNT_DELETE_REQUEST": "Bạn có chắc muốn xoá tài khoản không? Sau khi xoá, lịch sử đơn hàng, voucher và ví của bạn sẽ không còn nữa.",
}


def _confirmation_prompt(business_object_ids: List[str]) -> str:
    bo_id = business_object_ids[0] if business_object_ids else None
    if bo_id in _CONFIRMATION_QUESTIONS:
        return _CONFIRMATION_QUESTIONS[bo_id]
    bo = help_knowledge.get_business_object(bo_id) if bo_id else None
    description = (bo or {}).get("description", "yêu cầu này")
    return f"Bạn xác nhận: {description} Bạn đồng ý chứ?"


def _retry_key(business_object_ids: List[str]) -> str:
    return "_retry_" + "-".join(sorted(business_object_ids))


_EMPATHY_PREFIX = {
    "FRUSTRATED": "Mình hiểu bạn đang khó chịu vì việc này. ",
    "ANGRY": "Mình rất xin lỗi vì sự bất tiện này. ",
}


def _with_empathy(answer: str, emotion: str) -> str:
    """The templated ask_entity/confirmation/clarification/not_found replies
    are static text with no LLM call, so Principle 4 (acknowledge the
    customer's state before the ask) never applied to them - only to the
    final Step 3 answer. A message reporting FRUSTRATED (missing items on
    delivery) still got a cold, unqualified "which product?" - prepend a
    short acknowledgement instead of leaving these turns tone-deaf."""
    prefix = _EMPATHY_PREFIX.get(emotion, "")
    return f"{prefix}{answer}" if prefix else answer


async def _run_business_objects(
    business_object_ids: List[str],
    case: str,
    entities: Dict[str, Any],
    emotion: str,
    *,
    memory: Dict[str, Any],
    token: Optional[str],
    user_id: Optional[str],
    session_id: Optional[str],
    history: List[Dict[str, str]],
) -> HelpResponse:
    """Everything from the auth gate onward - shared by the fresh Step 1 path
    and every resumed-pending path, so a CLARIFYING/COLLECTING_ENTITY resume
    goes through EXACTLY the same gates as a first-turn resolution."""
    # ── Fail-fast auth gate (between Step 1 and Step 2 - see the agreed
    # placement: LLM #1 must run first to even know which business objects
    # are needed, so a guest still pays for that one call before being
    # blocked; there is no cheaper way to know auth is required here). ──
    if business_object_executor.requires_auth(business_object_ids) and not token:
        answer = render_or_fallback("RT_ERROR_UNAUTHENTICATED", {})
        return HelpResponse(answer=answer, case=case, mode="unauthenticated", warnings=["fail-fast: requires auth, no token supplied"])

    # ── Slot-filling gate ──
    required = business_object_executor.collect_required_entities(business_object_ids)
    missing = [e for e in required if not entities.get(e)]
    if missing:
        pending_entity = missing[0]
        answer = _with_empathy(_ask_for_entity(pending_entity), emotion)
        pending = cs.make_pending(
            ConversationState.COLLECTING_ENTITY,
            pending_entity=pending_entity, collected_entities=entities,
        )
        pending["business_object_ids"] = business_object_ids
        pending["case"] = case
        pending["emotion"] = emotion
        cs.set_pending(memory, pending)
        return HelpResponse(answer=answer, case=case, mode="ask_entity", follow_up_questions=[answer])

    # ── Confirmation gate (mutating actions) ──
    if business_object_executor.is_mutating(business_object_ids):
        confirmed = entities.get("_confirmed")
        if confirmed is None:
            answer = _with_empathy(_confirmation_prompt(business_object_ids), emotion)
            pending = cs.make_pending(ConversationState.AWAITING_CONFIRMATION, collected_entities=entities)
            pending["business_object_ids"] = business_object_ids
            pending["case"] = case
            pending["emotion"] = emotion
            cs.set_pending(memory, pending)
            return HelpResponse(answer=answer, case=case, mode="ask_confirmation", follow_up_questions=[answer])
        if confirmed is False:
            cs.clear_pending(memory)
            return HelpResponse(answer="Mình đã huỷ yêu cầu này. Bạn cần mình hỗ trợ gì khác không?", case=case, mode="cancelled")

    # ── Step 2: backend execution ── entities carries orchestration-only
    # keys (_raw_message, _confirmed) that must never reach tool calls,
    # fact_manifest, or the public `data` field - strip them here, once,
    # rather than filtering at every downstream consumer.
    clean_entities = {k: v for k, v in entities.items() if not k.startswith("_")}
    result = await business_object_executor.execute(
        business_object_ids, clean_entities, token=token, user_id=user_id, session_id=session_id,
    )
    retry_key = _retry_key(business_object_ids)
    retry_already_attempted = bool(memory.get(retry_key))
    is_critical = business_object_executor.highest_priority(business_object_ids) == "critical"
    always_escalate = business_object_executor.always_escalates(business_object_ids)

    ticket_id: Optional[str] = None
    escalated = False
    warnings = list(result.warnings)

    if result.hard_failure is not None:
        group, template_id, escalate_immediately = handle_exception(result.hard_failure, token_was_supplied=bool(token))
        if group == ErrorGroup.UNAUTHENTICATED:
            cs.clear_pending(memory)
            return HelpResponse(answer=render_or_fallback(template_id, {}), case=case, mode="unauthenticated", warnings=warnings)
        if group == ErrorGroup.NOT_FOUND:
            # Not transient - retrying the SAME wrong/typo'd code will 404
            # again forever, so this must never enter the retry-then-
            # escalate counter below (that counter is for genuinely
            # transient timeouts/5xx; routing a simple typo through it would
            # eventually auto-create a ticket for nothing). Answer directly
            # and let the conversation continue normally.
            memory.pop(retry_key, None)
            cs.clear_pending(memory)
            answer = _with_empathy(render_or_fallback(template_id, {}), emotion)
            return HelpResponse(answer=answer, case=case, mode="not_found", warnings=warnings)
        if not escalate_immediately and not is_critical:
            actions = escalation_actions_for({"priority": "critical" if is_critical else "normal"}, transient_error=True, retry_already_attempted=retry_already_attempted)
            if EscalationAction.CREATE_TICKET not in actions:
                memory[retry_key] = True
                return HelpResponse(answer=render_or_fallback(template_id, {}), case=case, mode="retry_later", warnings=warnings)
        ticket_id = await help_ticket_repo.create_ticket(
            domain=case, ko_id="-".join(business_object_ids), entities=result.context,
            conversation_snippet=history, priority="high" if is_critical else "normal",
            session_id=session_id, user_id=user_id,
        )
        answer = render_or_fallback(template_id, {**result.context, "ticket_id": ticket_id})
        memory.pop(retry_key, None)
        cs.clear_pending(memory)
        return HelpResponse(answer=answer, case=case, escalated=True, ticket_id=ticket_id, mode="escalated", warnings=warnings)

    memory.pop(retry_key, None)

    if always_escalate or is_critical:
        ticket_id = await help_ticket_repo.create_ticket(
            domain=case, ko_id="-".join(business_object_ids), entities=result.context,
            conversation_snippet=history, priority="critical" if is_critical else "high",
            session_id=session_id, user_id=user_id,
        )
        escalated = True

    # ── Fact Manifest + Step 3 (LLM #2) + grounding verifier ──
    facts = fact_manifest.build(business_object_ids, result.context, _SYSTEM_FIELDS)
    if ticket_id:
        facts.append(fact_manifest.Fact(fact_id="T1", source="ticket", text=f"Mã ticket hỗ trợ đã tạo: {ticket_id}"))
    if result.mutating_completed:
        # The ONLY basis Step 3 is allowed to claim an action (huỷ đơn...)
        # actually completed - added exclusively when the real mutating tool
        # ran and succeeded this turn (see business_object_executor.execute's
        # unattempted_mutating/mutating_completed logic). Never added
        # speculatively - fact_manifest.py deliberately stopped pulling the
        # KB's own "success" template text as a fact for mutating objects for
        # exactly this reason (it was describing a hypothetical outcome, not
        # an established one).
        bo0 = help_knowledge.get_business_object(business_object_ids[0]) if business_object_ids else None
        action_label = (bo0 or {}).get("action_label") or (bo0 or {}).get("description") or "Hành động"
        facts.append(fact_manifest.action_result_fact(action_label))
    if warnings:
        # One alternative tool failed (e.g. order code didn't match) while
        # another succeeded (fix: business_object_executor no longer treats
        # that as a hard failure) - Step 3 needs to know the lookup was only
        # PARTIAL so it can honestly hedge instead of presenting the
        # successful tool's data as if it fully answered the question.
        facts.append(fact_manifest.Fact(
            fact_id="W1", source="warning",
            text="Một phần dữ liệu không tra được đúng như khách cung cấp (ví dụ mã đơn không khớp) - chỉ có dữ liệu tổng quát/khác bên dưới, không phải dữ liệu khớp chính xác yêu cầu.",
        ))

    step3_result = await step3_respond.respond(entities.get("_raw_message", ""), history, facts, emotion)
    if not step3_result.grounded:
        if not ticket_id:
            ticket_id = await help_ticket_repo.create_ticket(
                domain=case, ko_id="-".join(business_object_ids), entities=result.context,
                conversation_snippet=history, priority="normal", session_id=session_id, user_id=user_id,
            )
        answer = render_or_fallback("RT_ESCALATE_GENERIC", {"ticket_id": ticket_id})
        cs.clear_pending(memory)
        return HelpResponse(
            answer=answer, case=case, escalated=True, ticket_id=ticket_id, mode="grounding_failed",
            warnings=warnings + step3_result.warnings,
        )

    active_business_object = None
    if entities.get("ma_don_hang"):
        active_business_object = {"type": "order", "id": entities["ma_don_hang"]}
    cs.set_active_case(memory, case=case, business_object_id=business_object_ids[0], active_business_object=active_business_object)
    cs.set_last_resolved(memory, business_object_ids, entities)
    cs.clear_pending(memory)

    public_context = {k: v for k, v in result.context.items() if k not in _SYSTEM_FIELDS}
    return HelpResponse(
        answer=step3_result.answer, case=case, escalated=escalated, ticket_id=ticket_id,
        mode="resolved", data=public_context or None, warnings=warnings,
    )


async def process_help_message(
    message: str,
    session_id: Optional[str],
    *,
    token: Optional[str] = None,
    user_id: Optional[str] = None,
    selected_order_id: Optional[str] = None,
) -> HelpResponse:
    """AI Customer Care v2 single entry point: Fast-path (0 LLM) -> resume a
    pending Business Conversation State if one exists -> Step 1 (LLM #1,
    understand) -> gates (confidence/auth/entity/confirmation) -> Step 2
    (backend) -> Step 3 (LLM #2, respond) -> grounding verifier -> persisted
    state for the next turn."""
    t0 = time.perf_counter()
    request_tokens.set(0)
    help_knowledge.maybe_reload()

    conversation = await help_session_manager.load_session(session_id)
    memory = conversation.memory
    state = cs.get_conversation_state(memory)

    print(f"\n[Help v2] === New Request ===")
    print(f"[Help v2] Message: {message!r} (user_id={user_id}, session_id={session_id}, selected_order_id={selected_order_id})")

    if selected_order_id:
        new_object = {"type": "order", "id": selected_order_id}
        cs.reset_if_switched(memory, new_object)
        cs.get_conversation_state(memory)["active_business_object"] = new_object
        state = cs.get_conversation_state(memory)

    await help_session_manager.add_message(conversation, "user", message)

    if selected_order_id:
        # BOT-01's "Theo dõi đơn hàng" button sends selected_order_id ONLY on
        # the tap action itself (auto-filling a generic opening message like
        # "Tôi muốn hỏi về đơn hàng: #..." into the chat), never on ordinary
        # follow-up turns - so its presence at all is itself the reliable
        # signal, regardless of whether this order was already the active
        # context earlier in the session. That placeholder text carries no
        # real intent to classify, so running Step 1 on it would burn an LLM
        # call just to land on a vague guess. Ask a free, deterministic
        # question instead and let the customer's ACTUAL next message (order
        # already anchored as active_business_object) drive Step 1 - cheaper
        # AND better-targeted.
        cs.clear_pending(memory)
        answer = "Bạn đang gặp vấn đề gì hoặc có thắc mắc gì về đơn hàng này ạ? Cứ nói cho mình biết nhé!"
        await help_session_manager.add_message(conversation, "assistant", answer)
        await help_session_manager.save_session(conversation)
        response_time_ms, tokens_used = _finalize_metrics(t0, "ask_order_topic")
        return HelpResponse(
            answer=answer, case="ORDER", mode="ask_order_topic",
            response_time_ms=response_time_ms, tokens_used=tokens_used,
        )

    pending = cs.get_active_pending(memory)

    if pending is None:
        fast = fastpath.match_fast_path(message)
        if fast is not None:
            bo_id, template_id = fast
            answer = render_or_fallback(template_id, {})
            await help_session_manager.add_message(conversation, "assistant", answer)
            await help_session_manager.save_session(conversation)
            response_time_ms, tokens_used = _finalize_metrics(t0, "fast_path")
            return HelpResponse(
                answer=answer, case="GENERAL", mode="fast_path",
                response_time_ms=response_time_ms, tokens_used=tokens_used,
            )

    resumed: Optional[Tuple[List[str], str, Dict[str, Any], str]] = None  # (business_object_ids, case, entities, emotion)

    if pending is not None:
        pstate = pending.get("state")
        collected = dict(pending.get("collected_entities") or {})

        if pstate == ConversationState.CLARIFYING.value:
            picked_id = _match_clarification_choice(message, pending.get("pending_options") or [])
            if picked_id:
                bo = help_knowledge.get_business_object(picked_id) or {}
                resumed = ([picked_id], bo.get("case", "GENERAL"), collected, pending.get("emotion", "NEUTRAL"))
        elif pstate == ConversationState.COLLECTING_ENTITY.value:
            value = entity_regex.extract_entity_value(pending.get("pending_entity"), message)
            if value is not None:
                collected[pending["pending_entity"]] = value
                resumed = (pending.get("business_object_ids") or [], pending.get("case", "GENERAL"), collected, pending.get("emotion", "NEUTRAL"))
        elif pstate == ConversationState.AWAITING_CONFIRMATION.value:
            confirmed = entity_regex.parse_yes_no(message)
            if confirmed is not None:
                collected["_confirmed"] = confirmed
                resumed = (pending.get("business_object_ids") or [], pending.get("case", "GENERAL"), collected, pending.get("emotion", "NEUTRAL"))
        elif pstate == ConversationState.AWAITING_EVIDENCE.value:
            text = message.strip()
            if text:
                collected["hinh_anh_minh_chung"] = text
                resumed = (pending.get("business_object_ids") or [], pending.get("case", "GENERAL"), collected, pending.get("emotion", "NEUTRAL"))

    if resumed is None and pending is not None:
        # Reply didn't resolve the pending state (e.g. an unrelated new
        # question) - fall through to a fresh Step 1 call, same as v1's
        # _try_resume returning None.
        pending = None

    if resumed is not None:
        business_object_ids, case, entities, emotion = resumed
        entities["_raw_message"] = message
        mode_used = "resumed"
    else:
        regex_entities = entity_regex.extract_regex_entities(message)
        understanding = await step1_understand.understand(
            message, conversation.history, active_business_object=state.get("active_business_object"),
        )
        merged_entities = {**regex_entities, **understanding.entities}

        # Sticky order context (plan §8/§9) - passing active_business_object
        # into the Step 1 PROMPT as a hint isn't enough; the model doesn't
        # reliably copy it back into its own entities output, so the
        # required-entities gate then sees ma_don_hang missing and asks for
        # it again even though the customer never left that order's context
        # (confirmed live: "vậy đơn đó giao chưa" after resolving an order
        # re-asked for the code). Backfill deterministically instead of
        # trusting the model to remember.
        active_bo = state.get("active_business_object")
        if understanding.case == "ORDER" and active_bo and active_bo.get("type") == "order":
            if merged_entities.get("ma_don_hang"):
                if merged_entities["ma_don_hang"] != active_bo.get("id"):
                    # Customer named a genuinely different order - switch
                    # context and wipe any stale collected_entities/pending
                    # left over from the old one (anti-leak).
                    cs.reset_if_switched(memory, {"type": "order", "id": merged_entities["ma_don_hang"]})
                    state = cs.get_conversation_state(memory)
            else:
                merged_entities["ma_don_hang"] = active_bo["id"]

        # Just-completed-flow backfill: a correction right after submitting
        # (e.g. "tôi nói lộn vì đưa sai hàng" moments after a return request
        # ticket was created) must not re-ask for the product/order the
        # customer already gave two turns ago - only fill what THIS message
        # still leaves missing, never override what it actually says.
        last_resolved = cs.get_last_resolved(memory)
        if last_resolved and understanding.business_objects_needed and set(understanding.business_objects_needed) == set(last_resolved.get("business_object_ids", [])):
            for k, v in (last_resolved.get("entities") or {}).items():
                merged_entities.setdefault(k, v)

        print(f"[Help v2] Step1: case={understanding.case} objects={understanding.business_objects_needed} "
              f"confidence={understanding.confidence} resolved={understanding.resolved} emotion={understanding.emotion}")

        if understanding.case == "OUT_OF_SCOPE":
            # The model itself judged this genuinely irrelevant to CSKH (e.g.
            # weather, sports) - a real decline, not a case we can offer a
            # menu for.
            cs.clear_pending(memory)
            await help_session_manager.add_message(conversation, "assistant", _OUT_OF_SCOPE_TEXT)
            await help_session_manager.save_session(conversation)
            response_time_ms, tokens_used = _finalize_metrics(t0, "out_of_scope")
            return HelpResponse(answer=_OUT_OF_SCOPE_TEXT, mode="out_of_scope", response_time_ms=response_time_ms, tokens_used=tokens_used)

        if not understanding.resolved:
            # Model recognized the CASE (GENERAL/ORDER/...) but couldn't pin a
            # specific Business Object and gave no alternatives of its own -
            # widen to every Business Object under that case rather than
            # declining outright (this is what actually fixes vague asks like
            # "tôi thắc mắc về" / "chính sách của công ty" landing on a flat
            # apology instead of a menu to pick from).
            candidates = understanding.alternative_candidates or understanding.business_objects_needed or _case_fallback_candidates(understanding.case)
            candidates = candidates[:_MAX_CLARIFICATION_OPTIONS]
            answer = _clarification_prompt(candidates)
            pending_new = cs.make_pending(ConversationState.CLARIFYING, pending_options=candidates, collected_entities=merged_entities)
            pending_new["emotion"] = understanding.emotion
            cs.set_pending(memory, pending_new)
            await help_session_manager.add_message(conversation, "assistant", answer)
            await help_session_manager.save_session(conversation)
            response_time_ms, tokens_used = _finalize_metrics(t0, "clarifying")
            return HelpResponse(
                answer=answer, case=understanding.case, mode="ask_clarification", follow_up_questions=[answer],
                response_time_ms=response_time_ms, tokens_used=tokens_used,
            )

        business_object_ids = understanding.business_objects_needed
        case = understanding.case
        entities = merged_entities
        entities["_raw_message"] = message
        emotion = understanding.emotion
        mode_used = "understood"

    response = await _run_business_objects(
        business_object_ids, case, entities, emotion,
        memory=memory, token=token, user_id=user_id, session_id=conversation.session_id, history=conversation.history,
    )

    await help_session_manager.add_message(conversation, "assistant", response.answer)
    await help_session_manager.save_session(conversation)
    response.response_time_ms, response.tokens_used = _finalize_metrics(t0, response.mode or mode_used)
    return response
