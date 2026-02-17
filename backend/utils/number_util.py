from decimal import Decimal
from typing import Any


def _to_decimal_safe(value: Any) -> Decimal:
    """Best-effort Decimal conversion for cache/DB values."""
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except Exception:
        return Decimal("0")