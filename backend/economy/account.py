"""
User account management with MySQL storage.

This module handles:
- User registration
- Daily login rewards (UTC-based)
- Balance management (atomic operations)
- Locked balance for in-game funds
- Transactional operations
- Local debug mode support (unlimited funds)
"""

from datetime import datetime, date
from decimal import Decimal
from typing import Optional, Dict
from sqlalchemy.orm import Session
from sqlalchemy import text

from ..database.models import UserLedger
from ..database.connection import get_db_session
from ..config import is_local_debug_mode, get_debug_balance


# Configuration
DAILY_LOGIN_REWARD = Decimal("100.0")  # 100 tokens per day


def register_user(wallet_address: str) -> Dict:
    """
    Register a new user in the database using UserLedger.
    
    In local debug mode, users get unlimited funds (configured via LOCAL_DEBUG_BALANCE).
    
    Args:
        wallet_address: Ethereum wallet address (should be checksummed)
        
    Returns:
        Dict with status and user information
        
    Raises:
        ValueError: If wallet address is invalid
    """
    if not wallet_address or len(wallet_address) != 42 or not wallet_address.startswith('0x'):
        raise ValueError("Invalid wallet address format")
    
    # Use debug balance in local debug mode
    initial_balance = get_debug_balance() if is_local_debug_mode() else DAILY_LOGIN_REWARD
    
    with get_db_session() as db:
        # Check if user already exists
        existing_user = db.query(UserLedger).filter_by(wallet_address=wallet_address).first()
        
        if existing_user:
            # In local debug mode, always ensure user has unlimited funds
            if is_local_debug_mode() and existing_user.offchain_balance < get_debug_balance():
                existing_user.offchain_balance = get_debug_balance()
                db.commit()
                db.refresh(existing_user)
            
            return {
                'status': 'already_registered',
                'user': {
                    'wallet_address': existing_user.wallet_address,
                    'balance': float(existing_user.offchain_balance),
                    'locked_balance': float(existing_user.locked_balance),
                    'created_at': existing_user.created_at.isoformat()
                }
            }
        
        # Create new user with initial balance
        new_user = UserLedger(
            wallet_address=wallet_address,
            offchain_balance=initial_balance,
            locked_balance=Decimal("0"),
            last_login_date=datetime.utcnow()
        )
        
        db.add(new_user)
        db.commit()
        db.refresh(new_user)
        
        return {
            'status': 'registered',
            'user': {
                'wallet_address': new_user.wallet_address,
                'balance': float(new_user.offchain_balance),
                'locked_balance': float(new_user.locked_balance),
                'created_at': new_user.created_at.isoformat()
            },
            'local_debug_mode': is_local_debug_mode()
        }


def handle_login(wallet_address: str) -> Dict:
    """
    Handle user login with daily reward check using UserLedger.
    
    In local debug mode, always ensures user has unlimited funds.
    
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
        user = db.query(UserLedger).filter_by(wallet_address=wallet_address).first()
        
        if not user:
            raise ValueError(f"User not found: {wallet_address}")
        
        now_utc = datetime.utcnow()
        today_utc = now_utc.date()
        
        # In local debug mode, always ensure user has unlimited funds
        if is_local_debug_mode():
            if user.offchain_balance < get_debug_balance():
                user.offchain_balance = get_debug_balance()
            user.last_login_date = now_utc
            db.commit()
            db.refresh(user)
            
            return {
                'status': 'success',
                'reward_granted': True,
                'reward_amount': float(get_debug_balance()),
                'local_debug_mode': True,
                'user': {
                    'wallet_address': user.wallet_address,
                    'balance': float(user.offchain_balance),
                    'locked_balance': float(user.locked_balance),
                    'last_login_date': user.last_login_date.isoformat() if user.last_login_date else None
                }
            }
        
        # Check if last login was on a different day
        reward_granted = False
        if user.last_login_date is None or user.last_login_date.date() < today_utc:
            # Grant daily reward using atomic operation - use str() to maintain precision
            db.execute(
                text("UPDATE user_ledger SET offchain_balance = offchain_balance + :reward WHERE wallet_address = :wallet"),
                {"reward": str(DAILY_LOGIN_REWARD), "wallet": wallet_address}
            )
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
                'balance': float(user.offchain_balance),
                'locked_balance': float(user.locked_balance),
                'last_login_date': user.last_login_date.isoformat() if user.last_login_date else None
            }
        }


def deduct_balance(wallet_address: str, amount: Decimal) -> Dict:
    """
    Deduct balance from user account using atomic SQL operation.
    
    In local debug mode, skips balance checks and always succeeds.
    
    This uses database-level atomic UPDATE to prevent race conditions during
    concurrent deductions. The balance check and update happen atomically.
    
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
        user = db.query(UserLedger).filter_by(wallet_address=wallet_address).first()
        
        if not user:
            raise ValueError(f"User not found: {wallet_address}")
        
        # In local debug mode, skip balance check and keep balance high
        if is_local_debug_mode():
            # Don't actually deduct, keep unlimited funds
            return {
                'status': 'success',
                'deducted': float(amount),
                'new_balance': float(user.offchain_balance),
                'locked_balance': float(user.locked_balance),
                'local_debug_mode': True
            }
        
        # Atomic balance deduction using SQL UPDATE
        # This prevents race conditions by doing check and update in single query
        result = db.execute(
            text("""
                UPDATE user_ledger 
                SET offchain_balance = offchain_balance - :amount 
                WHERE wallet_address = :wallet 
                AND offchain_balance >= :amount
            """),
            {"amount": str(amount), "wallet": wallet_address}
        )
        db.commit()
        
        # Check if update succeeded (row was updated)
        if result.rowcount == 0:
            # Refresh user to get current balance
            db.refresh(user)
            raise ValueError(
                f"Insufficient balance. Required: {amount}, Available: {user.offchain_balance}"
            )
        
        # Refresh to get updated balance
        db.refresh(user)
        
        return {
            'status': 'success',
            'deducted': float(amount),
            'new_balance': float(user.offchain_balance),
            'locked_balance': float(user.locked_balance)
        }


def add_balance(wallet_address: str, amount: Decimal) -> Dict:
    """
    Add balance to user account using atomic SQL operation.
    
    This uses database-level atomic UPDATE to prevent race conditions during
    concurrent additions (e.g., multiple game winnings).
    
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
        user = db.query(UserLedger).filter_by(wallet_address=wallet_address).first()
        
        if not user:
            raise ValueError(f"User not found: {wallet_address}")
        
        # Atomic balance addition using SQL UPDATE
        db.execute(
            text("UPDATE user_ledger SET offchain_balance = offchain_balance + :amount WHERE wallet_address = :wallet"),
            {"amount": str(amount), "wallet": wallet_address}
        )
        db.commit()
        
        # Refresh to get updated balance
        db.refresh(user)
        
        return {
            'status': 'success',
            'added': float(amount),
            'new_balance': float(user.offchain_balance),
            'locked_balance': float(user.locked_balance)
        }


def get_balance(wallet_address: str) -> Decimal:
    """
    Get current balance for a user from UserLedger.
    
    In local debug mode, returns the debug balance (unlimited funds).
    
    Args:
        wallet_address: Ethereum wallet address
        
    Returns:
        Current balance
        
    Raises:
        ValueError: If user not found
    """
    # In local debug mode, always return unlimited funds
    if is_local_debug_mode():
        return get_debug_balance()
    
    with get_db_session() as db:
        user = db.query(UserLedger).filter_by(wallet_address=wallet_address).first()
        
        if not user:
            raise ValueError(f"User not found: {wallet_address}")
        
        return user.offchain_balance


def lock_balance(wallet_address: str, amount: Decimal) -> Dict:
    """
    Lock balance for in-game use (prevents double-spending).
    
    Atomically moves funds from offchain_balance to locked_balance.
    
    Args:
        wallet_address: Ethereum wallet address
        amount: Amount to lock
        
    Returns:
        Dict with operation status
        
    Raises:
        ValueError: If insufficient balance or user not found
    """
    if amount <= 0:
        raise ValueError("Amount must be positive")
    
    with get_db_session() as db:
        user = db.query(UserLedger).filter_by(wallet_address=wallet_address).first()
        
        if not user:
            raise ValueError(f"User not found: {wallet_address}")
        
        # In local debug mode, skip balance check
        if is_local_debug_mode():
            return {
                'status': 'success',
                'locked': float(amount),
                'new_balance': float(user.offchain_balance),
                'new_locked_balance': float(user.locked_balance),
                'local_debug_mode': True
            }
        
        # Atomic lock operation: deduct from offchain_balance and add to locked_balance
        result = db.execute(
            text("""
                UPDATE user_ledger 
                SET offchain_balance = offchain_balance - :amount,
                    locked_balance = locked_balance + :amount
                WHERE wallet_address = :wallet 
                AND offchain_balance >= :amount
            """),
            {"amount": str(amount), "wallet": wallet_address}
        )
        db.commit()
        
        if result.rowcount == 0:
            db.refresh(user)
            raise ValueError(
                f"Insufficient balance to lock. Required: {amount}, Available: {user.offchain_balance}"
            )
        
        db.refresh(user)
        
        return {
            'status': 'success',
            'locked': float(amount),
            'new_balance': float(user.offchain_balance),
            'new_locked_balance': float(user.locked_balance)
        }


def unlock_balance(wallet_address: str, amount: Decimal) -> Dict:
    """
    Unlock balance after game completion.
    
    Atomically moves funds from locked_balance back to offchain_balance.
    
    Args:
        wallet_address: Ethereum wallet address
        amount: Amount to unlock
        
    Returns:
        Dict with operation status
        
    Raises:
        ValueError: If insufficient locked balance or user not found
    """
    if amount <= 0:
        raise ValueError("Amount must be positive")
    
    with get_db_session() as db:
        user = db.query(UserLedger).filter_by(wallet_address=wallet_address).first()
        
        if not user:
            raise ValueError(f"User not found: {wallet_address}")
        
        # In local debug mode, skip checks
        if is_local_debug_mode():
            return {
                'status': 'success',
                'unlocked': float(amount),
                'new_balance': float(user.offchain_balance),
                'new_locked_balance': float(user.locked_balance),
                'local_debug_mode': True
            }
        
        # Atomic unlock operation
        result = db.execute(
            text("""
                UPDATE user_ledger 
                SET offchain_balance = offchain_balance + :amount,
                    locked_balance = locked_balance - :amount
                WHERE wallet_address = :wallet 
                AND locked_balance >= :amount
            """),
            {"amount": str(amount), "wallet": wallet_address}
        )
        db.commit()
        
        if result.rowcount == 0:
            db.refresh(user)
            raise ValueError(
                f"Insufficient locked balance to unlock. Required: {amount}, Available: {user.locked_balance}"
            )
        
        db.refresh(user)
        
        return {
            'status': 'success',
            'unlocked': float(amount),
            'new_balance': float(user.offchain_balance),
            'new_locked_balance': float(user.locked_balance)
        }
