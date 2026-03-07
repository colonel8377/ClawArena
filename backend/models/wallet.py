from decimal import Decimal

from sqlalchemy import BigInteger, DateTime, Integer, String, func, Numeric
from sqlalchemy.orm import Mapped, mapped_column

from backend.models.base import Base


class AgentWallet(Base):
    __tablename__ = "agent_wallets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    agent_id: Mapped[int] = mapped_column(Integer, unique=True, nullable=False)
    agent_name: Mapped[str] = mapped_column(String(64), nullable=False)
    token_balance: Mapped[Decimal] = mapped_column(Numeric(38, 6), default=Decimal("0.000000"), nullable=False)
    chip_balance: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    token_locked: Mapped[Decimal] = mapped_column(Numeric(38, 6), default=Decimal("0.000000"), nullable=False)
    created_at: Mapped[str] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[str] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)
