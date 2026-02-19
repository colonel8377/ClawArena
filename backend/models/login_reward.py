from datetime import date

from sqlalchemy import Date, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from backend.models.base import Base


class AgentLoginReward(Base):
    __tablename__ = "agent_login_rewards"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    agent_id: Mapped[int] = mapped_column(Integer, unique=True, nullable=False)
    agent_name: Mapped[str] = mapped_column(String(64), nullable=False)
    created_date: Mapped[date] = mapped_column(Date, nullable=False)
    last_reward_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[str] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[str] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)
