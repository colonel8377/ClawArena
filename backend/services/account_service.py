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
import base64
import hashlib
import re
import secrets
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from decimal import Decimal
from typing import Optional, Dict, Any, List, Callable, Awaitable

from litellm.proxy.management_endpoints.scim.scim_v2 import get_user
from sqlalchemy import text, select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from backend.constant.account import LOGIN_SECRET_BYTES, LOGIN_SECRET_ITERATIONS, LOGIN_SECRET_ITERATIONS
from backend.views import RegisterResponse
from backend.config import LOCAL_DEBUG_MODE, BOT_TOKEN_TTL
from backend.config.arena_config import is_local_debug_mode, LOCAL_DEBUG_BALANCE
from backend.constant.api_error import InvalidLoginSecretError, InvalidWalletAddressError, InvalidPlayerIDError, \
    InvalidAmountError, UserNotFoundError, BotTokenPersistenceError, InvalidAmountError, InsufficientBalanceError
from backend.utils import log


from backend.database.connection import get_async_db_session
from backend.database.models import UserLedger, TransactionLog, TransactionType
from backend.database.redis_manager import redis_manager
from backend.views.api.account_view import (
    BotTokenRequest,
    BotTokenResponse,
    AccountSummaryResponse,
    TransactionView, UserView, LoginResponse
)



def _generate_login_secret() -> str:
    """Generate a new login secret string for agents."""
    return secrets.token_urlsafe(LOGIN_SECRET_BYTES)


def _generate_secret_salt() -> str:
    """Generate per-user salt stored as URL-safe base64."""
    return base64.urlsafe_b64encode(secrets.token_bytes(16)).decode("utf-8")


def _hash_login_secret(secret: str, salt_b64: str) -> str:
    """Derive PBKDF2 hash for the provided secret."""
    if not secret or not salt_b64:
        raise InvalidLoginSecretError("Login secret missing")
    salt = base64.urlsafe_b64decode(salt_b64.encode("utf-8"))
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        secret.encode("utf-8"),
        salt,
        LOGIN_SECRET_ITERATIONS,
    )
    return base64.urlsafe_b64encode(digest).decode("utf-8")


def _set_auth_secret(user: UserLedger, *, rotate: bool = False) -> str:
    """Assign a fresh login secret to the user and return the plaintext value."""
    secret = _generate_login_secret()
    salt = _generate_secret_salt()
    user.auth_secret_salt = salt
    user.auth_secret_hash = _hash_login_secret(secret, salt)
    if rotate or not getattr(user, "session_token_version", None):
        current = user.session_token_version or 0
        user.session_token_version = current + 1 if current else 1
    return secret


def _ensure_secret_fields(user: UserLedger) -> None:
    if not user.auth_secret_hash or not user.auth_secret_salt:
        raise InvalidLoginSecretError(
            "Account is missing login secret. Please re-register to obtain new credentials."
        )


def _verify_auth_secret(user: UserLedger, provided_secret: str) -> None:
    _ensure_secret_fields(user)
    if not provided_secret:
        raise InvalidLoginSecretError("login_secret is required")
    expected = user.auth_secret_hash
    computed = _hash_login_secret(provided_secret, user.auth_secret_salt)
    if not secrets.compare_digest(expected, computed):
        raise InvalidLoginSecretError("Invalid login secret")


async def verify_login_secret(
        player_id: str,
        login_secret: str
) -> UserLedger:
    """
    Verify login secret for a player and return their ledger row.

    Args:
        player_id: canonical player identifier
        login_secret: shared-secret issued at registration
        db_session: optional DB session for composition
    """
    if not login_secret:
        raise InvalidLoginSecretError("login_secret is required")

    normalized_id = _validate_player_id(player_id)

    async with get_async_db_session() as db:
        user = await get_user_with_player_id(normalized_id, db)
        _verify_auth_secret(user, login_secret)
        return user


def _validate_player_id(player_id: str) -> str:
    """Validate and normalize backend player identifier.

    We keep using the legacy wallet_address column as a generic player id store,
    so identifiers must fit in the existing DB column width.
    """
    normalized = (player_id or "").strip()
    if not normalized:
        raise InvalidPlayerIDError("Player ID is required")
    if len(normalized) > 42:
        raise InvalidWalletAddressError("Player ID too long (max 42 characters)")
    return normalized


def _normalize_optional_address(address: Optional[str]) -> Optional[str]:
    """Normalize optional external address (wallet/chain/etc.)."""
    normalized = (address or "").strip()
    if not normalized:
        return None
    if not re.match(r'^[A-Za-z]+$', normalized):
        raise ValueError("illegal player_name")
    if len(normalized) > 128:
        raise InvalidWalletAddressError("Address too long (max 128 characters)")
    return normalized


def _normalize_player_name(player_name: str) -> str:
    """Normalize required player display name."""
    normalized = (player_name or "").strip()
    if not normalized:
        raise ValueError("player_name is required")
    if not re.match(r'^[A-Za-z]+$', normalized):
        raise ValueError("illegal player_name")
    if len(normalized) > 50:
        raise ValueError("player_name too long (max 50 characters)")
    return normalized

def _generate_token() -> str:
    """Generate an opaque bot token."""
    return secrets.token_urlsafe(32)


async def get_token(token_request: BotTokenRequest) -> BotTokenResponse:
    """
    Issue a session token to an AI agent.

    Simple flow: provide fingerprint → get token
    No challenge, no proof-of-work, but credentials are required.
    """
    fingerprint = (token_request.fingerprint.strip() or "").strip()
    player_id = (token_request.player_id or "").strip()
    login_secret = token_request.login_secret or ""


    if not player_id:
        raise InvalidPlayerIDError("Player ID is required to get a bot token.")

    user = await verify_login_secret(player_id, login_secret)

    # Issue token (store metadata in Redis with TTL)
    now = int(time.time())
    token = _generate_token()
    token_payload = {
        "fp": fingerprint,
        "player_id": player_id,
        "session_version": user.session_token_version,
        "iat": now,
    }
    saved = await redis_manager.save_bot_token(token, token_payload, BOT_TOKEN_TTL)
    if not saved:
        raise BotTokenPersistenceError("Failed to persist bot token")

    return BotTokenResponse(
        token = token,
        player_id = player_id,
        expires_in = BOT_TOKEN_TTL,
        message = "Token issued. Include as 'x-bot-token' header or 'botToken' in Socket.IO auth."
    )



def _serialize_user(user: UserLedger) -> UserView:
    """Serialize user payload with canonical identity fields."""
    return  UserView(
        player_id = user.player_id,
        player_name = user.player_name,
        address = user.address,
        balance = str(user.offchain_balance),
        locked_balance = str(user.locked_balance),
        created_at = user.created_at.isoformat() if user.created_at else None,
        last_login_date  = user.last_login_date.isoformat() if user.last_login_date else None
    )


async def get_cached_balance(player_id: str) -> Optional[Decimal]:
    """
    Get balance from Redis cache.

    Args:
        player_id: User player id

    Returns:
        Cached balance or None if not cached
    """
    try:
        cached_balance = await redis_manager.get_cached_balance(player_id)
        if cached_balance is not None:
            return Decimal(cached_balance)
    except Exception:
        # Cache miss or error, return None to fall back to database
        pass
    return None


async def set_cached_balance(player_id: str, balance: Decimal, locked_balance: Decimal) -> None:
    """
    Cache balance in Redis.

    Args:
        player_id: User player id
        balance: Current balance
        locked_balance: Current locked balance
    """
    try:
        await redis_manager.set_cached_balance(player_id, str(balance), str(locked_balance))
    except Exception:
        # Cache write failure, continue without caching
        pass


async def invalidate_balance_cache(player_id: str) -> None:
    """
    Invalidate balance cache for a user.

    Args:
        player_id: User player id
    """
    try:
        await redis_manager.invalidate_balance_cache(player_id)
    except Exception:
        # Cache invalidation failure, continue
        pass


async def validate_account_balance(player_id: str) -> Dict[str, Any]:
    """
    Validate account balance consistency and return account status.

    Checks for:
    - Negative balances
    - Locked balance > total balance
    - Balance consistency between cache and database

    Args:
        player_id: User's player_id

    Returns:
        Dict containing validation results and account status

    Raises:
        UserNotFoundError: If user not found
        AccountError: If balance validation fails
    """
    async with get_async_db_session() as db:
        user = await get_user_with_player_id(player_id, db)

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
        cached_data = await redis_manager.get_cached_balance_data(player_id)
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


async def get_account_summary(player_id: str) -> AccountSummaryResponse:
    """
    Get comprehensive account summary including recent transactions.

    Args:
        player_id: User's player_id

    Returns:
        AccountSummaryResponse object
    """
    validation = await validate_account_balance(player_id)

    recent_transactions: List[TransactionView] = []
    transaction_error: Optional[str] = None

    try:
        async with get_async_db_session() as db:
            user = await get_user_with_player_id(player_id, db)
            stmt = select(TransactionLog).filter_by(
                user_id=user.id
            ).order_by(TransactionLog.created_at.desc()).limit(10)
            result = await db.execute(stmt)
            db_transactions = result.scalars().all()

            for tx in db_transactions:
                recent_transactions.append(TransactionView(
                    id=tx.id,
                    type=tx.tx_type,
                    amount=str(tx.amount),
                    balance_before=str(tx.balance_before),
                    balance_after=str(tx.balance_after),
                    description=tx.description,
                    created_at=tx.created_at.isoformat() if tx.created_at else None
                ))

    except Exception as e:
        transaction_error = str(e)
    
    return AccountSummaryResponse(
        status="ok" if validation.get("is_valid", True) else "warning",
        wallet_address=validation["wallet_address"],
        offchain_balance=str(validation["offchain_balance"]),
        locked_balance=str(validation["locked_balance"]),
        available_balance=str(validation["available_balance"]),
        recent_transactions=recent_transactions,
        transaction_error=transaction_error,
        balance_mismatch=not validation.get("is_valid", True),
        last_updated=datetime.utcnow().isoformat(),
        created_at=validation.get("created_at"),
        last_login_date=validation.get("last_login")
    )


async def get_user_with_player_id(player_id: str, db_session: AsyncSession) -> UserLedger:
    """
    Get user from database with validation.

    Args:
        player_id: User's player_id
        db_session: Database session

    Returns:
        UserLedger instance

    Raises:
        UserNotFoundError: If user not found
        InvalidWalletAddressError: If wallet address is invalid
    """
    validate_player_id = _validate_player_id(player_id)

    stmt = select(UserLedger).filter_by(player_id=validate_player_id)
    result = await db_session.execute(stmt)
    user = result.scalar_one_or_none()
    if not user:
        raise UserNotFoundError(f"User not found: {validate_player_id}")
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
        tx_hash: On-chain transaction hash (optional)
        description: Human-readable description (optional)
        db_session: Optional database session for atomic transaction logging
    """

    async def _log(db: AsyncSession):
        nonlocal user_id
        # Look up user_id if not provided

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
            log.warning(f"Warning: Failed to log transaction: {e}")
            pass


def _default_tx_description(tx_type: TransactionType) -> str:
    defaults = {
        TransactionType.DAILY_REWARD: "Daily reward",
        TransactionType.GAME_ENTRY: "Game entry",
        TransactionType.GAME_WIN: "Game win",
        TransactionType.GAME_REFUND: "Game refund",
        TransactionType.DEPOSIT: "Deposit",
        TransactionType.WITHDRAW: "Withdraw",
    }
    return defaults.get(tx_type, "Account balance update")


async def _post_transaction(
    *,
    user: UserLedger,
    tx_type: TransactionType,
    amount: Decimal,
    balance_before: Decimal,
    balance_after: Decimal,
    db: AsyncSession,
    description: Optional[str] = None,
) -> None:
    normalized_description = (description or "").strip() or _default_tx_description(tx_type)
    await log_transaction(
        wallet_address=user.wallet_address,
        tx_type=tx_type,
        amount=amount,
        balance_before=balance_before,
        balance_after=balance_after,
        user_id=user.id,
        description=normalized_description,
        db_session=db,
    )


async def register_user(player_name: str, address: Optional[str] = None) -> RegisterResponse:
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
    initial_balance = LOCAL_DEBUG_BALANCE if is_local_debug_mode() else DAILY_LOGIN_REWARD

    # Helper to encapsulate registration logic
    async def _perform_registration() -> RegisterResponse:
        async with get_async_db_session() as db:
            player_id = f"p_{uuid.uuid4().hex[:16]}"

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
            login_secret = _set_auth_secret(new_user)
            db.add(new_user)
            await db.flush()

            # Log initial balance transaction
            if not is_local_debug_mode():
                await _post_transaction(
                    user=new_user,
                    tx_type=TransactionType.DAILY_REWARD,
                    amount=initial_balance,
                    balance_before=Decimal("0"),
                    balance_after=initial_balance,
                    description="Initial account balance on registration",
                    db=db,
                )

            # Commit all changes (user creation + transaction log) atomically
            await db.commit()

            # Update cache after commit to avoid publishing uncommitted state.
            await set_cached_balance(new_user.player_id, new_user.offchain_balance, new_user.locked_balance)

            return RegisterResponse(
                user = _serialize_user(new_user),
                login_secret =  login_secret,
            )

    # Apply distributed lock for concurrency control (address or name).
    lock_key = f"addr:{address}" if address else f"name:{player_name}"
    async with redis_manager.lock(f"register:{lock_key}", timeout=5):
        return await _perform_registration()


async def _grant_award(user: UserLedger, grant_reward: bool, db: AsyncSession) -> int:
    if not grant_reward:
        return  0

    now_utc = datetime.utcnow()
    today_utc = now_utc.date()

    # In local debug mode, always ensure user has unlimited funds
    if is_local_debug_mode():
        if user.offchain_balance < LOCAL_DEBUG_BALANCE:
            user.offchain_balance = LOCAL_DEBUG_BALANCE
        user.last_login_date = now_utc
        await db.commit()
        await db.refresh(user)

        await set_cached_balance(user.player_id, user.offchain_balance, user.locked_balance)
        return LOCAL_DEBUG_BALANCE

    # Check eligibility: New user or new day
    eligible = False
    if user.last_login_date is None:
        eligible = True
    elif user.last_login_date.date() < today_utc:
        eligible = True

    if not eligible:
        return 0
    reward_amount = DAILY_LOGIN_REWARD
    user.offchain_balance += reward_amount

    balance_after = user.offchain_balance
    balance_before = balance_after - reward_amount

    await _post_transaction(
        user=user,
        tx_type=TransactionType.DAILY_REWARD,
        amount=reward_amount,
        balance_before=balance_before,
        balance_after=balance_after,
        description="Daily login reward",
        db=db,
    )
    user.last_login_date = now_utc
    await db.commit()
    await set_cached_balance(user.player_id, user.offchain_balance, user.locked_balance)
    return int(reward_amount)


def _serialize_user_view(user: UserLedger) -> UserView:
    return UserView(
        player_id=user.player_id,
        player_name=user.player_name,
        address=user.wallet_address,
        balance=str(user.offchain_balance),
        locked_balance=str(user.locked_balance),
        created_at=user.created_at.isoformat() if user.created_at else None,
        last_login_date=user.last_login_date.isoformat() if user.last_login_date else None
    )


@asynccontextmanager
async def _db_session_scope(db_session: Optional[AsyncSession] = None):
    """Yield caller-owned session or create/close one for this operation."""
    if db_session is not None:
        yield db_session
        return
    async with get_async_db_session() as db:
        yield db


async def _run_with_account_lock(
    account_id: str,
    operation: Callable[[], Awaitable[Dict[str, Any]]],
    db_session: Optional[AsyncSession] = None,
) -> Dict[str, Any]:
    """Run an account mutation under redis lock unless caller owns transaction."""
    if db_session is not None:
        return await operation()
    async with redis_manager.lock(f"lock:account:{account_id}", timeout=5):
        return await operation()


@redis_manager.distributed_lock("lock:account:{player_id}", timeout=10)
async def handle_check_in(player_id: str, grant_reward: bool = True) -> LoginResponse:
    """
    Handle login using a pre-verified bot token.
    """
    async with get_async_db_session() as db:
        user = await get_user_with_player_id(player_id, db)
        reward = await _grant_award(user, grant_reward, db)
        return LoginResponse(
            reward_granted = reward > 0,
            reward_amount = reward,
            user = user,
            local_debug_mode = LOCAL_DEBUG_MODE
        )


async def deduct_balance(wallet_address: str, amount: Decimal, tx_type: TransactionType = TransactionType.GAME_ENTRY,
                         description: str = "Balance deduction", db_session: Optional[AsyncSession] = None) -> Dict:
    """
    Deduct balance from user account.

    Thin wrapper over `_adjust_offchain_balance` to preserve legacy response keys.
    """
    if amount <= 0:
        raise InvalidAmountError("Amount must be positive")

    result = await _adjust_offchain_balance(
        wallet_address=wallet_address,
        delta=-amount,
        tx_type=tx_type,
        description=description,
        db_session=db_session,
    )
    payload = {
        'status': result['status'],
        'deducted': str(amount),
        'new_balance': result['new_balance'],
        'locked_balance': result['locked_balance'],
    }
    if result.get('local_debug_mode'):
        payload['local_debug_mode'] = True
    return payload


async def _adjust_offchain_balance(
    wallet_address: str,
    delta: Decimal,
    tx_type: TransactionType,
    description: str,
    db_session: Optional[AsyncSession] = None,
) -> Dict[str, Any]:
    """
    Adjust offchain balance (positive=add, negative=deduct) atomically.
    """
    if delta == 0:
        raise InvalidAmountError("Delta must be non-zero")

    async def _do_adjust():
        async with _db_session_scope(db_session) as db:
            try:
                user = await get_user_with_validation(wallet_address, db)
            except (UserNotFoundError, InvalidWalletAddressError) as e:
                raise ValueError(str(e)) from e

            if is_local_debug_mode():
                return {
                    'status': 'success',
                    'delta': str(delta),
                    'new_balance': str(user.offchain_balance),
                    'locked_balance': str(user.locked_balance),
                    'local_debug_mode': True
                }

            balance_before = user.offchain_balance

            if delta < 0:
                deduct_amount = -delta
                result = await db.execute(
                    text("""
                        UPDATE user_ledger
                        SET offchain_balance = offchain_balance - :amount
                        WHERE wallet_address = :wallet
                        AND (offchain_balance - locked_balance) >= :amount
                    """),
                    {"amount": str(deduct_amount), "wallet": wallet_address}
                )
                if result.rowcount == 0:
                    await db.refresh(user)
                    available = user.offchain_balance - user.locked_balance
                    raise InsufficientBalanceError(
                        f"Insufficient available balance. Required: {deduct_amount}, Available: {available}"
                    )
            else:
                await db.execute(
                    text(
                        "UPDATE user_ledger SET offchain_balance = offchain_balance + :amount "
                        "WHERE wallet_address = :wallet"
                    ),
                    {"amount": str(delta), "wallet": wallet_address}
                )

            await db.refresh(user)

            await _post_transaction(
                user=user,
                tx_type=tx_type,
                amount=delta,
                balance_before=balance_before,
                balance_after=user.offchain_balance,
                description=description,
                db=db,
            )

            if db_session is None:
                await db.commit()

            await set_cached_balance(user.player_id, user.offchain_balance, user.locked_balance)

            return {
                'status': 'success',
                'delta': str(delta),
                'new_balance': str(user.offchain_balance),
                'locked_balance': str(user.locked_balance)
            }

    return await _run_with_account_lock(wallet_address, _do_adjust, db_session=db_session)


async def add_balance(wallet_address: str, amount: Decimal, tx_type: TransactionType = TransactionType.GAME_WIN,
                      description: str = "Balance addition", db_session: Optional[AsyncSession] = None) -> Dict:
    """
    Add balance to user account.

    Thin wrapper over `_adjust_offchain_balance` to preserve legacy response keys.
    """
    if amount <= 0:
        raise InvalidAmountError("Amount must be positive")

    result = await _adjust_offchain_balance(
        wallet_address=wallet_address,
        delta=amount,
        tx_type=tx_type,
        description=description,
        db_session=db_session,
    )
    payload = {
        'status': result['status'],
        'added': str(amount),
        'new_balance': result['new_balance'],
        'locked_balance': result['locked_balance'],
    }
    if result.get('local_debug_mode'):
        payload['local_debug_mode'] = True
    return payload


async def get_balance(player_id: str) -> Decimal:
    """
    Get current balance for a user from UserLedger.

    Uses Redis cache for performance optimization.

    In local debug mode, returns the debug balance (unlimited funds).

    Args:
        player_id: Ethereum wallet address

    Returns:
        Current balance

    Raises:
        ValueError: If user not found
    """
    # In local debug mode, always return unlimited funds
    if is_local_debug_mode():
        return LOCAL_DEBUG_BALANCE

    # Try cache first
    cached_balance = await get_cached_balance(player_id)
    if cached_balance is not None:
        return cached_balance

    # Cache miss, fetch from database
    async with get_async_db_session() as db:
        user = await get_user_with_player_id(player_id, db)
        await set_cached_balance(player_id, user.offchain_balance, user.locked_balance)
        return user.offchain_balance



async def lock_balance(
    player_id: str,
    amount: Decimal,
    db_session: Optional[AsyncSession] = None,
) -> Dict:
    """
    Lock balance for in-game use (prevents double-spending).
    
    Atomically reserves funds by increasing locked_balance while leaving
    offchain_balance (total balance) unchanged.
    
    Args:
        player_id: player_id
        amount: Amount to lock
        db_session: Optional database session
        
    Returns:
        Dict with operation status
        
    Raises:
        ValueError: If insufficient balance or user not found
    """
    if amount <= 0:
        raise InvalidAmountError("Amount must be positive")

    async def _do_lock():
        async with _db_session_scope(db_session) as db:
            try:
                user = await get_user_with_player_id(player_id, db)
            except (UserNotFoundError, InvalidWalletAddressError) as e:
                raise ValueError(str(e)) from e

            if is_local_debug_mode():
                return {
                    'status': 'success',
                    'locked': str(amount),
                    'new_balance': str(user.offchain_balance),
                    'new_locked_balance': str(user.locked_balance),
                    'local_debug_mode': True
                }

            balance_before = user.offchain_balance
            result = await db.execute(
                text("""
                    UPDATE user_ledger
                    SET locked_balance = locked_balance + :amount
                    WHERE player_id = :player_id
                    AND (offchain_balance - locked_balance) >= :amount
                """),
                {"amount": str(amount), "player_id": player_id}
            )
            if result.rowcount == 0:
                await db.refresh(user)
                available = user.offchain_balance - user.locked_balance
                raise InsufficientBalanceError(
                    f"Insufficient available balance to lock. Required: {amount}, Available: {available}"
                )

            await _post_transaction(
                user=user,
                tx_type=TransactionType.GAME_ENTRY,
                amount=-amount,
                balance_before=balance_before,
                balance_after=user.offchain_balance,
                description="Balance locked for game entry",
                db=db,
            )

            if db_session is None:
                await db.commit()

            await db.refresh(user)

            await set_cached_balance(user.player_id, user.offchain_balance, user.locked_balance)

            return {
                'status': 'success',
                'locked': str(amount),
                'new_balance': str(user.offchain_balance),
                'new_locked_balance': str(user.locked_balance)
            }

    return await _run_with_account_lock(player_id, _do_lock, db_session=db_session)


async def unlock_balance(player_id: str, amount: Decimal, tx_type: TransactionType = TransactionType.GAME_REFUND,
                         description: str = "Balance unlocked",
                         db_session: Optional[AsyncSession] = None) -> Dict:
    """
    Unlock balance after game completion.
    
    Atomically releases funds by decreasing locked_balance only.
    
    Args:
        player_id: player_id
        amount: Amount to unlock
        db_session: Optional database session
        
    Returns:
        Dict with operation status
        
    Raises:
        ValueError: If insufficient locked balance or user not found
    """
    if amount <= 0:
        raise InvalidAmountError("Amount must be positive")

    async def _do_unlock():
        async with _db_session_scope(db_session) as db:
            try:
                user = await get_user_with_player_id(player_id, db)
            except (UserNotFoundError, InvalidWalletAddressError) as e:
                raise ValueError(str(e)) from e

            if is_local_debug_mode():
                return {
                    'status': 'success',
                    'unlocked': str(amount),
                    'new_balance': str(user.offchain_balance),
                    'new_locked_balance': str(user.locked_balance),
                    'local_debug_mode': True
                }

            balance_before = user.offchain_balance
            result = await db.execute(
                text("""
                    UPDATE user_ledger
                    SET locked_balance = locked_balance - :amount
                    WHERE player_id = :player_id
                    AND locked_balance >= :amount
                """),
                {"amount": str(amount), "player_id": player_id}
            )

            if result.rowcount == 0:
                await db.refresh(user)
                raise InsufficientBalanceError(
                    f"Insufficient locked balance to unlock. Required: {amount}, Available: {user.locked_balance}"
                )

            await db.refresh(user)

            await _post_transaction(
                user=user,
                tx_type=tx_type,
                amount=amount,
                balance_before=balance_before,
                balance_after=user.offchain_balance,
                description=description,
                db=db,
            )

            if db_session is None:
                await db.commit()

            await set_cached_balance(user.player_id, user.offchain_balance, user.locked_balance)

            return {
                'status': 'success',
                'unlocked': str(amount),
                'new_balance': str(user.offchain_balance),
                'new_locked_balance': str(user.locked_balance)
            }

    return await _run_with_account_lock(player_id, _do_unlock, db_session=db_session)
