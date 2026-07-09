from fastapi import APIRouter

router = APIRouter(prefix="/api/v1", tags=["System"])


@router.get("/health")
async def health_check():
    return {"success": True, "service": "Delippy-ai", "status": "ok"}
