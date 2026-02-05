"""
SQLAlchemy models for the OpenClaw Agent Arena database.

This module defines the database schema for:
- User ledger with off-chain balances and nonces
- Game sessions with state snapshots
- Game players with zombie tracking
- Game history for analytics
"""

from datetime import datetime, timezone
from decimal import Decimal
from sqlalchemy import (
    Column, Integer, String, DECIMAL, DateTime, Boolean, 
    Text, ForeignKey, Index, JSON, func
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
import enum

Base = declarative_base()


class PlayerStatus(enum.Enum):
    """Player status in a game."""
    ALIVE = "alive"
    DEAD = "dead"
    ZOMBIE = "zombie"


class GameStatus(enum.Enum):
    """Game session status."""
    WAITING = "waiting"
    ACTIVE = "active"
    FINISHED = "finished"
    ABORTED = "aborted"


class UserLedger(Base):
    """
    User ledger table (primary user account).
    
    Tracks wallet addresses, off-chain balances, and nonces for withdrawals.
    This is the single source of truth for user balances on the backend.
    """
    __tablename__ = 'user_ledger'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    wallet_address = Column(String(42), unique=True, nullable=False, index=True)
    offchain_balance = Column(DECIMAL(36, 18), nullable=False, default=Decimal("0"))
    locked_balance = Column(DECIMAL(36, 18), nullable=False, default=Decimal("0"))  # For in-game funds
    nonce = Column(Integer, nullable=False, default=0)  # For withdrawal signatures
    last_login_date = Column(DateTime, nullable=True)  # UTC timestamp
    last_daily_checkin = Column(DateTime, nullable=True)  # For daily rewards
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())
    
    # Relationships
    game_players = relationship("GamePlayer", back_populates="user")
    
    def __repr__(self):
        return f"<UserLedger(wallet_address='{self.wallet_address}', balance={self.offchain_balance}, locked={self.locked_balance})>"


class GameSession(Base):
    """
    Game session table.
    
    Tracks active and completed game sessions with state snapshots.
    """
    __tablename__ = 'game_sessions'
    
    id = Column(String(64), primary_key=True)  # UUID or custom game ID
    game_type = Column(String(50), nullable=False, index=True)  # 'werewolf'
    status = Column(String(20), nullable=False, default=GameStatus.WAITING.value, index=True)
    winner_team = Column(String(50), nullable=True)  # 'wolf', 'villager', or NULL
    entry_fee = Column(DECIMAL(36, 18), nullable=False, default=Decimal("0"))
    prize_pool = Column(DECIMAL(36, 18), nullable=False, default=Decimal("0"))
    player_count = Column(Integer, nullable=False, default=0)
    state_snapshot = Column(JSON, nullable=True)  # Full game state for recovery
    chat_history = Column(JSON, nullable=True)  # Chat messages for reconnection
    current_phase = Column(String(20), nullable=True)  # Current game phase
    day_count = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())
    
    # Relationships
    players = relationship("GamePlayer", back_populates="game_session", cascade="all, delete-orphan")
    chat_messages = relationship("ChatMessage", back_populates="game_session", cascade="all, delete-orphan")
    
    # Indexes
    __table_args__ = (
        Index('idx_game_sessions_status_type', 'status', 'game_type'),
    )
    
    def __repr__(self):
        return f"<GameSession(id='{self.id}', type='{self.game_type}', status='{self.status}')>"


class GamePlayer(Base):
    """
    Game player table.
    
    Tracks player participation in games with zombie handling.
    """
    __tablename__ = 'game_players'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    game_session_id = Column(String(64), ForeignKey('game_sessions.id'), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey('user_ledger.id'), nullable=False, index=True)
    wallet_address = Column(String(42), nullable=False, index=True)
    socket_sid = Column(String(64), nullable=True)  # Current socket session ID
    nickname = Column(String(50), nullable=False, default="Player")
    role = Column(String(20), nullable=True)  # wolf, seer, witch, hunter, villager
    team = Column(String(20), nullable=True)  # wolf, villager
    status = Column(String(20), nullable=False, default=PlayerStatus.ALIVE.value)
    is_alive = Column(Boolean, nullable=False, default=True)
    consecutive_timeouts = Column(Integer, nullable=False, default=0)  # For zombie detection
    entry_paid = Column(DECIMAL(36, 18), nullable=False, default=Decimal("0"))
    winnings = Column(DECIMAL(36, 18), nullable=False, default=Decimal("0"))
    joined_at = Column(DateTime, nullable=False, server_default=func.now())
    last_action_at = Column(DateTime, nullable=True)
    
    # Relationships
    game_session = relationship("GameSession", back_populates="players")
    user = relationship("UserLedger", back_populates="game_players")
    
    # Indexes
    __table_args__ = (
        Index('idx_game_players_session_wallet', 'game_session_id', 'wallet_address'),
        Index('idx_game_players_socket', 'socket_sid'),
    )
    
    def __repr__(self):
        return f"<GamePlayer(wallet='{self.wallet_address}', role='{self.role}', status='{self.status}')>"
    
    def is_zombie(self) -> bool:
        """Check if player is in zombie mode."""
        return self.status == PlayerStatus.ZOMBIE.value or self.consecutive_timeouts >= 2
    
    def mark_zombie(self):
        """Mark player as zombie."""
        self.status = PlayerStatus.ZOMBIE.value
    
    def recover_from_zombie(self):
        """Recover player from zombie status if they send a valid message."""
        if self.status == PlayerStatus.ZOMBIE.value and self.is_alive:
            self.status = PlayerStatus.ALIVE.value
            self.consecutive_timeouts = 0
    
    def record_timeout(self):
        """Record a timeout and check for zombie transition."""
        self.consecutive_timeouts += 1
        if self.consecutive_timeouts >= 2:
            self.mark_zombie()


class GameHistory(Base):
    """
    Game history table.
    
    Records all completed games for analytics and auditing.
    """
    __tablename__ = 'game_history'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    game_session_id = Column(String(64), nullable=True, index=True)
    game_type = Column(String(50), nullable=False, index=True)  # 'werewolf', 'texas_holdem', etc.
    winner_wallet = Column(String(42), nullable=True, index=True)  # NULL for draws or no winner
    winner_team = Column(String(20), nullable=True)  # wolf, villager
    prize_amount = Column(DECIMAL(36, 18), nullable=True)
    player_count = Column(Integer, nullable=True)
    duration_seconds = Column(Integer, nullable=True)
    was_aborted = Column(Boolean, nullable=False, default=False)
    timestamp = Column(DateTime, nullable=False, server_default=func.now(), index=True)
    
    def __repr__(self):
        return f"<GameHistory(game_type='{self.game_type}', winner='{self.winner_wallet}')>"


class ChatMessage(Base):
    """
    Chat message table.
    
    Stores all chat messages for games with persistence across sessions.
    """
    __tablename__ = 'chat_messages'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    game_session_id = Column(String(64), ForeignKey('game_sessions.id'), nullable=False, index=True)
    player_wallet = Column(String(42), nullable=False, index=True)  # Player who sent the message
    nickname = Column(String(50), nullable=False, default="Player")
    message = Column(Text, nullable=False)
    message_type = Column(String(20), nullable=False, default='chat')  # 'chat', 'action', 'system'
    message_metadata = Column(JSON, nullable=True)  # Additional message metadata (renamed to avoid SQLAlchemy conflict)
    timestamp = Column(DateTime, nullable=False, server_default=func.now(), index=True)
    
    # Relationships
    game_session = relationship("GameSession", back_populates="chat_messages")
    
    # Indexes
    __table_args__ = (
        Index('idx_chat_messages_game_time', 'game_session_id', 'timestamp'),
    )
    
    def __repr__(self):
        return f"<ChatMessage(game='{self.game_session_id}', player='{self.nickname}', type='{self.message_type}')>"


# Legacy User model for backwards compatibility
class User(Base):
    """
    Legacy user account table (deprecated, use UserLedger instead).
    
    Kept for backwards compatibility with existing poker game.
    """
    __tablename__ = 'users'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    wallet_address = Column(String(42), unique=True, nullable=False, index=True)
    balance = Column(DECIMAL(20, 8), nullable=False, default=0)  # Virtual balance
    last_login_date = Column(DateTime, nullable=True)  # UTC timestamp
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    
    def __repr__(self):
        return f"<User(wallet_address='{self.wallet_address}', balance={self.balance})>"
