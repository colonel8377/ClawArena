from sqlalchemy.exc import IntegrityError

from backend.models.system_event import SystemEventLog
from backend.repositories.db import db_session
from backend.utils.log import get_logger

logger = get_logger(__name__)


class SystemEventRepo:
    @staticmethod
    def insert(event_id: str, event_type: str, message: str, payload: dict, agent_id: int | None, agent_name: str | None) -> None:
        try:
            with db_session() as session:
                session.add(
                    SystemEventLog(
                        event_id=event_id,
                        event_type=event_type,
                        message=message,
                        payload_json=payload,
                        agent_id=agent_id,
                        agent_name=agent_name,
                    )
                )
        except IntegrityError:
            logger.info("system_event_duplicate event_id=%s", event_id)
