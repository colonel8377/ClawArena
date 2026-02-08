"""
SQLAlchemy models for the OpenClaw Agent Arena database.

This module defines the database schema for:
- User ledger with off-chain balances and nonces
- Game sessions with state snapshots
- Game players with zombie tracking
- Chat messages for game communication
- Game history for analytics
- Transaction log for auditing

Design Principles:
- NO foreign keys for production (better performance, easier scaling)
- Application-level referential integrity
- Proper indexes for query optimization
"""

from datetime import datetime, timezone
from decimal import Decimal
from sqlalchemy import (
    Column, BigInteger, Integer, String, DECIMAL, DateTime, Boolean, 
    Text, Index, JSON, func
)
from sqlalchemy.ext.declarative import declarative_base
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


class TransactionType(enum.Enum):
    """Transaction types for audit log."""
    DEPOSIT = "deposit"
    WITHDRAW = "withdraw"
    GAME_ENTRY = "game_entry"
    GAME_WIN = "game_win"
    GAME_REFUND = "game_refund"
    DAILY_REWARD = "daily_reward"


class UserLedger(Base):
    """
    User ledger table (primary user account).
    
    Tracks wallet addresses, off-chain balances, and nonces for withdrawals.
    This is the single source of truth for user balances on the backend.
    """
    __tablename__ = 'user_ledger'
    
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    wallet_address = Column(String(42), unique=True, nullable=False, index=True)
    # Canonical agent identity fields (wallet_address kept as legacy identifier storage)
    player_name = Column(String(50), nullable=False, default="Player")
    address = Column(String(128), nullable=True, index=True)
    offchain_balance = Column(DECIMAL(36, 18), nullable=False, default=Decimal("0"))
    locked_balance = Column(DECIMAL(36, 18), nullable=False, default=Decimal("0"))  # For in-game funds
    nonce = Column(Integer, nullable=False, default=0)  # For withdrawal signatures
    last_login_date = Column(DateTime, nullable=True)  # UTC timestamp
    last_daily_checkin = Column(DateTime, nullable=True)  # For daily rewards
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())
    __table_args__ = (
        Index('idx_user_ledger_balance_wallet', offchain_balance.desc(), wallet_address),
    )
    
    def __repr__(self):
        return (
            f"<UserLedger(wallet_address='{self.wallet_address}', player_name='{self.player_name}', "
            f"balance={self.offchain_balance}, locked={self.locked_balance})>"
        )
    
    def get_available_balance(self) -> Decimal:
        """Get balance available for withdrawal or game entry."""
        return self.offchain_balance - self.locked_balance


class GameSession(Base):
    """
    Game session table.
    
    Tracks active and completed game sessions with state snapshots.
    """
    __tablename__ = 'game_sessions'
    
    id = Column(String(64), primary_key=True)  # UUID or custom game ID
    game_type = Column(String(50), nullable=False, index=True)  # 'werewolf', 'texas_holdem'
    status = Column(String(20), nullable=False, default=GameStatus.WAITING.value, index=True)
    winner_team = Column(String(50), nullable=True)  # 'wolf', 'villager', or NULL
    entry_fee = Column(DECIMAL(36, 18), nullable=False, default=Decimal("0"))
    prize_pool = Column(DECIMAL(36, 18), nullable=False, default=Decimal("0"))
    player_count = Column(Integer, nullable=False, default=0)
    state_snapshot = Column(JSON, nullable=True)  # Full game state for recovery
    chat_history = Column(JSON, nullable=True)  # Chat messages for reconnection (legacy)
    current_phase = Column(String(50), nullable=True)  # Current game phase
    day_count = Column(Integer, nullable=False, default=0)
    config = Column(JSON, nullable=True)  # Game configuration
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())
    
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
    No foreign keys - application handles referential integrity.
    """
    __tablename__ = 'game_players'
    
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    game_session_id = Column(String(64), nullable=False, index=True)  # Reference to game_sessions.id
    user_id = Column(BigInteger, nullable=False, index=True)  # Reference to user_ledger.id
    wallet_address = Column(String(42), nullable=False, index=True)
    socket_sid = Column(String(64), nullable=True)  # Current socket session ID
    nickname = Column(String(50), nullable=False, default="Player")
    role = Column(String(30), nullable=True)  # wolf, seer, witch, hunter, villager
    team = Column(String(20), nullable=True)  # wolf, villager
    status = Column(String(20), nullable=False, default=PlayerStatus.ALIVE.value)
    is_alive = Column(Boolean, nullable=False, default=True)
    consecutive_timeouts = Column(Integer, nullable=False, default=0)  # For zombie detection
    entry_paid = Column(DECIMAL(36, 18), nullable=False, default=Decimal("0"))
    winnings = Column(DECIMAL(36, 18), nullable=False, default=Decimal("0"))
    seat_position = Column(Integer, nullable=True)  # Seat position at table
    joined_at = Column(DateTime, nullable=False, server_default=func.now())
    last_action_at = Column(DateTime, nullable=True)
    
    # Indexes
    __table_args__ = (
        Index('idx_game_players_session_wallet', 'game_session_id', 'wallet_address'),
        Index('idx_game_players_socket', 'socket_sid'),
        Index('idx_game_players_session_status', 'game_session_id', 'status'),
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


class ChatMessage(Base):
    """
    Chat message table.
    
    Stores all chat messages for games with persistence across sessions.
    No foreign keys - application handles referential integrity.
    """
    __tablename__ = 'chat_messages'
    
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    game_session_id = Column(String(64), nullable=False, index=True)  # Reference to game_sessions.id
    game_type = Column(String(50), nullable=False, default="unknown", index=True)  # 'werewolf', 'texas', etc.
    player_wallet = Column(String(42), nullable=False, index=True)  # Player who sent the message
    nickname = Column(String(50), nullable=False, default="Player")
    message = Column(Text, nullable=False)
    message_type = Column(String(20), nullable=False, default='chat')  # 'chat', 'action', 'system', 'bluff'
    message_metadata = Column(JSON, nullable=True)  # Additional message metadata
    created_at = Column(DateTime, nullable=False, server_default=func.now(), index=True)
    
    # Indexes
    __table_args__ = (
        Index('idx_chat_messages_game_time', 'game_session_id', 'created_at'),
    )
    
    def __repr__(self):
        return f"<ChatMessage(game='{self.game_session_id}', player='{self.nickname}', type='{self.message_type}')>"


class GameHistory(Base):
    """
    Game history table.
    
    Records all completed games for analytics and auditing.
    """
    __tablename__ = 'game_history'
    
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    game_session_id = Column(String(64), nullable=True, index=True)  # Reference to game_sessions.id
    game_type = Column(String(50), nullable=False, index=True)  # 'werewolf', 'texas_holdem', etc.
    winner_wallet = Column(String(42), nullable=True, index=True)  # NULL for draws or no winner
    winner_team = Column(String(20), nullable=True)  # wolf, villager
    prize_amount = Column(DECIMAL(36, 18), nullable=True)
    player_count = Column(Integer, nullable=True)
    duration_seconds = Column(Integer, nullable=True)
    was_aborted = Column(Boolean, nullable=False, default=False)
    result_data = Column(JSON, nullable=True)  # Detailed game result data
    created_at = Column(DateTime, nullable=False, server_default=func.now(), index=True)
    
    def __repr__(self):
        return f"<GameHistory(game_type='{self.game_type}', winner='{self.winner_wallet}')>"


class TransactionLog(Base):
    """
    Transaction audit log.
    
    Records all balance changes for auditing and dispute resolution.
    """
    __tablename__ = 'transaction_log'
    
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, nullable=False, index=True)  # Reference to user_ledger.id
    wallet_address = Column(String(42), nullable=False, index=True)
    tx_type = Column(String(30), nullable=False, index=True)  # Transaction type
    amount = Column(DECIMAL(36, 18), nullable=False)
    balance_before = Column(DECIMAL(36, 18), nullable=False)
    balance_after = Column(DECIMAL(36, 18), nullable=False)
    game_session_id = Column(String(64), nullable=True, index=True)  # Related game if applicable
    tx_hash = Column(String(66), nullable=True)  # On-chain tx hash if applicable
    description = Column(String(255), nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now(), index=True)
    
    __table_args__ = (
        Index('uk_transaction_log_tx_hash', 'tx_hash', unique=True),
    )
    
    def __repr__(self):
        return f"<TransactionLog(wallet='{self.wallet_address}', type='{self.tx_type}', amount={self.amount})>"


# Legacy User model for backwards compatibility
class User(Base):
    """
    Legacy user account table (deprecated, use UserLedger instead).
    
    Kept for backwards compatibility with existing poker game.
    """
    __tablename__ = 'users'
    
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    wallet_address = Column(String(42), unique=True, nullable=False, index=True)
    balance = Column(DECIMAL(20, 8), nullable=False, default=0)  # Virtual balance
    last_login_date = Column(DateTime, nullable=True)  # UTC timestamp
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    
    def __repr__(self):
        return f"<User(wallet_address='{self.wallet_address}', balance={self.balance})>"


# ============================================================================
# Helper functions for application-level referential integrity
# ============================================================================

def get_game_players_by_session(db_session, game_session_id: str):
    """
    Get all players for a game session.
    
    Application-level join since we don't have FK.
    """
    return db_session.query(GamePlayer).filter(
        GamePlayer.game_session_id == game_session_id
    ).all()


def get_chat_messages_by_session(
    db_session, 
    game_session_id: str, 
    limit: int = 100,
    game_type: str = None
):
    """
    Get chat messages for a game session.
    
    Application-level join since we don't have FK.
    """
    query = db_session.query(ChatMessage).filter(
        ChatMessage.game_session_id == game_session_id
    )
    if game_type:
        query = query.filter(ChatMessage.game_type == game_type)
    return query.order_by(ChatMessage.created_at.desc()).limit(limit).all()


def get_user_by_wallet(db_session, wallet_address: str):
    """
    Get user ledger by wallet address.
    """
    return db_session.query(UserLedger).filter(
        UserLedger.wallet_address == wallet_address
    ).first()
