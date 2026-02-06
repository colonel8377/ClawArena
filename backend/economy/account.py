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

from backend.database.models import UserLedger, TransactionLog, TransactionType
from backend.database.connection import get_db_session
from backend.database.redis_manager import redis_manager
from backend.config import is_local_debug_mode, get_debug_balance


# Custom exceptions for better error handling
class AccountError(Exception):
    """Base exception for account-related errors."""
    pass


class UserNotFoundError(AccountError):
    """Raised when a user is not found."""
    pass


class InsufficientBalanceError(AccountError):
    """Raised when user has insufficient balance for an operation."""
    pass


class InvalidAmountError(AccountError):
    """Raised when an invalid amount is provided."""
    pass


class InvalidWalletAddressError(AccountError):
    """Raised when an invalid wallet address is provided."""
    pass


# Configuration
DAILY_LOGIN_REWARD = Decimal("100.0")  # 100 tokens per day


def get_cached_balance(wallet_address: str) -> Optional[Decimal]:
    """
    Get balance from Redis cache.

    Args:
        wallet_address: User's wallet address

    Returns:
        Cached balance or None if not cached
    """
    try:
        cache_key = f"balance:{wallet_address.lower()}"
        cached_balance = redis_manager.get_cached_balance(wallet_address)
        if cached_balance is not None:
            return Decimal(str(cached_balance))
    except Exception:
        # Cache miss or error, return None to fall back to database
        pass
    return None


def set_cached_balance(wallet_address: str, balance: Decimal, locked_balance: Decimal) -> None:
    """
    Cache balance in Redis.

    Args:
        wallet_address: User's wallet address
        balance: Current balance
        locked_balance: Current locked balance
    """
    try:
        redis_manager.set_cached_balance(wallet_address, float(balance), float(locked_balance))
    except Exception:
        # Cache write failure, continue without caching
        pass


def invalidate_balance_cache(wallet_address: str) -> None:
    """
    Invalidate balance cache for a user.

    Args:
        wallet_address: User's wallet address
    """
    try:
        redis_manager.invalidate_balance_cache(wallet_address)
    except Exception:
        # Cache invalidation failure, continue
        pass


def validate_account_balance(wallet_address: str) -> Dict[str, Any]:
    """
    Validate account balance consistency and return account status.

    Checks for:
    - Negative balances
    - Locked balance > total balance
    - Balance consistency between cache and database

    Args:
        wallet_address: User's wallet address

    Returns:
        Dict containing validation results and account status

    Raises:
        UserNotFoundError: If user not found
        AccountError: If balance validation fails
    """
    with get_db_session() as db:
        user = get_user_with_validation(wallet_address, db)

        issues = []

        # Check for negative balances
        if user.offchain_balance < 0:
            issues.append(f"Negative offchain balance: {user.offchain_balance}")
        if user.locked_balance < 0:
            issues.append(f"Negative locked balance: {user.locked_balance}")

        # Check locked balance consistency
        if user.locked_balance > user.offchain_balance:
            issues.append(f"Locked balance ({user.locked_balance}) exceeds total balance ({user.offchain_balance})")

        # Check cache consistency
        cached_balance = get_cached_balance(wallet_address)
        cached_locked = None
        try:
            cached_data = redis_manager.get_cached_balance_data(wallet_address)
            if cached_data:
                cached_locked = Decimal(str(cached_data.get('locked_balance', 0)))
        except:
            pass

        if cached_balance is not None and cached_locked is not None:
            if cached_balance != user.offchain_balance:
                issues.append(f"Cache balance mismatch: cache={cached_balance}, db={user.offchain_balance}")
            if cached_locked != user.locked_balance:
                issues.append(f"Cache locked balance mismatch: cache={cached_locked}, db={user.locked_balance}")

        available_balance = user.offchain_balance - user.locked_balance

        return {
            'wallet_address': user.wallet_address,
            'offchain_balance': user.offchain_balance,
            'locked_balance': user.locked_balance,
            'available_balance': available_balance,
            'is_valid': len(issues) == 0,
            'issues': issues,
            'last_login': user.last_login_date.isoformat() if user.last_login_date else None,
            'created_at': user.created_at.isoformat() if user.created_at else None
        }


def get_account_summary(wallet_address: str) -> Dict[str, Any]:
    """
    Get comprehensive account summary including recent transactions.

    Args:
        wallet_address: User's wallet address

    Returns:
        Dict containing account summary
    """
    validation = validate_account_balance(wallet_address)

    # Get recent transactions (last 10)
    try:
        with get_db_session() as db:
            user = get_user_with_validation(wallet_address, db)
            recent_transactions = db.query(TransactionLog).filter_by(
                user_id=user.id
            ).order_by(TransactionLog.created_at.desc()).limit(10).all()

            transactions = []
            for tx in recent_transactions:
                transactions.append({
                    'id': tx.id,
                    'type': tx.tx_type,
                    'amount': float(tx.amount),
                    'balance_before': float(tx.balance_before),
                    'balance_after': float(tx.balance_after),
                    'description': tx.description,
                    'created_at': tx.created_at.isoformat() if tx.created_at else None
                })

            validation['recent_transactions'] = transactions

    except Exception as e:
        validation['transaction_error'] = str(e)
        validation['recent_transactions'] = []

    return validation


# ============================================================================
# HIGH-LEVEL API FUNCTIONS
# ============================================================================

def transfer_balance(
    from_wallet: str,
    to_wallet: str,
    amount: Decimal,
    description: str = "Balance transfer"
) -> Dict[str, Any]:
    """
    Transfer balance between two user accounts.

    This is an atomic operation that deducts from one account and adds to another.

    Args:
        from_wallet: Sender's wallet address
        to_wallet: Recipient's wallet address
        amount: Amount to transfer
        description: Transfer description

    Returns:
        Dict with transfer results

    Raises:
        InvalidAmountError: If amount is invalid
        InsufficientBalanceError: If sender has insufficient balance
        UserNotFoundError: If either user not found
    """
    if amount <= 0:
        raise InvalidAmountError("Transfer amount must be positive")

    with get_db_session() as db:
        # Get both users
        from_user = get_user_with_validation(from_wallet, db)
        to_user = get_user_with_validation(to_wallet, db)

        # Check sender balance
        if from_user.offchain_balance < amount:
            raise InsufficientBalanceError(
                f"Insufficient balance for transfer. Required: {amount}, Available: {from_user.offchain_balance}"
            )

        # Record balances before transfer
        from_balance_before = from_user.offchain_balance
        to_balance_before = to_user.offchain_balance

        # Perform transfer using atomic SQL
        try:
            # Deduct from sender
            db.execute(
                text("UPDATE user_ledger SET offchain_balance = offchain_balance - :amount WHERE wallet_address = :wallet"),
                {"amount": str(amount), "wallet": from_wallet}
            )

            # Add to recipient
            db.execute(
                text("UPDATE user_ledger SET offchain_balance = offchain_balance + :amount WHERE wallet_address = :wallet"),
                {"amount": str(amount), "wallet": to_wallet}
            )

            db.commit()

            # Refresh users
            db.refresh(from_user)
            db.refresh(to_user)

            # Update caches
            set_cached_balance(from_wallet, from_user.offchain_balance, from_user.locked_balance)
            set_cached_balance(to_wallet, to_user.offchain_balance, to_user.locked_balance)

            # Log transactions
            log_transaction(
                wallet_address=from_wallet,
                tx_type=TransactionType.WITHDRAW,
                amount=-amount,
                balance_before=from_balance_before,
                balance_after=from_user.offchain_balance,
                user_id=from_user.id,
                description=f"{description} (to {to_wallet})",
                db_session=db
            )

            log_transaction(
                wallet_address=to_wallet,
                tx_type=TransactionType.DEPOSIT,
                amount=amount,
                balance_before=to_balance_before,
                balance_after=to_user.offchain_balance,
                user_id=to_user.id,
                description=f"{description} (from {from_wallet})",
                db_session=db
            )

            return {
                'success': True,
                'from_wallet': from_wallet,
                'to_wallet': to_wallet,
                'amount': float(amount),
                'from_balance_after': float(from_user.offchain_balance),
                'to_balance_after': float(to_user.offchain_balance),
                'description': description
            }

        except Exception as e:
            db.rollback()
            raise AccountError(f"Transfer failed: {str(e)}") from e


def batch_get_balances(wallet_addresses: List[str]) -> Dict[str, Decimal]:
    """
    Get balances for multiple wallet addresses efficiently.

    Uses caching where possible and minimizes database queries.

    Args:
        wallet_addresses: List of wallet addresses

    Returns:
        Dict mapping wallet addresses to their balances
    """
    result = {}
    uncached_addresses = []

    # Check cache first
    for wallet in wallet_addresses:
        cached_balance = get_cached_balance(wallet)
        if cached_balance is not None:
            result[wallet] = cached_balance
        else:
            uncached_addresses.append(wallet)

    # Fetch uncached balances from database
    if uncached_addresses:
        with get_db_session() as db:
            users = db.query(UserLedger).filter(
                UserLedger.wallet_address.in_(uncached_addresses)
            ).all()

            user_dict = {user.wallet_address: user for user in users}

            for wallet in uncached_addresses:
                user = user_dict.get(wallet)
                if user:
                    balance = user.offchain_balance
                    result[wallet] = balance
                    # Update cache
                    set_cached_balance(wallet, balance, user.locked_balance)
                else:
                    # User not found, balance is 0
                    result[wallet] = Decimal("0")

    return result


def get_user_with_validation(wallet_address: str, db_session: Session) -> UserLedger:
    """
    Get user from database with validation.

    Args:
        wallet_address: User's wallet address
        db_session: Database session

    Returns:
        UserLedger instance

    Raises:
        UserNotFoundError: If user not found
        InvalidWalletAddressError: If wallet address is invalid
    """
    if not wallet_address or len(wallet_address) != 42 or not wallet_address.startswith('0x'):
        raise InvalidWalletAddressError(f"Invalid wallet address format: {wallet_address}")

    user = db_session.query(UserLedger).filter_by(wallet_address=wallet_address).first()
    if not user:
        raise UserNotFoundError(f"User not found: {wallet_address}")
    return user


def log_transaction(
    wallet_address: str,
    tx_type: TransactionType,
    amount: Decimal,
    balance_before: Decimal,
    balance_after: Decimal,
    user_id: Optional[int] = None,
    game_session_id: Optional[str] = None,
    tx_hash: Optional[str] = None,
    description: Optional[str] = None,
    db_session: Optional[Session] = None
) -> None:
    """
    Log a transaction to the transaction_log table.

    This provides complete audit trail for all balance changes.

    Args:
        wallet_address: User's wallet address
        tx_type: Type of transaction
        amount: Transaction amount (positive for credits, negative for debits)
        balance_before: Balance before transaction
        balance_after: Balance after transaction
        user_id: User ID (optional, will be looked up if not provided)
        game_session_id: Related game session (optional)
        tx_hash: On-chain transaction hash (optional)
        description: Human-readable description (optional)
    """
    if db_session is not None:
        # Use provided session (for atomic operations within existing transaction)
        try:
            # Look up user_id if not provided
            if user_id is None:
                user = db_session.query(UserLedger).filter_by(wallet_address=wallet_address).first()
                if user:
                    user_id = user.id

            if user_id is None:
                # User not found, skip logging
                return

            # Create transaction log entry
            tx_log = TransactionLog(
                user_id=user_id,
                wallet_address=wallet_address,
                tx_type=tx_type.value,
                amount=amount,
                balance_before=balance_before,
                balance_after=balance_after,
                game_session_id=game_session_id,
                tx_hash=tx_hash,
                description=description
            )

            db_session.add(tx_log)
            # Don't commit here - let the caller handle transaction

        except Exception as e:
            # Log error but don't fail the transaction
            print(f"Warning: Failed to log transaction: {e}")
            pass
    else:
        # Create new session (for operations that need their own transaction)
        try:
            with get_db_session() as db:
                # Look up user_id if not provided
                if user_id is None:
                    user = db.query(UserLedger).filter_by(wallet_address=wallet_address).first()
                    if user:
                        user_id = user.id

                if user_id is None:
                    # User not found, skip logging
                    return

                # Create transaction log entry
                tx_log = TransactionLog(
                    user_id=user_id,
                    wallet_address=wallet_address,
                    tx_type=tx_type.value,
                    amount=amount,
                    balance_before=balance_before,
                    balance_after=balance_after,
                    game_session_id=game_session_id,
                    tx_hash=tx_hash,
                    description=description
                )

                db.add(tx_log)
                db.commit()

        except Exception as e:
            # Log error but don't fail the transaction
            print(f"Warning: Failed to log transaction: {e}")
            pass


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
        raise InvalidWalletAddressError("Invalid wallet address format")
    
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

        # Update cache
        set_cached_balance(new_user.wallet_address, new_user.offchain_balance, new_user.locked_balance)

        # Log initial balance transaction
        if not is_local_debug_mode():
            log_transaction(
                wallet_address=new_user.wallet_address,
                tx_type=TransactionType.DAILY_REWARD,
                amount=initial_balance,
                balance_before=Decimal("0"),
                balance_after=initial_balance,
                user_id=new_user.id,
                description="Initial account balance on registration",
                db_session=db
            )

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
        try:
            user = get_user_with_validation(wallet_address, db)
        except (UserNotFoundError, InvalidWalletAddressError) as e:
            raise ValueError(str(e)) from e

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
            balance_before = user.offchain_balance
            db.execute(
                text("UPDATE user_ledger SET offchain_balance = offchain_balance + :reward WHERE wallet_address = :wallet"),
                {"reward": str(DAILY_LOGIN_REWARD), "wallet": wallet_address}
            )
            user.last_login_date = now_utc
            reward_granted = True
            db.commit()
            db.refresh(user)

            # Update cache
            set_cached_balance(user.wallet_address, user.offchain_balance, user.locked_balance)

            # Log daily reward transaction
            log_transaction(
                wallet_address=user.wallet_address,
                tx_type=TransactionType.DAILY_REWARD,
                amount=DAILY_LOGIN_REWARD,
                balance_before=balance_before,
                balance_after=user.offchain_balance,
                user_id=user.id,
                description="Daily login reward",
                db_session=db
            )
        
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


def deduct_balance(wallet_address: str, amount: Decimal, tx_type: TransactionType = TransactionType.GAME_ENTRY, description: str = "Balance deduction") -> Dict:
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
        raise InvalidAmountError("Amount must be positive")

    with get_db_session() as db:
        try:
            user = get_user_with_validation(wallet_address, db)
        except (UserNotFoundError, InvalidWalletAddressError) as e:
            raise ValueError(str(e)) from e

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

        balance_before = user.offchain_balance
        
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
            raise InsufficientBalanceError(
                f"Insufficient balance. Required: {amount}, Available: {user.offchain_balance}"
            )
        
        # Refresh to get updated balance
        db.refresh(user)

        # Update cache
        set_cached_balance(user.wallet_address, user.offchain_balance, user.locked_balance)

        # Log deduction transaction
        log_transaction(
            wallet_address=user.wallet_address,
            tx_type=tx_type,
            amount=-amount,  # Negative for deduction
            balance_before=balance_before,
            balance_after=user.offchain_balance,
            user_id=user.id,
            description=description,
            db_session=db
        )

        return {
            'status': 'success',
            'deducted': float(amount),
            'new_balance': float(user.offchain_balance),
            'locked_balance': float(user.locked_balance)
        }


def add_balance(wallet_address: str, amount: Decimal, tx_type: TransactionType = TransactionType.GAME_WIN, description: str = "Balance addition") -> Dict:
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
        raise InvalidAmountError("Amount must be positive")

    with get_db_session() as db:
        try:
            user = get_user_with_validation(wallet_address, db)
        except (UserNotFoundError, InvalidWalletAddressError) as e:
            raise ValueError(str(e)) from e

        # Record balance before addition
        balance_before = user.offchain_balance

        # Atomic balance addition using SQL UPDATE
        db.execute(
            text("UPDATE user_ledger SET offchain_balance = offchain_balance + :amount WHERE wallet_address = :wallet"),
            {"amount": str(amount), "wallet": wallet_address}
        )
        db.commit()

        # Refresh to get updated balance
        db.refresh(user)

        # Update cache
        set_cached_balance(user.wallet_address, user.offchain_balance, user.locked_balance)

        # Log addition transaction
        log_transaction(
            wallet_address=user.wallet_address,
            tx_type=tx_type,
            amount=amount,
            balance_before=balance_before,
            balance_after=user.offchain_balance,
            user_id=user.id,
            description=description,
            db_session=db
        )

        return {
            'status': 'success',
            'added': float(amount),
            'new_balance': float(user.offchain_balance),
            'locked_balance': float(user.locked_balance)
        }


def get_balance(wallet_address: str) -> Decimal:
    """
    Get current balance for a user from UserLedger.

    Uses Redis cache for performance optimization.

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

    # Try cache first
    cached_balance = get_cached_balance(wallet_address)
    if cached_balance is not None:
        return cached_balance

    # Cache miss, fetch from database
    with get_db_session() as db:
        try:
            user = get_user_with_validation(wallet_address, db)
        except (UserNotFoundError, InvalidWalletAddressError) as e:
            raise ValueError(str(e)) from e
        # Update cache
        set_cached_balance(wallet_address, user.offchain_balance, user.locked_balance)
        return user.offchain_balance


def lock_balance(wallet_address: str, amount: Decimal, game_session_id: Optional[str] = None) -> Dict:
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
        raise InvalidAmountError("Amount must be positive")

    with get_db_session() as db:
        try:
            user = get_user_with_validation(wallet_address, db)
        except (UserNotFoundError, InvalidWalletAddressError) as e:
            raise ValueError(str(e)) from e

        # In local debug mode, skip balance check
        if is_local_debug_mode():
            return {
                'status': 'success',
                'locked': float(amount),
                'new_balance': float(user.offchain_balance),
                'new_locked_balance': float(user.locked_balance),
                'local_debug_mode': True
            }
        
        # Record balances before lock operation
        balance_before = user.offchain_balance
        locked_before = user.locked_balance

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
            raise InsufficientBalanceError(
                f"Insufficient balance to lock. Required: {amount}, Available: {user.offchain_balance}"
            )

        db.refresh(user)

        # Update cache
        set_cached_balance(user.wallet_address, user.offchain_balance, user.locked_balance)

        # Log lock transaction (this moves funds to locked state)
        log_transaction(
            wallet_address=user.wallet_address,
            tx_type=TransactionType.GAME_ENTRY,
            amount=-amount,  # Negative because funds are moved to locked state
            balance_before=balance_before,
            balance_after=user.offchain_balance,
            user_id=user.id,
            game_session_id=game_session_id,
            description="Balance locked for game entry",
            db_session=db
        )

        return {
            'status': 'success',
            'locked': float(amount),
            'new_balance': float(user.offchain_balance),
            'new_locked_balance': float(user.locked_balance)
        }


def unlock_balance(wallet_address: str, amount: Decimal, tx_type: TransactionType = TransactionType.GAME_REFUND, game_session_id: Optional[str] = None, description: str = "Balance unlocked") -> Dict:
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
        raise InvalidAmountError("Amount must be positive")

    with get_db_session() as db:
        try:
            user = get_user_with_validation(wallet_address, db)
        except (UserNotFoundError, InvalidWalletAddressError) as e:
            raise ValueError(str(e)) from e

        # In local debug mode, skip checks
        if is_local_debug_mode():
            return {
                'status': 'success',
                'unlocked': float(amount),
                'new_balance': float(user.offchain_balance),
                'new_locked_balance': float(user.locked_balance),
                'local_debug_mode': True
            }
        
        # Record balances before unlock operation
        balance_before = user.offchain_balance
        locked_before = user.locked_balance

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
            raise InsufficientBalanceError(
                f"Insufficient locked balance to unlock. Required: {amount}, Available: {user.locked_balance}"
            )

        db.refresh(user)

        # Update cache
        set_cached_balance(user.wallet_address, user.offchain_balance, user.locked_balance)

        # Log unlock transaction (this returns funds from locked state)
        log_transaction(
            wallet_address=user.wallet_address,
            tx_type=tx_type,
            amount=amount,  # Positive because funds are returned
            balance_before=balance_before,
            balance_after=user.offchain_balance,
            user_id=user.id,
            game_session_id=game_session_id,
            description=description,
            db_session=db
        )

        return {
            'status': 'success',
            'unlocked': float(amount),
            'new_balance': float(user.offchain_balance),
            'new_locked_balance': float(user.locked_balance)
        }
