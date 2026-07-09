from app.core.database import get_database, close_mongo_connection

async def get_db():
    return await get_database()
