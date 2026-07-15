import asyncio
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from app.help import state as help_state
from app.help.errors import ErrorGroup, MissingAuthError, handle_exception
from app.help.escalation import EscalationAction, escalation_actions_for, help_ticket_repo
from app.help.templates import render_or_fallback
from app.help.tools import call_tool, is_tool_available
from app.knowledge.help.loader import help_knowledge


@dataclass
class FlowResult:
    answer: str
    escalated: bool = False
    ticket_id: Optional[str] = None
    data: Dict[str, Any] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)
    follow_up_questions: List[str] = field(default_factory=list)
    # What to persist to memory["awaiting"] this turn - None means clear it
    # (the flow either completed or escalated, nothing left to wait on).
    awaiting: Optional[Dict[str, Any]] = None


def _params_satisfied(api: Dict[str, Any], context: Dict[str, Any]) -> bool:
    """An api_mapping entry is ready to call once every one of its declared
    required_parameters is already present in `context` - initially just the
    user-supplied entities, but growing as earlier entries in the SAME
    api_mapping array complete (see _execute_api_mapping). This is the
    mechanical dependency signal from the approved plan §4 step 4: with the
    CURRENT tool.json content every entry's required_parameters are entity
    names already known up front, so in practice every entry runs in one
    concurrent wave today - the sequential path only activates once a future
    tool's required_parameters names an earlier tool's own output field."""
    tool = help_knowledge.get_tool(api.get("tool_id")) if api.get("tool_id") else None
    required_params = (tool or {}).get("required_parameters") or []
    return all(p in context for p in required_params)


def _flatten_into_context(context: Dict[str, Any], tool_id: str, result: Any) -> None:
    """Mapping from a real Delippy API response onto the Vietnamese
    {{placeholder}} names used in response_template.json. Verified against
    api-docs/order_api.md + api-docs/account_api.md (real backend contract,
    not guessed) - api-docs/ is the authoritative source, cross-check there
    first before changing field names here."""
    if not isinstance(result, dict):
        return
    payload = result.get("data") if isinstance(result.get("data"), dict) else result

    if tool_id in ("TOOL_ORDER_DETAIL", "TOOL_SHIPPING_TRACKING_DETAIL"):
        if payload.get("order_number") and not context.get("ma_don_hang"):
            context["ma_don_hang"] = payload["order_number"]
        status_label = payload.get("status_label") or payload.get("status")
        if status_label:
            context["trang_thai_hien_tai"] = status_label
        # tracks[] is ordered NEWEST FIRST (index 0 = latest) - confirmed in
        # api-docs/order_api.md ("tracks trả về mới nhất trước, index 0 là
        # mới nhất"). Using tracks[-1] here was a real bug: it read the
        # OLDEST entry (always "Pending"/order-placed) instead of the
        # current status.
        tracks = payload.get("tracks") or []
        if tracks:
            latest_track = tracks[0]
            context["moc_tracking_gan_nhat"] = latest_track.get("title") or latest_track.get("text")
            # order.created_at is the PLACEMENT time, not delivery time (no
            # separate "delivered_at" field exists per api-docs/order_api.md)
            # - the newest track's own timestamp is the closest real proxy
            # for "when did the order most recently change state", which for
            # a completed order is effectively the delivery time.
            if latest_track.get("created_at"):
                context.setdefault("thoi_gian_giao", latest_track["created_at"])

    elif tool_id == "TOOL_PAYMENT_METHODS_LIST":
        methods = result.get("data") if isinstance(result.get("data"), list) else (result if isinstance(result, list) else [])
        labels = [m.get("label") for m in methods if isinstance(m, dict) and m.get("is_active") and m.get("label")]
        if labels:
            context["danh_sach_phuong_thuc"] = ", ".join(labels)

    elif tool_id == "TOOL_ORDER_PAYMENT_STATUS":
        # GET /orders/{orderNumber}/payment-status is a DEDICATED, narrower
        # endpoint (api-docs/order_api.md mục 7) - its response shape is
        # {payment_status, order_status, amount, expired_at, paid_at}, NOT
        # the same field names as order detail. Real bug fixed here: the
        # previous code checked "status"/"status_label" which don't exist on
        # this response at all, so trang_thai_hien_tai was silently never
        # set from this tool.
        status = payload.get("payment_status") or payload.get("order_status")
        if status:
            context["trang_thai_hien_tai"] = status
        if payload.get("amount"):
            context["so_tien"] = payload["amount"]
        if payload.get("expired_at"):
            context.setdefault("thoi_gian_dong_bo_du_kien", payload["expired_at"])


async def _run_tool(api: Dict[str, Any], *, token: Optional[str], entities: Dict[str, Any]) -> Tuple[str, Any, Optional[Exception]]:
    tool_id = api.get("tool_id")
    if not tool_id or not is_tool_available(tool_id):
        return tool_id, None, ValueError(f"tool {tool_id!r} has no registered real callable")
    # .agents/AGENTS.md rule 3: a Guest (no token) attempting a Protected
    # Action must NEVER reach the backend API - checked here, before the
    # call, against tool.json's own required_auth flag, rather than waiting
    # for a real 401 to come back.
    tool_meta = help_knowledge.get_tool(tool_id)
    if (tool_meta or {}).get("required_auth") and not token:
        return tool_id, None, MissingAuthError(f"tool {tool_id!r} requires auth, no token supplied")
    try:
        result = await call_tool(tool_id, token=token, entities=entities)
        return tool_id, result, None
    except Exception as exc:  # noqa: BLE001 - deliberately broad, classified by errors.py upstream
        return tool_id, None, exc


async def _execute_api_mapping(
    api_mapping: List[Dict[str, Any]], entities: Dict[str, Any], token: Optional[str], system_fields: Dict[str, Any]
) -> Tuple[Dict[str, Any], List[str], Optional[Exception]]:
    """Runs api_mapping entries in dependency waves (concurrent within a
    wave) - see _params_satisfied(). A failed entry marked "optional": true
    in its own JSON degrades to a warning; anything else (the implicit
    default - see plan §4 step 4) is treated as required and escalates.

    system_fields (user_id/session_id) seeds the dependency-satisfaction
    context alongside entities - some tool.json entries declare a
    required_parameters value like "user_id" that comes from the request/
    session, never from message text, so without this a tool needing it
    would look permanently unsatisfied even when it's otherwise perfectly
    callable (confirmed live: TOOL_SECURITY_LOGOUT_ALL_DEVICES's declared
    "user_id" parameter tripped this before system_fields was added here -
    harmless today only because that tool isn't registered in tools.py yet
    anyway, but would have silently misfired once it is)."""
    context: Dict[str, Any] = {**system_fields, **entities}
    warnings: List[str] = []
    hard_failure: Optional[Exception] = None
    remaining = list(api_mapping)

    while remaining:
        ready = [api for api in remaining if _params_satisfied(api, context)]
        if not ready:
            for api in remaining:
                tool_id = api.get("tool_id")
                warnings.append(f"tool {tool_id} skipped: required_parameters never satisfied")
                if not api.get("optional", False):
                    hard_failure = hard_failure or RuntimeError(f"unmet dependency for {tool_id}")
            break
        remaining = [api for api in remaining if api not in ready]
        results = await asyncio.gather(*(_run_tool(api, token=token, entities=entities) for api in ready))
        for api, (tool_id, result, exc) in zip(ready, results):
            if exc is not None:
                warnings.append(f"tool {tool_id} failed: {exc}")
                if not api.get("optional", False):
                    hard_failure = hard_failure or exc
                continue
            _flatten_into_context(context, tool_id, result)

    return context, warnings, hard_failure


async def execute(
    domain_attr: str,
    intent: str,
    entities: Dict[str, Any],
    *,
    token: Optional[str],
    session_id: Optional[str],
    user_id: Optional[str],
    history: Optional[List[Dict[str, str]]] = None,
    retry_already_attempted: bool = False,
) -> FlowResult:
    """The generic, data-driven flow described in the approved plan §4 -
    resolve the Knowledge Object, check required_entities, run its
    api_mapping tools, render a template, escalate when needed. No
    per-domain Python branch anywhere in this function; everything domain-
    specific comes from the JSON itself."""
    ko = help_knowledge.get_knowledge_object(domain_attr, intent)
    if not ko:
        return FlowResult(answer=render_or_fallback("RT_ERROR_GENERIC_FALLBACK", {}))

    ko_id = ko["id"]
    history = history or []

    required = ko.get("required_entities") or []
    missing = [e for e in required if not entities.get(e)]
    if missing:
        pending_entity = missing[0]
        follow_ups = ko.get("follow_up_questions") or []
        answer = follow_ups[0] if follow_ups else render_or_fallback(
            "RT_ASK_MORE_INFO_GENERIC", {"ten_entity_con_thieu": pending_entity}
        )
        awaiting = help_state.make_awaiting(
            help_state.HelpAwaitAction.AWAITING_ENTITY, ko_id,
            pending_entity=pending_entity, collected_entities=entities,
        )
        return FlowResult(answer=answer, follow_up_questions=[answer], awaiting=awaiting)

    api_mapping = ko.get("api_mapping") or []
    
    # Pre-execution fail-fast auth check: intercept if any API requires login but no token is provided
    needs_auth = False
    for api in api_mapping:
        tool_id = api.get("tool_id")
        tool = help_knowledge.get_tool(tool_id) if tool_id else None
        if tool:
            req_auth = tool.get("required_auth")
            if req_auth is True or (isinstance(req_auth, str) and req_auth != "" and req_auth.lower() != "false"):
                needs_auth = True
                break

    if needs_auth and not token:
        answer = render_or_fallback("RT_ERROR_UNAUTHENTICATED", {})
        return FlowResult(answer=answer, escalated=False)

    system_fields = {k: v for k, v in {"user_id": user_id, "session_id": session_id}.items() if v is not None}
    context, warnings, hard_failure = await _execute_api_mapping(api_mapping, entities, token, system_fields)


    is_critical = ko.get("priority") == "critical"

    if hard_failure is not None:
        group, template_id, escalate_immediately = handle_exception(hard_failure, token_was_supplied=bool(token))
        answer = render_or_fallback(template_id, context)
        if group == ErrorGroup.UNAUTHENTICATED:
            # .agents/AGENTS.md rule 3, Guest path: never create a ticket
            # here, and NOT subject to the transient-error retry-then-
            # escalate logic below either - a Guest without a token won't
            # get one just because the chatbot "retried"; only the human
            # logging in resolves this, so escalating on a second attempt
            # would be pointless noise for the support queue.
            return FlowResult(answer=answer, warnings=warnings, escalated=False)
        if not escalate_immediately and not is_critical:
            # Transient errors (timeout/5xx) - ask again / retry, no ticket
            # yet unless this is the second time in this session (plan §6).
            actions = escalation_actions_for(ko, transient_error=True, retry_already_attempted=retry_already_attempted)
            if EscalationAction.CREATE_TICKET not in actions:
                return FlowResult(answer=answer, warnings=warnings, escalated=False)
        ticket_id = await help_ticket_repo.create_ticket(
            domain=domain_attr, ko_id=ko_id, entities=context, conversation_snippet=history,
            priority=ko.get("priority", "normal"), session_id=session_id, user_id=user_id,
        )
        return FlowResult(answer=answer, escalated=True, ticket_id=ticket_id, warnings=warnings)

    if is_critical:
        ticket_id = await help_ticket_repo.create_ticket(
            domain=domain_attr, ko_id=ko_id, entities=context, conversation_snippet=history,
            priority="critical", session_id=session_id, user_id=user_id,
        )
        answer = render_or_fallback(ko.get("response_templates", {}).get("success_response", "RT_ESCALATE_GENERIC"), {**context, "ticket_id": ticket_id})
        return FlowResult(answer=answer, escalated=True, ticket_id=ticket_id, warnings=warnings)

    response_templates = ko.get("response_templates") or {}
    template_id = response_templates.get("success_response") or "RT_ERROR_GENERIC_FALLBACK"
    answer = render_or_fallback(template_id, context)
    # system_fields (user_id/session_id) were only merged in to satisfy tool
    # required_parameters checks - strip them back out before exposing
    # `data` to the client, that field is for USEFUL fetched facts (order
    # status, tracking...), not internal session bookkeeping (confirmed live:
    # a static, no-api_mapping intent was otherwise leaking
    # {"session_id": "anonymous"} into the response for no reason).
    public_data = {k: v for k, v in context.items() if k not in system_fields}
    return FlowResult(answer=answer, data=public_data, warnings=warnings)
