"""
Werewolf game persistence models (async SQLAlchemy).

This module isolates the data layer for the Werewolf engine. It defines the
minimal tables required to reconstruct game state after a restart:
- GameSession: high-level state and pending night outcomes
- GamePlayer: roster with role assignments and per-role resources
- ActionLog: append-only audit trail of every action
"""

import enum
from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.ext.asyncio import AsyncAttrs
from sqlalchemy.orm import declarative_base, relationship


class PhaseEnum(str, enum.Enum):
    """Game state machine phases."""

    NIGHT_WOLF = "NIGHT_WOLF"
    NIGHT_SEER = "NIGHT_SEER"
    NIGHT_WITCH = "NIGHT_WITCH"
    DAY_DISCUSS = "DAY_DISCUSS"
    DAY_VOTE = "DAY_VOTE"
    DEATH_RATTLE = "DEATH_RATTLE"  # Hunter's final shot
    FINISHED = "FINISHED"


class RoleEnum(str, enum.Enum):
    """Player roles."""

    WEREWOLF = "WEREWOLF"
    VILLAGER = "VILLAGER"
    SEER = "SEER"
    WITCH = "WITCH"
    HUNTER = "HUNTER"


Base = declarative_base(cls=AsyncAttrs)


def _default_flags(role: RoleEnum) -> Dict[str, Any]:
    """Initialize status flags with role-specific resources."""

    flags = {"antidote_used": False, "poison_used": False, "gun_status": "loaded"}
    if role != RoleEnum.WITCH:
        flags["antidote_used"] = True
        flags["poison_used"] = True
    if role != RoleEnum.HUNTER:
        flags["gun_status"] = "unavailable"
    return flags


class GameSession(Base):
    """Top-level persisted game state."""

    __tablename__ = "werewolf_game_session"

    id = Column(Integer, primary_key=True, autoincrement=True)
    phase = Column(Enum(PhaseEnum), nullable=False, default=PhaseEnum.NIGHT_WOLF)
    turn_counter = Column(Integer, nullable=False, default=1)
    pending_death = Column(Integer, ForeignKey("werewolf_game_player.id"), nullable=True)
    pending_poison = Column(Integer, ForeignKey("werewolf_game_player.id"), nullable=True)
    # Extra state (e.g., active hunter id) without expanding columns
    state_flags = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    players = relationship(
        "GamePlayer",
        back_populates="session",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    actions = relationship(
        "ActionLog",
        back_populates="session",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="ActionLog.id",
    )


class GamePlayer(Base):
    """Persisted player roster."""

    __tablename__ = "werewolf_game_player"
    __table_args__ = (UniqueConstraint("session_id", "agent_id", name="uq_agent_per_game"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(Integer, ForeignKey("werewolf_game_session.id"), nullable=False)
    agent_id = Column(String(64), nullable=False, index=True)
    wallet_address = Column(String(64), nullable=True)
    role = Column(Enum(RoleEnum), nullable=False)
    is_alive = Column(Boolean, default=True, nullable=False)
    status_flags = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    session = relationship("GameSession", back_populates="players")

    def initialize_flags(self):
        """Ensure status_flags is populated for new players."""
        if not self.status_flags:
            self.status_flags = _default_flags(self.role)


class ActionLog(Base):
    """Append-only audit log of actions for replay/debugging."""

    __tablename__ = "werewolf_action_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(Integer, ForeignKey("werewolf_game_session.id"), nullable=False)
    player_id = Column(Integer, ForeignKey("werewolf_game_player.id"), nullable=True)
    action_type = Column(String(50), nullable=False)
    target_player_id = Column(Integer, ForeignKey("werewolf_game_player.id"), nullable=True)
    payload = Column(JSON, nullable=True)
    error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    session = relationship("GameSession", back_populates="actions")
