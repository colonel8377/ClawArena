"""
User account management with MySQL storage.

This module handles:
- User registration
- Daily login rewards (UTC-based)
- Balance management
- Transactional operations
"""

from datetime import datetime, date
from decimal import Decimal
from typing import Optional, Dict
from sqlalchemy.orm import Session

from backend.database.models import User
from backend.database.connection import get_db_session


# Configuration
DAILY_LOGIN_REWARD = Decimal("100.0")  # 100 tokens per day


def register_user(wallet_address: str) -> Dict:
    """
    Register a new user in the database.
    
    Args:
        wallet_address: Ethereum wallet address (should be checksummed)
        
    Returns:
        Dict with status and user information
        
    Raises:
        ValueError: If wallet address is invalid
    """
    if not wallet_address or len(wallet_address) != 42 or not wallet_address.startswith('0x'):
        raise ValueError("Invalid wallet address format")
    
    with get_db_session() as db:
        # Check if user already exists
        existing_user = db.query(User).filter_by(wallet_address=wallet_address).first()
        
        if existing_user:
            return {
                'status': 'already_registered',
                'user': {
                    'wallet_address': existing_user.wallet_address,
                    'balance': float(existing_user.balance),
                    'created_at': existing_user.created_at.isoformat()
                }
            }
        
        # Create new user with initial balance
        new_user = User(
            wallet_address=wallet_address,
            balance=DAILY_LOGIN_REWARD,  # Initial reward
            last_login_date=datetime.utcnow(),
            created_at=datetime.utcnow()
        )
        
        db.add(new_user)
        db.commit()
        db.refresh(new_user)
        
        return {
            'status': 'registered',
            'user': {
                'wallet_address': new_user.wallet_address,
                'balance': float(new_user.balance),
                'created_at': new_user.created_at.isoformat()
            }
        }


def handle_login(wallet_address: str) -> Dict:
    """
    Handle user login with daily reward check.
    
    Checks if it's a new UTC day since last login. If yes, adds tokens
    to virtual balance and updates last_login_date.
    
    Args:
        wallet_address: Ethereum wallet address
        
    Returns:
        Dict with login status and reward information
        
    Raises:
        ValueError: If user not found
    """
    with get_db_session() as db:
        user = db.query(User).filter_by(wallet_address=wallet_address).first()
        
        if not user:
            raise ValueError(f"User not found: {wallet_address}")
        
        now_utc = datetime.utcnow()
        today_utc = now_utc.date()
        
        # Check if last login was on a different day
        reward_granted = False
        if user.last_login_date is None or user.last_login_date.date() < today_utc:
            # Grant daily reward
            user.balance += DAILY_LOGIN_REWARD
            user.last_login_date = now_utc
            reward_granted = True
            db.commit()
            db.refresh(user)
        
        return {
            'status': 'success',
            'reward_granted': reward_granted,
            'reward_amount': float(DAILY_LOGIN_REWARD) if reward_granted else 0,
            'user': {
                'wallet_address': user.wallet_address,
                'balance': float(user.balance),
                'last_login_date': user.last_login_date.isoformat() if user.last_login_date else None
            }
        }


def deduct_balance(wallet_address: str, amount: Decimal) -> Dict:
    """
    Deduct balance from user account (e.g., for game entry fee).
    
    This is a transactional operation - either succeeds completely or fails.
    
    Args:
        wallet_address: Ethereum wallet address
        amount: Amount to deduct
        
    Returns:
        Dict with operation status
        
    Raises:
        ValueError: If insufficient balance or user not found
    """
    if amount <= 0:
        raise ValueError("Amount must be positive")
    
    with get_db_session() as db:
        user = db.query(User).filter_by(wallet_address=wallet_address).first()
        
        if not user:
            raise ValueError(f"User not found: {wallet_address}")
        
        if user.balance < amount:
            raise ValueError(
                f"Insufficient balance. Required: {amount}, Available: {user.balance}"
            )
        
        # Deduct balance
        user.balance -= amount
        db.commit()
        db.refresh(user)
        
        return {
            'status': 'success',
            'deducted': float(amount),
            'new_balance': float(user.balance)
        }


def add_balance(wallet_address: str, amount: Decimal) -> Dict:
    """
    Add balance to user account (e.g., for game winnings).
    
    Args:
        wallet_address: Ethereum wallet address
        amount: Amount to add
        
    Returns:
        Dict with operation status
        
    Raises:
        ValueError: If user not found
    """
    if amount <= 0:
        raise ValueError("Amount must be positive")
    
    with get_db_session() as db:
        user = db.query(User).filter_by(wallet_address=wallet_address).first()
        
        if not user:
            raise ValueError(f"User not found: {wallet_address}")
        
        # Add balance
        user.balance += amount
        db.commit()
        db.refresh(user)
        
        return {
            'status': 'success',
            'added': float(amount),
            'new_balance': float(user.balance)
        }


def get_balance(wallet_address: str) -> Decimal:
    """
    Get current balance for a user.
    
    Args:
        wallet_address: Ethereum wallet address
        
    Returns:
        Current balance
        
    Raises:
        ValueError: If user not found
    """
    with get_db_session() as db:
        user = db.query(User).filter_by(wallet_address=wallet_address).first()
        
        if not user:
            raise ValueError(f"User not found: {wallet_address}")
        
        return user.balance
