from typing import Optional, Dict, Any, List
from app.database.mongodb import get_db
from app.models.conversation import Conversation
from datetime import datetime
import math

def cosine_similarity(v1: List[float], v2: List[float]) -> float:
    if not v1 or not v2 or len(v1) != len(v2):
        return 0.0
    dot_product = sum(x * y for x, y in zip(v1, v2))
    norm_v1 = math.sqrt(sum(x * x for x in v1))
    norm_v2 = math.sqrt(sum(y * y for y in v2))
    if norm_v1 == 0.0 or norm_v2 == 0.0:
        return 0.0
    return dot_product / (norm_v1 * norm_v2)

class ConversationRepository:
    def __init__(self, collection_name: str = "conversations", message_collection: str = "chat_messages"):
        self.collection_name = collection_name
        self.message_collection = message_collection

    async def get_conversation(self, session_id: str) -> Optional[Conversation]:
        db = await get_db()
        data = await db[self.collection_name].find_one({"session_id": session_id})
        if data:
            data.pop("_id", None)
            return Conversation(**data)
        return None

    async def save_conversation(self, conversation: Conversation) -> None:
        db = await get_db()
        conversation.updated_at = datetime.utcnow().isoformat()
        await db[self.collection_name].replace_one(
            {"session_id": conversation.session_id},
            conversation.dict(),
            upsert=True
        )

    async def save_message(self, session_id: str, role: str, content: str, embedding: List[float]) -> None:
        db = await get_db()
        await db[self.message_collection].insert_one({
            "session_id": session_id,
            "role": role,
            "content": content,
            "embedding": embedding,
            "created_at": datetime.utcnow()
        })

    async def get_relevant_history(self, session_id: str, query_vector: List[float], limit: int = 3) -> List[Dict[str, Any]]:
        if not query_vector:
            return []
            
        db = await get_db()
        cursor = db[self.message_collection].find({"session_id": session_id})
        
        messages = []
        async for doc in cursor:
            doc.pop("_id", None)
            messages.append(doc)
            
        if not messages:
            return []
            
        # Calculate similarity in memory
        scored_messages = []
        for msg in messages:
            emb = msg.get("embedding")
            similarity = cosine_similarity(query_vector, emb) if emb else 0.0
            scored_messages.append((similarity, msg))
            
        # Sort descending by similarity
        scored_messages.sort(key=lambda x: x[0], reverse=True)
        
        # Return top N relevant messages
        return [item[1] for item in scored_messages[:limit]]

conversation_repo = ConversationRepository()
