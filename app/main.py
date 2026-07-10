# filepath: ai-service/app/main.py
from dotenv import load_dotenv
import os
from fastapi.middleware.cors import CORSMiddleware
load_dotenv(dotenv_path=".env")

# Only the providers with a bespoke SDK (see app/core/llm/factory.py) have a
# fixed env var name. Anything else is resolved generically at <PROVIDER>_*
# (DeepSeek, Groq, Mistral, a self-trained model behind an OpenAI-compatible
# server, ...) - checked via <PROVIDER>_BASE_URL instead.
_BUILTIN_REQUIRED_KEY = {
    "gemini": "GEMINI_API_KEY",
    "openai": "OPENAI_API_KEY",
    "claude": "ANTHROPIC_API_KEY",
}
_active_provider = os.getenv("AI_PROVIDER", "gemini").strip().lower()
if _active_provider in _BUILTIN_REQUIRED_KEY:
    _required_key = _BUILTIN_REQUIRED_KEY[_active_provider]
    if not os.getenv(_required_key):
        import logging
        logging.getLogger(__name__).warning(
            f"AI_PROVIDER={_active_provider} but {_required_key} is not set. "
            "Local chat can still boot for bootstrap and non-LLM flows."
        )
elif not os.getenv(f"{_active_provider.upper()}_BASE_URL"):
    import logging
    logging.getLogger(__name__).warning(
        f"AI_PROVIDER={_active_provider} is not a built-in provider and "
        f"{_active_provider.upper()}_BASE_URL is not set - LLM calls will fail until it is. "
        "See app/core/llm/factory.py for the required env var convention."
    )

import math
import time

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from app.client.delippy_client import DelippyClient, DelippyRateLimitedError
from app.api.v1.account import router as account_router
from app.api.v1.categories import router as categories_router
from app.api.v1.chat import router as chat_router
from app.api.v1.health import router as health_router
from app.api.v1.orders import router as orders_router
from app.api.v1.products import router as products_router
from app.api.v1.reviews import router as reviews_router
from app.core.database import get_mongo_client, close_mongo_connection

# CORS_ALLOW_ORIGINS từ env (danh sách cách nhau bởi dấu phẩy)
# Mặc định chỉ mở cho FE local dev để tránh lỗi preflight trên browser.
_raw_origins = os.getenv("CORS_ALLOW_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173")
origins = [o.strip() for o in _raw_origins.split(",") if o.strip()]

app = FastAPI(
    title="Delippy AI Service",
    description="E-commerce AI gateway for product discovery, comparison, orders, reviews, and account workflows",
    version="3.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(DelippyRateLimitedError)
async def _delippy_rate_limited_handler(request: Request, exc: DelippyRateLimitedError):
    # Our own proactive cooldown (delippy_client) tripped: the Delippy backend
    # recently 429'd us and we're short-circuiting instead of piling on. The
    # proxy endpoints' local _proxy only catches httpx errors, so without this
    # a cooldown short-circuit would surface as a raw 500. Return a clean 503 +
    # Retry-After. Chat itself never reaches here - search_provider swallows
    # the error into a normal "no results" fallback.
    remaining = max(0.0, DelippyClient._cooldown_until - time.monotonic())
    return JSONResponse(
        status_code=503,
        content={"success": False, "message": "Hệ thống đang tạm thời quá tải, bạn vui lòng thử lại sau ít giây nhé!"},
        headers={"Retry-After": str(math.ceil(remaining) or 1)},
    )


@app.on_event("startup")
async def startup_event():
    # Initialize MongoDB connection
    try:
        get_mongo_client()
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"[Startup] MongoDB not available: {e}")

    # Idempotent TTL index for the semantic parse cache (auto-expires stale
    # entries so the cache self-heals and its lookup scan stays bounded).
    try:
        from app.database.parse_cache_repository import parse_cache_repo
        await parse_cache_repo.ensure_ttl_index()
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"[Startup] parse_cache TTL index not created: {e}")


@app.on_event("shutdown")
async def shutdown_event():
    await close_mongo_connection()


# ── Routers ───────────────────────────────────────────────────────────────────
app.include_router(health_router)
app.include_router(chat_router)
app.include_router(products_router)
app.include_router(categories_router)
app.include_router(reviews_router)
app.include_router(orders_router)
app.include_router(account_router)