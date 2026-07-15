from typing import Any, Awaitable, Callable, Dict, Optional

from app.client.delippy_client import delippy_client

ToolCallable = Callable[[Optional[str], Dict[str, Any]], Awaitable[Any]]


async def _call_order_list(token: Optional[str], entities: Dict[str, Any]) -> Any:
    return await delippy_client.list_orders(params={}, token=token)


async def _call_order_detail(token: Optional[str], entities: Dict[str, Any]) -> Any:
    return await delippy_client.get_order_detail(entities.get("ma_don_hang"), token=token)


async def _call_order_cancel(token: Optional[str], entities: Dict[str, Any]) -> Any:
    return await delippy_client.cancel_order(entities.get("ma_don_hang"), token=token)


async def _call_order_payment_status(token: Optional[str], entities: Dict[str, Any]) -> Any:
    return await delippy_client.payment_status(entities.get("ma_don_hang"), token=token)


async def _call_payment_methods_list(token: Optional[str], entities: Dict[str, Any]) -> Any:
    return await delippy_client.get_payment_methods(token=token)


async def _call_shipping_tracking_detail(token: Optional[str], entities: Dict[str, Any]) -> Any:
    """No dedicated tracking endpoint exists - OrderDetail.tracks
    (app/models/ecommerce/order.py) IS the tracking history, so this reuses
    the same call as TOOL_ORDER_DETAIL. flow_executor.py reads the `tracks`
    field off the result."""
    return await delippy_client.get_order_detail(entities.get("ma_don_hang"), token=token)


async def _call_profile_get(token: Optional[str], entities: Dict[str, Any]) -> Any:
    return await delippy_client.get_profile(token=token)


# Only the tool_ids with a real, already-working DelippyClient method are
# registered here - see the approved plan's scope table. Every other
# tool_id in tool.json (status NEEDS_CONFIRMATION/MISSING_NEEDS_BUILD) has no
# entry, which is deliberate: flow_executor.py's "not registered" branch and
# the escalation taxonomy handle that case for free, no per-domain code
# needed as backend coverage grows - just add a row here.
TOOL_REGISTRY: Dict[str, ToolCallable] = {
    "TOOL_ORDER_LIST": _call_order_list,
    "TOOL_ORDER_DETAIL": _call_order_detail,
    "TOOL_ORDER_CANCEL": _call_order_cancel,
    "TOOL_ORDER_PAYMENT_STATUS": _call_order_payment_status,
    "TOOL_PAYMENT_METHODS_LIST": _call_payment_methods_list,
    "TOOL_SHIPPING_TRACKING_DETAIL": _call_shipping_tracking_detail,
    "TOOL_PROFILE_GET": _call_profile_get,
}


def get_tool_callable(tool_id: str) -> Optional[ToolCallable]:
    return TOOL_REGISTRY.get(tool_id)


def is_tool_available(tool_id: str) -> bool:
    return tool_id in TOOL_REGISTRY


async def call_tool(tool_id: str, *, token: Optional[str], entities: Dict[str, Any]) -> Any:
    """Raises whatever delippy_client/httpx raises - flow_executor.py routes
    that through app/help/errors.py. Callers should check
    is_tool_available()/get_tool_callable() first; this raises ValueError as
    a defensive guard only, not the primary "unavailable" signal (that's
    tool.json's own `status` field, already checked by flow_executor before
    ever reaching here)."""
    fn = TOOL_REGISTRY.get(tool_id)
    if fn is None:
        raise ValueError(f"No real callable registered for tool_id={tool_id!r}")
    return await fn(token, entities)
