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
from typing import Optional, Dict, Any, List
import uuid
from sqlalchemy import text, select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database.models import UserLedger, TransactionLog, TransactionType
from backend.database.connection import get_async_db_session
from backend.database.redis_manager import redis_manager
from backend.config.arena_config import is_local_debug_mode, get_debug_balance


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
    """Raised when an invalid player identifier is provided."""
    pass


class AmbiguousLoginIdentifierError(AccountError):
    """Raised when a login key matches multiple accounts."""
    pass


# Configuration
DAILY_LOGIN_REWARD = Decimal("1000.0")  # 1000 tokens per day
LEADERBOARD_LIMIT = 10


def _validate_player_id(player_id: str) -> str:
    """Validate and normalize backend player identifier.

    We keep using the legacy wallet_address column as a generic player id store,
    so identifiers must fit in the existing DB column width.
    """
    normalized = (player_id or "").strip()
    if not normalized:
        raise InvalidWalletAddressError("Player ID is required")
    if len(normalized) > 42:
        raise InvalidWalletAddressError("Player ID too long (max 42 characters)")
    return normalized


def _normalize_optional_address(address: Optional[str]) -> Optional[str]:
    """Normalize optional external address (wallet/chain/etc.)."""
    normalized = (address or "").strip()
    if not normalized:
        return None
    if len(normalized) > 128:
        raise InvalidWalletAddressError("Address too long (max 128 characters)")
    return normalized


def _normalize_login_key(login_key: str) -> str:
    """Normalize generic login key (player_id or external address)."""
    normalized = (login_key or "").strip()
    if not normalized:
        raise InvalidWalletAddressError("Login key is required")
    if len(normalized) > 128:
        raise InvalidWalletAddressError("Login key too long (max 128 characters)")
    return normalized


def _normalize_player_name(player_name: str) -> str:
    """Normalize required player display name."""
    normalized = (player_name or "").strip()
    if not normalized:
        raise ValueError("player_name is required")
    if len(normalized) > 50:
        raise ValueError("player_name too long (max 50 characters)")
    return normalized


def _generate_player_id() -> str:
    """Generate a short system player id that fits current DB column width."""
    return f"p_{uuid.uuid4().hex[:16]}"


def _serialize_user(user: UserLedger) -> Dict[str, Any]:
    """Serialize user payload with canonical identity fields."""
    return {
        'player_id': user.wallet_address,
        'player_name': user.player_name,
        'address': user.address,
        'balance': str(user.offchain_balance),
        'locked_balance': str(user.locked_balance),
        'created_at': user.created_at.isoformat() if user.created_at else None,
        'last_login_date': user.last_login_date.isoformat() if user.last_login_date else None,
    }


def _to_decimal_safe(value: Any) -> Decimal:
    """Best-effort Decimal conversion for cache/DB values."""
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except Exception:
        return Decimal("0")


async def get_cached_balance(wallet_address: str) -> Optional[Decimal]:
    """
    Get balance from Redis cache.

    Args:
        wallet_address: User's wallet address

    Returns:
        Cached balance or None if not cached
    """
    try:
        cached_balance = await redis_manager.get_cached_balance(wallet_address)
        if cached_balance is not None:
            return Decimal(cached_balance)
    except Exception:
        # Cache miss or error, return None to fall back to database
        pass
    return None


async def set_cached_balance(wallet_address: str, balance: Decimal, locked_balance: Decimal) -> None:
    """
    Cache balance in Redis.

    Args:
        wallet_address: User's wallet address
        balance: Current balance
        locked_balance: Current locked balance
    """
    try:
        await redis_manager.set_cached_balance(wallet_address, str(balance), str(locked_balance))
    except Exception:
        # Cache write failure, continue without caching
        pass


async def invalidate_balance_cache(wallet_address: str) -> None:
    """
    Invalidate balance cache for a user.

    Args:
        wallet_address: User's wallet address
    """
    try:
        await redis_manager.invalidate_balance_cache(wallet_address)
    except Exception:
        # Cache invalidation failure, continue
        pass


async def invalidate_leaderboard_cache() -> None:
    """Invalidate leaderboard cache after ranking-impacting balance updates."""
    try:
        await redis_manager.invalidate_leaderboard_cache()
    except Exception:
        # Cache invalidation failure should not block core transaction flow.
        pass


async def validate_account_balance(wallet_address: str) -> Dict[str, Any]:
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
    async with get_async_db_session() as db:
        user = await get_user_with_validation(wallet_address, db)

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
        cached_data = await redis_manager.get_cached_balance_data(wallet_address)
        cached_balance = None
        cached_locked = None
        if cached_data:
            cached_balance = Decimal(cached_data['balance'])
            cached_locked = Decimal(cached_data['locked_balance'])

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


async def get_account_summary(wallet_address: str) -> Dict[str, Any]:
    """
    Get comprehensive account summary including recent transactions.

    Args:
        wallet_address: User's wallet address

    Returns:
        Dict containing account summary
    """
    validation = await validate_account_balance(wallet_address)

    # Get recent transactions (last 10)
    try:
        async with get_async_db_session() as db:
            user = await get_user_with_validation(wallet_address, db)
            stmt = select(TransactionLog).filter_by(
                user_id=user.id
            ).order_by(TransactionLog.created_at.desc()).limit(10)
            result = await db.execute(stmt)
            recent_transactions = result.scalars().all()

            transactions = []
            for tx in recent_transactions:
                transactions.append({
                    'id': tx.id,
                    'type': tx.tx_type,
                    'amount': str(tx.amount),
                    'balance_before': str(tx.balance_before),
                    'balance_after': str(tx.balance_after),
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

async def transfer_balance(
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

    async with get_async_db_session() as db:
        # Get both users
        from_user = await get_user_with_validation(from_wallet, db)
        to_user = await get_user_with_validation(to_wallet, db)

        # Check sender available balance
        available = from_user.offchain_balance - from_user.locked_balance
        if available < amount:
            raise InsufficientBalanceError(
                f"Insufficient available balance for transfer. Required: {amount}, Available: {available}"
            )

        # Record balances before transfer
        from_balance_before = from_user.offchain_balance
        to_balance_before = to_user.offchain_balance

        # Perform transfer using atomic SQL
        try:
            # Deduct from sender with balance guard to avoid TOCTOU race.
            deduct_result = await db.execute(
                text("""
                    UPDATE user_ledger
                    SET offchain_balance = offchain_balance - :amount
                    WHERE wallet_address = :wallet
                    AND (offchain_balance - locked_balance) >= :amount
                """),
                {"amount": str(amount), "wallet": from_wallet}
            )
            if deduct_result.rowcount == 0:
                await db.refresh(from_user)
                available = from_user.offchain_balance - from_user.locked_balance
                raise InsufficientBalanceError(
                    f"Insufficient available balance for transfer. Required: {amount}, Available: {available}"
                )

            # Add to recipient
            credit_result = await db.execute(
                text("UPDATE user_ledger SET offchain_balance = offchain_balance + :amount WHERE wallet_address = :wallet"),
                {"amount": str(amount), "wallet": to_wallet}
            )
            if credit_result.rowcount == 0:
                raise UserNotFoundError(f"User not found: {to_wallet}")

            await db.refresh(from_user)
            await db.refresh(to_user)

            # Log transactions (before commit to ensure atomicity)
            await log_transaction(
                wallet_address=from_wallet,
                tx_type=TransactionType.WITHDRAW,
                amount=-amount,
                balance_before=from_balance_before,
                balance_after=from_user.offchain_balance,
                user_id=from_user.id,
                description=f"{description} (to {to_wallet})",
                db_session=db
            )

            await log_transaction(
                wallet_address=to_wallet,
                tx_type=TransactionType.DEPOSIT,
                amount=amount,
                balance_before=to_balance_before,
                balance_after=to_user.offchain_balance,
                user_id=to_user.id,
                description=f"{description} (from {from_wallet})",
                db_session=db
            )

            await db.commit()

            # Update caches
            await set_cached_balance(from_wallet, from_user.offchain_balance, from_user.locked_balance)
            await set_cached_balance(to_wallet, to_user.offchain_balance, to_user.locked_balance)
            await invalidate_leaderboard_cache()

            return {
                'success': True,
                'from_wallet': from_wallet,
                'to_wallet': to_wallet,
                'amount': str(amount),
                'from_balance_after': str(from_user.offchain_balance),
                'to_balance_after': str(to_user.offchain_balance),
                'description': description
            }

        except (InsufficientBalanceError, UserNotFoundError, InvalidWalletAddressError, InvalidAmountError):
            await db.rollback()
            raise
        except Exception as e:
            await db.rollback()
            raise AccountError(f"Transfer failed: {str(e)}") from e


async def batch_get_balances(wallet_addresses: List[str]) -> Dict[str, Decimal]:
    """
    Get balances for multiple wallet addresses efficiently.

    Uses caching where possible and minimizes database queries.

    Args:
        wallet_addresses: List of wallet addresses

    Returns:
        Dict mapping wallet addresses to their balances
    """
    result: Dict[str, Decimal] = {}
    uncached_addresses: List[str] = []

    # Check cache first in bulk (single Redis roundtrip via MGET).
    cached_rows = await redis_manager.get_cached_balances_data(wallet_addresses)
    for wallet in wallet_addresses:
        cached_data = cached_rows.get(wallet)
        if cached_data and cached_data.get("balance") is not None:
            result[wallet] = _to_decimal_safe(cached_data.get("balance"))
        else:
            uncached_addresses.append(wallet)

    # Fetch uncached balances from database
    if uncached_addresses:
        unique_uncached = list(dict.fromkeys(uncached_addresses))
        async with get_async_db_session() as db:
            stmt = select(UserLedger).filter(
                UserLedger.wallet_address.in_(unique_uncached)
            )
            users_result = await db.execute(stmt)
            users = users_result.scalars().all()

            user_dict = {user.wallet_address: user for user in users}

            for wallet in uncached_addresses:
                user = user_dict.get(wallet)
                if user:
                    balance = user.offchain_balance
                    result[wallet] = balance
                    # Update cache
                    await set_cached_balance(wallet, balance, user.locked_balance)
                else:
                    # User not found, balance is 0
                    result[wallet] = Decimal("0")

    return result


async def get_leaderboard(limit: int = LEADERBOARD_LIMIT) -> List[Dict[str, Any]]:
    """
    Get top players by token balance.

    Uses Redis cache for the default top-10 leaderboard with 60s TTL.

    Args:
        limit: Number of players to return

    Returns:
        List of leaderboard entries sorted by offchain balance descending
    """
    if limit <= 0:
        raise InvalidAmountError("Leaderboard limit must be positive")

    # Cache only the canonical top-10 query.
    if limit == LEADERBOARD_LIMIT:
        try:
            cached_entries = await redis_manager.get_cached_leaderboard()
            if cached_entries:
                entries = []
                for idx, row in enumerate(cached_entries, start=1):
                    balance = _to_decimal_safe(row.get("offchain_balance", "0"))
                    entries.append({
                        "rank": idx,
                        "player_id": row.get("player_id", ""),
                        "player_name": row.get("player_name", "Player"),
                        "balance": str(balance),
                    })
                return entries
        except Exception:
            # Fall through to DB query on cache errors.
            pass

    async with get_async_db_session() as db:
        stmt = (
            select(UserLedger.wallet_address, UserLedger.player_name, UserLedger.offchain_balance)
            .order_by(desc(UserLedger.offchain_balance), UserLedger.wallet_address)
            .limit(limit)
        )
        result = await db.execute(stmt)
        rows = result.all()

    entries: List[Dict[str, Any]] = []
    cache_payload: List[Dict[str, str]] = []

    for idx, row in enumerate(rows, start=1):
        player_id = row[0] if len(row) > 0 else ""
        player_name = row[1] if len(row) > 1 else "Player"
        balance = _to_decimal_safe(row[2] if len(row) > 2 else None)
        entries.append({
            "rank": idx,
            "player_id": player_id or "",
            "player_name": player_name or "Player",
            "balance": str(balance),
        })
        cache_payload.append({
            "player_id": player_id or "",
            "player_name": player_name or "Player",
            "offchain_balance": str(balance),
        })

    if limit == LEADERBOARD_LIMIT:
        try:
            await redis_manager.set_cached_leaderboard(cache_payload)
        except Exception:
            # Cache write failure should not affect response.
            pass

    return entries


async def get_user_with_validation(wallet_address: str, db_session: AsyncSession) -> UserLedger:
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
    wallet_address = _validate_player_id(wallet_address)

    stmt = select(UserLedger).filter_by(wallet_address=wallet_address)
    result = await db_session.execute(stmt)
    user = result.scalar_one_or_none()
    if not user:
        raise UserNotFoundError(f"User not found: {wallet_address}")
    return user


async def resolve_player_id(login_key: str, db_session: AsyncSession) -> str:
    """Resolve a login key to canonical player_id.

    Login key priority:
    1. Exact player_id match (legacy wallet_address field)
    2. Unique address match (case-insensitive)
    """
    normalized_key = _normalize_login_key(login_key)

    # Fast path: treat key as player_id first.
    if len(normalized_key) <= 42:
        by_id_stmt = select(UserLedger.wallet_address).filter_by(wallet_address=normalized_key)
        by_id_result = await db_session.execute(by_id_stmt)
        player_id = by_id_result.scalar_one_or_none()
        if player_id:
            return player_id

    # Address-based login is intentionally de-emphasized in current non-web3 mode.
    # Keep the field as metadata only and require canonical player_id login.
    raise UserNotFoundError(f"User not found: {normalized_key}. Please login with player_id")


async def log_transaction(
    wallet_address: str,
    tx_type: TransactionType,
    amount: Decimal,
    balance_before: Decimal,
    balance_after: Decimal,
    user_id: Optional[int] = None,
    game_session_id: Optional[str] = None,
    tx_hash: Optional[str] = None,
    description: Optional[str] = None,
    db_session: Optional[AsyncSession] = None
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
        db_session: Optional database session for atomic transaction logging
    """
    async def _log(db: AsyncSession):
        nonlocal user_id
        # Look up user_id if not provided
        if user_id is None:
            stmt = select(UserLedger).filter_by(wallet_address=wallet_address)
            result = await db.execute(stmt)
            user = result.scalar_one_or_none()
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
            description=description,
            created_at=datetime.utcnow()
        )

        db.add(tx_log)
        # Don't commit here - let the caller handle transaction

    if db_session is not None:
        # Use provided session (for atomic operations within existing transaction)
        # Do NOT catch exception here, let it propagate to rollback the whole transaction
        await _log(db_session)
    else:
        # Create new session (for operations that need their own transaction)
        try:
            async with get_async_db_session() as db:
                await _log(db)
                await db.commit()
        except Exception as e:
            # Log error but don't fail the transaction
            print(f"Warning: Failed to log transaction: {e}")
            pass


async def register_user(player_name: str, address: Optional[str] = None) -> Dict:
    """
    Register a new user in the database using UserLedger.
    
    In local debug mode, users get unlimited funds (configured via LOCAL_DEBUG_BALANCE).
    
    Args:
        player_name: User-defined display name
        address: Optional external address
        
    Returns:
        Dict with status and user information
        
    Raises:
        ValueError: If player data is invalid
    """
    player_name = _normalize_player_name(player_name)
    address = _normalize_optional_address(address)
    
    # Use debug balance in local debug mode
    initial_balance = get_debug_balance() if is_local_debug_mode() else DAILY_LOGIN_REWARD
    
    # Helper to encapsulate registration logic
    async def _perform_registration():
        async with get_async_db_session() as db:
            # Generate collision-safe system player id
            player_id = _generate_player_id()
            while True:
                stmt = select(UserLedger).filter_by(wallet_address=player_id)
                result = await db.execute(stmt)
                if not result.scalar_one_or_none():
                    break
                player_id = _generate_player_id()
            
            # Create new user with initial balance
            new_user = UserLedger(
                wallet_address=player_id,
                player_name=player_name,
                address=address,
                offchain_balance=initial_balance,
                locked_balance=Decimal("0"),
                last_login_date=datetime.utcnow(),
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow()
            )
            
            db.add(new_user)
            await db.flush()  # Generate ID for transaction logging
            await db.refresh(new_user)

            # Log initial balance transaction
            if not is_local_debug_mode():
                await log_transaction(
                    wallet_address=new_user.wallet_address,
                    tx_type=TransactionType.DAILY_REWARD,
                    amount=initial_balance,
                    balance_before=Decimal("0"),
                    balance_after=initial_balance,
                    user_id=new_user.id,
                    description="Initial account balance on registration",
                    db_session=db
                )
            
            # Commit all changes (user creation + transaction log) atomically
            await db.commit()
            await db.refresh(new_user)

            # Update cache after commit to avoid publishing uncommitted state.
            await set_cached_balance(new_user.wallet_address, new_user.offchain_balance, new_user.locked_balance)
            await invalidate_leaderboard_cache()

            return {
                'status': 'registered',
                'user': _serialize_user(new_user),
                'local_debug_mode': is_local_debug_mode()
            }

    # Apply distributed lock for concurrency control (address or name).
    lock_key = address or f"name:{player_name.lower()}"
    async with redis_manager.lock(f"register:{lock_key}", timeout=5):
        return await _perform_registration()


@redis_manager.distributed_lock("lock:account:{login_key}", timeout=5)
async def handle_login(login_key: str, grant_reward: bool = True) -> Dict:
    """
    Handle user login with daily reward check using UserLedger.
    
    In local debug mode, always ensures user has unlimited funds.
    
    Checks if it's a new UTC day since last login. If yes, adds tokens
    to virtual balance and updates last_login_date.
    
    Args:
        login_key: canonical player_id
        grant_reward: Whether to run daily reward mutation flow
        
    Returns:
        Dict with login status and reward information
        
    Raises:
        ValueError: If user not found
    """
    async with get_async_db_session() as db:
        player_id = await resolve_player_id(login_key, db)
        user = await get_user_with_validation(player_id, db)

        if not grant_reward:
            return {
                'status': 'success',
                'reward_granted': False,
                'reward_amount': "0",
                'user': _serialize_user(user)
            }

        now_utc = datetime.utcnow()
        today_utc = now_utc.date()
        
        # In local debug mode, always ensure user has unlimited funds
        if is_local_debug_mode():
            balance_changed = False
            if user.offchain_balance < get_debug_balance():
                user.offchain_balance = get_debug_balance()
                balance_changed = True
            user.last_login_date = now_utc
            await db.commit()
            await db.refresh(user)

            await set_cached_balance(user.wallet_address, user.offchain_balance, user.locked_balance)
            if balance_changed:
                await invalidate_leaderboard_cache()
            
            return {
                'status': 'success',
                'reward_granted': True,
                'reward_amount': str(get_debug_balance()),
                'local_debug_mode': True,
                'user': _serialize_user(user)
            }
        
        # Check if last login was on a different day.
        # Do reward + last_login_date update atomically to prevent duplicate rewards,
        # but skip the daily reward on the registration day.
        reward_granted = False
        today_start_utc = datetime(now_utc.year, now_utc.month, now_utc.day)
        eligible_for_reward = user.created_at is None or user.created_at.date() < today_utc
        
        # Use single SQL to determine if we should update and what the result is
        # We perform the update conditionally and return the rowcount
        reward_update_result = await db.execute(
            text("""
                UPDATE user_ledger
                SET offchain_balance = offchain_balance + CASE
                        WHEN (created_at IS NULL OR created_at < :today_start) THEN :reward
                        ELSE 0
                    END,
                    last_login_date = :now_utc,
                    updated_at = :now_utc
                WHERE wallet_address = :wallet
                  AND (last_login_date IS NULL OR last_login_date < :today_start)
            """),
            {
                "reward": str(DAILY_LOGIN_REWARD),
                "now_utc": now_utc,
                "today_start": today_start_utc,
                "wallet": player_id,
            }
        )

        if reward_update_result.rowcount > 0:
            # Re-fetch user to check if balance actually increased (it might not if created_at >= today_start)
            # But wait, we can just infer from eligible_for_reward.
            # If rowcount > 0, it means we updated last_login_date.
            # If eligible_for_reward is true, we also added balance.
            if eligible_for_reward:
                reward_granted = True
                
                # Log transaction BEFORE commit to ensure atomicity
                # Balance before reward is user.offchain_balance (which is stale now, but we know the delta)
                # But to be safe and accurate for the log, let's refresh.
                # However, refreshing before commit might not show changes in some isolation levels, 
                # but in default Read Committed it usually does if we did the update in same tx.
                # Let's trust the logic: balance_before = stale_balance, balance_after = stale + reward
                
                balance_before = user.offchain_balance
                balance_after = user.offchain_balance + DAILY_LOGIN_REWARD
                
                await log_transaction(
                    wallet_address=user.wallet_address,
                    tx_type=TransactionType.DAILY_REWARD,
                    amount=DAILY_LOGIN_REWARD,
                    balance_before=balance_before,
                    balance_after=balance_after,
                    user_id=user.id,
                    description="Daily login reward",
                    db_session=db
                )

        await db.commit()
        await db.refresh(user)

        # Update cache after login flow so balance/last_login_date stays fresh.
        await set_cached_balance(user.wallet_address, user.offchain_balance, user.locked_balance)

        if reward_granted:
            await invalidate_leaderboard_cache()
        
        return {
            'status': 'success',
            'reward_granted': reward_granted,
            'reward_amount': str(DAILY_LOGIN_REWARD) if reward_granted else "0",
            'user': _serialize_user(user)
        }


@redis_manager.distributed_lock("lock:account:{wallet_address}", timeout=5)
async def deduct_balance(wallet_address: str, amount: Decimal, tx_type: TransactionType = TransactionType.GAME_ENTRY, description: str = "Balance deduction", db_session: Optional[AsyncSession] = None) -> Dict:
    """
    Deduct balance from user account using atomic SQL operation.
    
    In local debug mode, skips balance checks and always succeeds.
    
    This uses database-level atomic UPDATE to prevent race conditions during
    concurrent deductions. The balance check and update happen atomically.
    
    Args:
        wallet_address: Ethereum wallet address
        amount: Amount to deduct
        db_session: Optional database session for atomic transaction logging
        
    Returns:
        Dict with operation status
        
    Raises:
        ValueError: If insufficient balance or user not found
    """
    if amount <= 0:
        raise InvalidAmountError("Amount must be positive")

    # Use provided session or create a new one
    db = db_session if db_session else get_async_db_session()
    # If we created the session, we need to manage it (enter context)
    # If session was provided, we just use it (and don't close/commit it here unless we own it)
    
    # Helper to handle session context
    class SessionContext:
        def __init__(self, session, is_owned):
            self.session = session
            self.is_owned = is_owned
            self.ctx = None
            
        async def __aenter__(self):
            if self.is_owned:
                self.ctx = self.session
                return await self.ctx.__aenter__()
            return self.session
            
        async def __aexit__(self, exc_type, exc_val, exc_tb):
            if self.is_owned:
                await self.ctx.__aexit__(exc_type, exc_val, exc_tb)
                
    session_ctx = SessionContext(db, db_session is None)

    async with session_ctx as db:
        try:
            user = await get_user_with_validation(wallet_address, db)
        except (UserNotFoundError, InvalidWalletAddressError) as e:
            raise ValueError(str(e)) from e

        # In local debug mode, skip balance check and keep balance high
        if is_local_debug_mode():
            # Don't actually deduct, keep unlimited funds
            return {
                'status': 'success',
                'deducted': str(amount),
                'new_balance': str(user.offchain_balance),
                'locked_balance': str(user.locked_balance),
                'local_debug_mode': True
            }

        balance_before = user.offchain_balance
        
        # Atomic balance deduction using SQL UPDATE
        # This prevents race conditions by doing check and update in single query
        result = await db.execute(
            text("""
                UPDATE user_ledger 
                SET offchain_balance = offchain_balance - :amount 
                WHERE wallet_address = :wallet 
                AND (offchain_balance - locked_balance) >= :amount
            """),
            {"amount": str(amount), "wallet": wallet_address}
        )
        
        # Check if update succeeded (row was updated)
        if result.rowcount == 0:
            # Refresh user to get current balance
            await db.refresh(user)
            available = user.offchain_balance - user.locked_balance
            raise InsufficientBalanceError(
                f"Insufficient available balance. Required: {amount}, Available: {available}"
            )
        
        # Refresh to get updated balance (needed for logging)
        await db.refresh(user)

        # Log deduction transaction (within the same transaction)
        await log_transaction(
            wallet_address=user.wallet_address,
            tx_type=tx_type,
            amount=-amount,  # Negative for deduction
            balance_before=balance_before,
            balance_after=user.offchain_balance,
            user_id=user.id,
            description=description,
            db_session=db
        )

        # Only commit if we own the session
        if db_session is None:
            await db.commit()
        
        # Update cache (fire and forget / after commit)
        await set_cached_balance(user.wallet_address, user.offchain_balance, user.locked_balance)
        await invalidate_leaderboard_cache()

        return {
            'status': 'success',
            'deducted': str(amount),
            'new_balance': str(user.offchain_balance),
            'locked_balance': str(user.locked_balance)
        }


@redis_manager.distributed_lock("lock:account:{wallet_address}", timeout=5)
async def add_balance(wallet_address: str, amount: Decimal, tx_type: TransactionType = TransactionType.GAME_WIN, description: str = "Balance addition", db_session: Optional[AsyncSession] = None) -> Dict:
    """
    Add balance to user account using atomic SQL operation.
    
    Args:
        wallet_address: Ethereum wallet address
        amount: Amount to add
        db_session: Optional database session for atomic transaction logging
        
    Returns:
        Dict with operation status
        
    Raises:
        ValueError: If amount is invalid or user not found
    """
    if amount <= 0:
        raise InvalidAmountError("Amount must be positive")

    # Use provided session or create a new one
    db = db_session if db_session else get_async_db_session()
    
    # Helper to handle session context (duplicated for clarity in each function)
    class SessionContext:
        def __init__(self, session, is_owned):
            self.session = session
            self.is_owned = is_owned
            self.ctx = None
            
        async def __aenter__(self):
            if self.is_owned:
                self.ctx = self.session
                return await self.ctx.__aenter__()
            return self.session
            
        async def __aexit__(self, exc_type, exc_val, exc_tb):
            if self.is_owned:
                await self.ctx.__aexit__(exc_type, exc_val, exc_tb)
                
    session_ctx = SessionContext(db, db_session is None)

    async with session_ctx as db:
        try:
            user = await get_user_with_validation(wallet_address, db)
        except (UserNotFoundError, InvalidWalletAddressError) as e:
            raise ValueError(str(e)) from e

        # Record balance before addition
        balance_before = user.offchain_balance

        # Atomic balance addition using SQL UPDATE
        await db.execute(
            text("UPDATE user_ledger SET offchain_balance = offchain_balance + :amount WHERE wallet_address = :wallet"),
            {"amount": str(amount), "wallet": wallet_address}
        )
        
        # Refresh to get updated balance
        await db.refresh(user)

        # Log addition transaction
        await log_transaction(
            wallet_address=user.wallet_address,
            tx_type=tx_type,
            amount=amount,
            balance_before=balance_before,
            balance_after=user.offchain_balance,
            user_id=user.id,
            description=description,
            db_session=db
        )
        
        # Only commit if we own the session
        if db_session is None:
            await db.commit()

        # Update cache
        await set_cached_balance(user.wallet_address, user.offchain_balance, user.locked_balance)
        await invalidate_leaderboard_cache()

        return {
            'status': 'success',
            'added': str(amount),
            'new_balance': str(user.offchain_balance),
            'locked_balance': str(user.locked_balance)
        }


async def get_balance(wallet_address: str) -> Decimal:
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
    cached_balance = await get_cached_balance(wallet_address)
    if cached_balance is not None:
        return cached_balance

    # Cache miss, fetch from database
    async with get_async_db_session() as db:
        try:
            user = await get_user_with_validation(wallet_address, db)
        except (UserNotFoundError, InvalidWalletAddressError) as e:
            raise ValueError(str(e)) from e
        # Update cache
        await set_cached_balance(wallet_address, user.offchain_balance, user.locked_balance)
        return user.offchain_balance


@redis_manager.distributed_lock("lock:account:{wallet_address}", timeout=5)
async def lock_balance(wallet_address: str, amount: Decimal, game_session_id: Optional[str] = None, db_session: Optional[AsyncSession] = None) -> Dict:
    """
    Lock balance for in-game use (prevents double-spending).
    
    Atomically reserves funds by increasing locked_balance while leaving
    offchain_balance (total balance) unchanged.
    
    Args:
        wallet_address: Ethereum wallet address
        amount: Amount to lock
        db_session: Optional database session
        
    Returns:
        Dict with operation status
        
    Raises:
        ValueError: If insufficient balance or user not found
    """
    if amount <= 0:
        raise InvalidAmountError("Amount must be positive")

    # Use provided session or create a new one
    db = db_session if db_session else get_async_db_session()

    class SessionContext:
        def __init__(self, session, is_owned):
            self.session = session
            self.is_owned = is_owned
            self.ctx = None

        async def __aenter__(self):
            if self.is_owned:
                self.ctx = self.session
                return await self.ctx.__aenter__()
            return self.session

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            if self.is_owned:
                await self.ctx.__aexit__(exc_type, exc_val, exc_tb)

    session_ctx = SessionContext(db, db_session is None)

    async with session_ctx as db:
        try:
            user = await get_user_with_validation(wallet_address, db)
        except (UserNotFoundError, InvalidWalletAddressError) as e:
            raise ValueError(str(e)) from e

        # In local debug mode, skip balance check
        if is_local_debug_mode():
            return {
                'status': 'success',
                'locked': str(amount),
                'new_balance': str(user.offchain_balance),
                'new_locked_balance': str(user.locked_balance),
                'local_debug_mode': True
            }
        
        # Record balances before lock operation
        balance_before = user.offchain_balance
        # Atomic lock operation: increase locked_balance only.
        result = await db.execute(
            text("""
                UPDATE user_ledger
                SET locked_balance = locked_balance + :amount
                WHERE wallet_address = :wallet
                AND (offchain_balance - locked_balance) >= :amount
            """),
            {"amount": str(amount), "wallet": wallet_address}
        )
        if result.rowcount == 0:
            await db.refresh(user)
            available = user.offchain_balance - user.locked_balance
            raise InsufficientBalanceError(
                f"Insufficient available balance to lock. Required: {amount}, Available: {available}"
            )

        # Log lock transaction (funds moved to locked state; total balance unchanged)
        await log_transaction(
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
        
        # Only commit if we own the session
        if db_session is None:
            await db.commit()

        await db.refresh(user)

        # Update cache
        await set_cached_balance(user.wallet_address, user.offchain_balance, user.locked_balance)
        await invalidate_leaderboard_cache()

        return {
            'status': 'success',
            'locked': str(amount),
            'new_balance': str(user.offchain_balance),
            'new_locked_balance': str(user.locked_balance)
        }


@redis_manager.distributed_lock("lock:account:{wallet_address}", timeout=5)
async def unlock_balance(wallet_address: str, amount: Decimal, tx_type: TransactionType = TransactionType.GAME_REFUND, game_session_id: Optional[str] = None, description: str = "Balance unlocked", db_session: Optional[AsyncSession] = None) -> Dict:
    """
    Unlock balance after game completion.
    
    Atomically releases funds by decreasing locked_balance only.
    
    Args:
        wallet_address: Ethereum wallet address
        amount: Amount to unlock
        db_session: Optional database session
        
    Returns:
        Dict with operation status
        
    Raises:
        ValueError: If insufficient locked balance or user not found
    """
    if amount <= 0:
        raise InvalidAmountError("Amount must be positive")

    # Use provided session or create a new one
    db = db_session if db_session else get_async_db_session()
    
    # Helper to handle session context
    class SessionContext:
        def __init__(self, session, is_owned):
            self.session = session
            self.is_owned = is_owned
            self.ctx = None
            
        async def __aenter__(self):
            if self.is_owned:
                self.ctx = self.session
                return await self.ctx.__aenter__()
            return self.session
            
        async def __aexit__(self, exc_type, exc_val, exc_tb):
            if self.is_owned:
                await self.ctx.__aexit__(exc_type, exc_val, exc_tb)
                
    session_ctx = SessionContext(db, db_session is None)

    async with session_ctx as db:
        try:
            user = await get_user_with_validation(wallet_address, db)
        except (UserNotFoundError, InvalidWalletAddressError) as e:
            raise ValueError(str(e)) from e

        # In local debug mode, skip checks
        if is_local_debug_mode():
            return {
                'status': 'success',
                'unlocked': str(amount),
                'new_balance': str(user.offchain_balance),
                'new_locked_balance': str(user.locked_balance),
                'local_debug_mode': True
            }
        
        # Record balances before unlock operation
        balance_before = user.offchain_balance
        locked_before = user.locked_balance

        # Atomic unlock operation: decrease locked_balance only.
        result = await db.execute(
            text("""
                UPDATE user_ledger
                SET locked_balance = locked_balance - :amount
                WHERE wallet_address = :wallet
                AND locked_balance >= :amount
            """),
            {"amount": str(amount), "wallet": wallet_address}
        )
        
        if result.rowcount == 0:
            await db.refresh(user)
            raise InsufficientBalanceError(
                f"Insufficient locked balance to unlock. Required: {amount}, Available: {user.locked_balance}"
            )

        await db.refresh(user)

        # Log unlock transaction (this returns funds from locked state)
        await log_transaction(
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
        
        # Only commit if we own the session
        if db_session is None:
            await db.commit()

        # Update cache
        await set_cached_balance(user.wallet_address, user.offchain_balance, user.locked_balance)
        await invalidate_leaderboard_cache()

        return {
            'status': 'success',
            'unlocked': str(amount),
            'new_balance': str(user.offchain_balance),
            'new_locked_balance': str(user.locked_balance)
        }