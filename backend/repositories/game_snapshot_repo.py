from sqlalchemy.exc import IntegrityError

from backend.models.game_snapshot import GameSnapshot
from backend.repositories.db import db_session
from backend.utils.log import get_logger

logger = get_logger(__name__)


class GameSnapshotRepo:
    @staticmethod
    def insert(game_id: int, room_id: int, phase: str, state_json: str) -> None:
        try:
            with db_session() as session:
                session.add(
                    GameSnapshot(
                        game_id=game_id,
                        room_id=room_id,
                        phase=phase,
                        state_json=state_json,
                    )
                )
        except IntegrityError:
            logger.info("game_snapshot_duplicate room_id=%s phase=%s", room_id, phase)
