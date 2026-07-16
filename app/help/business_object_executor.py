import asyncio
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from app.help.errors import MissingAuthError
from app.help.tools import call_tool, is_tool_available
from app.knowledge.help.loader import help_knowledge


@dataclass
class ExecutionResult:
    context: Dict[str, Any]
    warnings: List[str] = field(default_factory=list)
    hard_failure: Optional[Exception] = None
    tool_ids_called: List[str] = field(default_factory=list)
    # True only when a mutating business object's actual state-changing tool
    # (POST/PUT/DELETE, not a companion read like TOOL_ORDER_DETAIL) ran and
    # succeeded THIS turn - the one fact orchestrator.py is allowed to base
    # an "action completed" statement on. Always False for non-mutating
    # business objects (nothing to complete).
    mutating_completed: bool = False


def dedup_tool_ids(business_object_ids: List[str]) -> List[str]:
    tool_ids: List[str] = []
    for bo_id in business_object_ids:
        bo = help_knowledge.get_business_object(bo_id) or {}
        for t in bo.get("tool_ids") or []:
            if t not in tool_ids:
                tool_ids.append(t)
    return tool_ids


def requires_auth(business_object_ids: List[str]) -> bool:
    return any((help_knowledge.get_business_object(bid) or {}).get("required_auth") for bid in business_object_ids)


def collect_required_entities(business_object_ids: List[str]) -> List[str]:
    seen: List[str] = []
    for bo_id in business_object_ids:
        bo = help_knowledge.get_business_object(bo_id) or {}
        for e in bo.get("required_entities") or []:
            if e not in seen:
                seen.append(e)
    return seen


def is_mutating(business_object_ids: List[str]) -> bool:
    return any((help_knowledge.get_business_object(bid) or {}).get("mutating") for bid in business_object_ids)


def always_escalates(business_object_ids: List[str]) -> bool:
    return any((help_knowledge.get_business_object(bid) or {}).get("escalate_always") for bid in business_object_ids)


def highest_priority(business_object_ids: List[str]) -> str:
    order = {"critical": 3, "high": 2, "normal": 1}
    best = "normal"
    for bid in business_object_ids:
        p = (help_knowledge.get_business_object(bid) or {}).get("priority", "normal")
        if order.get(p, 1) > order.get(best, 1):
            best = p
    return best


def _params_satisfied(tool_id: str, context: Dict[str, Any]) -> bool:
    tool = help_knowledge.get_tool(tool_id) or {}
    required_params = tool.get("required_parameters") or []
    return all(p in context for p in required_params)


def _is_mutating_tool(tool_id: str) -> bool:
    """tool.json's `method` field is like "POST /orders/{id}/cancel" - the
    HTTP verb tells us whether this specific tool call changes state (vs a
    companion GET like TOOL_ORDER_DETAIL that a mutating business object
    also lists to read the latest status first)."""
    method = ((help_knowledge.get_tool(tool_id) or {}).get("method") or "").strip().upper()
    verb = method.split()[0] if method else ""
    return verb not in ("GET", "")


def _flatten_into_context(context: Dict[str, Any], tool_id: str, result: Any) -> None:
    """Mapping from a real Delippy API response onto the Vietnamese
    {{placeholder}}/fact names used downstream - ported verbatim from v1's
    app/help/flow_executor.py (verified against api-docs/order_api.md +
    api-docs/account_api.md, not guessed)."""
    if not isinstance(result, dict):
        return
    payload = result.get("data") if isinstance(result.get("data"), dict) else result

    if tool_id in ("TOOL_ORDER_DETAIL", "TOOL_SHIPPING_TRACKING_DETAIL"):
        if payload.get("order_number") and not context.get("ma_don_hang"):
            context["ma_don_hang"] = payload["order_number"]
        status = str(payload.get("status") or "")
        status_label = payload.get("status_label") or status
        if status_label:
            context["trang_thai_hien_tai"] = status_label
        tracks = payload.get("tracks") or []
        if tracks:
            latest_track = tracks[0]  # newest-first - see api-docs/order_api.md
            context["moc_tracking_gan_nhat"] = latest_track.get("title") or latest_track.get("text")
            # BUG FIXED: this used to label the latest track's timestamp as
            # "thoi_gian_giao" (delivery time) UNCONDITIONALLY - for an order
            # that was only just placed today, the one and only track IS
            # "Order Placed", so its own timestamp got presented as if it
            # were the delivery date (confirmed live: a same-day-placed,
            # still-"pending" order got told back to the customer as
            # delivered/arriving that same day). Only the "completed"
            # (= delivered) status genuinely makes "latest track timestamp"
            # a proxy for delivery time - see api-docs/order_api.md's own
            # note that there's no separate delivered_at field.
            if status.lower() == "completed" and latest_track.get("created_at"):
                context.setdefault("thoi_gian_giao", latest_track["created_at"])

        # Real handoff-to-carrier signal (the `shipping` array, previously
        # not read at all) - an order still "pending"/"processing" with no
        # tracking code hasn't left the seller yet, and must never be
        # answered with a delivery estimate (see fix + Step 3 prompt rule).
        shipping_legs = [s for s in (payload.get("shipping") or []) if isinstance(s, dict)]
        if shipping_legs:
            has_code = any(leg.get("code") for leg in shipping_legs)
            carrier_keys = sorted({leg["partner"] for leg in shipping_legs if leg.get("partner")})
            if has_code:
                codes = ", ".join(str(leg["code"]) for leg in shipping_legs if leg.get("code"))
                context["ma_van_don"] = codes
                display_names: List[str] = []
                # Curated (never LLM-guessed) average transit-time text, only
                # while the order is genuinely still in transit - once
                # delivered ("completed"), an ETA is moot; the real delivery
                # time is already covered by thoi_gian_giao above.
                transit_texts: List[str] = []
                for key in carrier_keys:
                    curated = help_knowledge.get_carrier_transit_time(key)
                    display_names.append(curated["display_name"] if curated else key)
                    if curated and status.lower() != "completed":
                        transit_texts.append(f"{curated['display_name']}: {curated['avg_transit_time_text']}")
                if display_names:
                    context["don_vi_van_chuyen"] = ", ".join(display_names)
                if transit_texts:
                    context["thoi_gian_van_chuyen_tham_khao"] = " ".join(transit_texts)
            else:
                context["chua_ban_giao_van_chuyen"] = (
                    "Đơn hàng chưa có mã vận đơn - chưa được bàn giao cho đơn vị vận chuyển, "
                    "hiện vẫn đang chờ người bán chuẩn bị/xác nhận."
                )

        if payload.get("seller"):
            context["thong_tin_seller"] = payload["seller"]

    elif tool_id == "TOOL_PAYMENT_METHODS_LIST":
        methods = result.get("data") if isinstance(result.get("data"), list) else (result if isinstance(result, list) else [])
        labels = [m.get("label") for m in methods if isinstance(m, dict) and m.get("is_active") and m.get("label")]
        if labels:
            context["danh_sach_phuong_thuc"] = ", ".join(labels)

    elif tool_id == "TOOL_ORDER_PAYMENT_STATUS":
        status = payload.get("payment_status") or payload.get("order_status")
        if status:
            context["trang_thai_hien_tai"] = status
        if payload.get("amount"):
            context["so_tien"] = payload["amount"]
        if payload.get("expired_at"):
            context.setdefault("thoi_gian_dong_bo_du_kien", payload["expired_at"])

    elif tool_id == "TOOL_PROFILE_GET":
        for k in ("display_name", "email", "phone", "avatar_url", "default_address"):
            if payload.get(k) is not None:
                context[k] = payload[k]

    elif tool_id == "TOOL_ORDER_CANCEL":
        # Runs alongside TOOL_ORDER_DETAIL's pre-cancel read (same business
        # object, both in `ready`) - this branch must overwrite
        # trang_thai_hien_tai with the POST-cancel status, not leave the
        # detail call's now-stale pre-cancel value sitting in context
        # (dedup_tool_ids preserves the registry's declared tool_ids order,
        # so TOOL_ORDER_CANCEL's result is always flattened after
        # TOOL_ORDER_DETAIL's here).
        status_label = payload.get("status_label") or payload.get("status")
        if status_label:
            context["trang_thai_hien_tai"] = status_label


async def _run_tool(tool_id: str, *, token: Optional[str], entities: Dict[str, Any]) -> Tuple[str, Any, Optional[Exception]]:
    if not is_tool_available(tool_id):
        return tool_id, None, ValueError(f"tool {tool_id!r} has no registered real callable")
    # .agents/AGENTS.md rule 3: a Guest attempting a Protected Action must
    # never reach the backend - checked here against tool.json's own
    # required_auth, same fail-fast v1 did in flow_executor._run_tool.
    tool_meta = help_knowledge.get_tool(tool_id)
    if (tool_meta or {}).get("required_auth") and not token:
        return tool_id, None, MissingAuthError(f"tool {tool_id!r} requires auth, no token supplied")
    try:
        result = await call_tool(tool_id, token=token, entities=entities)
        return tool_id, result, None
    except Exception as exc:  # noqa: BLE001 - classified upstream by errors.py
        return tool_id, None, exc


async def execute(
    business_object_ids: List[str],
    entities: Dict[str, Any],
    *,
    token: Optional[str],
    user_id: Optional[str],
    session_id: Optional[str],
) -> ExecutionResult:
    """Step 2 - resolves business_object_ids to their union of tool_ids and
    runs them concurrently. Tools whose required_parameters aren't satisfied
    this turn are silently skipped (not a failure) - business objects like
    BO_ORDER_STATUS deliberately list TWO alternative tools (detail-by-code
    vs list-when-no-code) and exactly one of them is expected to be
    unsatisfied on any given turn, that's normal branching, not an error."""
    tool_ids = dedup_tool_ids(business_object_ids)
    system_fields = {k: v for k, v in {"user_id": user_id, "session_id": session_id}.items() if v is not None}
    context: Dict[str, Any] = {**system_fields, **entities}
    mutating_bo = is_mutating(business_object_ids)
    mutating_tool_ids = {t for t in tool_ids if _is_mutating_tool(t)} if mutating_bo else set()

    if not tool_ids:
        return ExecutionResult(context=context, tool_ids_called=[])

    ready = [t for t in tool_ids if _params_satisfied(t, context)]
    warnings: List[str] = []

    # A mutating business object whose actual state-changing tool never even
    # got attempted (its required_parameters weren't satisfied - e.g.
    # ly_do_huy missing from a cancel request) must NEVER fall through to
    # Step 3 as a normal success just because a companion read-only tool
    # (TOOL_ORDER_DETAIL) was satisfied and ran fine. Confirmed live: exactly
    # this happened for order cancellation - TOOL_ORDER_CANCEL silently never
    # ran, TOOL_ORDER_DETAIL alone "succeeded", and Step 3 was left free to
    # narrate a cancellation that never occurred.
    unattempted_mutating = mutating_tool_ids - set(ready)
    if mutating_bo and mutating_tool_ids and unattempted_mutating:
        return ExecutionResult(
            context=context,
            warnings=[f"mutating tool(s) {sorted(unattempted_mutating)} never ran: required_parameters unsatisfied"],
            hard_failure=RuntimeError(f"mutating tool(s) {sorted(unattempted_mutating)} unattempted"),
            tool_ids_called=ready,
        )

    if not ready:
        # No tool had its required_parameters satisfied at all - genuinely
        # unexpected this late (the required_entities gate upstream in the
        # orchestrator should have already caught a missing entity), so this
        # is a defensive branch, not the normal "one alternative unsatisfied"
        # case above.
        return ExecutionResult(
            context=context, warnings=[f"no tool ready among {tool_ids}"],
            hard_failure=RuntimeError(f"no tool ready among {tool_ids}"), tool_ids_called=[],
        )

    results = await asyncio.gather(*(_run_tool(t, token=token, entities=entities) for t in ready))
    any_success = False
    mutating_completed = False
    first_exc: Optional[Exception] = None
    for tool_id, result, exc in results:
        if exc is not None:
            warnings.append(f"tool {tool_id} failed: {exc}")
            first_exc = first_exc or exc
            continue
        any_success = True
        if tool_id in mutating_tool_ids:
            mutating_completed = True
        _flatten_into_context(context, tool_id, result)

    if mutating_bo and mutating_tool_ids and not mutating_completed:
        # The mutating tool WAS attempted (it's in `ready`) but it's the one
        # that failed - never report success for the companion read-only
        # tool's sake.
        return ExecutionResult(
            context=context, warnings=warnings,
            hard_failure=first_exc or RuntimeError("mutating tool attempted but did not succeed"),
            tool_ids_called=ready,
        )

    # Only a hard failure if EVERY ready tool failed - e.g. BO_ORDER_STATUS
    # tries both TOOL_ORDER_DETAIL (by code) and TOOL_ORDER_LIST (browse) when
    # both have satisfied params; a wrong/typo'd order code 404ing on the
    # first must not throw away the second's real, successfully-fetched data
    # (confirmed live: it was discarding a real 15-order list and answering
    # as if the whole lookup had failed, just because ONE of two alternative
    # tools didn't find that specific code).
    hard_failure = None if any_success else first_exc
    if not any_success and first_exc is not None:
        warnings.append("no tool among the ready set succeeded")

    return ExecutionResult(
        context=context, warnings=warnings, hard_failure=hard_failure,
        tool_ids_called=ready, mutating_completed=mutating_completed,
    )
