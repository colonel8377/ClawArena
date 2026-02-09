"""
Persistence Manager for ClawArena.

Unified interface for managing game data persistence across:
- Redis (hot storage): Active game core state (for server restart recovery)
- MySQL (cold storage): Game sessions, player records, history, chat messages

Architecture (Single-Server):
- Chat messages: In-memory + Socket.IO broadcast + MySQL async persistence
- Game state: Redis core state (for recovery)
- Formal speeches: MySQL (permanent history)

Critical Sync Points:
- Game creation → MySQL GameSession
- Player join → MySQL GamePlayer
- Game start → MySQL GameSession update + Redis core state
- Phase change → Redis core state (MySQL only for significant phases)
- Game end → MySQL GameSession update + GameHistory + cleanup Redis
"""

import asyncio
import logging
from datetime import datetime
from decimal import Decimal
from typing import Optional, Dict, Any, List

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .redis_manager import redis_manager
from .connection import get_async_db_session, AsyncSessionLocal
from .models import (
    GameSession, GamePlayer, GameHistory, ChatMessage,
    UserLedger, GameStatus, PlayerStatus
)

logger = logging.getLogger(__name__)


class PersistenceManager:
    """
    Unified persistence manager for game data.
    
    Coordinates between Redis (hot storage) and MySQL (cold storage).
    """
    
    def __init__(self):
        """Initialize the persistence manager."""
        self._redis = redis_manager
        # Throttle poker cold writes to avoid high-frequency MySQL pressure.
        self._poker_last_mysql_checkpoint: Dict[str, datetime] = {}
        self._poker_mysql_checkpoint_interval_seconds = 15
    
    # ========================================================================
    # GAME LIFECYCLE PERSISTENCE
    # ========================================================================
    
    async def on_game_created(
        self,
        game_id: str,
        game_type: str,
        entry_fee: Decimal = Decimal("0"),
        **kwargs
    ) -> bool:
        """
        Persist game creation to MySQL.
        
        Called when a new game is created.
        
        Args:
            game_id: Unique game identifier
            game_type: Type of game ('werewolf', 'texas')
            entry_fee: Entry fee for the game
            
        Returns:
            True if persisted successfully
        """
        try:
            if AsyncSessionLocal is None:
                logger.warning("Async database not available")
                return False
            
            async with get_async_db_session() as db:
                # Check if game session already exists
                result = await db.execute(
                    select(GameSession).where(GameSession.id == game_id)
                )
                existing = result.scalar_one_or_none()
                
                if existing:
                    logger.warning(f"Game session already exists: {game_id}")
                    return True
                
                # Create new game session
                game_session = GameSession(
                    id=game_id,
                    game_type=game_type,
                    status=GameStatus.WAITING.value,
                    entry_fee=entry_fee,
                    prize_pool=Decimal("0"),
                    player_count=0,
                    day_count=0,
                    created_at=datetime.utcnow()
                )
                db.add(game_session)
                await db.commit()
                
                logger.info(f"Game session created in MySQL: {game_id}")
                return True
                
        except Exception as e:
            logger.error(f"Error creating game session {game_id}: {e}")
            return False
    
    async def on_player_joined(
        self,
        game_id: str,
        player_id: str,
        socket_sid: str,
        nickname: str = "Player",
        entry_paid: Decimal = Decimal("0"),
        **kwargs
    ) -> bool:
        """
        Persist player joining to MySQL.
        
        Called when a player joins a game.
        
        Args:
            game_id: Game identifier
            player_id: Player identifier
            socket_sid: Player's socket session ID
            nickname: Player's display name
            entry_paid: Entry fee paid by player
            
        Returns:
            True if persisted successfully
        """
        try:
            if AsyncSessionLocal is None:
                logger.warning("Async database not available")
                return False
            
            async with get_async_db_session() as db:
                # Get or create user
                result = await db.execute(
                    select(UserLedger).where(
                        UserLedger.wallet_address == player_id
                    )
                )
                user = result.scalar_one_or_none()
                
                if not user:
                    logger.warning(f"Rejecting game join persistence for unknown player_id: {player_id}")
                    return False
                
                # Check if player already in game
                result = await db.execute(
                    select(GamePlayer).where(
                        GamePlayer.game_session_id == game_id,
                        GamePlayer.wallet_address == player_id
                    )
                )
                existing = result.scalar_one_or_none()
                
                if existing:
                    # Update socket SID for reconnection
                    existing.socket_sid = socket_sid
                    await db.commit()
                    return True
                
                # Create game player record
                game_player = GamePlayer(
                    game_session_id=game_id,
                    user_id=user.id,
                    wallet_address=player_id,
                    socket_sid=socket_sid,
                    nickname=nickname,
                    status=PlayerStatus.ALIVE.value,
                    is_alive=True,
                    entry_paid=entry_paid,
                    joined_at=datetime.utcnow()
                )
                db.add(game_player)
                
                # Update game session player count
                await db.execute(
                    update(GameSession)
                    .where(GameSession.id == game_id)
                    .values(player_count=GameSession.player_count + 1)
                )
                
                await db.commit()
                logger.info(f"Player {player_id[:8]} joined game {game_id} in MySQL")
                return True
                
        except Exception as e:
            logger.error(f"Error recording player join {game_id}: {e}")
            return False
    
    async def on_game_started(
        self,
        game_id: str,
        players_with_roles: List[Dict[str, Any]],
        initial_state: Dict[str, Any]
    ) -> bool:
        """
        Persist game start to MySQL and Redis.
        
        Called when the game transitions from WAITING to active.
        
        Args:
            game_id: Game identifier
            players_with_roles: List of player dicts with assigned roles
            initial_state: Initial game state (for Redis)
            
        Returns:
            True if persisted successfully
        """
        try:
            # MySQL: Update game session and player roles
            if AsyncSessionLocal:
                async with get_async_db_session() as db:
                    # Update game session status
                    await db.execute(
                        update(GameSession)
                        .where(GameSession.id == game_id)
                        .values(
                            status=GameStatus.ACTIVE.value,
                            started_at=datetime.utcnow(),
                            current_phase=initial_state.get('phase', 'unknown')
                        )
                    )
                    
                    # Update player roles
                    for player_data in players_with_roles:
                        player_id = player_data.get('player_id') or player_data.get('wallet_address', '')
                        role = player_data.get('role_type', player_data.get('role'))
                        team = player_data.get('team')
                        
                        if player_id and role:
                            await db.execute(
                                update(GamePlayer)
                                .where(
                                    GamePlayer.game_session_id == game_id,
                                    GamePlayer.wallet_address == player_id
                                )
                                .values(
                                    role=role if isinstance(role, str) else role.value if hasattr(role, 'value') else str(role),
                                    team=team if isinstance(team, str) else team.value if hasattr(team, 'value') else str(team) if team else None
                                )
                            )
                    
                    await db.commit()
            
            # Redis: Save core state (without chat)
            core_state = self._extract_core_state(initial_state)
            await self._redis.save_game_core(
                game_id,
                core_state,
                game_type=initial_state.get('game_type', 'werewolf')
            )
            
            logger.info(f"Game started: {game_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error recording game start {game_id}: {e}")
            return False
    
    async def on_phase_changed(
        self,
        game_id: str,
        new_phase: str,
        day_count: int,
        game_state: Dict[str, Any],
        deaths: List[Dict] = None,
        significant: bool = False
    ) -> bool:
        """
        Persist phase change.
        
        Redis: Always update core state
        MySQL: Only update for significant phases (day start, game end)
        
        Args:
            game_id: Game identifier
            new_phase: New phase name
            day_count: Current day count
            game_state: Full game state
            deaths: List of deaths this phase
            significant: Whether to sync to MySQL
            
        Returns:
            True if persisted successfully
        """
        try:
            # Redis: Always save core state
            core_state = self._extract_core_state(game_state)
            await self._redis.save_game_core(
                game_id,
                core_state,
                game_type=game_state.get('game_type', 'werewolf')
            )
            
            # MySQL: Only for significant phases
            if significant and AsyncSessionLocal:
                async with get_async_db_session() as db:
                    await db.execute(
                        update(GameSession)
                        .where(GameSession.id == game_id)
                        .values(
                            current_phase=new_phase,
                            day_count=day_count,
                            updated_at=datetime.utcnow()
                        )
                    )
                    
                    # Update player death status
                    if deaths:
                        for death in deaths:
                            player_id = death.get('player_id') or death.get('wallet_address', '')
                            if player_id:
                                await db.execute(
                                    update(GamePlayer)
                                    .where(
                                        GamePlayer.game_session_id == game_id,
                                        GamePlayer.wallet_address == player_id
                                    )
                                    .values(
                                        is_alive=False,
                                        status=PlayerStatus.DEAD.value
                                    )
                                )
                    
                    await db.commit()
            
            return True
            
        except Exception as e:
            logger.error(f"Error recording phase change {game_id}: {e}")
            return False
    
    async def on_game_ended(
        self,
        game_id: str,
        winner_team: Optional[str],
        winners: List[str],
        was_aborted: bool = False,
        final_state: Dict[str, Any] = None,
        prize_pool: Optional[Decimal] = None,
    ) -> bool:
        """
        Persist game end to MySQL and cleanup Redis.
        
        Args:
            game_id: Game identifier
            winner_team: Winning team ('wolf', 'villager', or None)
            winners: List of winner wallet addresses
            was_aborted: Whether game was aborted
            final_state: Final game state
            
        Returns:
            True if persisted successfully
        """
        try:
            if AsyncSessionLocal:
                async with get_async_db_session() as db:
                    # Get game session for duration calculation
                    result = await db.execute(
                        select(GameSession).where(GameSession.id == game_id)
                    )
                    game_session = result.scalar_one_or_none()
                    
                    duration_seconds = None
                    player_count = 0
                    prize_amount = Decimal("0")
                    
                    if game_session:
                        player_count = game_session.player_count
                        if prize_pool is not None:
                            prize_amount = prize_pool
                        else:
                            prize_amount = game_session.prize_pool
                        
                        if game_session.started_at:
                            duration_seconds = int(
                                (datetime.utcnow() - game_session.started_at).total_seconds()
                            )
                        
                        # Update game session
                        update_values = {
                            'status': GameStatus.ABORTED.value if was_aborted else GameStatus.FINISHED.value,
                            'winner_team': winner_team,
                            'finished_at': datetime.utcnow(),
                            'current_phase': 'finished' if not was_aborted else 'aborted',
                        }
                        if prize_pool is not None:
                            update_values['prize_pool'] = prize_pool

                        await db.execute(
                            update(GameSession)
                            .where(GameSession.id == game_id)
                            .values(**update_values)
                        )
                    
                    # Create game history records
                    for winner_player_id in winners:
                        game_history = GameHistory(
                            game_session_id=game_id,
                            game_type='werewolf',
                            winner_wallet=winner_player_id,
                            winner_team=winner_team,
                            prize_amount=prize_amount / len(winners) if winners else Decimal("0"),
                            player_count=player_count,
                            duration_seconds=duration_seconds,
                            was_aborted=was_aborted,
                            created_at=datetime.utcnow()
                        )
                        db.add(game_history)
                    
                    # Update player winnings
                    if winners and prize_amount > 0:
                        prize_per_winner = prize_amount / len(winners)
                        for winner_player_id in winners:
                            await db.execute(
                                update(GamePlayer)
                                .where(
                                    GamePlayer.game_session_id == game_id,
                                    GamePlayer.wallet_address == winner_player_id
                                )
                                .values(winnings=prize_per_winner)
                            )
                    
                    await db.commit()
            
            # Redis: Delete game data after a delay (allow final state reads)
            # Schedule cleanup for 5 minutes later
            asyncio.create_task(self._delayed_redis_cleanup(game_id, delay=300))
            
            logger.info(f"Game ended: {game_id}, winners: {winners}")
            return True
            
        except Exception as e:
            logger.error(f"Error recording game end {game_id}: {e}")
            return False

    async def save_poker_checkpoint(
        self,
        game_id: str,
        game_state: Dict[str, Any],
        event_type: str = "manual",
        force_mysql: bool = False
    ) -> bool:
        """
        Persist poker cold snapshot to MySQL with event-aware throttling.

        Redis hot state should be saved by caller before invoking this method.
        This method intentionally rate-limits MySQL updates to control write cost
        while still forcing durability on critical hand lifecycle events.
        """
        try:
            if not AsyncSessionLocal:
                return False

            now = datetime.utcnow()
            if not self._should_write_poker_mysql(game_id, event_type, now, force_mysql):
                return True

            snapshot = self._extract_core_state(game_state)
            phase = str(snapshot.get('phase') or 'unknown')
            players = snapshot.get('players') or []
            player_count = len(players) if isinstance(players, list) else 0
            status = GameStatus.WAITING.value if phase == 'waiting' else GameStatus.ACTIVE.value

            async with get_async_db_session() as db:
                result = await db.execute(
                    select(GameSession).where(GameSession.id == game_id)
                )
                game_session = result.scalar_one_or_none()

                if game_session is None:
                    game_session = GameSession(
                        id=game_id,
                        game_type='texas',
                        status=status,
                        player_count=player_count,
                        current_phase=phase,
                        state_snapshot=snapshot,
                        created_at=now,
                        started_at=now if event_type == 'hand_start' else None,
                    )
                    db.add(game_session)
                else:
                    update_values = {
                        'game_type': game_session.game_type or 'texas',
                        'status': status,
                        'player_count': max(game_session.player_count or 0, player_count),
                        'current_phase': phase,
                        'state_snapshot': snapshot,
                        'updated_at': now,
                    }
                    if event_type == 'hand_start' and not game_session.started_at:
                        update_values['started_at'] = now

                    await db.execute(
                        update(GameSession)
                        .where(GameSession.id == game_id)
                        .values(**update_values)
                    )

                await db.commit()

            self._poker_last_mysql_checkpoint[game_id] = now
            return True

        except Exception as e:
            logger.error(f"Error saving poker checkpoint {game_id}: {e}")
            return False

    def _should_write_poker_mysql(
        self,
        game_id: str,
        event_type: str,
        now: datetime,
        force_mysql: bool = False
    ) -> bool:
        """Decide whether to write a poker checkpoint to MySQL now."""
        if force_mysql:
            return True

        critical_events = {
            'hand_start',
            'phase_change',
            'hand_end',
            'showdown',
            'shutdown',
        }
        if event_type in critical_events:
            return True

        last_write = self._poker_last_mysql_checkpoint.get(game_id)
        if not last_write:
            return True

        elapsed = (now - last_write).total_seconds()
        return elapsed >= self._poker_mysql_checkpoint_interval_seconds
    
    async def _delayed_redis_cleanup(self, game_id: str, delay: int = 300):
        """Cleanup Redis data after a delay."""
        await asyncio.sleep(delay)
        await self._redis.delete_game_data(game_id)
        logger.info(f"Redis data cleaned up for game: {game_id}")
    
    # ========================================================================
    # CHAT & SPEECH PERSISTENCE (Async MySQL)
    # ========================================================================
    
    async def save_chat_message(
        self,
        game_id: str,
        game_type: str,
        player_id: str,
        nickname: str,
        message: str,
        message_type: str = "chat",
        metadata: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Save chat message to MySQL.
        
        Args:
            game_id: Game identifier
            game_type: Game type ('werewolf', 'texas', etc.)
            player_id: Speaker's player ID
            nickname: Speaker's display name
            message: Message content
            message_type: Type of message (chat, wolf_chat, speak, action, etc.)
            metadata: Optional message metadata
            
        Returns:
            True if saved successfully
        """
        try:
            if not AsyncSessionLocal:
                return True
            if not message:
                return True
            
            async with get_async_db_session() as db:
                chat_record = ChatMessage(
                    game_session_id=game_id,
                    game_type=game_type or "unknown",
                    player_wallet=player_id,
                    nickname=nickname,
                    message=message,
                    message_type=message_type,
                    message_metadata=metadata or None
                )
                db.add(chat_record)
                await db.commit()
            
            return True
        
        except Exception as e:
            logger.error(f"Error saving chat message {game_id}: {e}")
            return False
    
    async def save_speech(
        self,
        game_id: str,
        player_id: str,
        nickname: str,
        message: str,
        phase: str = None,
        game_type: str = "werewolf"
    ) -> bool:
        """
        Save formal speech to MySQL for permanent game history.
        
        Args:
            game_id: Game identifier
            player_id: Speaker's player ID
            nickname: Speaker's display name
            message: Speech content
            phase: Current game phase
            game_type: Game type (default: werewolf)
            
        Returns:
            True if saved successfully
        """
        metadata = {'phase': phase} if phase else None
        saved = await self.save_chat_message(
            game_id=game_id,
            game_type=game_type,
            player_id=player_id,
            nickname=nickname,
            message=message,
            message_type='speak',
            metadata=metadata
        )
        if saved:
            logger.debug(f"Speech persisted to MySQL: {game_id}/{nickname}")
        return saved
    
    # ========================================================================
    # STATE RECOVERY
    # ========================================================================
    
    async def restore_game_state(self, game_id: str) -> Optional[Dict[str, Any]]:
        """
        Restore game state from Redis.
        
        For single-server deployment:
        - Core state is restored from Redis
        - Chat history is NOT restored into memory (chat is persisted in MySQL)
        - Game continues without old in-memory chat (players can still communicate)
        
        Args:
            game_id: Game identifier
            
        Returns:
            Game state dict or None
        """
        try:
            # Get core state from Redis
            core_data = await self._redis.restore_game_core(game_id)
            if not core_data:
                return None
            
            state = core_data.get('state', {})
            
            # Chat history is intentionally empty after restart
            # (was stored in memory only for single-server efficiency)
            state['public_chat'] = []
            state['wolf_chat'] = []
            
            return {
                'game_id': core_data.get('game_id'),
                'game_type': core_data.get('game_type'),
                'saved_at': core_data.get('saved_at'),
                'state': state
            }
            
        except Exception as e:
            logger.error(f"Error restoring game state {game_id}: {e}")
            return None
    
    async def get_mysql_game_session(self, game_id: str) -> Optional[Dict[str, Any]]:
        """
        Get game session from MySQL.
        
        Used for recovery when Redis data is lost.
        
        Args:
            game_id: Game identifier
            
        Returns:
            Game session dict or None
        """
        try:
            if not AsyncSessionLocal:
                return None
            
            async with get_async_db_session() as db:
                result = await db.execute(
                    select(GameSession).where(GameSession.id == game_id)
                )
                session = result.scalar_one_or_none()
                
                if not session:
                    return None
                
                # Get players
                players_result = await db.execute(
                    select(GamePlayer).where(GamePlayer.game_session_id == game_id)
                )
                players = players_result.scalars().all()
                
                return {
                    'game_id': session.id,
                    'game_type': session.game_type,
                    'status': session.status,
                    'winner_team': session.winner_team,
                    'player_count': session.player_count,
                    'current_phase': session.current_phase,
                    'day_count': session.day_count,
                    'created_at': session.created_at.isoformat() if session.created_at else None,
                    'started_at': session.started_at.isoformat() if session.started_at else None,
                    'finished_at': session.finished_at.isoformat() if session.finished_at else None,
                    'players': [
                        {
                            'wallet_address': p.wallet_address,
                            'nickname': p.nickname,
                            'role': p.role,
                            'team': p.team,
                            'is_alive': p.is_alive,
                            'status': p.status
                        }
                        for p in players
                    ]
                }
                
        except Exception as e:
            logger.error(f"Error getting MySQL game session {game_id}: {e}")
            return None
    
    # ========================================================================
    # PLAYER STATUS UPDATES
    # ========================================================================
    
    async def update_player_status(
        self,
        game_id: str,
        player_id: str,
        status: str,
        is_alive: bool = None,
        consecutive_timeouts: int = None
    ) -> bool:
        """
        Update player status in MySQL.
        
        Args:
            game_id: Game identifier
            player_id: Player's player ID
            status: New status ('alive', 'dead', 'zombie')
            is_alive: Whether player is alive
            consecutive_timeouts: Timeout count
            
        Returns:
            True if updated successfully
        """
        try:
            if not AsyncSessionLocal:
                return False
            
            async with get_async_db_session() as db:
                update_values = {'status': status}
                
                if is_alive is not None:
                    update_values['is_alive'] = is_alive
                if consecutive_timeouts is not None:
                    update_values['consecutive_timeouts'] = consecutive_timeouts
                
                await db.execute(
                    update(GamePlayer)
                    .where(
                        GamePlayer.game_session_id == game_id,
                        GamePlayer.wallet_address == player_id
                    )
                    .values(**update_values)
                )
                await db.commit()
                return True
                
        except Exception as e:
            logger.error(f"Error updating player status: {e}")
            return False
    
    async def update_player_socket_sid(
        self,
        game_id: str,
        player_id: str,
        new_sid: str
    ) -> bool:
        """
        Update player's socket SID for reconnection.
        
        Args:
            game_id: Game identifier
            player_id: Player's player ID
            new_sid: New socket session ID
            
        Returns:
            True if updated successfully
        """
        try:
            if not AsyncSessionLocal:
                return False
            
            async with get_async_db_session() as db:
                await db.execute(
                    update(GamePlayer)
                    .where(
                        GamePlayer.game_session_id == game_id,
                        GamePlayer.wallet_address == player_id
                    )
                    .values(socket_sid=new_sid, last_action_at=datetime.utcnow())
                )
                await db.commit()
                return True
                
        except Exception as e:
            logger.error(f"Error updating player socket SID: {e}")
            return False
    
    # ========================================================================
    # HELPER METHODS
    # ========================================================================
    
    def _extract_core_state(self, full_state: Dict[str, Any]) -> Dict[str, Any]:
        """
        Extract core state from full state (excluding chat).
        
        This reduces the size of frequently-updated Redis entries.
        
        Args:
            full_state: Full game state dict
            
        Returns:
            Core state without chat history
        """
        core = dict(full_state)
        
        # Remove chat data (stored separately)
        core.pop('public_chat', None)
        core.pop('wolf_chat', None)
        core.pop('chat_messages', None)
        
        return core


# Global singleton instance
persistence_manager = PersistenceManager()
