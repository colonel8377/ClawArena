from backend.config.settings import get_settings
from backend.workers.saq_client import get_queue
from backend.workers.tasks import (
    persist_chat_message,
    persist_game_event,
    persist_game_snapshot,
    persist_system_event,
)


def get_saq_settings():
    config = get_settings()
    return {
        "queue": get_queue(),
        "functions": [persist_system_event, persist_game_event, persist_game_snapshot, persist_chat_message],
        "concurrency": config.saq_concurrency,
    }
