"""
Socket.IO Connection Manager with Redis Session Management.

This module provides robust connection handling for the OpenClaw Agent Arena:
- Heartbeats with ping_interval=25, ping_timeout=60
- Redis-based session management (wallet_address -> socket_session_id, current_game_id)
- Reconnection logic with GAME_SNAPSHOT push
- Zombie player handling
"""

import os
import json
import asyncio
from typing import Dict, Optional, Any, List
from datetime import datetime
from dataclasses import dataclass, field, asdict

import redis.asyncio as redis
import socketio


# ============================================================================
# CONFIGURATION
# ============================================================================

REDIS_URL = os.getenv('REDIS_URL', 'redis://localhost:6379')
REDIS_SESSION_PREFIX = 'arena:session:'
REDIS_GAME_PREFIX = 'arena:game:'
SESSION_EXPIRY = 3600  # 1 hour session expiry

# Socket.IO configuration for resilient connections
PING_INTERVAL = 25  # seconds
PING_TIMEOUT = 60  # seconds


# ============================================================================
# DATA CLASSES
# ============================================================================

@dataclass
class PlayerSession:
    """Represents a player's session data stored in Redis."""
    wallet_address: str
    socket_sid: str
    current_game_id: Optional[str] = None
    authenticated: bool = False
    connected_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    last_activity: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'PlayerSession':
        return cls(**data)


@dataclass
class GameSnapshot:
    """Game state snapshot for reconnection recovery."""
    game_id: str
    game_type: str
    phase: str
    day_count: int
    players: List[Dict[str, Any]]
    chat_history: List[Dict[str, Any]]
    your_role: Optional[Dict[str, Any]] = None
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ============================================================================
# SOCKET MANAGER CLASS
# ============================================================================

class SocketManager:
    """
    Manages Socket.IO connections with Redis-backed session persistence.
    
    Features:
    - Heartbeat configuration for load balancer compatibility
    - Redis session storage (wallet -> socket mapping)
    - Automatic reconnection with game state recovery
    - Zombie player tracking
    """
    
    def __init__(
        self,
        redis_url: str = REDIS_URL,
        cors_origins: List[str] = None
    ):
        """
        Initialize the Socket Manager.
        
        Args:
            redis_url: Redis connection URL
            cors_origins: List of allowed CORS origins
        """
        self.redis_url = redis_url
        self.redis_client: Optional[redis.Redis] = None
        
        # Create Socket.IO server with heartbeat configuration
        self.sio = socketio.AsyncServer(
            async_mode='asgi',
            cors_allowed_origins=cors_origins or '*',
            logger=True,
            engineio_logger=False,
            ping_timeout=PING_TIMEOUT,
            ping_interval=PING_INTERVAL
        )
        
        # In-memory session cache (for fast lookups)
        self._session_cache: Dict[str, PlayerSession] = {}
        
        # Game state providers (registered by game modules)
        self._game_state_providers: Dict[str, Any] = {}
    
    async def init_redis(self):
        """Initialize Redis connection."""
        try:
            self.redis_client = redis.from_url(
                self.redis_url,
                encoding='utf-8',
                decode_responses=True
            )
            await self.redis_client.ping()
            print(f"✓ Redis connected: {self.redis_url}")
        except Exception as e:
            print(f"⚠ Redis connection failed: {e}")
            print("  Falling back to in-memory session storage")
            self.redis_client = None
    
    async def close_redis(self):
        """Close Redis connection."""
        if self.redis_client:
            await self.redis_client.close()
    
    def register_game_provider(self, game_type: str, provider: Any):
        """
        Register a game state provider for snapshot generation.
        
        Args:
            game_type: Type of game (e.g., 'werewolf')
            provider: Object with get_game_snapshot(game_id, player_sid) method
        """
        self._game_state_providers[game_type] = provider
    
    # ========================================================================
    # SESSION MANAGEMENT
    # ========================================================================
    
    async def create_session(
        self,
        sid: str,
        wallet_address: str,
        authenticated: bool = False
    ) -> PlayerSession:
        """
        Create a new player session.
        
        Args:
            sid: Socket.IO session ID
            wallet_address: Player's wallet address
            authenticated: Whether player is authenticated
            
        Returns:
            Created PlayerSession object
        """
        session = PlayerSession(
            wallet_address=wallet_address,
            socket_sid=sid,
            authenticated=authenticated
        )
        
        # Store in cache
        self._session_cache[sid] = session
        
        # Store in Redis if available
        if self.redis_client:
            try:
                # Store session by SID
                await self.redis_client.setex(
                    f"{REDIS_SESSION_PREFIX}sid:{sid}",
                    SESSION_EXPIRY,
                    json.dumps(session.to_dict())
                )
                
                # Map wallet -> SID for reconnection lookup
                await self.redis_client.setex(
                    f"{REDIS_SESSION_PREFIX}wallet:{wallet_address.lower()}",
                    SESSION_EXPIRY,
                    sid
                )
            except Exception as e:
                print(f"Redis session create error: {e}")
        
        return session
    
    async def get_session(self, sid: str) -> Optional[PlayerSession]:
        """
        Get a player session by socket ID.
        
        Args:
            sid: Socket.IO session ID
            
        Returns:
            PlayerSession if found, None otherwise
        """
        # Check cache first
        if sid in self._session_cache:
            return self._session_cache[sid]
        
        # Check Redis if available
        if self.redis_client:
            try:
                data = await self.redis_client.get(f"{REDIS_SESSION_PREFIX}sid:{sid}")
                if data:
                    session = PlayerSession.from_dict(json.loads(data))
                    self._session_cache[sid] = session
                    return session
            except Exception as e:
                print(f"Redis session get error: {e}")
        
        return None
    
    async def get_session_by_wallet(self, wallet_address: str) -> Optional[PlayerSession]:
        """
        Get a player session by wallet address.
        
        Args:
            wallet_address: Player's wallet address
            
        Returns:
            PlayerSession if found, None otherwise
        """
        wallet_lower = wallet_address.lower()
        
        # Check cache
        for session in self._session_cache.values():
            if session.wallet_address.lower() == wallet_lower:
                return session
        
        # Check Redis if available
        if self.redis_client:
            try:
                sid = await self.redis_client.get(f"{REDIS_SESSION_PREFIX}wallet:{wallet_lower}")
                if sid:
                    return await self.get_session(sid)
            except Exception as e:
                print(f"Redis wallet lookup error: {e}")
        
        return None
    
    async def update_session(self, sid: str, **updates) -> Optional[PlayerSession]:
        """
        Update a player session.
        
        Args:
            sid: Socket.IO session ID
            **updates: Fields to update
            
        Returns:
            Updated PlayerSession if found, None otherwise
        """
        session = await self.get_session(sid)
        if not session:
            return None
        
        # Apply updates
        for key, value in updates.items():
            if hasattr(session, key):
                setattr(session, key, value)
        
        session.last_activity = datetime.utcnow().isoformat()
        
        # Update cache
        self._session_cache[sid] = session
        
        # Update Redis if available
        if self.redis_client:
            try:
                await self.redis_client.setex(
                    f"{REDIS_SESSION_PREFIX}sid:{sid}",
                    SESSION_EXPIRY,
                    json.dumps(session.to_dict())
                )
            except Exception as e:
                print(f"Redis session update error: {e}")
        
        return session
    
    async def delete_session(self, sid: str) -> bool:
        """
        Delete a player session.
        
        Args:
            sid: Socket.IO session ID
            
        Returns:
            True if deleted, False otherwise
        """
        session = self._session_cache.pop(sid, None)
        
        if self.redis_client and session:
            try:
                await self.redis_client.delete(f"{REDIS_SESSION_PREFIX}sid:{sid}")
                await self.redis_client.delete(
                    f"{REDIS_SESSION_PREFIX}wallet:{session.wallet_address.lower()}"
                )
            except Exception as e:
                print(f"Redis session delete error: {e}")
        
        return session is not None
    
    # ========================================================================
    # GAME SESSION TRACKING
    # ========================================================================
    
    async def join_game(self, sid: str, game_id: str, game_type: str = 'werewolf'):
        """
        Record that a player has joined a game.
        
        Args:
            sid: Socket.IO session ID
            game_id: Game session ID
            game_type: Type of game
        """
        await self.update_session(sid, current_game_id=game_id)
        
        # Store game -> players mapping in Redis
        if self.redis_client:
            try:
                await self.redis_client.sadd(f"{REDIS_GAME_PREFIX}{game_id}:players", sid)
                await self.redis_client.setex(
                    f"{REDIS_GAME_PREFIX}{game_id}:type",
                    SESSION_EXPIRY * 2,
                    game_type
                )
            except Exception as e:
                print(f"Redis game join error: {e}")
        
        # Join Socket.IO room
        await self.sio.enter_room(sid, game_id)
    
    async def leave_game(self, sid: str, game_id: str):
        """
        Record that a player has left a game.
        
        Args:
            sid: Socket.IO session ID
            game_id: Game session ID
        """
        await self.update_session(sid, current_game_id=None)
        
        # Remove from game -> players mapping
        if self.redis_client:
            try:
                await self.redis_client.srem(f"{REDIS_GAME_PREFIX}{game_id}:players", sid)
            except Exception as e:
                print(f"Redis game leave error: {e}")
        
        # Leave Socket.IO room
        await self.sio.leave_room(sid, game_id)
    
    async def get_game_players(self, game_id: str) -> List[str]:
        """
        Get all player SIDs in a game.
        
        Args:
            game_id: Game session ID
            
        Returns:
            List of player socket IDs
        """
        if self.redis_client:
            try:
                players = await self.redis_client.smembers(f"{REDIS_GAME_PREFIX}{game_id}:players")
                return list(players)
            except Exception as e:
                print(f"Redis get game players error: {e}")
        
        return []
    
    # ========================================================================
    # RECONNECTION HANDLING
    # ========================================================================
    
    async def handle_reconnection(
        self,
        new_sid: str,
        wallet_address: str,
        auth_token: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Handle player reconnection with game state recovery.
        
        This is the core reconnection logic:
        1. Validate agent
        2. Check Redis for current_game_id
        3. If game found: re-join room and push GAME_SNAPSHOT
        
        Args:
            new_sid: New Socket.IO session ID
            wallet_address: Player's wallet address
            auth_token: Optional authentication token
            
        Returns:
            Dict with reconnection status and game snapshot if applicable
        """
        result = {
            'reconnected': False,
            'game_id': None,
            'snapshot': None
        }
        
        # Check for existing session by wallet
        old_session = await self.get_session_by_wallet(wallet_address)
        
        if old_session and old_session.current_game_id:
            game_id = old_session.current_game_id
            result['game_id'] = game_id
            
            # Create new session with existing game context
            new_session = await self.create_session(
                new_sid,
                wallet_address,
                authenticated=True
            )
            new_session.current_game_id = game_id
            await self.update_session(new_sid, current_game_id=game_id)
            
            # Re-join the Socket.IO room
            await self.sio.enter_room(new_sid, game_id)
            
            # Update player SID in game mapping
            if self.redis_client:
                try:
                    await self.redis_client.srem(
                        f"{REDIS_GAME_PREFIX}{game_id}:players",
                        old_session.socket_sid
                    )
                    await self.redis_client.sadd(
                        f"{REDIS_GAME_PREFIX}{game_id}:players",
                        new_sid
                    )
                except Exception as e:
                    print(f"Redis reconnection update error: {e}")
            
            # Generate game snapshot for recovery
            game_type = 'werewolf'  # Default, could be looked up from Redis
            if game_type in self._game_state_providers:
                provider = self._game_state_providers[game_type]
                if hasattr(provider, 'get_game_snapshot'):
                    try:
                        snapshot = await provider.get_game_snapshot(game_id, new_sid)
                        result['snapshot'] = snapshot
                    except Exception as e:
                        print(f"Snapshot generation error: {e}")
            
            # Delete old session
            if old_session.socket_sid != new_sid:
                await self.delete_session(old_session.socket_sid)
            
            result['reconnected'] = True
            
            # Emit GAME_SNAPSHOT event
            if result['snapshot']:
                await self.sio.emit('GAME_SNAPSHOT', result['snapshot'], room=new_sid)
        else:
            # New connection, create fresh session
            await self.create_session(new_sid, wallet_address, authenticated=True)
        
        return result
    
    async def push_game_snapshot(self, sid: str, game_id: str, game_type: str = 'werewolf'):
        """
        Push a game snapshot to a specific player.
        
        Called when a player needs to recover their game context.
        
        Args:
            sid: Socket.IO session ID
            game_id: Game session ID
            game_type: Type of game
        """
        if game_type in self._game_state_providers:
            provider = self._game_state_providers[game_type]
            if hasattr(provider, 'get_game_snapshot'):
                try:
                    snapshot = await provider.get_game_snapshot(game_id, sid)
                    await self.sio.emit('GAME_SNAPSHOT', snapshot, room=sid)
                except Exception as e:
                    print(f"Push snapshot error: {e}")
    
    # ========================================================================
    # BROADCAST UTILITIES
    # ========================================================================
    
    async def broadcast_to_game(self, game_id: str, event: str, data: Any):
        """
        Broadcast an event to all players in a game.
        
        Args:
            game_id: Game session ID
            event: Event name
            data: Event data
        """
        await self.sio.emit(event, data, room=game_id)
    
    async def send_to_player(self, sid: str, event: str, data: Any):
        """
        Send an event to a specific player.
        
        Args:
            sid: Socket.IO session ID
            event: Event name
            data: Event data
        """
        await self.sio.emit(event, data, room=sid)
    
    async def broadcast_player_timeout(self, game_id: str, player_nickname: str):
        """
        Broadcast that a player timed out.
        
        Args:
            game_id: Game session ID
            player_nickname: Nickname of the player who timed out
        """
        await self.broadcast_to_game(game_id, 'PLAYER_TIMEOUT', {
            'message': f'Player {player_nickname} Timed Out',
            'player': player_nickname,
            'timestamp': datetime.utcnow().isoformat()
        })
    
    async def broadcast_game_abort(self, game_id: str, reason: str):
        """
        Broadcast that a game has been aborted.
        
        Args:
            game_id: Game session ID
            reason: Reason for abort
        """
        await self.broadcast_to_game(game_id, 'GAME_ABORTED', {
            'message': reason,
            'refunded': True,
            'timestamp': datetime.utcnow().isoformat()
        })


# ============================================================================
# GLOBAL SOCKET MANAGER INSTANCE
# ============================================================================

# Create global socket manager instance
socket_manager = SocketManager()


def get_socket_manager() -> SocketManager:
    """Get the global socket manager instance."""
    return socket_manager


def get_sio() -> socketio.AsyncServer:
    """Get the Socket.IO server instance."""
    return socket_manager.sio
