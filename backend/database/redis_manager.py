"""
Unified Redis Manager for ClawArena.

This module centralizes all Redis operations:
- Connection pooling and management
- Distributed locking for critical sections
- Nonce synchronization for secure withdrawals
- Game core state persistence (save/restore)
- Session management

Architecture (Single-Server):
- Chat messages: In-memory (WerewolfGame) + Socket.IO broadcast
- Game state: Redis (core state for server restart recovery)
- Formal speeches: MySQL (permanent history)

Features:
- Async context manager for distributed locks
- Automatic connection retry logic
- Graceful fallback when Redis unavailable
- Configurable TTL for different data types
"""

import os
import json
import asyncio
import socket
from urllib.parse import urlparse
from typing import Optional, Dict, Any, List
from contextlib import asynccontextmanager
from datetime import datetime
import logging

import redis.asyncio as redis

from backend.utils import log

logger = logging.getLogger(__name__)


# ============================================================================
# CONFIGURATION
# ============================================================================

REDIS_URL = os.getenv('REDIS_URL', 'redis://localhost:6379')
REDIS_PASSWORD = os.getenv('REDIS_PASSWORD', None)

# Key prefixes for namespacing
REDIS_SESSION_PREFIX = 'arena:session:'
REDIS_GAME_PREFIX = 'arena:game:'
REDIS_NONCE_PREFIX = 'arena:nonce:'
REDIS_LOCK_PREFIX = 'arena:lock:'
REDIS_PERSISTENCE_PREFIX = 'arena:persist:'  # Legacy, for full state
REDIS_GAME_CORE_PREFIX = 'arena:core:'       # Core game state (frequent updates)
REDIS_INDEXER_PREFIX = 'arena:indexer:'      # Indexer state and dedup
REDIS_BALANCE_PREFIX = 'arena:balance:'      # User balance cache
REDIS_SETTLEMENT_PREFIX = 'arena:settlement:'  # Settlement idempotency keys
REDIS_BOT_TOKEN_PREFIX = 'arena:bot_token:'  # Bot token -> metadata

# Timeouts and TTLs (seconds)
SESSION_EXPIRY = 3600           # 1 hour
LOCK_TIMEOUT = 10               # seconds
LOCK_RETRY_DELAY = 0.1          # seconds
GAME_STATE_EXPIRY = 86400       # 24 hours (legacy, for full state)
GAME_CORE_EXPIRY = 7200         # 2 hours (active game core state)
NONCE_EXPIRY = 86400            # 24 hours
EVENT_PROCESSING_LOCK_EXPIRY = 300  # 5 minutes
PROCESSED_EVENT_EXPIRY = 86400 * 30  # 30 days
SETTLEMENT_STAGE_EXPIRY = 86400 * 30  # 30 days
LEADERBOARD_CACHE_EXPIRY = 60      # 1 minute
REDIS_LEADERBOARD_KEY = 'arena:leaderboard:top10'
BALANCE_CACHE_EXPIRY = int(os.getenv('BALANCE_CACHE_EXPIRY', '300'))  # 5 minutes


# ============================================================================
# REDIS MANAGER CLASS
# ============================================================================

class RedisManager:
    """
    Centralized Redis manager for all Arena operations.

    Provides:
    - Connection management with pooling
    - Distributed locking
    - Nonce synchronization
    - Game state persistence
    - Session management
    """

    # Lua script for atomic lock release: only deletes the key if it still
    # holds the expected value, preventing accidental release of another
    # process's lock (TOCTOU race between GET and DELETE).
    _UNLOCK_SCRIPT = """
    if redis.call("get", KEYS[1]) == ARGV[1] then
        return redis.call("del", KEYS[1])
    else
        return 0
    end
    """

    def __init__(self, redis_url: str = REDIS_URL, redis_password: str = REDIS_PASSWORD):
        """
        Initialize Redis Manager.
        
        Args:
            redis_url: Redis connection URL
        """
        # Mask password for logging/printing
        safe_url = redis_url
        if '@' in redis_url:
            parts = redis_url.split('@')
            safe_url = f"*****@{parts[-1]}"
            
        # Use print to ensure visibility even if logging isn't configured yet (Import time)
        log.info(f"DEBUG: Initializing RedisManager with URL: {safe_url}")
        logger.info(f"Initializing RedisManager with URL: {safe_url}")
        
        self.redis_url = redis_url
        self.redis_password = redis_password
        self._redis: Optional[redis.Redis] = None
        self._connection_lock = asyncio.Lock()
        self._connected = False
    
    @property
    def client(self) -> Optional[redis.Redis]:
        """
        Get the underlying Redis client for advanced operations.
        
        Returns:
            Redis client if connected, None otherwise
        """
        return self._redis if self._connected else None
        
    async def connect(self) -> bool:
        """
        Establish connection to Redis with retry logic.
        
        Returns:
            True if connected successfully, False otherwise
        """
        async with self._connection_lock:
            if self._connected and self._redis:
                try:
                    await self._redis.ping()
                    return True
                except Exception:
                    self._connected = False
            
            try:
                # Prioritize password in URL if REDIS_PASSWORD is empty
                # redis-py's from_url might use empty string password if provided
                kwargs = {
                    "encoding": "utf-8",
                    "decode_responses": True,
                    "max_connections": 20
                }
                
                # Only explicitly pass password if it's set in env var
                if self.redis_password:
                    kwargs["password"] = self.redis_password
                
                # DIAGNOSTIC: Perform explicit DNS lookup to verify network visibility
                try:
                    parsed = urlparse(self.redis_url)
                    hostname = parsed.hostname
                    port = parsed.port or 6379
                    log.info(f"DEBUG: Diagnosing connection to host: '{hostname}' on port {port}...")
                    
                    # Try to resolve IP
                    ip_address = socket.gethostbyname(hostname)
                    log.info(f"DEBUG: ✓ DNS Resolution successful: {hostname} -> {ip_address}")
                    
                    # Optional: Try simple TCP handshake
                    s = socket.create_connection((hostname, port), timeout=2)
                    s.close()
                    log.info(f"DEBUG: ✓ TCP Handshake successful to {hostname}:{port}")
                    
                except socket.gaierror as e:
                    log.error(f"CRITICAL: ❌ DNS Resolution FAILED for '{hostname}'.")
                    log.info(f"  Reason: {e}")
                    log.info(f"  Diagnosis: The service name '{hostname}' cannot be found in this private network.")
                    log.info(f"  Fix: Check if your Railway Service Name is exactly '{hostname.split('.')[0]}'.")
                except socket.timeout:
                    log.error(f"CRITICAL: ❌ TCP Connection TIMED OUT to {hostname}:{port}.")
                    log.info(f"  Diagnosis: Host resolved but port is not reachable.")
                except Exception as e:
                    log.warning(f"DEBUG: Network diagnosis warning: {e}")

                self._redis = redis.from_url(
                    self.redis_url,
                    **kwargs
                )
                await self._redis.ping()
                self._connected = True
                logger.info("Redis connection established")
                return True
            except Exception as e:
                logger.error(f"Failed to connect to Redis: {e}")
                self._connected = False
                return False
    
    async def disconnect(self):
        """Close Redis connection gracefully."""
        if self._redis:
            await self._redis.close()
            self._connected = False
            logger.info("Redis connection closed")
    
    async def ping(self) -> bool:
        """
        Check if Redis is available.
        
        Returns:
            True if Redis responds to ping, False otherwise
        """
        try:
            if not self._redis:
                await self.connect()
            await self._redis.ping()
            return True
        except Exception:
            return False
    
    # ========================================================================
    # DISTRIBUTED LOCKING DECORATOR
    # ========================================================================
    
    def distributed_lock(self, resource_id_template: str, timeout: int = LOCK_TIMEOUT):
        """
        Decorator for distributed locking using Redis.
        
        Supports template strings for resource_id, e.g., "lock:{wallet_address}".
        Arguments from the decorated function will be injected into the template.
        
        Args:
            resource_id_template: Lock key template (e.g., "account:{wallet_address}")
            timeout: Lock timeout in seconds
            
        Usage:
            @redis_manager.distributed_lock("account:{wallet_address}")
            async def transfer(wallet_address, amount):
                ...
        """
        def decorator(func):
            from functools import wraps
            import inspect

            @wraps(func)
            async def wrapper(*args, **kwargs):
                # Bind arguments to signature to resolve template variables
                sig = inspect.signature(func)
                bound_args = sig.bind(*args, **kwargs)
                bound_args.apply_defaults()
                
                # Format the resource ID
                try:
                    resource_id = resource_id_template.format(**bound_args.arguments)
                except KeyError as e:
                    logger.error(f"Missing argument for lock template: {e}")
                    # Fallback to function name if template fails
                    resource_id = f"{func.__name__}:{args[0] if args else 'global'}"

                async with self.lock(resource_id, timeout):
                    return await func(*args, **kwargs)
            
            return wrapper
        return decorator

    # ========================================================================
    # DISTRIBUTED LOCKING
    # ========================================================================
    
    @asynccontextmanager
    async def lock(
        self,
        resource_id: str,
        timeout: int = LOCK_TIMEOUT,
        fail_closed: bool = True,
    ):
        """
        Distributed lock context manager using Redis.
        
        Prevents race conditions in critical sections across multiple servers.
        
        Args:
            resource_id: Unique identifier for the resource to lock
            timeout: Lock timeout in seconds
            fail_closed: If True, raise when Redis is unavailable instead of proceeding unlocked
            
        Usage:
            async with redis_manager.lock(game_id):
                # Critical section - guaranteed exclusive access
                game.update_state()
                
        Raises:
            RuntimeError: If lock cannot be acquired within timeout
        """
        lock_key = f"{REDIS_LOCK_PREFIX}{resource_id}"
        lock_value = f"{os.getpid()}:{datetime.utcnow().timestamp()}"
        acquired = False
        
        try:
            if not await self.ping():
                if fail_closed:
                    raise RuntimeError(
                        f"Redis unavailable; refusing to enter critical section for '{resource_id}'"
                    )
                logger.warning(
                    f"Redis unavailable for lock '{resource_id}', proceeding without lock"
                )
                yield
                return

            if not self._redis:
                raise RuntimeError(
                    f"Redis unavailable; refusing to enter critical section for '{resource_id}'"
                )

            loop_time = asyncio.get_event_loop().time
            start_time = loop_time()
            while (loop_time() - start_time) < timeout:
                
                # Try to acquire lock (SET NX with expiry)
                acquired = await self._redis.set(
                    lock_key, 
                    lock_value, 
                    nx=True,  # Only set if not exists
                    ex=timeout  # Auto-expire to prevent deadlocks
                )
                
                if acquired:
                    logger.debug(f"Lock acquired: {resource_id}")
                    break
                
                await asyncio.sleep(LOCK_RETRY_DELAY)
            
            if not acquired:
                raise RuntimeError(f"Failed to acquire lock for '{resource_id}' within {timeout}s")
            
            yield
            
        finally:
            # Release lock only if we acquired it, using atomic Lua script
            # to prevent releasing another process's lock (TOCTOU safety).
            if acquired and self._redis:
                try:
                    await self._redis.eval(
                        self._UNLOCK_SCRIPT, 1, lock_key, lock_value
                    )
                    logger.debug(f"Lock released: {resource_id}")
                except Exception as e:
                    logger.error(f"Error releasing lock '{resource_id}': {e}")
    
    # ========================================================================
    # NONCE SYNCHRONIZATION (Anti-Race Condition for Withdrawals)
    # ========================================================================
    
    async def get_and_increment_nonce(self, wallet_address: str) -> int:
        """
        Atomically get and increment nonce for a wallet address.
        
        Prevents race conditions during concurrent withdrawal requests.
        Uses Redis INCR for atomic increment operation.
        
        Args:
            wallet_address: Canonical player identifier
            
        Returns:
            Current nonce value (before increment)
            
        Example:
            nonce = await redis_manager.get_and_increment_nonce("0x123...")
            # Use nonce for withdrawal signature
        """
        if not await self.ping():
            raise RuntimeError("Redis unavailable - cannot generate synchronized nonce")
        
        nonce_key = f"{REDIS_NONCE_PREFIX}{wallet_address}"
        
        # INCR is atomic - no race condition possible
        new_nonce = await self._redis.incr(nonce_key)
        
        # Set expiry on first use (prevent memory leak)
        if new_nonce == 1:
            await self._redis.expire(nonce_key, NONCE_EXPIRY)
        
        # Return previous value (new_nonce - 1)
        return new_nonce - 1
    
    async def sync_nonce_from_blockchain(self, wallet_address: str, blockchain_nonce: int) -> bool:
        """
        Sync Redis nonce with blockchain nonce if blockchain is ahead.
        
        This ensures Redis cache stays in sync with on-chain state, preventing
        signature generation with stale nonces.
        
        Args:
            wallet_address: Canonical player identifier
            blockchain_nonce: Current nonce from blockchain
            
        Returns:
            True if sync was performed, False otherwise
        """
        if not await self.ping():
            return False
        
        nonce_key = f"{REDIS_NONCE_PREFIX}{wallet_address}"
        redis_nonce = await self.get_nonce(wallet_address)
        
        # Only update if blockchain is ahead (user may have withdrawn on-chain)
        if blockchain_nonce > redis_nonce:
            await self._redis.set(nonce_key, blockchain_nonce, ex=NONCE_EXPIRY)
            logger.info(
                f"Synced nonce for {wallet_address}: {redis_nonce} -> {blockchain_nonce}"
            )
            return True
        
        return False
    
    async def get_nonce(self, wallet_address: str) -> int:
        """
        Get current nonce without incrementing.
        
        Args:
            wallet_address: Canonical player identifier
            
        Returns:
            Current nonce value (0 if not set)
        """
        if not await self.ping():
            return 0
        
        nonce_key = f"{REDIS_NONCE_PREFIX}{wallet_address}"
        nonce = await self._redis.get(nonce_key)
        return int(nonce) if nonce else 0
    
    # ========================================================================
    # GAME STATE PERSISTENCE
    # ========================================================================
    
    async def save_game_state(
        self, 
        game_id: str, 
        game_state: Dict[str, Any],
        game_type: str = "unknown"
    ) -> bool:
        """
        Persist game state to Redis.
        
        Saves complete game state for recovery after server restart.
        
        Args:
            game_id: Unique game identifier
            game_state: Complete game state dictionary
            game_type: Type of game (e.g., "werewolf", "poker")
            
        Returns:
            True if saved successfully, False otherwise
        """
        if not await self.ping():
            logger.warning(f"Redis unavailable - cannot persist game {game_id}")
            return False
        
        try:
            persist_key = f"{REDIS_PERSISTENCE_PREFIX}{game_id}"
            
            # Add metadata
            state_with_meta = {
                "game_id": game_id,
                "game_type": game_type,
                "saved_at": datetime.utcnow().isoformat(),
                "state": game_state
            }
            
            # Save as JSON with expiry
            await self._redis.setex(
                persist_key,
                GAME_STATE_EXPIRY,
                json.dumps(state_with_meta)
            )
            
            logger.info(f"Game state saved: {game_id} ({game_type})")
            return True
            
        except Exception as e:
            logger.error(f"Error saving game state {game_id}: {e}")
            return False
    
    async def restore_game_state(self, game_id: str) -> Optional[Dict[str, Any]]:
        """
        Restore game state from Redis.
        
        Args:
            game_id: Unique game identifier
            
        Returns:
            Game state dictionary if found, None otherwise
        """
        if not await self.ping():
            logger.warning(f"Redis unavailable - cannot restore game {game_id}")
            return None
        
        try:
            persist_key = f"{REDIS_PERSISTENCE_PREFIX}{game_id}"
            data = await self._redis.get(persist_key)
            
            if not data:
                return None
            
            state_with_meta = json.loads(data)
            logger.info(f"Game state restored: {game_id}")
            return state_with_meta
            
        except Exception as e:
            logger.error(f"Error restoring game state {game_id}: {e}")
            return None
    
    async def delete_game_state(self, game_id: str) -> bool:
        """
        Delete persisted game state.
        
        Args:
            game_id: Unique game identifier
            
        Returns:
            True if deleted successfully
        """
        if not await self.ping():
            return False
        
        try:
            persist_key = f"{REDIS_PERSISTENCE_PREFIX}{game_id}"
            await self._redis.delete(persist_key)
            logger.info(f"Game state deleted: {game_id}")
            return True
        except Exception as e:
            logger.error(f"Error deleting game state {game_id}: {e}")
            return False
    
    async def list_persisted_games(self) -> List[str]:
        """
        List all persisted game IDs.
        
        Returns:
            List of game IDs with persisted state
        """
        if not await self.ping():
            return []
        
        try:
            pattern = f"{REDIS_PERSISTENCE_PREFIX}*"
            keys = await self._redis.keys(pattern)
            
            # Extract game IDs from keys
            game_ids = [
                key.replace(REDIS_PERSISTENCE_PREFIX, "") 
                for key in keys
            ]
            
            return game_ids
            
        except Exception as e:
            logger.error(f"Error listing persisted games: {e}")
            return []
    
    # ========================================================================
    # OPTIMIZED GAME STATE PERSISTENCE (Separated Storage)
    # ========================================================================
    
    async def save_game_core(
        self,
        game_id: str,
        core_state: Dict[str, Any],
        game_type: str = "unknown"
    ) -> bool:
        """
        Save core game state (without chat) to Redis.
        
        This is optimized for frequent updates - excludes bulky chat data.
        Use this for phase changes, player actions, etc.
        
        Args:
            game_id: Unique game identifier
            core_state: Game state WITHOUT chat history
            game_type: Type of game
            
        Returns:
            True if saved successfully
        """
        if not await self.ping():
            logger.warning(f"Redis unavailable - cannot persist core state {game_id}")
            return False
        
        try:
            core_key = f"{REDIS_GAME_CORE_PREFIX}{game_id}"
            
            state_with_meta = {
                "game_id": game_id,
                "game_type": game_type,
                "saved_at": datetime.utcnow().isoformat(),
                "state": core_state
            }
            
            await self._redis.setex(
                core_key,
                GAME_CORE_EXPIRY,
                json.dumps(state_with_meta)
            )
            
            logger.debug(f"Game core state saved: {game_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error saving game core state {game_id}: {e}")
            return False
    
    async def restore_game_core(self, game_id: str) -> Optional[Dict[str, Any]]:
        """
        Restore core game state from Redis.
        
        Args:
            game_id: Unique game identifier
            
        Returns:
            Core state dictionary if found, None otherwise
        """
        if not await self.ping():
            return None
        
        try:
            core_key = f"{REDIS_GAME_CORE_PREFIX}{game_id}"
            data = await self._redis.get(core_key)
            
            if not data:
                return None
            
            return json.loads(data)
            
        except Exception as e:
            logger.error(f"Error restoring game core state {game_id}: {e}")
            return None
    
    async def delete_game_data(self, game_id: str) -> bool:
        """
        Delete all game-related data from Redis.
        
        Cleans up: core state, legacy full state.
        
        Args:
            game_id: Game identifier
            
        Returns:
            True if deleted
        """
        if not await self.ping():
            return False
        
        try:
            keys_to_delete = [
                f"{REDIS_GAME_CORE_PREFIX}{game_id}",
                f"{REDIS_PERSISTENCE_PREFIX}{game_id}",  # Legacy key
            ]
            
            await self._redis.delete(*keys_to_delete)
            logger.info(f"Game data deleted: {game_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error deleting game data {game_id}: {e}")
            return False
    
    async def refresh_game_ttl(self, game_id: str) -> bool:
        """
        Refresh TTL for game core state key.
        
        Call this periodically for active games to prevent expiration.
        
        Args:
            game_id: Game identifier
            
        Returns:
            True if refreshed
        """
        if not await self.ping():
            return False
        
        try:
            core_key = f"{REDIS_GAME_CORE_PREFIX}{game_id}"
            await self._redis.expire(core_key, GAME_CORE_EXPIRY)
            return True
            
        except Exception as e:
            logger.error(f"Error refreshing game TTL {game_id}: {e}")
            return False
    
    async def list_active_games(self) -> List[str]:
        """
        List all games with active core state in Redis.
        
        Returns:
            List of game IDs
        """
        if not await self.ping():
            return []
        
        try:
            pattern = f"{REDIS_GAME_CORE_PREFIX}*"
            keys = await self._redis.keys(pattern)
            
            return [key.replace(REDIS_GAME_CORE_PREFIX, "") for key in keys]
            
        except Exception as e:
            logger.error(f"Error listing active games: {e}")
            return []
    
    # ========================================================================
    # SESSION MANAGEMENT (Delegated from SocketManager)
    # ========================================================================
    
    async def save_session(
        self, 
        key: str, 
        data: Dict[str, Any],
        expiry: int = SESSION_EXPIRY
    ) -> bool:
        """
        Save session data to Redis.
        
        Args:
            key: Session key
            data: Session data dictionary
            expiry: TTL in seconds
            
        Returns:
            True if saved successfully
        """
        if not await self.ping():
            return False
        
        try:
            await self._redis.setex(
                key,
                expiry,
                json.dumps(data)
            )
            return True
        except Exception as e:
            logger.error(f"Error saving session {key}: {e}")
            return False
    
    async def get_session(self, key: str) -> Optional[Dict[str, Any]]:
        """
        Get session data from Redis.
        
        Args:
            key: Session key
            
        Returns:
            Session data dictionary if found, None otherwise
        """
        if not await self.ping():
            return None
        
        try:
            data = await self._redis.get(key)
            if data:
                return json.loads(data)
            return None
        except Exception as e:
            logger.error(f"Error getting session {key}: {e}")
            return None
    
    async def delete_session(self, key: str) -> bool:
        """
        Delete session from Redis.
        
        Args:
            key: Session key
            
        Returns:
            True if deleted
        """
        if not await self.ping():
            return False
        
        try:
            await self._redis.delete(key)
            return True
        except Exception as e:
            logger.error(f"Error deleting session {key}: {e}")
            return False

    # ========================================================================
    # BOT TOKEN MANAGEMENT
    # ========================================================================

    def _bot_token_key(self, token: str) -> str:
        return f"{REDIS_BOT_TOKEN_PREFIX}{token}"

    async def save_bot_token(
        self,
        token: str,
        data: Dict[str, Any],
        expiry: int,
    ) -> bool:
        """
        Save bot token metadata to Redis with TTL.

        Args:
            token: Bot token string
            data: Metadata dict (must include player_id)
            expiry: TTL in seconds
        """
        if not await self.ping():
            return False

        try:
            key = self._bot_token_key(token)
            await self._redis.setex(key, expiry, json.dumps(data))
            return True
        except Exception as e:
            logger.error(f"Error saving bot token {token}: {e}")
            return False

    async def get_bot_token_data(self, token: str) -> Optional[Dict[str, Any]]:
        """
        Get bot token metadata from Redis.

        Args:
            token: Bot token string

        Returns:
            Metadata dict if found, None otherwise
        """
        if not await self.ping():
            return None

        try:
            key = self._bot_token_key(token)
            data = await self._redis.get(key)
            if not data:
                return None
            return json.loads(data)
        except Exception as e:
            logger.error(f"Error getting bot token {token}: {e}")
            return None
    
    # ========================================================================
    # INDEXER STATE (Deposit Deduplication + Progress Tracking)
    # ========================================================================
    
    def _indexer_last_block_key(self, vault_address: str) -> str:
        """Build Redis key for last processed block per vault."""
        return f"{REDIS_INDEXER_PREFIX}last_block:{vault_address.lower()}"
    
    def _processed_event_key(self, event_id: str) -> str:
        """Build Redis key for processed event ID."""
        return f"{REDIS_INDEXER_PREFIX}processed:{event_id}"
    
    def _processing_lock_key(self, event_id: str) -> str:
        """Build Redis key for in-progress event processing lock."""
        return f"{REDIS_INDEXER_PREFIX}processing:{event_id}"
    
    async def get_last_processed_block(self, vault_address: str) -> Optional[int]:
        """
        Get last processed block for a vault address.
        
        Returns:
            Block number if found, None otherwise
        """
        if not await self.ping():
            return None
        
        try:
            key = self._indexer_last_block_key(vault_address)
            value = await self._redis.get(key)
            return int(value) if value is not None else None
        except Exception as e:
            logger.error(f"Error getting last processed block: {e}")
            return None
    
    async def set_last_processed_block(self, vault_address: str, block_number: int) -> bool:
        """
        Persist last processed block for a vault address.
        
        Returns:
            True if persisted successfully
        """
        if not await self.ping():
            return False
        
        try:
            key = self._indexer_last_block_key(vault_address)
            await self._redis.set(key, int(block_number))
            return True
        except Exception as e:
            logger.error(f"Error setting last processed block: {e}")
            return False
    
    async def is_event_processed(self, event_id: str) -> bool:
        """
        Check if an event has already been processed.
        
        Returns:
            True if processed, False otherwise
        """
        if not await self.ping():
            return False
        
        try:
            key = self._processed_event_key(event_id)
            return await self._redis.exists(key) == 1
        except Exception as e:
            logger.error(f"Error checking processed event {event_id}: {e}")
            return False
    
    async def acquire_event_processing_lock(self, event_id: str) -> bool:
        """
        Acquire a short-lived lock for event processing.

        Returns:
            True if lock acquired, False if already locked or Redis unavailable
        """
        if not await self.ping():
            logger.warning("Redis unavailable - blocking event processing (fail-closed)")
            return False
        
        try:
            key = self._processing_lock_key(event_id)
            return await self._redis.set(key, "1", nx=True, ex=EVENT_PROCESSING_LOCK_EXPIRY)
        except Exception as e:
            logger.error(f"Error acquiring event lock {event_id}: {e}")
            return False
    
    async def release_event_processing_lock(self, event_id: str):
        """
        Release event processing lock.
        """
        if not await self.ping():
            return
        
        try:
            key = self._processing_lock_key(event_id)
            await self._redis.delete(key)
        except Exception as e:
            logger.error(f"Error releasing event lock {event_id}: {e}")
    
    async def mark_event_processed(self, event_id: str) -> bool:
        """
        Mark an event as processed to prevent duplicate credits.
        
        Returns:
            True if marked successfully
        """
        if not await self.ping():
            return False
        
        try:
            key = self._processed_event_key(event_id)
            await self._redis.setex(key, PROCESSED_EVENT_EXPIRY, "1")
            return True
        except Exception as e:
            logger.error(f"Error marking event processed {event_id}: {e}")
            return False

    # ========================================================================
    # SETTLEMENT IDEMPOTENCY
    # ========================================================================

    async def mark_settlement_stage_once(self, game_id: str, stage: str) -> bool:
        """
        Mark settlement stage as completed once (SET NX).

        Returns:
            True if this call acquired stage ownership (first execution),
            False if the stage was already marked before.
            If Redis is unavailable, returns False to avoid duplicate settlement.
        """
        if not await self.ping():
            logger.warning("Redis unavailable - settlement idempotency blocked")
            return False

        try:
            key = f"{REDIS_SETTLEMENT_PREFIX}{game_id}:{stage}"
            created = await self._redis.set(key, "1", nx=True, ex=SETTLEMENT_STAGE_EXPIRY)
            return bool(created)
        except Exception as e:
            logger.error(f"Error marking settlement stage {game_id}:{stage}: {e}")
            return False

    async def clear_settlement_stage(self, game_id: str, stage: str) -> bool:
        """
        Clear settlement stage marker (to allow retry).
        
        Args:
            game_id: Game identifier
            stage: Stage identifier
            
        Returns:
            True if cleared successfully
        """
        if not await self.ping():
            return False
            
        try:
            key = f"{REDIS_SETTLEMENT_PREFIX}{game_id}:{stage}"
            await self._redis.delete(key)
            return True
        except Exception as e:
            logger.error(f"Error clearing settlement stage {game_id}:{stage}: {e}")
            return False
    
    # ========================================================================
    # ANTI-COLLUSION (Stub for Future Implementation)
    # ========================================================================
    
    async def record_player_action(
        self, 
        wallet_address: str, 
        game_id: str,
        action_type: str,
        action_data: Dict[str, Any]
    ):
        """
        Record player action for collusion analysis.
        
        Future enhancement: ML-based pattern detection.
        
        Args:
            wallet_address: Player wallet
            game_id: Game identifier
            action_type: Type of action (vote, kill, etc.)
            action_data: Action details
        """
        # TODO: Implement pattern analysis
        # - Track voting patterns
        # - Detect suspicious coordination
        # - Flag potential collusion
        pass
    
    async def analyze_collusion_risk(
        self, 
        wallet_addresses: List[str]
    ) -> Dict[str, Any]:
        """
        Analyze collusion risk between players.
        
        Future enhancement: Statistical analysis of player interactions.
        
        Args:
            wallet_addresses: List of player wallets to analyze
            
        Returns:
            Risk analysis results
        """
        # TODO: Implement statistical analysis
        # - Analyze historical interactions
        # - Calculate collusion probability
        # - Return risk score
        return {
            "risk_level": "low",
            "confidence": 0.0,
            "note": "Anti-collusion analysis not yet implemented"
        }

    # ========================================================================
    # BALANCE CACHING
    # ========================================================================

    async def set_cached_balance(self, player_id: str, balance: str, locked_balance: str) -> None:
        """
        Cache balance and locked balance in Redis as JSON.

        Args:
            player_id: Canonical player identifier
            balance: Current balance as string
            locked_balance: Current locked balance as string
        """
        if not await self.ping():
            return

        try:
            key = f"{REDIS_BALANCE_PREFIX}{player_id}"
            value = json.dumps({"balance": balance, "locked_balance": locked_balance})
            await self._redis.setex(key, BALANCE_CACHE_EXPIRY, value)
        except Exception as e:
            logger.error(f"Error setting cached balance for {player_id}: {e}")

    async def get_cached_balance(self, wallet_address: str) -> Optional[str]:
        """
        Get cached balance from Redis.

        Args:
            wallet_address: Canonical player identifier

        Returns:
            Cached balance as string or None
        """
        if not await self.ping():
            return None

        try:
            data = await self.get_cached_balance_data(wallet_address)
            if data:
                return data.get("balance")
            return None
        except Exception as e:
            logger.error(f"Error getting cached balance for {wallet_address}: {e}")
            return None

    async def get_cached_balance_data(self, player_id: str) -> Optional[Dict[str, str]]:
        """
        Get cached balance data from Redis.

        Args:
            player_id: Canonical player_id

        Returns:
            Dict with balance and locked_balance as strings or None
        """
        if not await self.ping():
            return None

        try:
            key = f"{REDIS_BALANCE_PREFIX}{player_id}"
            value = await self._redis.get(key)
            if value:
                return json.loads(value)
            return None
        except Exception as e:
            logger.error(f"Error getting cached balance data for {player_id}: {e}")
            return None

    async def get_cached_balances_data(self, wallet_addresses: List[str]) -> Dict[str, Dict[str, str]]:
        """
        Bulk get cached balance data for multiple users.

        Args:
            wallet_addresses: Canonical player identifiers

        Returns:
            Mapping of wallet_address -> {balance, locked_balance}
        """
        if not wallet_addresses:
            return {}
        if not await self.ping():
            return {}

        try:
            keys = [f"{REDIS_BALANCE_PREFIX}{wallet}" for wallet in wallet_addresses]
            values = await self._redis.mget(keys)
            result: Dict[str, Dict[str, str]] = {}

            for wallet, raw in zip(wallet_addresses, values):
                if not raw:
                    continue
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    result[wallet] = parsed

            return result
        except Exception as e:
            logger.error(f"Error bulk getting cached balances: {e}")
            return {}

    async def invalidate_balance_cache(self, wallet_address: str) -> None:
        """
        Invalidate balance cache for a user.

        Args:
            wallet_address: Canonical player identifier
        """
        if not await self.ping():
            return

        try:
            key = f"{REDIS_BALANCE_PREFIX}{wallet_address}"
            await self._redis.delete(key)
        except Exception as e:
            logger.error(f"Error invalidating cache for {wallet_address}: {e}")

    # ========================================================================
    # LEADERBOARD CACHING
    # ========================================================================

    async def set_cached_leaderboard(self, entries: List[Dict[str, str]]) -> None:
        """
        Cache leaderboard entries in Redis.

        Args:
            entries: List of leaderboard rows with stringified balances
        """
        if not await self.ping():
            return

        try:
            await self._redis.setex(
                REDIS_LEADERBOARD_KEY,
                LEADERBOARD_CACHE_EXPIRY,
                json.dumps(entries),
            )
        except Exception as e:
            logger.error(f"Error setting cached leaderboard: {e}")

    async def get_cached_leaderboard(self) -> Optional[List[Dict[str, str]]]:
        """
        Get cached leaderboard entries from Redis.

        Returns:
            List of leaderboard rows if cache hit, else None
        """
        if not await self.ping():
            return None

        try:
            cached = await self._redis.get(REDIS_LEADERBOARD_KEY)
            if not cached:
                return None
            data = json.loads(cached)
            return data if isinstance(data, list) else None
        except Exception as e:
            logger.error(f"Error getting cached leaderboard: {e}")
            return None

    async def invalidate_leaderboard_cache(self) -> None:
        """Invalidate cached leaderboard payload."""
        if not await self.ping():
            return

        try:
            await self._redis.delete(REDIS_LEADERBOARD_KEY)
        except Exception as e:
            logger.error(f"Error invalidating cached leaderboard: {e}")


# ============================================================================
# GLOBAL INSTANCE
# ============================================================================

# Create singleton instance
redis_manager = RedisManager()
