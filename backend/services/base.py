"""Base service lifecycle abstraction."""


class BaseService:
    """Minimal lifecycle hooks shared by backend services."""

    async def start(self) -> None:
        """Start background resources for the service."""

    async def stop(self) -> None:
        """Stop background resources for the service."""
