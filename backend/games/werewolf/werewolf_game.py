"""
Werewolf Game State Machine Implementation.

This module implements the complete Werewolf (Mafia) game as a state machine:
- Detailed night phases: Wolf Discussion → Wolf Vote → Seer Check → Witch Action
- Day phases: Death Announcement → Speaking (ordered) → Voting
- Special triggers: Hunter shoot on death

The design follows real-world Werewolf rules and is optimized for AI agent gameplay.
"""

import random
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Any, Callable, Awaitable, Set

from .game_config import get_setup
from .roles import (
    RoleType, Team, create_role,
    Wolf, Seer, Witch, Hunter
)
from ..base import BaseGame, chat_restricted_error, check_chat_phase

# ============================================================================
# CONSTANTS
# ============================================================================

# Timeout configuration (seconds)
PHASE_TIMEOUTS = {
    'wolf_discussion': 30,    # Wolves discuss who to kill
    'wolf_voting': 20,        # Wolves vote on target
    'seer_action': 15,        # Seer checks one player
    'witch_action': 20,       # Witch decides save/poison
    'hunter_action': 15,      # Hunter shoots if dying
    'death_announcement': 10, # Announce deaths
    'speaking': 30,           # Each player speaks (per player)
    'voting': 30,             # All players vote
}

DEFAULT_TIMEOUT = 60
ZOMBIE_THRESHOLD = 2
ABORT_ZOMBIE_THRESHOLD = 0.5


# ============================================================================
# GAME PHASE STATE MACHINE
# ============================================================================

class WerewolfPhase(Enum):
    """
    Complete Werewolf game phases as a state machine.
    
    Game flow:
    WAITING → NIGHT_WOLF_DISCUSSION → NIGHT_WOLF_VOTING → NIGHT_SEER 
    → NIGHT_WITCH → [NIGHT_HUNTER] → DAY_ANNOUNCEMENT → DAY_SPEAKING 
    → DAY_VOTING → [DAY_HUNTER] → (repeat from NIGHT_WOLF_DISCUSSION)
    → FINISHED / ABORTED
    """
    # Pre-game
    WAITING = "waiting"
    
    # Night phases (sequential)
    NIGHT_WOLF_DISCUSSION = "night_wolf_discussion"  # Wolves private chat
    NIGHT_WOLF_VOTING = "night_wolf_voting"          # Wolves vote target
    NIGHT_SEER = "night_seer"                        # Seer checks player
    NIGHT_WITCH = "night_witch"                      # Witch save/poison
    NIGHT_HUNTER = "night_hunter"                    # Hunter shoots (if killed at night)
    
    # Day phases (sequential)
    DAY_ANNOUNCEMENT = "day_announcement"            # Announce deaths
    DAY_SPEAKING = "day_speaking"                    # Ordered speaking
    DAY_VOTING = "day_voting"                        # Public vote
    DAY_HUNTER = "day_hunter"                        # Hunter shoots (if voted out)
    
    # End states
    FINISHED = "finished"
    ABORTED = "aborted"


# Phase transition map
PHASE_TRANSITIONS = {
    WerewolfPhase.WAITING: WerewolfPhase.NIGHT_WOLF_DISCUSSION,
    WerewolfPhase.NIGHT_WOLF_DISCUSSION: WerewolfPhase.NIGHT_WOLF_VOTING,
    WerewolfPhase.NIGHT_WOLF_VOTING: WerewolfPhase.NIGHT_SEER,
    WerewolfPhase.NIGHT_SEER: WerewolfPhase.NIGHT_WITCH,
    WerewolfPhase.NIGHT_WITCH: WerewolfPhase.DAY_ANNOUNCEMENT,  # or NIGHT_HUNTER
    WerewolfPhase.NIGHT_HUNTER: WerewolfPhase.DAY_ANNOUNCEMENT,
    WerewolfPhase.DAY_ANNOUNCEMENT: WerewolfPhase.DAY_SPEAKING,
    WerewolfPhase.DAY_SPEAKING: WerewolfPhase.DAY_VOTING,
    WerewolfPhase.DAY_VOTING: WerewolfPhase.NIGHT_WOLF_DISCUSSION,  # or DAY_HUNTER
    WerewolfPhase.DAY_HUNTER: WerewolfPhase.NIGHT_WOLF_DISCUSSION,
}


# ============================================================================
# DATA CLASSES
# ============================================================================

@dataclass
class ChatMessage:
    """Represents a chat message in the game."""
    sid: str
    nickname: str
    message: str
    timestamp: datetime
    phase: str
    is_wolf_chat: bool = False  # True if this is wolf-only private chat
    
    def to_dict(self) -> Dict:
        return {
            'sid': self.sid,
            'nickname': self.nickname,
            'message': self.message,
            'timestamp': self.timestamp.isoformat(),
            'phase': self.phase,
            'is_wolf_chat': self.is_wolf_chat
        }


@dataclass  
class DeathEvent:
    """Represents a player death event."""
    sid: str
    nickname: str
    cause: str  # 'wolf_kill', 'poison', 'vote', 'hunter_shot'
    role_revealed: Optional[str] = None  # Role revealed on death (for vote deaths)
    
    def to_dict(self) -> Dict:
        return {
            'sid': self.sid,
            'nickname': self.nickname,
            'cause': self.cause,
            'role_revealed': self.role_revealed
        }


# ============================================================================
# WEREWOLF GAME CLASS
# ============================================================================

class WerewolfGame(BaseGame):
    """
    Complete Werewolf game implementation with state machine.
    
    Features:
    - Multi-phase night cycle (wolves discuss, then vote, then special roles act)
    - Wolf private chat channel
    - Ordered speaking during day
    - Proper witch mechanics (knows who died, can't use both potions same night)
    - Hunter death trigger
    - Abstain/skip vote support
    - Zombie handling for inactive players
    """
    
    MIN_PLAYERS = 6
    MAX_PLAYERS = 9
    
    def __init__(
        self,
        game_id: str,
        on_phase_change: Optional[Callable[..., Awaitable[None]]] = None,
        on_game_end: Optional[Callable[..., Awaitable[None]]] = None,
        on_timeout: Optional[Callable[..., Awaitable[None]]] = None
    ):
        """Initialize a Werewolf game."""
        super().__init__(game_id, game_type="werewolf", timeout_seconds=DEFAULT_TIMEOUT)
        
        # Game state
        self.phase = WerewolfPhase.WAITING
        self.players: List[Dict] = []
        self.day_count = 0
        
        # Night action tracking
        self.wolf_vote: Dict[str, str] = {}           # wolf_sid -> target_sid
        self.pending_wolf_kill: Optional[str] = None  # Target chosen by wolves
        self.seer_check: Optional[str] = None         # Seer's check target
        self.seer_result: Optional[Dict] = None       # Seer's check result
        self.witch_action: Dict[str, Any] = {}        # {save: bool, poison: Optional[str]}
        self.hunter_shot: Optional[str] = None        # Hunter's shot target
        
        # Day tracking
        self.votes: Dict[str, Optional[str]] = {}     # voter_sid -> target_sid (None = abstain)
        self.current_speaker_index: int = 0           # Index in speaking order
        self.speaking_order: List[str] = []           # List of sids in speaking order
        self.speakers_done: Set[str] = set()          # Players who have spoken
        
        # Pending deaths (resolved at phase transitions)
        self.pending_deaths: List[DeathEvent] = []
        self.last_night_deaths: List[DeathEvent] = []  # For announcement
        
        # Chat history (public and wolf-private)
        self.public_chat: List[ChatMessage] = []
        self.wolf_chat: List[ChatMessage] = []
        
        # Role tracking
        self.initial_role_counts: Dict[RoleType, int] = {}
        
        # Phase management
        self._phase_start_time: Optional[datetime] = None
        self._pending_actions: Dict[str, bool] = {}
        self._hunter_death_pending: bool = False  # Hunter needs to shoot
        
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
        
        if self.phase != WerewolfPhase.WAITING:
            return False
        
        if any(p['sid'] == sid for p in self.players):
            return False
        
        nickname = kwargs.get('nickname', f'Player{len(self.players) + 1}')
        
        player = {
            'sid': sid,
            'wallet_address': wallet_address,
            'nickname': nickname,
            'role': None,
            'is_alive': True,
            'status': 'alive',  # 'alive', 'zombie', 'dead'
            'consecutive_timeouts': 0,
        }
        
        self.players.append(player)
        self.channel.add_participant(
            player_id=sid,
            wallet_address=wallet_address,
            nickname=nickname
        )
        
        return True
    
    def remove_player(self, sid: str) -> bool:
        """Remove a player from the game (only in waiting phase)."""
        if self.phase != WerewolfPhase.WAITING:
            return False
        self.players = [p for p in self.players if p['sid'] != sid]
        return True
    
    def _get_player_by_sid(self, sid: str) -> Optional[Dict]:
        """Get player by socket ID."""
        for player in self.players:
            if player['sid'] == sid:
                return player
        return None
    
    def _get_alive_players(self) -> List[Dict]:
        """Get all alive players."""
        return [p for p in self.players if p['is_alive']]
    
    def _get_alive_wolves(self) -> List[Dict]:
        """Get all alive wolves."""
        return [p for p in self.players if p['is_alive'] and isinstance(p.get('role'), Wolf)]
    
    def _get_player_with_role(self, role_class) -> Optional[Dict]:
        """Get the player with a specific role class."""
        for p in self.players:
            if p['is_alive'] and isinstance(p.get('role'), role_class):
                return p
        return None
    
    def _has_role(self, role_type: RoleType) -> bool:
        """Check if a specific role exists and is alive."""
        return any(
            p['is_alive'] and p.get('role') and p['role'].role_type == role_type
            for p in self.players
        )
    
    # ========================================================================
    # GAME LIFECYCLE
    # ========================================================================
    
    def can_start(self) -> bool:
        """Check if game can start."""
        return len(self.players) >= self.MIN_PLAYERS
    
    def start_game(self) -> bool:
        """Start the game by assigning roles and moving to first night."""
        if not self.can_start():
            return False
        
        if self.phase != WerewolfPhase.WAITING:
            return False
        
        # Assign roles
        self._assign_roles()
        
        # Initialize game state
        self.started_at = datetime.utcnow()
        self.day_count = 1
        
        # Move to first night phase
        self._transition_to_phase(WerewolfPhase.NIGHT_WOLF_DISCUSSION)
        
        return True
    
    def _assign_roles(self):
        """Assign roles to players."""
        num_players = len(self.players)
        roles = get_setup(num_players)
        
        self.initial_role_counts.clear()
        for role_type in roles:
            self.initial_role_counts[role_type] = self.initial_role_counts.get(role_type, 0) + 1
        
        for player, role_type in zip(self.players, roles):
            player['role'] = create_role(role_type)
    
    # ========================================================================
    # PHASE MANAGEMENT (STATE MACHINE)
    # ========================================================================
    
    def _transition_to_phase(self, new_phase: WerewolfPhase):
        """Transition to a new game phase."""
        old_phase = self.phase
        self.phase = new_phase
        self._phase_start_time = datetime.utcnow()
        self._pending_actions.clear()
        
        # Phase-specific initialization
        if new_phase == WerewolfPhase.NIGHT_WOLF_DISCUSSION:
            self._init_wolf_discussion()
        elif new_phase == WerewolfPhase.NIGHT_WOLF_VOTING:
            self._init_wolf_voting()
        elif new_phase == WerewolfPhase.NIGHT_SEER:
            self._init_seer_phase()
        elif new_phase == WerewolfPhase.NIGHT_WITCH:
            self._init_witch_phase()
        elif new_phase == WerewolfPhase.NIGHT_HUNTER:
            self._init_hunter_phase()
        elif new_phase == WerewolfPhase.DAY_ANNOUNCEMENT:
            self._init_day_announcement()
        elif new_phase == WerewolfPhase.DAY_SPEAKING:
            self._init_day_speaking()
        elif new_phase == WerewolfPhase.DAY_VOTING:
            self._init_day_voting()
        elif new_phase == WerewolfPhase.DAY_HUNTER:
            self._init_hunter_phase()
    
    def _init_wolf_discussion(self):
        """Initialize wolf discussion phase."""
        self.wolf_vote.clear()
        self.pending_wolf_kill = None
        self.witch_action.clear()
        self.seer_check = None
        self.seer_result = None
        
        # Wolves need to participate in discussion
        for wolf in self._get_alive_wolves():
            if wolf.get('status') != 'zombie':
                self._pending_actions[wolf['sid']] = False
    
    def _init_wolf_voting(self):
        """Initialize wolf voting phase."""
        self.wolf_vote.clear()
        for wolf in self._get_alive_wolves():
            if wolf.get('status') != 'zombie':
                self._pending_actions[wolf['sid']] = False
    
    def _init_seer_phase(self):
        """Initialize seer action phase."""
        seer = self._get_player_with_role(Seer)
        if seer and seer.get('status') != 'zombie':
            self._pending_actions[seer['sid']] = False
    
    def _init_witch_phase(self):
        """Initialize witch action phase."""
        witch = self._get_player_with_role(Witch)
        if witch and witch.get('status') != 'zombie':
            self._pending_actions[witch['sid']] = False
    
    def _init_hunter_phase(self):
        """Initialize hunter action phase (triggered on death)."""
        # Find the hunter who needs to shoot
        for death in self.pending_deaths:
            player = self._get_player_by_sid(death.sid)
            if player and isinstance(player.get('role'), Hunter):
                if player['role'].can_shoot():
                    self._pending_actions[player['sid']] = False
                    self._hunter_death_pending = True
                    break
    
    def _init_day_announcement(self):
        """Initialize death announcement phase."""
        self.last_night_deaths = self.pending_deaths.copy()
        # Apply deaths immediately when entering announcement so alive/dead state
        # is already correct during speaking/voting setup.
        self._apply_deaths(self.last_night_deaths)
        self.pending_deaths.clear()
        # No actions needed - just display deaths
    
    def _init_day_speaking(self):
        """Initialize ordered speaking phase."""
        alive_players = self._get_alive_players()
        
        # Determine speaking order: start from first alive player after last victim
        if self.last_night_deaths:
            # Find index of first death
            first_death_sid = self.last_night_deaths[0].sid
            # Find the next alive player
            start_idx = 0
            for i, p in enumerate(self.players):
                if p['sid'] == first_death_sid:
                    # Start from next player
                    for j in range(i + 1, len(self.players) + i + 1):
                        candidate = self.players[j % len(self.players)]
                        if candidate['is_alive']:
                            start_idx = alive_players.index(candidate)
                            break
                    break
        else:
            start_idx = 0
        
        # Create speaking order
        self.speaking_order = []
        for i in range(len(alive_players)):
            idx = (start_idx + i) % len(alive_players)
            self.speaking_order.append(alive_players[idx]['sid'])
        
        self.current_speaker_index = 0
        self.speakers_done.clear()

        # Prepare first actionable speaker (skip zombie/dead placeholders).
        self._advance_speaking_turn()

    def _advance_speaking_turn(self) -> bool:
        """Advance to the next non-zombie alive speaker and set pending action."""
        self._pending_actions.clear()

        while self.current_speaker_index < len(self.speaking_order):
            speaker_sid = self.speaking_order[self.current_speaker_index]
            player = self._get_player_by_sid(speaker_sid)

            if player and player['is_alive'] and player.get('status') != 'zombie':
                self._pending_actions[speaker_sid] = False
                return True

            # Auto-skip speakers who can no longer speak (dead/zombie/disconnected).
            self.speakers_done.add(speaker_sid)
            self.current_speaker_index += 1

        return False
    
    def _init_day_voting(self):
        """Initialize voting phase."""
        self.votes.clear()
        for player in self._get_alive_players():
            if player.get('status') != 'zombie':
                self._pending_actions[player['sid']] = False
    
    def get_current_timeout(self) -> int:
        """Get timeout for current phase."""
        timeout_map = {
            WerewolfPhase.NIGHT_WOLF_DISCUSSION: 'wolf_discussion',
            WerewolfPhase.NIGHT_WOLF_VOTING: 'wolf_voting',
            WerewolfPhase.NIGHT_SEER: 'seer_action',
            WerewolfPhase.NIGHT_WITCH: 'witch_action',
            WerewolfPhase.NIGHT_HUNTER: 'hunter_action',
            WerewolfPhase.DAY_ANNOUNCEMENT: 'death_announcement',
            WerewolfPhase.DAY_SPEAKING: 'speaking',
            WerewolfPhase.DAY_VOTING: 'voting',
            WerewolfPhase.DAY_HUNTER: 'hunter_action',
        }
        phase_key = timeout_map.get(self.phase)
        return PHASE_TIMEOUTS.get(phase_key, DEFAULT_TIMEOUT)
    
    def get_time_remaining(self) -> float:
        """Get time remaining in current phase."""
        if not self._phase_start_time:
            return float(self.get_current_timeout())
        
        elapsed = (datetime.utcnow() - self._phase_start_time).total_seconds()
        remaining = self.get_current_timeout() - elapsed
        return max(0, remaining)
    
    def advance_phase(self) -> Dict:
        """
        Advance to the next game phase.
        
        Returns:
            Dict with phase change details
        """
        result = {'success': True, 'old_phase': self.phase.value}
        
        # Resolve current phase
        if self.phase == WerewolfPhase.NIGHT_WOLF_DISCUSSION:
            # Just move to voting, discussion doesn't resolve anything
            pass
        elif self.phase == WerewolfPhase.NIGHT_WOLF_VOTING:
            self._resolve_wolf_vote()
        elif self.phase == WerewolfPhase.NIGHT_SEER:
            # Seer already got result, nothing to resolve
            pass
        elif self.phase == WerewolfPhase.NIGHT_WITCH:
            self._resolve_witch_action()
        elif self.phase == WerewolfPhase.NIGHT_HUNTER:
            self._resolve_hunter_shot()
            self._hunter_death_pending = False
        elif self.phase == WerewolfPhase.DAY_ANNOUNCEMENT:
            # Deaths are already applied on entering announcement
            pass
        elif self.phase == WerewolfPhase.DAY_SPEAKING:
            # Speaking done, nothing to resolve
            pass
        elif self.phase == WerewolfPhase.DAY_VOTING:
            self._resolve_voting()
        elif self.phase == WerewolfPhase.DAY_HUNTER:
            self._resolve_hunter_shot()
            self._hunter_death_pending = False
        
        # Check win conditions
        if self._check_game_over():
            self.phase = WerewolfPhase.FINISHED
            self.finished_at = datetime.utcnow()
            result['game_over'] = True
            result['winners'] = self.get_winners()
            result['new_phase'] = self.phase.value
            return result
        
        # Determine next phase
        next_phase = self._get_next_phase()
        self._transition_to_phase(next_phase)
        
        result['new_phase'] = self.phase.value
        result['day_count'] = self.day_count
        result['deaths'] = [d.to_dict() for d in self.last_night_deaths] if self.phase == WerewolfPhase.DAY_ANNOUNCEMENT else []
        
        return result
    
    def _get_next_phase(self) -> WerewolfPhase:
        """Determine the next phase based on game state."""
        current = self.phase
        
        # Special case: Hunter death trigger
        if self._hunter_death_pending:
            if current in [WerewolfPhase.NIGHT_WITCH, WerewolfPhase.NIGHT_SEER]:
                return WerewolfPhase.NIGHT_HUNTER
            elif current == WerewolfPhase.DAY_VOTING:
                return WerewolfPhase.DAY_HUNTER
        
        # Skip seer phase if no alive seer
        if current == WerewolfPhase.NIGHT_WOLF_VOTING:
            if not self._has_role(RoleType.SEER):
                if not self._has_role(RoleType.WITCH):
                    return WerewolfPhase.DAY_ANNOUNCEMENT
                return WerewolfPhase.NIGHT_WITCH
        
        # Skip witch phase if no alive witch
        if current == WerewolfPhase.NIGHT_SEER:
            if not self._has_role(RoleType.WITCH):
                return WerewolfPhase.DAY_ANNOUNCEMENT
        
        # After day voting, check if new night or game over
        if current == WerewolfPhase.DAY_VOTING or current == WerewolfPhase.DAY_HUNTER:
            self.day_count += 1
            return WerewolfPhase.NIGHT_WOLF_DISCUSSION
        
        # Default transition
        return PHASE_TRANSITIONS.get(current, WerewolfPhase.FINISHED)
    
    # ========================================================================
    # ACTION PROCESSING
    # ========================================================================
    
    def process_action(self, sid: str, action: str, **kwargs) -> Dict:
        """
        Process a player action.
        
        Actions:
        - wolf_chat: Wolf sends private message (night discussion)
        - night_kill: Wolf votes to kill (night voting)
        - seer_check: Seer checks a player
        - witch_save: Witch uses antidote
        - witch_poison: Witch uses poison
        - witch_skip: Witch skips action
        - hunter_shoot: Hunter shoots someone
        - speak: Player speaks during day (with message)
        - vote: Vote to eliminate (target_sid or None to abstain)
        - chat: Public chat message
        """
        player = self._get_player_by_sid(sid)
        
        # Chat actions are phase-restricted (see _handle_public_chat)
        if action == 'chat':
            return self._handle_public_chat(sid, kwargs.get('message', ''))
        
        if action == 'wolf_chat':
            return self._handle_wolf_chat(sid, kwargs.get('message', ''))
        
        # Other actions require being alive
        if not player or not player['is_alive']:
            return {'success': False, 'error': 'Player not found or dead'}
        
        # Zombie recovery on valid action
        if player.get('status') == 'zombie':
            player['status'] = 'alive'
            player['consecutive_timeouts'] = 0
        
        # Reset timeout counter
        player['consecutive_timeouts'] = 0
        self.update_player_action_time(sid)
        
        # Route to handler
        handlers = {
            'night_kill': self._handle_wolf_kill,
            'seer_check': self._handle_seer_check,
            'witch_save': self._handle_witch_save,
            'witch_poison': self._handle_witch_poison,
            'witch_skip': self._handle_witch_skip,
            'hunter_shoot': self._handle_hunter_shoot,
            'speak': self._handle_speak,
            'vote': self._handle_vote,
        }
        
        handler = handlers.get(action)
        if not handler:
            return {'success': False, 'error': f'Unknown action: {action}'}
        
        result = handler(sid, **kwargs)
        
        # Mark action complete if successful
        if result.get('success') and sid in self._pending_actions:
            self._pending_actions[sid] = True
            
            # Check if all actions complete
            if self._all_actions_complete():
                result['all_actions_complete'] = True
        
        return result
    
    def _all_actions_complete(self) -> bool:
        """Check if all pending actions are complete."""
        if not self._pending_actions:
            return True
        return all(self._pending_actions.values())
    
    # ========================================================================
    # CHAT HANDLERS
    # ========================================================================
    
    # Phases where public chat is freely allowed (pre-game lobby and post-game discussion)
    CHAT_ALLOWED_PHASES = {WerewolfPhase.WAITING, WerewolfPhase.FINISHED}

    def _check_public_chat_allowed(self, sid: str) -> Optional[Dict]:
        """
        Check if this player can send public chat right now.
        
        Returns None if allowed, or a CHAT_PHASE_RESTRICTED error dict if blocked.
        
        Rules (matching real werewolf):
        - WAITING / FINISHED: free chat
        - DAY_SPEAKING: only current speaker
        - Everything else (night, announcement, voting): blocked
        """
        # DAY_SPEAKING: only the current speaker
        if self.phase == WerewolfPhase.DAY_SPEAKING:
            if self.speaking_order and self.current_speaker_index < len(self.speaking_order):
                if sid == self.speaking_order[self.current_speaker_index]:
                    return None  # Current speaker is allowed
            return chat_restricted_error(self.phase.value, 'Only the current speaker can chat during speaking phase')
        
        # All other phases: use the shared check
        return check_chat_phase(self.phase, self.CHAT_ALLOWED_PHASES)

    def _handle_public_chat(self, sid: str, message: str) -> Dict:
        """Handle public chat message with phase-based restrictions."""
        player = self._get_player_by_sid(sid)
        if not player:
            return {'success': False, 'error': 'Player not found'}
        
        if not message:
            return {'success': False, 'error': 'Message required'}
        
        # Phase-based chat gate
        gate = self._check_public_chat_allowed(sid)
        if gate:
            return gate
        
        chat_msg = ChatMessage(
            sid=sid,
            nickname=player['nickname'],
            message=message,
            timestamp=datetime.utcnow(),
            phase=self.phase.value,
            is_wolf_chat=False
        )
        self.public_chat.append(chat_msg)
        
        return {'success': True, 'chat': chat_msg.to_dict()}
    
    def _handle_wolf_chat(self, sid: str, message: str) -> Dict:
        """Handle wolf private chat (only during wolf discussion)."""
        player = self._get_player_by_sid(sid)
        if not player:
            return {'success': False, 'error': 'Player not found'}

        if not player['is_alive']:
            return {'success': False, 'error': 'Dead players cannot chat'}
        
        if not isinstance(player.get('role'), Wolf):
            return {'success': False, 'error': 'Only wolves can use wolf chat'}
        
        if self.phase not in [WerewolfPhase.NIGHT_WOLF_DISCUSSION, WerewolfPhase.NIGHT_WOLF_VOTING]:
            return {'success': False, 'error': 'Wolf chat only available during night wolf phases'}
        
        if not message:
            return {'success': False, 'error': 'Message required'}
        
        chat_msg = ChatMessage(
            sid=sid,
            nickname=player['nickname'],
            message=message,
            timestamp=datetime.utcnow(),
            phase=self.phase.value,
            is_wolf_chat=True
        )
        self.wolf_chat.append(chat_msg)
        
        # Mark discussion participation
        if sid in self._pending_actions:
            self._pending_actions[sid] = True
        
        return {'success': True, 'chat': chat_msg.to_dict(), 'wolf_only': True}
    
    # ========================================================================
    # NIGHT ACTION HANDLERS
    # ========================================================================
    
    def _handle_wolf_kill(self, sid: str, **kwargs) -> Dict:
        """Handle wolf kill vote."""
        if self.phase != WerewolfPhase.NIGHT_WOLF_VOTING:
            return {'success': False, 'error': 'Not wolf voting phase'}
        
        player = self._get_player_by_sid(sid)
        if not isinstance(player.get('role'), Wolf):
            return {'success': False, 'error': 'Not a wolf'}
        
        target_sid = kwargs.get('target_sid')
        if not target_sid:
            return {'success': False, 'error': 'Target required'}
        
        target = self._get_player_by_sid(target_sid)
        if not target or not target['is_alive']:
            return {'success': False, 'error': 'Invalid target'}
        
        # Wolves can't kill other wolves
        if isinstance(target.get('role'), Wolf):
            return {'success': False, 'error': 'Cannot kill fellow wolves'}
        
        self.wolf_vote[sid] = target_sid
        return {'success': True, 'action': 'night_kill', 'target': target['nickname']}
    
    def _handle_seer_check(self, sid: str, **kwargs) -> Dict:
        """Handle seer check."""
        if self.phase != WerewolfPhase.NIGHT_SEER:
            return {'success': False, 'error': 'Not seer phase'}
        
        player = self._get_player_by_sid(sid)
        if not isinstance(player.get('role'), Seer):
            return {'success': False, 'error': 'Not a seer'}
        
        target_sid = kwargs.get('target_sid')
        if not target_sid:
            return {'success': False, 'error': 'Target required'}
        
        target = self._get_player_by_sid(target_sid)
        if not target or not target['is_alive']:
            return {'success': False, 'error': 'Invalid target'}
        
        # Perform check
        result = player['role'].check_player(target_sid, target['role'].team)
        self.seer_check = target_sid
        self.seer_result = {
            'target_sid': target_sid,
            'target_nickname': target['nickname'],
            'team': result['team']
        }
        
        return {
            'success': True,
            'action': 'seer_check',
            'result': self.seer_result
        }
    
    def _handle_witch_save(self, sid: str, **kwargs) -> Dict:
        """Handle witch save action."""
        if self.phase != WerewolfPhase.NIGHT_WITCH:
            return {'success': False, 'error': 'Not witch phase'}
        
        player = self._get_player_by_sid(sid)
        if not isinstance(player.get('role'), Witch):
            return {'success': False, 'error': 'Not a witch'}
        
        # Can't use both potions same night
        if self.witch_action.get('poison'):
            return {'success': False, 'error': 'Cannot use both potions same night'}
        
        # Must have antidote
        if not player['role'].has_antidote:
            return {'success': False, 'error': 'Antidote already used'}
        
        # Must have someone to save
        if not self.pending_wolf_kill:
            return {'success': False, 'error': 'No one to save'}
        
        # Use antidote
        if not player['role'].use_antidote():
            return {'success': False, 'error': 'Failed to use antidote'}
        
        self.witch_action['save'] = True
        return {'success': True, 'action': 'witch_save'}
    
    def _handle_witch_poison(self, sid: str, **kwargs) -> Dict:
        """Handle witch poison action."""
        if self.phase != WerewolfPhase.NIGHT_WITCH:
            return {'success': False, 'error': 'Not witch phase'}
        
        player = self._get_player_by_sid(sid)
        if not isinstance(player.get('role'), Witch):
            return {'success': False, 'error': 'Not a witch'}
        
        # Can't use both potions same night
        if self.witch_action.get('save'):
            return {'success': False, 'error': 'Cannot use both potions same night'}
        
        target_sid = kwargs.get('target_sid')
        if not target_sid:
            return {'success': False, 'error': 'Target required'}
        
        target = self._get_player_by_sid(target_sid)
        if not target or not target['is_alive']:
            return {'success': False, 'error': 'Invalid target'}
        
        # Must have poison
        if not player['role'].has_poison:
            return {'success': False, 'error': 'Poison already used'}
        
        # Use poison
        if not player['role'].use_poison():
            return {'success': False, 'error': 'Failed to use poison'}
        
        self.witch_action['poison'] = target_sid
        return {'success': True, 'action': 'witch_poison', 'target': target['nickname']}
    
    def _handle_witch_skip(self, sid: str, **kwargs) -> Dict:
        """Handle witch skipping action."""
        if self.phase != WerewolfPhase.NIGHT_WITCH:
            return {'success': False, 'error': 'Not witch phase'}
        
        player = self._get_player_by_sid(sid)
        if not isinstance(player.get('role'), Witch):
            return {'success': False, 'error': 'Not a witch'}
        
        self.witch_action['skip'] = True
        return {'success': True, 'action': 'witch_skip'}
    
    def _handle_hunter_shoot(self, sid: str, **kwargs) -> Dict:
        """Handle hunter's dying shot."""
        if self.phase not in [WerewolfPhase.NIGHT_HUNTER, WerewolfPhase.DAY_HUNTER]:
            return {'success': False, 'error': 'Not hunter phase'}
        
        player = self._get_player_by_sid(sid)
        if not isinstance(player.get('role'), Hunter):
            return {'success': False, 'error': 'Not a hunter'}
        
        target_sid = kwargs.get('target_sid')
        
        # Hunter can choose not to shoot (pass None)
        if target_sid is None:
            self.hunter_shot = None
            return {'success': True, 'action': 'hunter_skip'}
        
        target = self._get_player_by_sid(target_sid)
        if not target or not target['is_alive']:
            return {'success': False, 'error': 'Invalid target'}
        
        # Shoot
        result = player['role'].shoot(target_sid)
        if result['success']:
            self.hunter_shot = target_sid
            return {'success': True, 'action': 'hunter_shoot', 'target': target['nickname']}
        
        return result
    
    # ========================================================================
    # DAY ACTION HANDLERS
    # ========================================================================
    
    def _handle_speak(self, sid: str, **kwargs) -> Dict:
        """Handle player speaking during day."""
        if self.phase != WerewolfPhase.DAY_SPEAKING:
            return {'success': False, 'error': 'Not speaking phase'}
        
        if not self.speaking_order:
            return {'success': False, 'error': 'No speaking order'}
        
        # Check if it's this player's turn
        current_speaker = self.speaking_order[self.current_speaker_index]
        if sid != current_speaker:
            return {'success': False, 'error': 'Not your turn to speak'}
        
        message = kwargs.get('message', '')
        if not message:
            return {'success': False, 'error': 'Speech message required'}
        
        # Record speech as public chat
        result = self._handle_public_chat(sid, message)
        if not result['success']:
            return result
        
        # Mark as spoken
        self.speakers_done.add(sid)
        
        # Move to next speaker
        self.current_speaker_index += 1

        # Prepare next actionable speaker; auto-skip zombie/dead entries.
        self._advance_speaking_turn()
        
        return {
            'success': True,
            'action': 'speak',
            'speakers_remaining': len(self.speaking_order) - self.current_speaker_index
        }
    
    def _handle_vote(self, sid: str, **kwargs) -> Dict:
        """Handle elimination vote."""
        if self.phase != WerewolfPhase.DAY_VOTING:
            return {'success': False, 'error': 'Not voting phase'}
        
        target_sid = kwargs.get('target_sid')  # None = abstain
        
        if target_sid is not None:
            target = self._get_player_by_sid(target_sid)
            if not target or not target['is_alive']:
                return {'success': False, 'error': 'Invalid target'}
            
            # Can't vote for self
            if target_sid == sid:
                return {'success': False, 'error': 'Cannot vote for yourself'}
        
        self.votes[sid] = target_sid
        
        if target_sid is None:
            return {'success': True, 'action': 'abstain'}
        else:
            target = self._get_player_by_sid(target_sid)
            return {'success': True, 'action': 'vote', 'target': target['nickname']}
    
    # ========================================================================
    # PHASE RESOLUTION
    # ========================================================================
    
    def _resolve_wolf_vote(self):
        """Resolve wolf voting to determine kill target."""
        if not self.wolf_vote:
            # No votes - random target
            non_wolves = [p for p in self._get_alive_players() if not isinstance(p.get('role'), Wolf)]
            if non_wolves:
                self.pending_wolf_kill = random.choice(non_wolves)['sid']
            return
        
        # Count votes
        vote_counts: Dict[str, int] = {}
        for target in self.wolf_vote.values():
            vote_counts[target] = vote_counts.get(target, 0) + 1
        
        # Find max votes
        max_votes = max(vote_counts.values())
        candidates = [sid for sid, count in vote_counts.items() if count == max_votes]
        
        # Random tiebreak
        self.pending_wolf_kill = random.choice(candidates)
    
    def _resolve_witch_action(self):
        """Resolve witch actions and create death events."""
        # Wolf kill (unless saved)
        if self.pending_wolf_kill and not self.witch_action.get('save'):
            target = self._get_player_by_sid(self.pending_wolf_kill)
            if target:
                death = DeathEvent(
                    sid=self.pending_wolf_kill,
                    nickname=target['nickname'],
                    cause='wolf_kill'
                )
                self.pending_deaths.append(death)
                
                # Check if hunter dies
                if isinstance(target.get('role'), Hunter):
                    if target['role'].can_shoot():
                        self._hunter_death_pending = True
        
        # Poison kill
        poison_target = self.witch_action.get('poison')
        if poison_target:
            target = self._get_player_by_sid(poison_target)
            if target:
                death = DeathEvent(
                    sid=poison_target,
                    nickname=target['nickname'],
                    cause='poison'
                )
                self.pending_deaths.append(death)
                
                # Hunter killed by poison usually can't shoot (rule variant)
                # We'll allow it for simplicity
                if isinstance(target.get('role'), Hunter):
                    if target['role'].can_shoot():
                        self._hunter_death_pending = True
    
    def _resolve_hunter_shot(self):
        """Resolve hunter's shot."""
        if self.hunter_shot:
            target = self._get_player_by_sid(self.hunter_shot)
            if target and target['is_alive']:
                death = DeathEvent(
                    sid=self.hunter_shot,
                    nickname=target['nickname'],
                    cause='hunter_shot',
                    role_revealed=target['role'].role_type.value if target.get('role') else None
                )
                self.pending_deaths.append(death)
        
        self.hunter_shot = None
    
    def _resolve_voting(self):
        """Resolve day voting."""
        if not self.votes:
            return
        
        # Count non-abstain votes
        vote_counts: Dict[str, int] = {}
        total_votes = 0
        abstentions = 0
        
        for voter_sid, target_sid in self.votes.items():
            if target_sid is None:
                abstentions += 1
            else:
                total_votes += 1
                vote_counts[target_sid] = vote_counts.get(target_sid, 0) + 1
        
        if not vote_counts:
            return  # All abstained
        
        # Find max votes
        max_votes = max(vote_counts.values())
        candidates = [sid for sid, count in vote_counts.items() if count == max_votes]
        
        # Check for tie (no elimination on tie, different rule variants exist)
        if len(candidates) > 1:
            # Tie - no elimination (or could random choose)
            return
        
        # Eliminate
        eliminated_sid = candidates[0]
        eliminated = self._get_player_by_sid(eliminated_sid)
        if eliminated:
            death = DeathEvent(
                sid=eliminated_sid,
                nickname=eliminated['nickname'],
                cause='vote',
                role_revealed=eliminated['role'].role_type.value if eliminated.get('role') else None
            )
            self.pending_deaths.append(death)
            
            # Check if hunter
            if isinstance(eliminated.get('role'), Hunter):
                if eliminated['role'].can_shoot():
                    self._hunter_death_pending = True
    
    def _apply_deaths(self, deaths: List[DeathEvent]):
        """Apply a list of death events to player states."""
        for death in deaths:
            player = self._get_player_by_sid(death.sid)
            if player:
                player['is_alive'] = False
                player['status'] = 'dead'

    def _apply_pending_deaths(self):
        """Apply all pending deaths to players."""
        self._apply_deaths(self.pending_deaths)
    
    # ========================================================================
    # WIN CONDITIONS
    # ========================================================================
    
    def _check_game_over(self) -> bool:
        """Check if game is over."""
        alive_players = self._get_alive_players()
        
        if not alive_players:
            return True
        
        wolves_alive = sum(1 for p in alive_players if isinstance(p.get('role'), Wolf))
        villagers_alive = len(alive_players) - wolves_alive
        
        # Wolves win if they equal or outnumber villagers
        if wolves_alive >= villagers_alive:
            return True
        
        # Villagers win if no wolves left
        if wolves_alive == 0:
            return True
        
        return False
    
    def is_game_over(self) -> bool:
        """Public method to check if game is over."""
        return self._check_game_over()
    
    def get_winners(self) -> List[str]:
        """Get winning wallet addresses."""
        if not self._check_game_over():
            return []
        
        alive_players = self._get_alive_players()
        if not alive_players:
            return []  # Draw
        
        wolves_alive = sum(1 for p in alive_players if isinstance(p.get('role'), Wolf))
        
        # Determine winning team
        winning_team = Team.WOLF if wolves_alive > 0 else Team.VILLAGER
        
        # Return all players on winning team
        return [
            p['wallet_address']
            for p in self.players
            if p.get('role') and p['role'].team == winning_team
        ]
    
    # ========================================================================
    # TIMEOUT HANDLING
    # ========================================================================
    
    async def handle_phase_timeout(self) -> Dict:
        """Handle phase timeout - execute default actions and advance."""
        timed_out_players = []
        
        for sid, has_acted in self._pending_actions.items():
            if not has_acted:
                player = self._get_player_by_sid(sid)
                if player and player['is_alive']:
                    player.setdefault('consecutive_timeouts', 0)
                    player['consecutive_timeouts'] += 1
                    timed_out_players.append(player)
                    
                    # Mark as zombie after threshold
                    if player['consecutive_timeouts'] >= ZOMBIE_THRESHOLD:
                        player['status'] = 'zombie'
                    
                    # Execute default action
                    await self._execute_default_action(player)
                    
                    if self._on_timeout:
                        await self._on_timeout(
                            self.game_id,
                            player['nickname'],
                            player['consecutive_timeouts'],
                            player.get('status') == 'zombie'
                        )
        
        # Check abort condition
        if self.get_zombie_ratio() > ABORT_ZOMBIE_THRESHOLD:
            return await self.abort_game("More than 50% of players are inactive")

        # Day speaking timeout is per speaker; continue same phase when another
        # speaker is pending rather than jumping directly to voting.
        if self.phase == WerewolfPhase.DAY_SPEAKING and self._pending_actions:
            self._phase_start_time = datetime.utcnow()
            return {
                'success': True,
                'old_phase': self.phase.value,
                'new_phase': self.phase.value,
                'day_count': self.day_count,
                'timed_out_players': [p['nickname'] for p in timed_out_players]
            }
        
        # Advance phase
        result = self.advance_phase()
        result['timed_out_players'] = [p['nickname'] for p in timed_out_players]
        
        return result
    
    async def _execute_default_action(self, player: Dict):
        """Execute default action for timed-out player."""
        sid = player['sid']
        
        if self.phase == WerewolfPhase.NIGHT_WOLF_DISCUSSION:
            # Just mark as participated
            pass
        
        elif self.phase == WerewolfPhase.NIGHT_WOLF_VOTING:
            if isinstance(player.get('role'), Wolf):
                # Random kill
                non_wolves = [p for p in self._get_alive_players() if not isinstance(p.get('role'), Wolf)]
                if non_wolves:
                    target = random.choice(non_wolves)
                    self.wolf_vote[sid] = target['sid']
        
        elif self.phase == WerewolfPhase.NIGHT_SEER:
            if isinstance(player.get('role'), Seer):
                # Random check
                others = [p for p in self._get_alive_players() if p['sid'] != sid]
                if others:
                    target = random.choice(others)
                    self.seer_check = target['sid']
        
        elif self.phase == WerewolfPhase.NIGHT_WITCH:
            # Witch skips by default
            self.witch_action['skip'] = True
        
        elif self.phase in [WerewolfPhase.NIGHT_HUNTER, WerewolfPhase.DAY_HUNTER]:
            # Hunter doesn't shoot by default on timeout
            self.hunter_shot = None
        
        elif self.phase == WerewolfPhase.DAY_SPEAKING:
            # Skip speech, move to next
            self.speakers_done.add(sid)
            self.current_speaker_index += 1
            self._advance_speaking_turn()
        
        elif self.phase == WerewolfPhase.DAY_VOTING:
            # Random vote
            others = [p for p in self._get_alive_players() if p['sid'] != sid]
            if others:
                target = random.choice(others)
                self.votes[sid] = target['sid']
    
    async def abort_game(self, reason: str = "Game aborted") -> Dict:
        """Abort the game."""
        self.phase = WerewolfPhase.ABORTED
        self.finished_at = datetime.utcnow()
        
        result = {
            'success': True,
            'aborted': True,
            'reason': reason,
            'refund_players': [p['wallet_address'] for p in self.players]
        }
        
        if self._on_game_end:
            await self._on_game_end(
                self.game_id,
                is_aborted=True,
                reason=reason,
                refunds=result['refund_players']
            )
        
        return result
    
    def get_zombie_count(self) -> int:
        """Get count of zombie players."""
        return sum(1 for p in self.players if p.get('status') == 'zombie' and p['is_alive'])
    
    def get_zombie_ratio(self) -> float:
        """Get ratio of zombies among alive players."""
        alive = self._get_alive_players()
        if not alive:
            return 0.0
        return self.get_zombie_count() / len(alive)
    
    async def execute_default_action(self, sid: str) -> Dict:
        """Execute default action (interface requirement)."""
        player = self._get_player_by_sid(sid)
        if player:
            await self._execute_default_action(player)
        return {'success': True, 'action': 'default'}
    
    # ========================================================================
    # STATE SERIALIZATION
    # ========================================================================
    
    def get_game_state(self, sid: Optional[str] = None, reveal_all: bool = False) -> Dict:
        """
        Get game state with appropriate masking.
        
        Players see:
        - Their own role
        - Other wolves (if they're a wolf)
        - Wolf chat (if they're a wolf)
        - Public information only otherwise
        """
        requesting_player = self._get_player_by_sid(sid) if sid else None
        is_wolf = requesting_player and isinstance(requesting_player.get('role'), Wolf)
        is_spectator = sid is None
        allow_full_reveal = reveal_all and is_spectator
        
        state = {
            'game_id': self.game_id,
            'phase': self.phase.value,
            'day_count': self.day_count,
            'time_remaining': self.get_time_remaining(),
            'players': [],
            'chat_messages': [c.to_dict() for c in self.public_chat[-50:]],
        }
        
        # Add wolf chat for wolves
        if is_wolf or is_spectator:
            state['wolf_chat'] = [c.to_dict() for c in self.wolf_chat[-50:]]
        
        # Add player info
        for player in self.players:
            player_info = {
                'sid': player['sid'],
                'nickname': player['nickname'],
                'is_alive': player['is_alive'],
                'status': player.get('status', 'alive'),
                'is_zombie': player.get('status') == 'zombie'
            }
            
            # Role visibility
            if player.get('role'):
                # Spectators in full reveal mode see all roles
                if allow_full_reveal:
                    player_info['role'] = player['role'].get_role_info()
                # Own role always visible
                elif sid and player['sid'] == sid:
                    player_info['role'] = player['role'].get_role_info()
                # Wolves see each other
                elif is_wolf and isinstance(player['role'], Wolf):
                    player_info['role'] = player['role'].get_role_info()
                # Dead players' roles revealed (optional rule)
                elif not player['is_alive']:
                    player_info['role'] = player['role'].get_role_info()
            
            state['players'].append(player_info)
        
        # Phase-specific info
        if self.phase == WerewolfPhase.NIGHT_WITCH and requesting_player:
            if isinstance(requesting_player.get('role'), Witch):
                # Witch sees who is about to die
                state['pending_death'] = None
                if self.pending_wolf_kill:
                    victim = self._get_player_by_sid(self.pending_wolf_kill)
                    if victim:
                        state['pending_death'] = {
                            'sid': self.pending_wolf_kill,
                            'nickname': victim['nickname']
                        }
                state['witch_has_antidote'] = requesting_player['role'].has_antidote
                state['witch_has_poison'] = requesting_player['role'].has_poison
        
        if self.phase == WerewolfPhase.DAY_SPEAKING:
            state['speaking_order'] = self.speaking_order
            state['current_speaker_index'] = self.current_speaker_index
            state['speakers_done'] = list(self.speakers_done)
            if self.speaking_order and self.current_speaker_index < len(self.speaking_order):
                current_speaker_sid = self.speaking_order[self.current_speaker_index]
                current_speaker = self._get_player_by_sid(current_speaker_sid)
                state['current_speaker'] = current_speaker['nickname'] if current_speaker else None
        
        if self.phase == WerewolfPhase.DAY_ANNOUNCEMENT:
            state['deaths'] = [d.to_dict() for d in self.last_night_deaths]
        
        return state
    
    def get_game_snapshot(self, player_sid: str) -> Dict:
        """Get full game snapshot for reconnection."""
        state = self.get_game_state(player_sid)
        player = self._get_player_by_sid(player_sid)
        
        snapshot = {
            'game_id': self.game_id,
            'game_type': 'werewolf',
            **state,
            'your_role': player['role'].get_role_info() if player and player.get('role') else None,
            'is_alive': player['is_alive'] if player else False,
            'timestamp': datetime.utcnow().isoformat()
        }
        
        return snapshot
    
    def to_dict(self) -> Dict:
        """Convert game to dictionary for persistence."""
        players_data = []
        for p in self.players:
            player_dict = {
                'sid': p['sid'],
                'wallet_address': p['wallet_address'],
                'nickname': p['nickname'],
                'is_alive': p['is_alive'],
                'status': p.get('status', 'alive'),
                'consecutive_timeouts': p.get('consecutive_timeouts', 0)
            }
            if p.get('role'):
                player_dict['role_type'] = p['role'].role_type.value
                player_dict['role_info'] = p['role'].get_role_info()
            players_data.append(player_dict)
        
        return {
            'game_id': self.game_id,
            'game_type': self.game_type,
            'phase': self.phase.value,
            'day_count': self.day_count,
            'players': players_data,
            'wolf_vote': self.wolf_vote,
            'pending_wolf_kill': self.pending_wolf_kill,
            'seer_check': self.seer_check,
            'witch_action': self.witch_action,
            'votes': {k: v for k, v in self.votes.items()},  # Handle None values
            'public_chat': [c.to_dict() for c in self.public_chat[-100:]],
            'wolf_chat': [c.to_dict() for c in self.wolf_chat[-100:]],
            'speaking_order': self.speaking_order,
            'current_speaker_index': self.current_speaker_index,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'started_at': self.started_at.isoformat() if self.started_at else None,
            'finished_at': self.finished_at.isoformat() if self.finished_at else None
        }
    
    def update_player_sid(self, old_sid: str, new_sid: str) -> bool:
        """Update player socket ID for reconnection."""
        player = self._get_player_by_sid(old_sid)
        if player:
            player['sid'] = new_sid
            # Update tracking dicts
            if old_sid in self._pending_actions:
                self._pending_actions[new_sid] = self._pending_actions.pop(old_sid)
            if old_sid in self.wolf_vote:
                self.wolf_vote[new_sid] = self.wolf_vote.pop(old_sid)
            if old_sid in self.votes:
                self.votes[new_sid] = self.votes.pop(old_sid)
            if old_sid in self.speaking_order:
                idx = self.speaking_order.index(old_sid)
                self.speaking_order[idx] = new_sid
            if old_sid in self.speakers_done:
                self.speakers_done.remove(old_sid)
                self.speakers_done.add(new_sid)
            return True
        return False
    
    # ========================================================================
    # STATE RESTORATION (from_dict)
    # ========================================================================
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'WerewolfGame':
        """
        Restore a WerewolfGame instance from a serialized dictionary.
        
        Used for recovering game state from Redis/MySQL after server restart.
        
        Args:
            data: Dictionary from to_dict() or similar serialization
            
        Returns:
            Restored WerewolfGame instance
        """
        game_id = data.get('game_id', 'restored_game')
        game = cls(game_id)
        
        # Restore basic state
        game.game_type = data.get('game_type', 'werewolf')
        game.day_count = data.get('day_count', 0)
        
        # Restore phase
        phase_value = data.get('phase', 'waiting')
        try:
            game.phase = WerewolfPhase(phase_value)
        except ValueError:
            game.phase = WerewolfPhase.WAITING
        
        # Restore timestamps
        if data.get('created_at'):
            try:
                game.created_at = datetime.fromisoformat(data['created_at'])
            except (ValueError, TypeError):
                game.created_at = datetime.utcnow()
        
        if data.get('started_at'):
            try:
                game.started_at = datetime.fromisoformat(data['started_at'])
            except (ValueError, TypeError):
                pass
        
        if data.get('finished_at'):
            try:
                game.finished_at = datetime.fromisoformat(data['finished_at'])
            except (ValueError, TypeError):
                pass
        
        # Restore players with roles
        game.players = []
        for p_data in data.get('players', []):
            player = {
                'sid': p_data.get('sid'),
                'wallet_address': p_data.get('wallet_address'),
                'nickname': p_data.get('nickname', 'Player'),
                'is_alive': p_data.get('is_alive', True),
                'status': p_data.get('status', 'alive'),
                'consecutive_timeouts': p_data.get('consecutive_timeouts', 0),
                'role': None
            }
            
            # Restore role
            role_type_str = p_data.get('role_type')
            if role_type_str:
                try:
                    role_type = RoleType(role_type_str)
                    player['role'] = create_role(role_type)
                    
                    # Restore role-specific state
                    role_info = p_data.get('role_info', {})
                    if isinstance(player['role'], Witch):
                        player['role'].has_antidote = role_info.get('has_antidote', True)
                        player['role'].has_poison = role_info.get('has_poison', True)
                    elif isinstance(player['role'], Hunter):
                        player['role']._can_shoot = role_info.get('can_shoot', True)
                    elif isinstance(player['role'], Seer):
                        # Restore check history if present
                        check_history = role_info.get('check_history', [])
                        for check in check_history:
                            if check.get('target') and check.get('team'):
                                player['role'].check_history.append({
                                    'target': check['target'],
                                    'team': check['team']
                                })
                except (ValueError, KeyError):
                    pass
            
            game.players.append(player)
        
        # Restore night action tracking
        game.wolf_vote = data.get('wolf_vote', {})
        game.pending_wolf_kill = data.get('pending_wolf_kill')
        game.seer_check = data.get('seer_check')
        game.witch_action = data.get('witch_action', {})
        
        # Restore day tracking
        game.votes = data.get('votes', {})
        game.speaking_order = data.get('speaking_order', [])
        game.current_speaker_index = data.get('current_speaker_index', 0)
        game.speakers_done = set(data.get('speakers_done', []))
        
        # Restore chat history
        public_chat_data = data.get('public_chat', [])
        game.public_chat = []
        for c in public_chat_data:
            try:
                msg = ChatMessage(
                    sid=c.get('sid', ''),
                    nickname=c.get('nickname', ''),
                    message=c.get('message', ''),
                    timestamp=datetime.fromisoformat(c['timestamp']) if c.get('timestamp') else datetime.utcnow(),
                    phase=c.get('phase', ''),
                    is_wolf_chat=c.get('is_wolf_chat', False)
                )
                game.public_chat.append(msg)
            except (ValueError, TypeError):
                pass
        
        wolf_chat_data = data.get('wolf_chat', [])
        game.wolf_chat = []
        for c in wolf_chat_data:
            try:
                msg = ChatMessage(
                    sid=c.get('sid', ''),
                    nickname=c.get('nickname', ''),
                    message=c.get('message', ''),
                    timestamp=datetime.fromisoformat(c['timestamp']) if c.get('timestamp') else datetime.utcnow(),
                    phase=c.get('phase', ''),
                    is_wolf_chat=c.get('is_wolf_chat', True)
                )
                game.wolf_chat.append(msg)
            except (ValueError, TypeError):
                pass
        
        # Restore initial role counts
        game.initial_role_counts = {}
        for role_type_str, count in data.get('initial_role_counts', {}).items():
            try:
                game.initial_role_counts[RoleType(role_type_str)] = count
            except ValueError:
                pass
        
        # Set phase start time to now (timeout will restart)
        game._phase_start_time = datetime.utcnow()
        
        # Re-initialize pending actions for current phase
        game._pending_actions = {}
        if game.phase not in [WerewolfPhase.WAITING, WerewolfPhase.FINISHED, WerewolfPhase.ABORTED]:
            # Determine who needs to act in current phase
            if game.phase in [WerewolfPhase.NIGHT_WOLF_DISCUSSION, WerewolfPhase.NIGHT_WOLF_VOTING]:
                for wolf in game._get_alive_wolves():
                    if wolf.get('status') != 'zombie':
                        game._pending_actions[wolf['sid']] = wolf['sid'] in game.wolf_vote
            elif game.phase == WerewolfPhase.NIGHT_SEER:
                seer = game._get_player_with_role(Seer)
                if seer and seer.get('status') != 'zombie':
                    game._pending_actions[seer['sid']] = game.seer_check is not None
            elif game.phase == WerewolfPhase.NIGHT_WITCH:
                witch = game._get_player_with_role(Witch)
                if witch and witch.get('status') != 'zombie':
                    game._pending_actions[witch['sid']] = bool(game.witch_action)
            elif game.phase == WerewolfPhase.DAY_VOTING:
                for player in game._get_alive_players():
                    if player.get('status') != 'zombie':
                        game._pending_actions[player['sid']] = player['sid'] in game.votes
            elif game.phase == WerewolfPhase.DAY_SPEAKING:
                if game.speaking_order and game.current_speaker_index < len(game.speaking_order):
                    current_speaker = game.speaking_order[game.current_speaker_index]
                    player = game._get_player_by_sid(current_speaker)
                    if player and player.get('status') != 'zombie':
                        game._pending_actions[current_speaker] = current_speaker in game.speakers_done
        
        return game
    
    def get_core_state(self) -> Dict[str, Any]:
        """
        Get core game state without chat history.
        
        Used for efficient Redis persistence (chat stored separately).
        
        Returns:
            Core state dictionary
        """
        state = self.to_dict()
        # Remove chat data (stored separately in Redis)
        state.pop('public_chat', None)
        state.pop('wolf_chat', None)
        return state


# Export for backwards compatibility
PHASE_TIMEOUT_SECONDS = DEFAULT_TIMEOUT
