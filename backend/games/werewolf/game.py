"""
Werewolf game logic implementation.

This module implements the main Werewolf game mechanics:
- Game phases (Night, Day, Vote)
- Action handling
- State masking for hidden information
- Win condition checking
"""

import random
from typing import Dict, List, Optional, Any
from enum import Enum

from backend.games.base import BaseGame, GamePhase
from backend.games.werewolf.roles import (
    Role, RoleType, Team, create_role,
    Wolf, Seer, Witch, Hunter
)


class WerewolfPhase(Enum):
    """Werewolf-specific game phases."""
    WAITING = "waiting"
    NIGHT = "night"
    DAY = "day"
    VOTING = "voting"
    FINISHED = "finished"


class WerewolfGame(BaseGame):
    """
    Werewolf game implementation.
    
    Game flow:
    1. WAITING: Players join
    2. NIGHT: Wolves choose victim, special roles act
    3. DAY: Discussion and accusation
    4. VOTING: Vote to eliminate someone
    5. Repeat NIGHT/DAY/VOTING until win condition
    6. FINISHED: Game over
    """
    
    MIN_PLAYERS = 4
    MAX_PLAYERS = 12
    
    def __init__(self, game_id: str):
        """
        Initialize a Werewolf game.
        
        Args:
            game_id: Unique identifier for this game
        """
        super().__init__(game_id)
        self.phase = WerewolfPhase.WAITING
        self.players: List[Dict] = []
        self.day_count = 0
        
        # Night action tracking
        self.wolf_vote: Dict[str, str] = {}  # wolf_sid -> target_sid
        self.seer_check: Optional[str] = None  # target_sid
        self.witch_action: Dict[str, Any] = {}  # {save: bool, poison: Optional[str]}
        self.hunter_shot: Optional[str] = None  # target_sid
        
        # Day/voting tracking
        self.votes: Dict[str, str] = {}  # voter_sid -> target_sid
        
    def add_player(self, sid: str, wallet_address: str, **kwargs) -> bool:
        """Add a player to the game."""
        if len(self.players) >= self.MAX_PLAYERS:
            return False
        
        if self.phase != WerewolfPhase.WAITING:
            return False
        
        # Check if player already in game
        if any(p['sid'] == sid for p in self.players):
            return False
        
        player = {
            'sid': sid,
            'wallet_address': wallet_address,
            'role': None,  # Assigned when game starts
            'is_alive': True,
            'nickname': kwargs.get('nickname', f'Player{len(self.players) + 1}')
        }
        
        self.players.append(player)
        return True
    
    def remove_player(self, sid: str) -> bool:
        """Remove a player from the game."""
        self.players = [p for p in self.players if p['sid'] != sid]
        return True
    
    def can_start(self) -> bool:
        """Check if game can start."""
        return len(self.players) >= self.MIN_PLAYERS
    
    def start_game(self) -> bool:
        """Start the game by assigning roles and moving to night phase."""
        if not self.can_start():
            return False
        
        if self.phase != WerewolfPhase.WAITING:
            return False
        
        # Assign roles
        self._assign_roles()
        
        # Move to first night
        self.phase = WerewolfPhase.NIGHT
        self.day_count = 1
        
        return True
    
    def _assign_roles(self):
        """Assign roles to players based on player count."""
        num_players = len(self.players)
        
        # Role distribution based on player count
        if num_players <= 5:
            num_wolves = 1
            special_roles = [RoleType.SEER]
        elif num_players <= 8:
            num_wolves = 2
            special_roles = [RoleType.SEER, RoleType.WITCH]
        else:
            num_wolves = 2
            special_roles = [RoleType.SEER, RoleType.WITCH, RoleType.HUNTER]
        
        # Create role list
        roles = [RoleType.WOLF] * num_wolves
        roles.extend(special_roles)
        
        # Fill remaining with villagers
        while len(roles) < num_players:
            roles.append(RoleType.VILLAGER)
        
        # Shuffle and assign
        random.shuffle(roles)
        for player, role_type in zip(self.players, roles):
            player['role'] = create_role(role_type)
    
    def process_action(self, sid: str, action: str, **kwargs) -> Dict:
        """
        Process a player action.
        
        Actions:
        - night_kill: Wolf votes to kill (target_sid)
        - seer_check: Seer checks a player (target_sid)
        - witch_save: Witch uses antidote
        - witch_poison: Witch uses poison (target_sid)
        - vote: Vote to eliminate someone (target_sid)
        - hunter_shoot: Hunter shoots someone when dying (target_sid)
        """
        player = self._get_player_by_sid(sid)
        if not player or not player['is_alive']:
            return {'success': False, 'error': 'Player not found or dead'}
        
        # Route to appropriate handler
        if action == 'night_kill':
            return self._handle_wolf_kill(sid, kwargs.get('target_sid'))
        elif action == 'seer_check':
            return self._handle_seer_check(sid, kwargs.get('target_sid'))
        elif action == 'witch_save':
            return self._handle_witch_save(sid)
        elif action == 'witch_poison':
            return self._handle_witch_poison(sid, kwargs.get('target_sid'))
        elif action == 'vote':
            return self._handle_vote(sid, kwargs.get('target_sid'))
        elif action == 'hunter_shoot':
            return self._handle_hunter_shoot(sid, kwargs.get('target_sid'))
        else:
            return {'success': False, 'error': 'Unknown action'}
    
    def _handle_wolf_kill(self, sid: str, target_sid: Optional[str]) -> Dict:
        """Handle wolf kill vote."""
        if self.phase != WerewolfPhase.NIGHT:
            return {'success': False, 'error': 'Not night phase'}
        
        player = self._get_player_by_sid(sid)
        if not isinstance(player['role'], Wolf):
            return {'success': False, 'error': 'Not a wolf'}
        
        if not target_sid:
            return {'success': False, 'error': 'Target required'}
        
        target = self._get_player_by_sid(target_sid)
        if not target or not target['is_alive']:
            return {'success': False, 'error': 'Invalid target'}
        
        self.wolf_vote[sid] = target_sid
        return {'success': True}
    
    def _handle_seer_check(self, sid: str, target_sid: Optional[str]) -> Dict:
        """Handle seer check."""
        if self.phase != WerewolfPhase.NIGHT:
            return {'success': False, 'error': 'Not night phase'}
        
        player = self._get_player_by_sid(sid)
        if not isinstance(player['role'], Seer):
            return {'success': False, 'error': 'Not a seer'}
        
        if not target_sid:
            return {'success': False, 'error': 'Target required'}
        
        target = self._get_player_by_sid(target_sid)
        if not target or not target['is_alive']:
            return {'success': False, 'error': 'Invalid target'}
        
        # Seer can check one player per night
        result = player['role'].check_player(target_sid, target['role'].team)
        self.seer_check = target_sid
        
        return {
            'success': True,
            'result': result
        }
    
    def _handle_witch_save(self, sid: str) -> Dict:
        """Handle witch save action."""
        if self.phase != WerewolfPhase.NIGHT:
            return {'success': False, 'error': 'Not night phase'}
        
        player = self._get_player_by_sid(sid)
        if not isinstance(player['role'], Witch):
            return {'success': False, 'error': 'Not a witch'}
        
        if not player['role'].use_antidote():
            return {'success': False, 'error': 'Antidote already used'}
        
        self.witch_action['save'] = True
        return {'success': True}
    
    def _handle_witch_poison(self, sid: str, target_sid: Optional[str]) -> Dict:
        """Handle witch poison action."""
        if self.phase != WerewolfPhase.NIGHT:
            return {'success': False, 'error': 'Not night phase'}
        
        player = self._get_player_by_sid(sid)
        if not isinstance(player['role'], Witch):
            return {'success': False, 'error': 'Not a witch'}
        
        if not target_sid:
            return {'success': False, 'error': 'Target required'}
        
        if not player['role'].use_poison():
            return {'success': False, 'error': 'Poison already used'}
        
        self.witch_action['poison'] = target_sid
        return {'success': True}
    
    def _handle_vote(self, sid: str, target_sid: Optional[str]) -> Dict:
        """Handle elimination vote."""
        if self.phase != WerewolfPhase.VOTING:
            return {'success': False, 'error': 'Not voting phase'}
        
        if not target_sid:
            return {'success': False, 'error': 'Target required'}
        
        target = self._get_player_by_sid(target_sid)
        if not target or not target['is_alive']:
            return {'success': False, 'error': 'Invalid target'}
        
        self.votes[sid] = target_sid
        return {'success': True}
    
    def _handle_hunter_shoot(self, sid: str, target_sid: Optional[str]) -> Dict:
        """Handle hunter's dying shot."""
        player = self._get_player_by_sid(sid)
        if not isinstance(player['role'], Hunter):
            return {'success': False, 'error': 'Not a hunter'}
        
        if not target_sid:
            return {'success': False, 'error': 'Target required'}
        
        result = player['role'].shoot(target_sid)
        if result['success']:
            self.hunter_shot = target_sid
            # Kill the target
            target = self._get_player_by_sid(target_sid)
            if target:
                target['is_alive'] = False
        
        return result
    
    def advance_phase(self) -> Dict:
        """
        Advance to the next game phase and resolve actions.
        
        Returns:
            Dict with phase change information and action results
        """
        if self.phase == WerewolfPhase.NIGHT:
            return self._resolve_night()
        elif self.phase == WerewolfPhase.DAY:
            return self._start_voting()
        elif self.phase == WerewolfPhase.VOTING:
            return self._resolve_voting()
        else:
            return {'success': False, 'error': 'Cannot advance from current phase'}
    
    def _resolve_night(self) -> Dict:
        """Resolve night actions."""
        results = {
            'phase': 'night_resolution',
            'deaths': [],
            'seer_result': None
        }
        
        # Determine wolf kill target (majority vote)
        if self.wolf_vote:
            target_counts = {}
            for target in self.wolf_vote.values():
                target_counts[target] = target_counts.get(target, 0) + 1
            wolf_target = max(target_counts, key=target_counts.get)
        else:
            wolf_target = None
        
        # Check if witch saves
        saved = self.witch_action.get('save', False)
        
        # Apply wolf kill (unless saved)
        if wolf_target and not saved:
            target = self._get_player_by_sid(wolf_target)
            if target:
                target['is_alive'] = False
                results['deaths'].append({
                    'sid': wolf_target,
                    'cause': 'wolf_kill'
                })
        
        # Apply witch poison
        poison_target = self.witch_action.get('poison')
        if poison_target:
            target = self._get_player_by_sid(poison_target)
            if target:
                target['is_alive'] = False
                results['deaths'].append({
                    'sid': poison_target,
                    'cause': 'poison'
                })
        
        # Clear night actions
        self.wolf_vote.clear()
        self.seer_check = None
        self.witch_action.clear()
        
        # Move to day phase
        self.phase = WerewolfPhase.DAY
        
        return results
    
    def _start_voting(self) -> Dict:
        """Start voting phase."""
        self.phase = WerewolfPhase.VOTING
        self.votes.clear()
        return {'phase': 'voting', 'success': True}
    
    def _resolve_voting(self) -> Dict:
        """Resolve voting phase."""
        results = {
            'phase': 'voting_resolution',
            'eliminated': None
        }
        
        # Count votes
        if self.votes:
            vote_counts = {}
            for target in self.votes.values():
                vote_counts[target] = vote_counts.get(target, 0) + 1
            
            # Find player with most votes
            max_votes = max(vote_counts.values())
            candidates = [sid for sid, count in vote_counts.items() if count == max_votes]
            
            # Eliminate (random if tie)
            if candidates:
                eliminated_sid = random.choice(candidates)
                eliminated = self._get_player_by_sid(eliminated_sid)
                if eliminated:
                    eliminated['is_alive'] = False
                    results['eliminated'] = {
                        'sid': eliminated_sid,
                        'votes': vote_counts[eliminated_sid]
                    }
        
        # Clear votes
        self.votes.clear()
        
        # Check win conditions
        if self.is_game_over():
            self.phase = WerewolfPhase.FINISHED
            results['game_over'] = True
            results['winners'] = self.get_winners()
        else:
            # Move to next night
            self.phase = WerewolfPhase.NIGHT
            self.day_count += 1
        
        return results
    
    def get_game_state(self, sid: Optional[str] = None) -> Dict:
        """
        Get game state with appropriate information masking.
        
        If sid is provided, returns player-specific view with:
        - Their own role
        - Other wolves (if they're a wolf)
        - Only alive/dead status of other players
        """
        # Base state visible to all
        state = {
            'game_id': self.game_id,
            'phase': self.phase.value,
            'day_count': self.day_count,
            'players': []
        }
        
        # Add player information
        requesting_player = self._get_player_by_sid(sid) if sid else None
        
        for player in self.players:
            player_info = {
                'sid': player['sid'],
                'nickname': player['nickname'],
                'is_alive': player['is_alive']
            }
            
            # Reveal role only to the player themselves
            if sid and player['sid'] == sid:
                player_info['role'] = player['role'].get_role_info()
            # Wolves can see other wolves
            elif (requesting_player and 
                  isinstance(requesting_player['role'], Wolf) and 
                  isinstance(player['role'], Wolf)):
                player_info['role'] = player['role'].get_role_info()
            
            state['players'].append(player_info)
        
        return state
    
    def is_game_over(self) -> bool:
        """Check if game is over."""
        alive_players = [p for p in self.players if p['is_alive']]
        
        if not alive_players:
            return True
        
        wolves_alive = sum(1 for p in alive_players if p['role'].team == Team.WOLF)
        villagers_alive = sum(1 for p in alive_players if p['role'].team == Team.VILLAGER)
        
        # Wolves win if they equal or outnumber villagers
        if wolves_alive >= villagers_alive:
            return True
        
        # Villagers win if no wolves left
        if wolves_alive == 0:
            return True
        
        return False
    
    def get_winners(self) -> List[str]:
        """Get list of winning wallet addresses."""
        if not self.is_game_over():
            return []
        
        alive_players = [p for p in self.players if p['is_alive']]
        
        if not alive_players:
            return []  # Draw - everyone died
        
        wolves_alive = sum(1 for p in alive_players if p['role'].team == Team.WOLF)
        
        # Determine winning team
        if wolves_alive > 0:
            # Wolves won
            winning_team = Team.WOLF
        else:
            # Villagers won
            winning_team = Team.VILLAGER
        
        # Return all players on winning team (alive or dead)
        return [
            p['wallet_address'] 
            for p in self.players 
            if p['role'].team == winning_team
        ]
    
    def _get_player_by_sid(self, sid: str) -> Optional[Dict]:
        """Get player by socket ID."""
        for player in self.players:
            if player['sid'] == sid:
                return player
        return None
