"""
MongoDB async client for AI Service.
Uses MONGO_CORE_URI from env (same Atlas cluster as core service).
"""
import os
import logging
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

logger = logging.getLogger(__name__)

_client: AsyncIOMotorClient | None = None
_db: AsyncIOMotorDatabase | None = None

MONGO_URI = os.getenv("MONGO_CORE_URI", "")
if not MONGO_URI:
    MONGO_URI = os.getenv("MONGO_URI", "")
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME", "delippy_ai")


def get_mongo_client() -> AsyncIOMotorClient:
    global _client
    if _client is None:
        if not MONGO_URI:
            raise ValueError("MONGO_CORE_URI environment variable is not set")
        _client = AsyncIOMotorClient(MONGO_URI)
        logger.info(f"[DB] MongoDB client created, db={MONGO_DB_NAME}")
    return _client


async def get_database() -> AsyncIOMotorDatabase:
    global _db
    if _db is None:
        client = get_mongo_client()
        _db = client[MONGO_DB_NAME]
    return _db


async def close_mongo_connection():
    global _client, _db
    if _client:
        _client.close()
        _client = None
        _db = None
        logger.info("[DB] MongoDB connection closed")
