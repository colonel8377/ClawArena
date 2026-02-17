"""Centralized in-memory runtime state for backend services and handlers."""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Iterator, Optional

from backend.games.texas import TexasGame
from backend.games.texas.matchmaker import TexasMatchmaker
from backend.games.werewolf.matchmaker import WerewolfMatchmaker
from backend.games.werewolf.werewolf_game import WerewolfGame


@dataclass
class PlayerSession:
    """Runtime session state for a single socket connection."""

    player_id: Optional[str]
    player_name: Optional[str] = None
    table_id: Optional[str] = None
    game_id: Optional[str] = None
    authenticated: bool = False
    read_only: bool = False
    spectator_mode: bool = False
    agent_id: Optional[str] = None

    def is_read_only(self) -> bool:
        return bool(self.read_only or self.spectator_mode)


class PlayerSessionStore:
    """Store for socket session objects keyed by sid."""

    def __init__(self) -> None:
        self._sessions: Dict[str, PlayerSession] = {}

    def create(
        self,
        sid: str,
        *,
        player_id: Optional[str],
        player_name: Optional[str] = None,
        table_id: Optional[str] = None,
        game_id: Optional[str] = None,
        authenticated: bool = False,
        read_only: bool = False,
        spectator_mode: bool = False,
        agent_id: Optional[str] = None,
    ) -> PlayerSession:
        session = PlayerSession(
            player_id=player_id,
            player_name=player_name,
            table_id=table_id,
            game_id=game_id,
            authenticated=authenticated,
            read_only=read_only,
            spectator_mode=spectator_mode,
            agent_id=agent_id,
        )
        self._sessions[sid] = session
        return session

    def get(self, sid: Optional[str], default=None) -> Optional[PlayerSession]:
        if sid is None:
            return default
        return self._sessions.get(sid, default)

    def pop(self, sid: str, default=None):
        return self._sessions.pop(sid, default)

    def remove(self, sid: str) -> Optional[PlayerSession]:
        return self._sessions.pop(sid, None)

    def items(self):
        return self._sessions.items()

    def set_table_id(self, sid: str, table_id: Optional[str]) -> None:
        session = self._sessions.get(sid)
        if session:
            session.table_id = table_id

    def set_game_id(self, sid: str, game_id: Optional[str]) -> None:
        session = self._sessions.get(sid)
        if session:
            session.game_id = game_id

    def is_authenticated(self, sid: str) -> bool:
        session = self._sessions.get(sid)
        return bool(session and session.authenticated)

    def is_read_only(self, sid: str) -> bool:
        session = self._sessions.get(sid)
        return bool(session and session.is_read_only())

    def __contains__(self, sid: str) -> bool:
        return sid in self._sessions


@dataclass
class SpectatorSubscription:
    """Spectator room subscription preferences for a sid."""

    poker: Dict[str, bool] = field(default_factory=dict)
    werewolf: Dict[str, bool] = field(default_factory=dict)

    def is_reveal_enabled(self, game_type: str, room_id: str) -> bool:
        if game_type == "poker":
            return bool(self.poker.get(room_id))
        if game_type == "werewolf":
            return bool(self.werewolf.get(room_id))
        return False

    def set_reveal(self, game_type: str, room_id: str, reveal: bool) -> None:
        if game_type == "poker":
            self.poker[room_id] = bool(reveal)
            return
        if game_type == "werewolf":
            self.werewolf[room_id] = bool(reveal)


class SpectatorSubscriptions:
    """Store spectator subscriptions keyed by sid."""

    def __init__(self) -> None:
        self._subscriptions: Dict[str, SpectatorSubscription] = {}

    def get(self, sid: str, default=None):
        return self._subscriptions.get(sid, default)

    def items(self) -> Iterator:
        return self._subscriptions.items()

    def pop(self, sid: str, default=None):
        return self._subscriptions.pop(sid, default)

    def clear_sid(self, sid: str) -> None:
        self._subscriptions.pop(sid, None)

    def subscribe(self, sid: str, game_type: str, room_id: str, reveal: bool) -> None:
        sid_subs = self._subscriptions.setdefault(sid, SpectatorSubscription())
        sid_subs.set_reveal(game_type, room_id, bool(reveal))

    def unsubscribe(self, sid: str, game_type: str, room_id: Optional[str] = None) -> None:
        sid_subs = self._subscriptions.get(sid)
        if not sid_subs:
            return
        if game_type == "poker":
            room_subs = sid_subs.poker
        elif game_type == "werewolf":
            room_subs = sid_subs.werewolf
        else:
            return
        if room_id:
            room_subs.pop(room_id, None)
        else:
            room_subs.clear()
        if not sid_subs.poker and not sid_subs.werewolf:
            self._subscriptions.pop(sid, None)


@dataclass
class WerewolfFinalizationRecord:
    status: str
    finalized_at: datetime = field(default_factory=datetime.utcnow)


class WerewolfFinalizationRegistry:
    """Tracks whether werewolf games have already been finalized."""

    def __init__(self) -> None:
        self._records: Dict[str, WerewolfFinalizationRecord] = {}

    def is_finalized(self, game_id: str) -> bool:
        return game_id in self._records

    def mark_ended(self, game_id: str) -> None:
        self._records[game_id] = WerewolfFinalizationRecord(status="ended")

    def mark_aborted(self, game_id: str) -> None:
        self._records[game_id] = WerewolfFinalizationRecord(status="aborted")

    def get_status(self, game_id: str) -> Optional[str]:
        record = self._records.get(game_id)
        return record.status if record else None


class PokerDisconnectTracker:
    """Tracks disconnected poker players per table."""

    def __init__(self) -> None:
        self._by_table: Dict[str, Dict[str, datetime]] = {}

    def mark(self, table_id: str, player_id: str, seen_at: Optional[datetime] = None) -> None:
        if not table_id or not player_id:
            return
        table_map = self._by_table.setdefault(table_id, {})
        table_map[player_id] = seen_at or datetime.utcnow()

    def clear(self, table_id: str, player_id: str) -> None:
        table_map = self._by_table.get(table_id)
        if not table_map:
            return
        table_map.pop(player_id, None)
        if not table_map:
            self._by_table.pop(table_id, None)

    def clear_table(self, table_id: str) -> None:
        self._by_table.pop(table_id, None)

    def get_table(self, table_id: str) -> Dict[str, datetime]:
        table_map = self._by_table.get(table_id)
        return dict(table_map) if table_map else {}


@dataclass
class RuntimeState:
    """Holds process-local mutable state used by HTTP/Socket orchestrators."""

    poker_tables: Dict[str, TexasGame] = field(default_factory=dict)
    werewolf_games: Dict[str, WerewolfGame] = field(default_factory=dict)
    player_sessions: PlayerSessionStore = field(default_factory=PlayerSessionStore)
    spectator_subscriptions: SpectatorSubscriptions = field(default_factory=SpectatorSubscriptions)

    werewolf_matchmaker: Optional[WerewolfMatchmaker] = None
    texas_matchmaker: Optional[TexasMatchmaker] = None
    werewolf_timeout_task: Optional[asyncio.Task] = None
    poker_timeout_task: Optional[asyncio.Task] = None

    werewolf_settlement_locks: Dict[str, asyncio.Lock] = field(default_factory=dict)
    werewolf_finalized_games: WerewolfFinalizationRegistry = field(default_factory=WerewolfFinalizationRegistry)
    poker_disconnected_since: PokerDisconnectTracker = field(default_factory=PokerDisconnectTracker)

    # Runtime execution cache helpers (prefer these over direct dict writes).
    def register_poker_table(self, table_id: str, table: TexasGame) -> None:
        self.poker_tables[table_id] = table

    def register_werewolf_game(self, game_id: str, game: WerewolfGame) -> None:
        self.werewolf_games[game_id] = game

    def remove_poker_table(self, table_id: str) -> None:
        self.poker_tables.pop(table_id, None)

    def remove_werewolf_game(self, game_id: str) -> None:
        self.werewolf_games.pop(game_id, None)


runtime_state = RuntimeState()
