"""
SQLAlchemy models for the Agent Arena database.

This module defines the database schema for:
- User accounts with virtual balances
- Game history tracking
"""

from datetime import datetime
from sqlalchemy import Column, Integer, String, DECIMAL, DateTime, Boolean, Enum
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()


class User(Base):
    """
    User account table.
    
    Tracks user wallet addresses, virtual balances, and login information.
    """
    __tablename__ = 'users'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    wallet_address = Column(String(42), unique=True, nullable=False, index=True)
    balance = Column(DECIMAL(20, 8), nullable=False, default=0)  # Virtual balance
    last_login_date = Column(DateTime, nullable=True)  # UTC timestamp
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    
    def __repr__(self):
        return f"<User(wallet_address='{self.wallet_address}', balance={self.balance})>"


class GameHistory(Base):
    """
    Game history table.
    
    Records all completed games for analytics and auditing.
    """
    __tablename__ = 'game_history'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    game_type = Column(String(50), nullable=False, index=True)  # 'werewolf', 'texas_holdem', etc.
    winner_wallet = Column(String(42), nullable=True, index=True)  # NULL for draws or no winner
    timestamp = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    
    def __repr__(self):
        return f"<GameHistory(game_type='{self.game_type}', winner='{self.winner_wallet}')>"
