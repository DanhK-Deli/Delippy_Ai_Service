from fastapi import APIRouter, Request

from app.models.help import HelpRequest, HelpResponse

router = APIRouter(prefix="/api/v1", tags=["Help"])


@router.post("/help", response_model=HelpResponse)
async def help_endpoint(request: Request, payload: HelpRequest):
    from app.help.orchestrator import process_help_message

    session_id = payload.session_id or request.headers.get("x-session-id") or payload.user_id or "anonymous"
    token = request.headers.get("authorization")
    return await process_help_message(
        payload.message,
        session_id,
        token=token,
        user_id=payload.user_id,
        selected_order_id=payload.selected_order_id,
    )
