from sqlalchemy.exc import IntegrityError

from backend.models.chat_message import ChatMessage
from backend.repositories.db import db_session
from backend.utils.log import get_logger

logger = get_logger(__name__)


class ChatMessageRepo:
    @staticmethod
    def insert(
        stream_id: str,
        event_id: str | None,
        action_id: str | None,
        room_id: int,
        game_id: int,
        game_type: int,
        channel: int,
        sender_id: int | None,
        sender_name: str | None,
        content: str,
        ts_ms: int,
    ) -> None:
        try:
            with db_session() as session:
                session.add(
                    ChatMessage(
                        stream_id=stream_id,
                        event_id=event_id,
                        action_id=action_id,
                        room_id=room_id,
                        game_id=game_id,
                        game_type=game_type,
                        channel=channel,
                        sender_id=sender_id,
                        sender_name=sender_name,
                        content=content,
                        ts_ms=ts_ms,
                    )
                )
        except IntegrityError:
            logger.info("chat_message_duplicate stream_id=%s", stream_id)
