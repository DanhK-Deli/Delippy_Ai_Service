import uuid
from typing import Optional

from app.database.conversation_repository import ConversationRepository
from app.models.conversation import Conversation

# Reuses app.models.conversation.Conversation as-is (already fully generic -
# session_id/user_id/history/memory/created_at/updated_at, no product-search
# fields baked in) with its own Mongo collection, mirroring
# app/database/conversation_repository.py's ConversationRepository exactly.
# Kept in a SEPARATE collection from /chat's "conversations" - see the
# approved plan §8 - so /help's memory["awaiting"] shape can never collide
# with /chat's own memory keys, even though both share the same Mongo DB
# (app/core/database.py's get_db(), no new config needed).
help_conversation_repo = ConversationRepository(collection_name="help_conversations", message_collection="help_chat_messages")


class HelpSessionManager:
    """Mirrors app/chat/session_manager.py's SessionManager exactly, just
    pointed at help_conversation_repo instead of chat's conversation_repo -
    SessionManager itself hardcodes the chat repo, so a parallel class (not a
    parametrized constructor) avoids touching /chat's own file for this."""

    async def load_session(self, session_id: Optional[str]) -> Conversation:
        if not session_id:
            session_id = str(uuid.uuid4())
            conv = Conversation(session_id=session_id)
            await help_conversation_repo.save_conversation(conv)
            return conv

        conv = await help_conversation_repo.get_conversation(session_id)
        if not conv:
            conv = Conversation(session_id=session_id)
            await help_conversation_repo.save_conversation(conv)
        return conv

    async def save_session(self, conversation: Conversation) -> None:
        await help_conversation_repo.save_conversation(conversation)

    async def add_message(self, conversation: Conversation, role: str, content: str) -> None:
        conversation.history.append({"role": role, "content": content})
        # Same token-cost rationale as /chat's SessionManager: keep only the
        # last 10 turns.
        if len(conversation.history) > 10:
            conversation.history = conversation.history[-10:]


help_session_manager = HelpSessionManager()
