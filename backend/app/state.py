"""Centralized in-memory runtime state for backend services and handlers."""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Optional

from ..games.texas import TexasGame
from ..games.texas.matchmaker import TexasMatchmaker
from ..games.werewolf.matchmaker import WerewolfMatchmaker
from ..games.werewolf.werewolf_game import WerewolfGame


@dataclass
class RuntimeState:
    """Holds process-local mutable state used by HTTP/Socket orchestrators."""

    poker_tables: Dict[str, TexasGame] = field(default_factory=dict)
    werewolf_games: Dict[str, WerewolfGame] = field(default_factory=dict)
    player_sessions: Dict[str, Dict] = field(default_factory=dict)
    spectator_subscriptions: Dict[str, Dict[str, Dict[str, bool]]] = field(default_factory=dict)

    werewolf_matchmaker: Optional[WerewolfMatchmaker] = None
    texas_matchmaker: Optional[TexasMatchmaker] = None
    werewolf_timeout_task: Optional[asyncio.Task] = None
    poker_timeout_task: Optional[asyncio.Task] = None

    werewolf_settlement_locks: Dict[str, asyncio.Lock] = field(default_factory=dict)
    werewolf_finalized_games: Dict[str, str] = field(default_factory=dict)
    poker_disconnected_since: Dict[str, Dict[str, datetime]] = field(default_factory=dict)


runtime_state = RuntimeState()
