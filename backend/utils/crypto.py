import hashlib

from backend.config.settings import get_settings


def hash_secret(secret: str) -> str:
    settings = get_settings()
    pepper = settings.secret_pepper or ""
    payload = f"{secret}{pepper}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
