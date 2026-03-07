from sqlalchemy.exc import IntegrityError

from backend.models.game_event import GameEventLog
from backend.repositories.db import db_session
from backend.utils.log import get_logger

logger = get_logger(__name__)


class EventRepo:
    @staticmethod
    def insert_game_event(
        event_id: str,
        game_id: int,
        room_id: int,
        actor_id: int | None,
        actor_name: str | None,
        phase: str,
        action_type: str,
        payload: dict,
    ) -> None:
        try:
            with db_session() as session:
                session.add(
                    GameEventLog(
                        event_id=event_id,
                        game_id=game_id,
                        room_id=room_id,
                        actor_id=actor_id,
                        actor_name=actor_name,
                        phase=phase,
                        action_type=action_type,
                        payload_json=payload,
                    )
                )
        except IntegrityError:
            logger.info("game_event_duplicate event_id=%s", event_id)
