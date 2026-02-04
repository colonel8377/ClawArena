"""
Werewolf game role definitions.

This module defines all player roles in the Werewolf game:
- Villager: Basic role with no special abilities
- Wolf: Can kill one person per night
- Seer: Can check one person's identity per night
- Witch: Has a poison and an antidote (one-time use each)
- Hunter: Can shoot someone when they die
"""

from enum import Enum
from typing import Dict


class RoleType(Enum):
    """Enumeration of all possible roles in Werewolf."""
    VILLAGER = "villager"
    WOLF = "wolf"
    SEER = "seer"
    WITCH = "witch"
    HUNTER = "hunter"


class Team(Enum):
    """Teams in Werewolf."""
    VILLAGER = "villager"
    WOLF = "wolf"


class Role:
    """Base class for all roles."""
    
    def __init__(self, role_type: RoleType, team: Team):
        """
        Initialize a role.
        
        Args:
            role_type: The type of role
            team: The team this role belongs to
        """
        self.role_type = role_type
        self.team = team
        self.is_alive = True
    
    def can_act_at_night(self) -> bool:
        """Check if this role can perform a night action."""
        return False
    
    def get_role_info(self) -> Dict:
        """Get role information for the player."""
        return {
            'role': self.role_type.value,
            'team': self.team.value,
            'description': self.get_description()
        }
    
    def get_description(self) -> str:
        """Get role description."""
        return "A basic role"


class Villager(Role):
    """
    Villager role - the most basic role with no special abilities.
    
    Villagers win when all wolves are eliminated.
    """
    
    def __init__(self):
        super().__init__(RoleType.VILLAGER, Team.VILLAGER)
    
    def get_description(self) -> str:
        return "A regular villager with no special abilities. Vote wisely during the day!"


class Wolf(Role):
    """
    Wolf role - can kill one person per night.
    
    Wolves win when they equal or outnumber the villagers.
    """
    
    def __init__(self):
        super().__init__(RoleType.WOLF, Team.WOLF)
    
    def can_act_at_night(self) -> bool:
        return self.is_alive
    
    def get_description(self) -> str:
        return "A werewolf. At night, work with other wolves to choose a victim to kill."


class Seer(Role):
    """
    Seer role - can check one person's identity (team) per night.
    
    The Seer is on the villager team and helps identify wolves.
    """
    
    def __init__(self):
        super().__init__(RoleType.SEER, Team.VILLAGER)
        self.has_checked: list = []  # Track who has been checked
    
    def can_act_at_night(self) -> bool:
        return self.is_alive
    
    def check_player(self, player_id: str, player_team: Team) -> Dict:
        """
        Check a player's team.
        
        Args:
            player_id: ID of player being checked
            player_team: The actual team of the player
            
        Returns:
            Dict with check result
        """
        self.has_checked.append(player_id)
        return {
            'player_id': player_id,
            'team': player_team.value
        }
    
    def get_description(self) -> str:
        return "The Seer. Each night, you can check one player to learn their team (Wolf or Villager)."


class Witch(Role):
    """
    Witch role - has one poison and one antidote.
    
    The Witch can save someone from death (antidote) or kill someone (poison).
    Each ability can only be used once per game.
    """
    
    def __init__(self):
        super().__init__(RoleType.WITCH, Team.VILLAGER)
        self.has_antidote = True
        self.has_poison = True
    
    def can_act_at_night(self) -> bool:
        return self.is_alive and (self.has_antidote or self.has_poison)
    
    def use_antidote(self) -> bool:
        """
        Use the antidote to save someone.
        
        Returns:
            True if antidote was available and used, False otherwise
        """
        if self.has_antidote:
            self.has_antidote = False
            return True
        return False
    
    def use_poison(self) -> bool:
        """
        Use poison to kill someone.
        
        Returns:
            True if poison was available and used, False otherwise
        """
        if self.has_poison:
            self.has_poison = False
            return True
        return False
    
    def get_description(self) -> str:
        status = []
        if self.has_antidote:
            status.append("antidote available")
        if self.has_poison:
            status.append("poison available")
        return f"The Witch. You have one antidote (save) and one poison (kill). Status: {', '.join(status) if status else 'no abilities left'}"


class Hunter(Role):
    """
    Hunter role - can shoot someone when they die.
    
    When the Hunter dies (by any means), they can choose one player to eliminate.
    """
    
    def __init__(self):
        super().__init__(RoleType.HUNTER, Team.VILLAGER)
        self.has_shot = False
    
    def can_shoot(self) -> bool:
        """
        Check if the Hunter can still shoot.
        
        Returns:
            True if Hunter hasn't used their shot yet
        """
        return not self.has_shot
    
    def shoot(self, target_id: str) -> Dict:
        """
        Shoot a target player.
        
        Args:
            target_id: ID of the target player
            
        Returns:
            Dict with shot result
        """
        if self.can_shoot():
            self.has_shot = True
            return {
                'success': True,
                'target': target_id
            }
        return {
            'success': False,
            'error': 'Already used shot'
        }
    
    def get_description(self) -> str:
        return "The Hunter. When you die, you can take one player down with you by shooting them."


def create_role(role_type: RoleType) -> Role:
    """
    Factory function to create role instances.
    
    Args:
        role_type: The type of role to create
        
    Returns:
        Role instance
    """
    role_map = {
        RoleType.VILLAGER: Villager,
        RoleType.WOLF: Wolf,
        RoleType.SEER: Seer,
        RoleType.WITCH: Witch,
        RoleType.HUNTER: Hunter
    }
    
    role_class = role_map.get(role_type)
    if not role_class:
        raise ValueError(f"Unknown role type: {role_type}")
    
    return role_class()
