from typing import Any, Dict, Optional

from backend.config.settings import get_settings


class AnnouncementService:
    @staticmethod
    def get_current() -> Optional[Dict[str, Any]]:
        settings = get_settings()
        message = getattr(settings, "announcement_message", "")
        if not message:
            return None
        return {
            "id": getattr(settings, "announcement_id", ""),
            "level": getattr(settings, "announcement_level", "info"),
            "message": message,
        }
