from typing import Optional
from app.database.conversation_repository import conversation_repo
from app.models.conversation import Conversation
import uuid

class SessionManager:
    async def load_session(self, session_id: Optional[str]) -> Conversation:
        if not session_id:
            session_id = str(uuid.uuid4())
            conv = Conversation(session_id=session_id)
            await conversation_repo.save_conversation(conv)
            return conv
            
        conv = await conversation_repo.get_conversation(session_id)
        if not conv:
            conv = Conversation(session_id=session_id)
            await conversation_repo.save_conversation(conv)
        return conv

    async def save_session(self, conversation: Conversation) -> None:
        await conversation_repo.save_conversation(conversation)

    async def add_message(self, conversation: Conversation, role: str, content: str) -> None:
        conversation.history.append({"role": role, "content": content})
        # Limit history length to save token costs (keep last 10 messages)
        if len(conversation.history) > 10:
            conversation.history = conversation.history[-10:]

session_manager = SessionManager()
