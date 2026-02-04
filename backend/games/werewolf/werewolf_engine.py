"""
Werewolf Game Engine with Timeout and Zombie Handling.

This module implements the complete Werewolf (Mafia) game engine:
- State Machine: Night -> Day -> Voting -> Repeat
- Dynamic Roles: Factory Pattern for 6-9 players
- Zombie Logic: Timeout tracking and recovery
- Settlement Hook: Prize distribution and refunds

The engine is designed for AI Agent gameplay with robust timeout handling.
"""

import asyncio
import random
import uuid
from typing import Dict, List, Optional, Any, Callable, Awaitable
from enum import Enum
from datetime import datetime
from decimal import Decimal
from dataclasses import dataclass, field

from backend.games.base import BaseGame
from backend.games.werewolf.roles import (
    Role, RoleType, Team, create_role,
    Wolf, Seer, Witch, Hunter
)
from backend.games.werewolf.game_config import get_setup


# ============================================================================
# CONSTANTS
# ============================================================================

# Timeout configuration
TURN_TIMEOUT_SECONDS = 120  # Extended timeout for LLM reasoning (was 60s)
ZOMBIE_THRESHOLD = 2  # Consecutive timeouts before zombie mode
ABORT_ZOMBIE_THRESHOLD = 0.5  # >50% zombies triggers abort


# ============================================================================
# ENUMS AND DATA CLASSES
# ============================================================================

class GamePhase(Enum):
    """Werewolf game phases."""
    WAITING = "waiting"
    NIGHT = "night"
    DAY = "day"
    VOTING = "voting"
    FINISHED = "finished"
    ABORTED = "aborted"


class PlayerStatus(Enum):
    """Player status in game."""
    ALIVE = "alive"
    DEAD = "dead"
    ZOMBIE = "zombie"


@dataclass
class GamePlayer:
    """
    Represents a player in the Werewolf game.
    
    Tracks zombie status and timeout behavior.
    """
    sid: str
    wallet_address: str
    nickname: str
    role: Optional[Role] = None
    is_alive: bool = True
    status: PlayerStatus = PlayerStatus.ALIVE
    consecutive_timeouts: int = 0
    last_action_time: Optional[datetime] = None
    entry_fee_paid: Decimal = Decimal("0")
    
    def is_zombie(self) -> bool:
        """Check if player is in zombie mode."""
        return self.status == PlayerStatus.ZOMBIE or self.consecutive_timeouts >= ZOMBIE_THRESHOLD
    
    def mark_zombie(self):
        """Mark player as zombie after consecutive timeouts."""
        self.status = PlayerStatus.ZOMBIE
    
    def recover_from_zombie(self):
        """Recover from zombie status on valid action."""
        if self.status == PlayerStatus.ZOMBIE and self.is_alive:
            self.status = PlayerStatus.ALIVE
            self.consecutive_timeouts = 0
    
    def record_timeout(self):
        """Record a timeout and check for zombie transition."""
        self.consecutive_timeouts += 1
        if self.consecutive_timeouts >= ZOMBIE_THRESHOLD:
            self.mark_zombie()
    
    def record_action(self):
        """Record that player took an action (resets timeout counter)."""
        self.last_action_time = datetime.utcnow()
        if self.status == PlayerStatus.ZOMBIE:
            self.recover_from_zombie()
        else:
            self.consecutive_timeouts = 0
    
    def to_dict(self, reveal_role: bool = False, is_wolf_viewer: bool = False) -> Dict:
        """Convert to dictionary for game state."""
        result = {
            'sid': self.sid,
            'wallet_address': self.wallet_address,
            'nickname': self.nickname,
            'is_alive': self.is_alive,
            'status': self.status.value,
            'is_zombie': self.is_zombie()
        }
        
        # Reveal role only if explicitly requested or if wolf viewing other wolves
        if reveal_role and self.role:
            result['role'] = self.role.get_role_info()
        elif is_wolf_viewer and self.role and isinstance(self.role, Wolf):
            result['role'] = self.role.get_role_info()
        
        return result


@dataclass
class PhaseAction:
    """Represents an action pending for the current phase."""
    player_sid: str
    action_type: str
    target_sid: Optional[str] = None
    extra_data: Optional[Dict] = None
    timestamp: datetime = field(default_factory=datetime.utcnow)


# ============================================================================
# WEREWOLF ENGINE CLASS
# ============================================================================

class WerewolfEngine(BaseGame):
    """
    Werewolf game engine with complete game logic.
    
    Features:
    - Dynamic role assignment (6-9 players)
    - State machine (Night -> Day -> Voting)
    - Zombie handling (timeout tracking, recovery)
    - Settlement hooks (prize distribution, refunds)
    
    Usage:
        engine = WerewolfEngine(game_id="game_123")
        engine.add_player(sid, wallet_address, nickname="Player1")
        await engine.start_game()
        
        # Game loop handled by engine with timeouts
        result = await engine.process_action(sid, "vote", target_sid=target)
    """
    
    MIN_PLAYERS = 6
    MAX_PLAYERS = 9
    
    def __init__(
        self,
        game_id: str,
        entry_fee: Decimal = Decimal("10.0"),
        on_phase_change: Optional[Callable[..., Awaitable[None]]] = None,
        on_game_end: Optional[Callable[..., Awaitable[None]]] = None,
        on_timeout: Optional[Callable[..., Awaitable[None]]] = None
    ):
        """
        Initialize the Werewolf engine.
        
        Args:
            game_id: Unique game identifier
            entry_fee: Entry fee per player (for prize pool)
            on_phase_change: Callback when phase changes
            on_game_end: Callback when game ends
            on_timeout: Callback when player times out
        """
        super().__init__(game_id)
        
        self.entry_fee = entry_fee
        self.prize_pool = Decimal("0")
        self.phase = GamePhase.WAITING
        self.day_count = 0
        
        # Player management
        self.players: List[GamePlayer] = []
        self._player_map: Dict[str, GamePlayer] = {}  # sid -> player
        
        # Initial role tracking
        self.initial_role_counts: Dict[RoleType, int] = {}
        
        # Phase action tracking
        self.wolf_votes: Dict[str, str] = {}  # wolf_sid -> target_sid
        self.seer_check: Optional[str] = None
        self.witch_action: Dict[str, Any] = {}
        self.hunter_shot: Optional[str] = None
        self.votes: Dict[str, str] = {}  # voter_sid -> target_sid
        
        # Chat history for reconnection
        self.chat_history: List[Dict] = []
        
        # Timeout management
        self._phase_timer: Optional[asyncio.Task] = None
        self._pending_actions: Dict[str, bool] = {}  # sid -> has_acted
        
        # Callbacks
        self._on_phase_change = on_phase_change
        self._on_game_end = on_game_end
        self._on_timeout = on_timeout
        
        # Timestamps
        self.created_at = datetime.utcnow()
        self.started_at: Optional[datetime] = None
        self.finished_at: Optional[datetime] = None
    
    # ========================================================================
    # PLAYER MANAGEMENT
    # ========================================================================
    
    def add_player(self, sid: str, wallet_address: str, **kwargs) -> bool:
        """Add a player to the game."""
        if len(self.players) >= self.MAX_PLAYERS:
            return False
        
        if self.phase != GamePhase.WAITING:
            return False
        
        if sid in self._player_map:
            return False
        
        nickname = kwargs.get('nickname', f'Player{len(self.players) + 1}')
        entry_fee_paid = kwargs.get('entry_fee_paid', self.entry_fee)
        
        player = GamePlayer(
            sid=sid,
            wallet_address=wallet_address,
            nickname=nickname,
            entry_fee_paid=entry_fee_paid
        )
        
        self.players.append(player)
        self._player_map[sid] = player
        self.prize_pool += entry_fee_paid
        
        return True
    
    def remove_player(self, sid: str) -> bool:
        """Remove a player from the game (only in waiting phase)."""
        if self.phase != GamePhase.WAITING:
            return False
        
        player = self._player_map.pop(sid, None)
        if player:
            self.players.remove(player)
            self.prize_pool -= player.entry_fee_paid
            return True
        return False
    
    def update_player_sid(self, old_sid: str, new_sid: str) -> bool:
        """Update a player's socket ID (for reconnection)."""
        player = self._player_map.pop(old_sid, None)
        if player:
            player.sid = new_sid
            self._player_map[new_sid] = player
            return True
        return False
    
    def get_player(self, sid: str) -> Optional[GamePlayer]:
        """Get a player by socket ID."""
        return self._player_map.get(sid)
    
    def get_player_by_wallet(self, wallet_address: str) -> Optional[GamePlayer]:
        """Get a player by wallet address."""
        wallet_lower = wallet_address.lower()
        for player in self.players:
            if player.wallet_address.lower() == wallet_lower:
                return player
        return None
    
    def get_alive_players(self) -> List[GamePlayer]:
        """Get all alive players."""
        return [p for p in self.players if p.is_alive]
    
    def get_zombie_count(self) -> int:
        """Get count of zombie players."""
        return sum(1 for p in self.players if p.is_zombie() and p.is_alive)
    
    def get_zombie_ratio(self) -> float:
        """Get ratio of zombie players among alive players."""
        alive = self.get_alive_players()
        if not alive:
            return 0.0
        return self.get_zombie_count() / len(alive)
    
    # ========================================================================
    # GAME LIFECYCLE
    # ========================================================================
    
    def can_start(self) -> bool:
        """Check if game can start."""
        return len(self.players) >= self.MIN_PLAYERS
    
    async def start_game(self) -> bool:
        """Start the game by assigning roles and moving to night phase."""
        if not self.can_start():
            return False
        
        if self.phase != GamePhase.WAITING:
            return False
        
        # Assign roles
        self._assign_roles()
        
        # Initialize game state
        self.started_at = datetime.utcnow()
        self.phase = GamePhase.NIGHT
        self.day_count = 1
        
        # Notify phase change
        if self._on_phase_change:
            await self._on_phase_change(self.game_id, self.phase, self.day_count)
        
        # Start phase timer
        await self._start_phase_timer()
        
        return True
    
    def _assign_roles(self):
        """Assign roles to players using the factory pattern."""
        num_players = len(self.players)
        roles = get_setup(num_players)
        
        # Track initial role counts
        self.initial_role_counts.clear()
        for role_type in roles:
            self.initial_role_counts[role_type] = self.initial_role_counts.get(role_type, 0) + 1
        
        # Assign roles to players
        for player, role_type in zip(self.players, roles):
            player.role = create_role(role_type)
    
    async def abort_game(self, reason: str = "Too many zombies"):
        """
        Abort the game and refund all players.
        
        Called when >50% of players are zombies.
        """
        self.phase = GamePhase.ABORTED
        self.finished_at = datetime.utcnow()
        
        # Cancel any active timers
        if self._phase_timer and not self._phase_timer.done():
            self._phase_timer.cancel()
        
        # Calculate refunds
        refund_data = await self._calculate_refunds()
        
        # Notify game end with abort
        if self._on_game_end:
            await self._on_game_end(
                self.game_id,
                is_aborted=True,
                reason=reason,
                refunds=refund_data
            )
        
        return refund_data
    
    async def _calculate_refunds(self) -> List[Dict]:
        """Calculate refund amounts for each player."""
        refunds = []
        for player in self.players:
            refunds.append({
                'wallet_address': player.wallet_address,
                'amount': float(player.entry_fee_paid),
                'reason': 'game_aborted'
            })
        return refunds
    
    # ========================================================================
    # TIMEOUT HANDLING
    # ========================================================================
    
    async def _start_phase_timer(self):
        """Start the phase timer for timeout handling."""
        if self._phase_timer and not self._phase_timer.done():
            self._phase_timer.cancel()
        
        # Reset pending actions for this phase
        self._pending_actions.clear()
        for player in self.get_alive_players():
            # Skip zombies - they don't need to act
            if not player.is_zombie():
                self._pending_actions[player.sid] = False
        
        # Start timer
        self._phase_timer = asyncio.create_task(self._phase_timeout_task())
    
    async def _phase_timeout_task(self):
        """
        Async task that handles phase timeout.
        
        After TURN_TIMEOUT_SECONDS:
        - Execute default actions for players who didn't act
        - Record timeouts for those players
        - Check for zombie threshold and potentially abort game
        """
        try:
            await asyncio.sleep(TURN_TIMEOUT_SECONDS)
            
            # Handle timeout
            await self._handle_phase_timeout()
            
        except asyncio.CancelledError:
            pass  # Timer was cancelled (phase advanced normally)
    
    async def _handle_phase_timeout(self):
        """
        Handle timeout for the current phase.
        
        Tier 1: Execute default actions for timed-out players
        Tier 2: Mark players as zombies if they timeout twice
        Tier 3: Abort game if >50% are zombies
        """
        timed_out_players = []
        
        for sid, has_acted in self._pending_actions.items():
            if not has_acted:
                player = self.get_player(sid)
                if player and player.is_alive:
                    # Record timeout
                    player.record_timeout()
                    timed_out_players.append(player)
                    
                    # Execute default action
                    await self._execute_default_action(player)
                    
                    # Notify timeout
                    if self._on_timeout:
                        await self._on_timeout(
                            self.game_id,
                            player.nickname,
                            player.consecutive_timeouts,
                            player.is_zombie()
                        )
        
        # Check for game abort condition (>50% zombies)
        if self.get_zombie_ratio() > ABORT_ZOMBIE_THRESHOLD:
            await self.abort_game("More than 50% of players are inactive (zombies)")
            return
        
        # Advance to next phase
        await self.advance_phase()
    
    async def _execute_default_action(self, player: GamePlayer):
        """
        Execute default action for a timed-out player.
        
        UPDATED: Zombies now perform random legal actions instead of just passing
        to prevent game stalling.
        
        Default actions by phase:
        - Night (Wolf): Random kill vote on alive non-wolf
        - Night (Seer): Random check on alive player
        - Night (Witch): Skip (to preserve strategic potion use)
        - Voting: Random vote on alive player
        """
        if not player.is_zombie():
            # Non-zombie timeout: just skip (original behavior)
            return
        
        # Zombie timeout: perform random legal action
        # Apply zombie penalty (deduct reputation/tokens)
        # TODO: Implement actual penalty logic with economy system
        # For now, we just log the penalty
        print(f"Zombie penalty applied to {player.nickname} (timeout count: {player.consecutive_timeouts})")
        
        # Get list of alive players for random selection
        alive_players = [p for p in self.players.values() if p.is_alive and p.sid != player.sid]
        
        if not alive_players:
            return  # No valid targets
        
        # Execute random action based on role and phase
        if self.phase == GamePhase.NIGHT:
            # Night phase: role-specific actions
            if isinstance(player.role, Wolf):
                # Random wolf kill vote
                non_wolf_targets = [p for p in alive_players if not isinstance(p.role, Wolf)]
                if non_wolf_targets:
                    target = random.choice(non_wolf_targets)
                    self.wolf_votes[player.sid] = target.sid
                    print(f"Zombie wolf {player.nickname} auto-voted to kill {target.nickname}")
            
            elif isinstance(player.role, Seer):
                # Random seer check
                target = random.choice(alive_players)
                player.role.check_player(target.sid, target.role.team)
                self.seer_check = target.sid
                print(f"Zombie seer {player.nickname} auto-checked {target.nickname}")
            
            # Note: Witch potions are not used automatically to preserve strategic value
        
        elif self.phase == GamePhase.VOTING:
            # Random vote during day voting
            target = random.choice(alive_players)
            self.day_votes[player.sid] = target.sid
            print(f"Zombie {player.nickname} auto-voted for {target.nickname}")
    
    # ========================================================================
    # ACTION PROCESSING
    # ========================================================================
    
    def process_action(self, sid: str, action: str, **kwargs) -> Dict:
        """
        Process a player action synchronously.
        
        For async version, use process_action_async.
        """
        return asyncio.get_event_loop().run_until_complete(
            self.process_action_async(sid, action, **kwargs)
        )
    
    async def process_action_async(self, sid: str, action: str, **kwargs) -> Dict:
        """
        Process a player action.
        
        Actions:
        - night_kill: Wolf votes to kill
        - seer_check: Seer checks a player
        - witch_save: Witch uses antidote
        - witch_poison: Witch uses poison
        - vote: Vote to eliminate
        - hunter_shoot: Hunter shoots when dying
        - chat: Send chat message
        """
        player = self.get_player(sid)
        if not player:
            return {'success': False, 'error': 'Player not found'}
        
        if not player.is_alive:
            return {'success': False, 'error': 'Player is dead'}
        
        # If player was zombie and sends valid action, recover them
        if player.is_zombie():
            player.recover_from_zombie()
        
        # Record that player took action
        player.record_action()
        self._pending_actions[sid] = True
        
        # Route to appropriate handler
        handlers = {
            'night_kill': self._handle_wolf_kill,
            'seer_check': self._handle_seer_check,
            'witch_save': self._handle_witch_save,
            'witch_poison': self._handle_witch_poison,
            'vote': self._handle_vote,
            'hunter_shoot': self._handle_hunter_shoot,
            'chat': self._handle_chat
        }
        
        handler = handlers.get(action)
        if not handler:
            return {'success': False, 'error': 'Unknown action'}
        
        return await handler(player, **kwargs)
    
    async def _handle_wolf_kill(self, player: GamePlayer, **kwargs) -> Dict:
        """Handle wolf kill vote."""
        if self.phase != GamePhase.NIGHT:
            return {'success': False, 'error': 'Not night phase'}
        
        if not isinstance(player.role, Wolf):
            return {'success': False, 'error': 'Not a wolf'}
        
        target_sid = kwargs.get('target_sid')
        if not target_sid:
            return {'success': False, 'error': 'Target required'}
        
        target = self.get_player(target_sid)
        if not target or not target.is_alive:
            return {'success': False, 'error': 'Invalid target'}
        
        self.wolf_votes[player.sid] = target_sid
        return {'success': True, 'action': 'night_kill', 'target': target.nickname}
    
    async def _handle_seer_check(self, player: GamePlayer, **kwargs) -> Dict:
        """Handle seer check."""
        if self.phase != GamePhase.NIGHT:
            return {'success': False, 'error': 'Not night phase'}
        
        if not isinstance(player.role, Seer):
            return {'success': False, 'error': 'Not a seer'}
        
        target_sid = kwargs.get('target_sid')
        if not target_sid:
            return {'success': False, 'error': 'Target required'}
        
        target = self.get_player(target_sid)
        if not target or not target.is_alive:
            return {'success': False, 'error': 'Invalid target'}
        
        # Perform the check
        result = player.role.check_player(target_sid, target.role.team)
        self.seer_check = target_sid
        
        return {
            'success': True,
            'action': 'seer_check',
            'target': target.nickname,
            'result': result
        }
    
    async def _handle_witch_save(self, player: GamePlayer, **kwargs) -> Dict:
        """Handle witch save action."""
        if self.phase != GamePhase.NIGHT:
            return {'success': False, 'error': 'Not night phase'}
        
        if not isinstance(player.role, Witch):
            return {'success': False, 'error': 'Not a witch'}
        
        # Prevent using both potions in the same night
        if self.witch_action.get('poison'):
            return {'success': False, 'error': 'Cannot use both potions in the same night'}
        
        if not player.role.use_antidote():
            return {'success': False, 'error': 'Antidote already used'}
        
        self.witch_action['save'] = True
        return {'success': True, 'action': 'witch_save'}
    
    async def _handle_witch_poison(self, player: GamePlayer, **kwargs) -> Dict:
        """Handle witch poison action."""
        if self.phase != GamePhase.NIGHT:
            return {'success': False, 'error': 'Not night phase'}
        
        if not isinstance(player.role, Witch):
            return {'success': False, 'error': 'Not a witch'}
        
        # Prevent using both potions in the same night
        if self.witch_action.get('save'):
            return {'success': False, 'error': 'Cannot use both potions in the same night'}
        
        target_sid = kwargs.get('target_sid')
        if not target_sid:
            return {'success': False, 'error': 'Target required'}
        
        if not player.role.use_poison():
            return {'success': False, 'error': 'Poison already used'}
        
        self.witch_action['poison'] = target_sid
        return {'success': True, 'action': 'witch_poison'}
    
    async def _handle_vote(self, player: GamePlayer, **kwargs) -> Dict:
        """Handle elimination vote."""
        if self.phase != GamePhase.VOTING:
            return {'success': False, 'error': 'Not voting phase'}
        
        target_sid = kwargs.get('target_sid')
        if not target_sid:
            return {'success': False, 'error': 'Target required'}
        
        target = self.get_player(target_sid)
        if not target or not target.is_alive:
            return {'success': False, 'error': 'Invalid target'}
        
        self.votes[player.sid] = target_sid
        return {'success': True, 'action': 'vote', 'target': target.nickname}
    
    async def _handle_hunter_shoot(self, player: GamePlayer, **kwargs) -> Dict:
        """Handle hunter's dying shot."""
        if not isinstance(player.role, Hunter):
            return {'success': False, 'error': 'Not a hunter'}
        
        target_sid = kwargs.get('target_sid')
        if not target_sid:
            return {'success': False, 'error': 'Target required'}
        
        result = player.role.shoot(target_sid)
        if result['success']:
            self.hunter_shot = target_sid
            target = self.get_player(target_sid)
            if target:
                target.is_alive = False
                target.status = PlayerStatus.DEAD
        
        return result
    
    async def _handle_chat(self, player: GamePlayer, **kwargs) -> Dict:
        """Handle chat message."""
        message = kwargs.get('message', '')
        if not message:
            return {'success': False, 'error': 'Message required'}
        
        chat_entry = {
            'sid': player.sid,
            'nickname': player.nickname,
            'message': message,
            'timestamp': datetime.utcnow().isoformat(),
            'phase': self.phase.value
        }
        
        self.chat_history.append(chat_entry)
        return {'success': True, 'action': 'chat', 'entry': chat_entry}
    
    # ========================================================================
    # PHASE ADVANCEMENT
    # ========================================================================
    
    async def advance_phase(self) -> Dict:
        """
        Advance to the next game phase and resolve actions.
        
        Handles zombie logic - if a player is zombie, skip their phase logic.
        """
        # Cancel any active timer
        if self._phase_timer and not self._phase_timer.done():
            self._phase_timer.cancel()
        
        if self.phase == GamePhase.NIGHT:
            result = await self._resolve_night()
        elif self.phase == GamePhase.DAY:
            result = await self._start_voting()
        elif self.phase == GamePhase.VOTING:
            result = await self._resolve_voting()
        else:
            result = {'success': False, 'error': 'Cannot advance from current phase'}
            return result
        
        # Check win conditions
        if self.is_game_over():
            self.phase = GamePhase.FINISHED
            self.finished_at = datetime.utcnow()
            result['game_over'] = True
            result['winners'] = self.get_winners()
            
            # Calculate and distribute prizes
            settlement = await self._settle_game()
            result['settlement'] = settlement
            
            if self._on_game_end:
                await self._on_game_end(
                    self.game_id,
                    is_aborted=False,
                    winners=result['winners'],
                    settlement=settlement
                )
        else:
            # Start timer for next phase
            await self._start_phase_timer()
            
            if self._on_phase_change:
                await self._on_phase_change(self.game_id, self.phase, self.day_count)
        
        return result
    
    async def _resolve_night(self) -> Dict:
        """Resolve night actions."""
        results = {
            'phase': 'night_resolution',
            'deaths': [],
            'day_count': self.day_count
        }
        
        # Determine wolf kill target (majority vote among non-zombie wolves)
        wolf_target = None
        if self.wolf_votes:
            target_counts = {}
            for target in self.wolf_votes.values():
                target_counts[target] = target_counts.get(target, 0) + 1
            if target_counts:
                wolf_target = max(target_counts, key=target_counts.get)
        
        # Check if witch saves
        saved = self.witch_action.get('save', False)
        
        # Apply wolf kill (unless saved)
        if wolf_target and not saved:
            target = self.get_player(wolf_target)
            if target:
                target.is_alive = False
                target.status = PlayerStatus.DEAD
                results['deaths'].append({
                    'sid': wolf_target,
                    'nickname': target.nickname,
                    'cause': 'wolf_kill'
                })
        
        # Apply witch poison
        poison_target = self.witch_action.get('poison')
        if poison_target:
            target = self.get_player(poison_target)
            if target:
                target.is_alive = False
                target.status = PlayerStatus.DEAD
                results['deaths'].append({
                    'sid': poison_target,
                    'nickname': target.nickname,
                    'cause': 'poison'
                })
        
        # Clear night actions
        self.wolf_votes.clear()
        self.seer_check = None
        self.witch_action.clear()
        
        # Move to day phase
        self.phase = GamePhase.DAY
        results['new_phase'] = 'day'
        
        return results
    
    async def _start_voting(self) -> Dict:
        """Start voting phase."""
        self.phase = GamePhase.VOTING
        self.votes.clear()
        return {
            'phase': 'voting',
            'success': True,
            'alive_players': [p.nickname for p in self.get_alive_players()]
        }
    
    async def _resolve_voting(self) -> Dict:
        """Resolve voting phase."""
        import random
        
        results = {
            'phase': 'voting_resolution',
            'eliminated': None,
            'votes': {}
        }
        
        # Count votes (exclude zombie abstentions)
        if self.votes:
            vote_counts = {}
            for voter_sid, target_sid in self.votes.items():
                voter = self.get_player(voter_sid)
                target = self.get_player(target_sid)
                if voter and target and not voter.is_zombie():
                    vote_counts[target_sid] = vote_counts.get(target_sid, 0) + 1
                    results['votes'][voter.nickname] = target.nickname
            
            if vote_counts:
                # Find player with most votes
                max_votes = max(vote_counts.values())
                candidates = [sid for sid, count in vote_counts.items() if count == max_votes]
                
                # Eliminate (random if tie)
                eliminated_sid = random.choice(candidates)
                eliminated = self.get_player(eliminated_sid)
                if eliminated:
                    eliminated.is_alive = False
                    eliminated.status = PlayerStatus.DEAD
                    results['eliminated'] = {
                        'sid': eliminated_sid,
                        'nickname': eliminated.nickname,
                        'votes': vote_counts[eliminated_sid],
                        'role': eliminated.role.role_type.value if eliminated.role else None
                    }
        
        # Clear votes
        self.votes.clear()
        
        # Move to next night (if game not over)
        if not self.is_game_over():
            self.phase = GamePhase.NIGHT
            self.day_count += 1
            results['new_phase'] = 'night'
            results['day_count'] = self.day_count
        
        return results
    
    # ========================================================================
    # WIN CONDITIONS AND SETTLEMENT
    # ========================================================================
    
    def is_game_over(self) -> bool:
        """Check if game is over."""
        alive_players = self.get_alive_players()
        
        if not alive_players:
            return True
        
        wolves_alive = sum(1 for p in alive_players if p.role and p.role.team == Team.WOLF)
        villagers_alive = sum(1 for p in alive_players if p.role and p.role.team == Team.VILLAGER)
        
        # Wolves win if they equal or outnumber villagers
        if wolves_alive >= villagers_alive:
            return True
        
        # Villagers win if no wolves left
        if wolves_alive == 0:
            return True
        
        return False
    
    def get_winning_team(self) -> Optional[Team]:
        """Get the winning team."""
        if not self.is_game_over():
            return None
        
        alive_players = self.get_alive_players()
        if not alive_players:
            return None  # Draw
        
        wolves_alive = sum(1 for p in alive_players if p.role and p.role.team == Team.WOLF)
        
        if wolves_alive > 0:
            return Team.WOLF
        return Team.VILLAGER
    
    def get_winners(self) -> List[str]:
        """Get list of winning wallet addresses."""
        if not self.is_game_over():
            return []
        
        winning_team = self.get_winning_team()
        if not winning_team:
            return []  # Draw
        
        # Return all players on winning team (alive or dead)
        return [
            p.wallet_address
            for p in self.players
            if p.role and p.role.team == winning_team
        ]
    
    async def _settle_game(self) -> Dict:
        """
        Settle the game and calculate prize distribution.
        
        Called when game ends normally (not aborted).
        """
        winners = self.get_winners()
        
        if not winners:
            # Draw - return entry fees
            return await self._calculate_refunds()
        
        # Calculate prize per winner
        prize_per_winner = self.prize_pool / len(winners)
        
        settlement = {
            'winning_team': self.get_winning_team().value if self.get_winning_team() else None,
            'total_prize_pool': float(self.prize_pool),
            'winner_count': len(winners),
            'prize_per_winner': float(prize_per_winner),
            'payouts': []
        }
        
        for wallet_address in winners:
            settlement['payouts'].append({
                'wallet_address': wallet_address,
                'amount': float(prize_per_winner),
                'type': 'prize'
            })
        
        return settlement
    
    # ========================================================================
    # GAME STATE
    # ========================================================================
    
    def get_game_state(self, sid: Optional[str] = None) -> Dict:
        """
        Get game state with appropriate information masking.
        
        Returns player-specific view with:
        - Their own role
        - Other wolves (if they're a wolf)
        - Alive/dead/zombie status of all players
        """
        requesting_player = self.get_player(sid) if sid else None
        is_wolf = requesting_player and isinstance(requesting_player.role, Wolf)
        
        state = {
            'game_id': self.game_id,
            'phase': self.phase.value,
            'day_count': self.day_count,
            'player_count': len(self.players),
            'alive_count': len(self.get_alive_players()),
            'zombie_count': self.get_zombie_count(),
            'players': []
        }
        
        for player in self.players:
            is_self = sid and player.sid == sid
            player_info = player.to_dict(
                reveal_role=is_self,
                is_wolf_viewer=is_wolf
            )
            state['players'].append(player_info)
        
        return state
    
    async def get_game_snapshot(self, game_id: str, player_sid: str) -> Dict:
        """
        Get full game snapshot for reconnection.
        
        Includes:
        - Current game state
        - Chat history
        - Phase information
        
        Args:
            game_id: Game ID to verify (must match self.game_id)
            player_sid: Player socket ID
        """
        if game_id != self.game_id:
            raise ValueError(f"Game ID mismatch: expected {self.game_id}, got {game_id}")
        
        player = self.get_player(player_sid)
        state = self.get_game_state(player_sid)
        
        snapshot = {
            'game_id': game_id,
            'game_type': 'werewolf',
            'phase': self.phase.value,
            'day_count': self.day_count,
            'players': state['players'],
            'chat_history': self.chat_history[-50:],  # Last 50 messages
            'your_role': player.role.get_role_info() if player and player.role else None,
            'is_alive': player.is_alive if player else False,
            'timestamp': datetime.utcnow().isoformat()
        }
        
        return snapshot
    
    def _has_role(self, role_type: RoleType) -> bool:
        """Check if a role exists in the game."""
        return any(
            p.role and p.role.role_type == role_type
            for p in self.players
        )
