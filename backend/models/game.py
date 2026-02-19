from decimal import Decimal

from sqlalchemy import DateTime, Integer, func, Numeric
from sqlalchemy.orm import Mapped, mapped_column

from backend.models.base import Base


class Game(Base):
    __tablename__ = "games"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    game_type: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[int] = mapped_column(Integer, nullable=False)
    prize_pool_tokens: Mapped[Decimal] = mapped_column(Numeric(38, 6), default=Decimal("0.000000"), nullable=False)
    created_at: Mapped[str] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[str] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)
    ended_at: Mapped[str | None] = mapped_column(DateTime, nullable=True)
