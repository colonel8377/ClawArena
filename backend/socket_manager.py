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

import socketio
from backend.database.redis_manager import redis_manager, REDIS_SESSION_PREFIX, REDIS_GAME_PREFIX, SESSION_EXPIRY


# ============================================================================
# CONFIGURATION
# ============================================================================

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
        cors_origins: List[str] = None
    ):
        """
        Initialize the Socket Manager.
        
        Args:
            cors_origins: List of allowed CORS origins
        """
        # Use global RedisManager instance
        self.redis_manager = redis_manager
        
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
        """Initialize Redis connection via RedisManager."""
        connected = await self.redis_manager.connect()
        if connected:
            print(f"✓ Redis connected via RedisManager")
        else:
            print(f"⚠ Redis connection failed")
            print("  Falling back to in-memory session storage")
    
    async def close_redis(self):
        """Close Redis connection via RedisManager."""
        await self.redis_manager.disconnect()
    
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
        
        # Store in Redis via RedisManager
        try:
            # Store session by SID
            await self.redis_manager.save_session(
                f"{REDIS_SESSION_PREFIX}sid:{sid}",
                session.to_dict(),
                SESSION_EXPIRY
            )
            
            # Map wallet -> SID for reconnection lookup
            await self.redis_manager.save_session(
                f"{REDIS_SESSION_PREFIX}wallet:{wallet_address.lower()}",
                {"sid": sid},
                SESSION_EXPIRY
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
        
        # Check Redis via RedisManager
        try:
            data = await self.redis_manager.get_session(f"{REDIS_SESSION_PREFIX}sid:{sid}")
            if data:
                session = PlayerSession.from_dict(data)
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
        
        # Check Redis via RedisManager
        try:
            data = await self.redis_manager.get_session(f"{REDIS_SESSION_PREFIX}wallet:{wallet_lower}")
            if data and "sid" in data:
                return await self.get_session(data["sid"])
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
        
        # Update Redis via RedisManager
        try:
            await self.redis_manager.save_session(
                f"{REDIS_SESSION_PREFIX}sid:{sid}",
                session.to_dict(),
                SESSION_EXPIRY
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
        
        if session:
            try:
                await self.redis_manager.delete_session(f"{REDIS_SESSION_PREFIX}sid:{sid}")
                await self.redis_manager.delete_session(
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
        redis_client = self.redis_manager.client
        if redis_client:
            try:
                await redis_client.sadd(f"{REDIS_GAME_PREFIX}{game_id}:players", sid)
                await redis_client.setex(
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
        redis_client = self.redis_manager.client
        if redis_client:
            try:
                await redis_client.srem(f"{REDIS_GAME_PREFIX}{game_id}:players", sid)
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
        redis_client = self.redis_manager.client
        if redis_client:
            try:
                players = await redis_client.smembers(f"{REDIS_GAME_PREFIX}{game_id}:players")
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
            redis_client = self.redis_manager.client
            if redis_client:
                try:
                    await redis_client.srem(
                        f"{REDIS_GAME_PREFIX}{game_id}:players",
                        old_session.socket_sid
                    )
                    await redis_client.sadd(
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
    
    # ========================================================================
    # POKER UNIFIED ROOM BROADCAST (Privacy Filter Architecture)
    # ========================================================================
    
    def _get_room_id(self, game_id: str) -> str:
        """
        Get the unified room ID for a poker game.
        
        All agents AND spectators join this SAME room.
        
        Args:
            game_id: Game session ID
            
        Returns:
            Room ID in format "room_game_{id}"
        """
        return f"room_game_{game_id}"
    
    async def join_poker_room(self, sid: str, game_id: str):
        """
        Join a player/spectator to the unified poker room.
        
        Args:
            sid: Socket.IO session ID
            game_id: Game session ID
        """
        room_id = self._get_room_id(game_id)
        await self.sio.enter_room(sid, room_id)
    
    async def leave_poker_room(self, sid: str, game_id: str):
        """
        Remove a player/spectator from the poker room.
        
        Args:
            sid: Socket.IO session ID
            game_id: Game session ID
        """
        room_id = self._get_room_id(game_id)
        await self.sio.leave_room(sid, room_id)
    
    async def broadcast_game_state(
        self,
        game_id: str,
        game_state: Dict[str, Any],
        last_event: Optional[Dict[str, Any]] = None,
        active_agent_sids: Optional[List[str]] = None,
        player_hole_cards: Optional[Dict[str, List[str]]] = None
    ):
        """
        Broadcast game state with Privacy Filter.
        
        This implements the unified room broadcast architecture:
        
        Step 1 - Public Payload (For Everyone):
        - community_cards: Visible cards on the board
        - pot: Current pot size  
        - last_event: Player action + chat message
        - CRITICAL: All hole_cards are MASKED as ["??", "??"] unless showdown
        
        Step 2 - Private Payload (For Active Agents Only):
        - Send 'private_hand' event to each agent's specific socket_id
        - Contains ONLY that agent's real hole cards
        
        Args:
            game_id: Game session ID
            game_state: Current game state from poker engine
            last_event: Optional last action event with chat
            active_agent_sids: List of active agent socket IDs
            player_hole_cards: Dict mapping agent_sid -> their real hole cards
        """
        timestamp = datetime.utcnow().isoformat()
        room_id = self._get_room_id(game_id)
        is_showdown = game_state.get('phase') == 'showdown'
        
        # ====================================================================
        # STEP 1: Public Payload (For Everyone in the Room)
        # ====================================================================
        
        # Build player list with MASKED hole cards (unless showdown)
        public_players = []
        for player in game_state.get('players', []):
            player_info = {
                'sid': player.get('sid'),
                'wallet_address': player.get('wallet_address'),
                'nickname': player.get('nickname'),
                'chips': player.get('chips'),
                'current_bet': player.get('current_bet'),
                'status': player.get('status'),
                'last_action': player.get('last_action'),
                # CRITICAL: Mask hole cards unless showdown
                'hole_cards': player.get('hole_cards', ['??', '??']) if is_showdown else ['??', '??']
            }
            public_players.append(player_info)
        
        public_payload = {
            'game_id': game_id,
            'phase': game_state.get('phase'),
            'community_cards': game_state.get('community_cards', []),
            'pot': game_state.get('pot', 0),
            'current_bet': game_state.get('current_bet', 0),
            'current_player': game_state.get('current_player'),
            'players': public_players,
            'last_event': last_event,
            'timestamp': timestamp
        }
        
        # Broadcast to unified room (all agents + spectators)
        await self.sio.emit('game_update', public_payload, room=room_id)
        
        # ====================================================================
        # STEP 2: Private Payload (For Active Agents Only)
        # ====================================================================
        
        if player_hole_cards:
            for agent_sid, hole_cards in player_hole_cards.items():
                if not active_agent_sids or agent_sid in active_agent_sids:
                    private_payload = {
                        'game_id': game_id,
                        'hole_cards': hole_cards,
                        'your_turn': game_state.get('current_player') == agent_sid,
                        'timestamp': timestamp
                    }
                    # Send directly to agent's specific socket_id
                    await self.sio.emit('private_hand', private_payload, room=agent_sid)
    
    async def broadcast_poker_action(
        self,
        game_id: str,
        agent_sid: str,
        agent_wallet: str,
        agent_nickname: str,
        action: str,
        amount: int,
        message: str,
        game_state: Dict[str, Any],
        active_agent_sids: List[str],
        player_hole_cards: Dict[str, List[str]]
    ):
        """
        Broadcast a poker action with the player's chat/bluff message.
        
        Creates the last_event log entry and broadcasts via Privacy Filter.
        
        Args:
            game_id: Game session ID
            agent_sid: Socket ID of the acting agent
            agent_wallet: Wallet address of the acting agent
            agent_nickname: Display name of the acting agent
            action: Action taken (fold/call/raise/check)
            amount: Bet amount (for raise/call)
            message: The agent's chat/bluff message
            game_state: Current game state
            active_agent_sids: List of active agent socket IDs
            player_hole_cards: Dict mapping agent_sid -> their real hole cards
        """
        # Construct the last_event log entry
        last_event = {
            'player': agent_wallet,
            'player_sid': agent_sid,
            'nickname': agent_nickname,
            'action': action.upper(),
            'amt': amount,
            'chat': message,
            'timestamp': datetime.utcnow().isoformat()
        }
        
        # Broadcast with Privacy Filter
        await self.broadcast_game_state(
            game_id=game_id,
            game_state=game_state,
            last_event=last_event,
            active_agent_sids=active_agent_sids,
            player_hole_cards=player_hole_cards
        )
    
    async def broadcast_showdown(
        self,
        game_id: str,
        game_state: Dict[str, Any],
        winners: List[Dict[str, Any]]
    ):
        """
        Broadcast showdown - all hole cards are now revealed publicly.
        
        At showdown, the Privacy Filter is lifted and all hole cards
        are visible to everyone in the room.
        
        Args:
            game_id: Game session ID
            game_state: Game state with phase='showdown'
            winners: List of winner information
        """
        timestamp = datetime.utcnow().isoformat()
        room_id = self._get_room_id(game_id)
        
        # Build player list with REVEALED hole cards
        revealed_players = []
        for player in game_state.get('players', []):
            player_info = {
                'sid': player.get('sid'),
                'wallet_address': player.get('wallet_address'),
                'nickname': player.get('nickname'),
                'chips': player.get('chips'),
                'status': player.get('status'),
                # At showdown, reveal real hole cards (with fallback)
                'hole_cards': player.get('hole_cards') or ['??', '??']
            }
            revealed_players.append(player_info)
        
        showdown_payload = {
            'game_id': game_id,
            'event': 'showdown',
            'phase': 'showdown',
            'community_cards': game_state.get('community_cards', []),
            'pot': game_state.get('pot', 0),
            'players': revealed_players,
            'winners': winners,
            'timestamp': timestamp
        }
        
        # Broadcast to unified room - everyone sees all cards now
        await self.sio.emit('game_update', showdown_payload, room=room_id)
    
    async def send_private_hand(
        self,
        agent_sid: str,
        game_id: str,
        hole_cards: List[str],
        is_your_turn: bool = False
    ):
        """
        Send private hand info to a specific agent.
        
        Used during initial deal or when agent reconnects.
        
        Args:
            agent_sid: Socket ID of the agent
            game_id: Game session ID
            hole_cards: The agent's hole cards (e.g., ["Th", "Ts"])
            is_your_turn: Whether it's this agent's turn to act
        """
        private_payload = {
            'game_id': game_id,
            'hole_cards': hole_cards,
            'your_turn': is_your_turn,
            'timestamp': datetime.utcnow().isoformat()
        }
        
        await self.sio.emit('private_hand', private_payload, room=agent_sid)
    
    async def broadcast_poker_chat(
        self,
        game_id: str,
        player_sid: str,
        player_nickname: str,
        message: str,
        action: Optional[str] = None
    ):
        """
        Broadcast a standalone chat message (not tied to an action).
        
        Args:
            game_id: Game session ID
            player_sid: Socket ID of the sender
            player_nickname: Display name of the sender
            message: The chat message
            action: Optional action context
        """
        room_id = self._get_room_id(game_id)
        
        chat_payload = {
            'game_id': game_id,
            'event': 'chat',
            'player_sid': player_sid,
            'nickname': player_nickname,
            'message': message,
            'action': action,
            'timestamp': datetime.utcnow().isoformat()
        }
        
        await self.sio.emit('game_update', chat_payload, room=room_id)
    
    async def send_poker_game_snapshot(
        self,
        sid: str,
        game_id: str,
        game_state: Dict[str, Any],
        hole_cards: Optional[List[str]] = None,
        is_agent: bool = True
    ):
        """
        Send a complete game snapshot to a reconnecting participant.
        
        For agents: Includes private hole cards via separate event.
        For spectators: Only public state with masked cards.
        
        Args:
            sid: Socket.IO session ID of the reconnecting participant
            game_id: Game session ID
            game_state: Current public game state
            hole_cards: Agent's hole cards (None for spectators)
            is_agent: Whether the participant is an agent or spectator
        """
        timestamp = datetime.utcnow().isoformat()
        is_showdown = game_state.get('phase') == 'showdown'
        
        # Build public player list with masked cards (unless showdown)
        public_players = []
        for player in game_state.get('players', []):
            player_info = {
                'sid': player.get('sid'),
                'nickname': player.get('nickname'),
                'chips': player.get('chips'),
                'current_bet': player.get('current_bet'),
                'status': player.get('status'),
                'hole_cards': player.get('hole_cards', ['??', '??']) if is_showdown else ['??', '??']
            }
            public_players.append(player_info)
        
        # Send public game state
        snapshot_data = {
            'game_id': game_id,
            'game_type': 'poker',
            'phase': game_state.get('phase'),
            'community_cards': game_state.get('community_cards', []),
            'pot': game_state.get('pot', 0),
            'current_bet': game_state.get('current_bet', 0),
            'current_player': game_state.get('current_player'),
            'players': public_players,
            'chat_history': game_state.get('chat_history', []),
            'timestamp': timestamp
        }
        
        await self.sio.emit('GAME_SNAPSHOT', snapshot_data, room=sid)
        
        # If agent, also send their private hand
        if is_agent and hole_cards:
            await self.send_private_hand(
                agent_sid=sid,
                game_id=game_id,
                hole_cards=hole_cards,
                is_your_turn=game_state.get('current_player') == sid
            )


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
