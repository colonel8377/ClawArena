"""
Production-grade Werewolf (Mafia) engine for AI agents.

Key characteristics:
- Strict state machine (NIGHT_WOLF -> NIGHT_SEER -> NIGHT_WITCH -> DAY_DISCUSS -> DAY_VOTE)
- Async SQLAlchemy persistence for every action (crash-safe)
- Clear separation between data layer (models) and logic (this engine)

The engine exposes a single entry point: `process_action(game_id, agent_id, action_type, target_id)`
which validates turn order, resources, and player state, and returns structured JSON responses.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Tuple
import enum

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy import select

from .models import (
    ActionLog,
    GamePlayer,
    GameSession,
    PhaseEnum,
    RoleEnum,
    Base,
    _default_flags,
)

# ---------------------------------------------------------------------------
# Async DB setup helper (simple factory; in production wire via DI)
# ---------------------------------------------------------------------------


def make_async_session(database_url: str) -> async_sessionmaker[AsyncSession]:
    engine = create_async_engine(database_url, echo=False, future=True)
    return async_sessionmaker(engine, expire_on_commit=False)


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


@dataclass
class ProcessResult:
    success: bool
    error: Optional[str] = None
    data: Optional[Dict] = None


class SeerResult(str, enum.Enum):
    GOOD = "GOOD"
    BAD = "BAD"


class WerewolfEngine:
    """
    Core Werewolf game engine with immediate persistence.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self.session_factory = session_factory

    async def create_game(self, players: Dict[str, RoleEnum]) -> int:
        """
        Create a new game with predefined roles.

        Args:
            players: mapping of agent_id -> RoleEnum

        Returns:
            game_id of the newly created session
        """
        async with self.session_factory() as session:
            game = GameSession()
            session.add(game)
            await session.flush()
            for agent_id, role in players.items():
                gp = GamePlayer(
                    session_id=game.id,
                    agent_id=agent_id,
                    role=role,
                    status_flags=_default_flags(role),
                )
                session.add(gp)
            await session.commit()
            return game.id

    # ------------------------------- Public API --------------------------- #

    async def load_game(self, game_id: int) -> Tuple[GameSession, Dict[int, GamePlayer]]:
        """Load a game session and return session + players mapping."""
        async with self.session_factory() as session:
            stmt = (
                select(GameSession)
                .where(GameSession.id == game_id)
                .options()
            )
            result = await session.execute(stmt)
            game: GameSession = result.scalar_one()
            players = {p.id: p for p in game.players}
            # initialize missing flags
            for p in players.values():
                p.initialize_flags()
            return game, players

    async def process_action(
        self, game_id: int, agent_id: str, action_type: str, target_id: Optional[int] = None
    ) -> Dict:
        """
        Entry point for agent actions. Validates turn order/resources and persists outcomes.
        """
        async with self.session_factory() as session:
            game, players = await self._load_for_update(session, game_id)
            actor = self._find_player(players, agent_id)
            if not actor:
                return await self._log_and_response(
                    session, game, None, action_type, target_id, "Player not found"
                )
            if not actor.is_alive:
                return await self._log_and_response(
                    session, game, actor.id, action_type, target_id, "Player is dead"
                )

            # Phase dispatch
            handler = {
                PhaseEnum.NIGHT_WOLF: self._handle_wolf,
                PhaseEnum.NIGHT_SEER: self._handle_seer,
                PhaseEnum.NIGHT_WITCH: self._handle_witch,
                PhaseEnum.DAY_DISCUSS: self._handle_discuss,
                PhaseEnum.DAY_VOTE: self._handle_vote,
                PhaseEnum.DEATH_RATTLE: self._handle_hunter,
            }.get(game.phase)

            if not handler:
                return await self._log_and_response(
                    session, game, actor.id, action_type, target_id, "Invalid phase"
                )

            result = await handler(session, game, players, actor, action_type, target_id)
            await session.commit()
            return result

    # --------------------------- Phase Handlers -------------------------- #

    async def _handle_wolf(
        self, session, game, players, actor, action, target_id
    ) -> Dict:
        if actor.role != RoleEnum.WEREWOLF or action != "kill":
            return await self._log_and_response(
                session, game, actor.id, action, target_id, "Not wolf turn"
            )
        target = self._validate_target(players, target_id)
        if target is None or not target.is_alive:
            return await self._log_and_response(
                session, game, actor.id, action, target_id, "Invalid target"
            )
        game.state_flags["wolf_target"] = target.id
        game.pending_death = target.id
        return await self._advance(session, game, PhaseEnum.NIGHT_SEER, actor, action, target)

    async def _handle_seer(
        self, session, game, players, actor, action, target_id
    ) -> Dict:
        if actor.role != RoleEnum.SEER or action != "inspect":
            return await self._log_and_response(
                session, game, actor.id, action, target_id, "Not seer turn"
            )
        target = self._validate_target(players, target_id)
        if target is None or not target.is_alive:
            return await self._log_and_response(
                session, game, actor.id, action, target_id, "Invalid target"
            )
        result = SeerResult.BAD if target.role == RoleEnum.WEREWOLF else SeerResult.GOOD
        game.state_flags["seer_last_result"] = result.value
        return await self._advance(session, game, PhaseEnum.NIGHT_WITCH, actor, action, target)

    async def _handle_witch(
        self, session, game, players, actor, action, target_id
    ) -> Dict:
        if actor.role != RoleEnum.WITCH:
            return await self._log_and_response(
                session, game, actor.id, action, target_id, "Not witch turn"
            )
        flags = actor.status_flags or {}
        # prevent double action in same night
        if game.state_flags.get("witch_acted"):
            return await self._log_and_response(
                session, game, actor.id, action, target_id, "Witch already acted this night"
            )
        wolf_target_id = game.state_flags.get("wolf_target") or game.pending_death
        # Witch vision
        vision = wolf_target_id

        if action == "save":
            if flags.get("antidote_used"):
                return await self._log_and_response(
                    session, game, actor.id, action, target_id, "Antidote already used"
                )
            flags["antidote_used"] = True
            game.pending_death = None  # cancel wolf target
            game.state_flags["wolf_target"] = None
        elif action == "poison":
            if flags.get("poison_used"):
                return await self._log_and_response(
                    session, game, actor.id, action, target_id, "Poison already used"
                )
            tgt = self._validate_target(players, target_id)
            if tgt is None or not tgt.is_alive:
                return await self._log_and_response(
                    session, game, actor.id, action, target_id, "Invalid target"
                )
            flags["poison_used"] = True
            game.pending_poison = tgt.id
        elif action == "pass":
            pass
        else:
            return await self._log_and_response(
                session, game, actor.id, action, target_id, "Invalid witch action"
            )

        actor.status_flags = flags
        # Witch cannot use both in same night: enforced by flags checks above
        game.state_flags["witch_acted"] = True

        # Morning resolution happens immediately after witch action
        await self._resolve_night_deaths(game, players)
        if game.phase == PhaseEnum.FINISHED:
            await self._log_and_response(
                session, game, actor.id, action, target_id, None, extra={"vision": vision}
            )
            return {"success": True, "phase": game.phase.value, "winner": game.state_flags.get("winner")}

        if game.state_flags.get("hunter_pending"):
            game.phase = PhaseEnum.DEATH_RATTLE
        else:
            game.phase = PhaseEnum.DAY_DISCUSS
        return await self._log_and_response(
            session,
            game,
            actor.id,
            action,
            target_id,
            None,
            extra={"vision": vision, "phase": game.phase.value},
        )

    async def _handle_discuss(
        self, session, game, players, actor, action, target_id
    ) -> Dict:
        # Discussion is free-form; any action simply progresses when called "proceed"
        if action != "proceed":
            return await self._log_and_response(
                session, game, actor.id, action, target_id, "Only proceed allowed"
            )
        return await self._advance(session, game, PhaseEnum.DAY_VOTE, actor, action, None)

    async def _handle_vote(
        self, session, game, players, actor, action, target_id
    ) -> Dict:
        if action != "vote":
            return await self._log_and_response(
                session, game, actor.id, action, target_id, "Invalid vote action"
            )
        target = self._validate_target(players, target_id)
        if target is None or not target.is_alive:
            return await self._log_and_response(
                session, game, actor.id, action, target_id, "Invalid target"
            )
        # Persist vote
        votes = game.state_flags.get("votes", {})
        votes[int(actor.id)] = target.id  # enforce int keys
        game.state_flags["votes"] = votes

        # For simplicity, resolve when all alive players have voted
        alive_ids = {p.id for p in players.values() if p.is_alive}
        if set(votes.keys()) >= alive_ids:
            await self._resolve_votes(game, players)
            if game.phase != PhaseEnum.FINISHED and game.state_flags.get("hunter_pending"):
                game.phase = PhaseEnum.DEATH_RATTLE
            elif game.phase != PhaseEnum.FINISHED:
                game.phase = PhaseEnum.NIGHT_WOLF
                game.turn_counter += 1
        return await self._log_and_response(
            session, game, actor.id, action, target_id, None, extra={"vote_recorded": True}
        )

    async def _handle_hunter(
        self, session, game, players, actor, action, target_id
    ) -> Dict:
        if actor.role != RoleEnum.HUNTER or action != "shoot":
            return await self._log_and_response(
                session, game, actor.id, action, target_id, "Not hunter turn"
            )
        flags = actor.status_flags or {}
        if flags.get("gun_status") != "loaded":
            return await self._log_and_response(
                session, game, actor.id, action, target_id, "Gun unavailable"
            )
        target = self._validate_target(players, target_id)
        if target is None or not target.is_alive:
            return await self._log_and_response(
                session, game, actor.id, action, target_id, "Invalid target"
            )
        flags["gun_status"] = "spent"
        actor.status_flags = flags
        target.is_alive = False
        await self._check_win(game, players)
        game.phase = PhaseEnum.FINISHED if game.state_flags.get("winner") else PhaseEnum.NIGHT_WOLF
        return await self._log_and_response(session, game, actor.id, action, target_id, None)

    # --------------------------- Helpers --------------------------------- #

    async def _load_for_update(self, session: AsyncSession, game_id: int):
        stmt = select(GameSession).where(GameSession.id == game_id).with_for_update()
        res = await session.execute(stmt)
        game = res.scalar_one()
        players = {p.id: p for p in game.players}
        for p in players.values():
            p.initialize_flags()
        return game, players

    def _find_player(self, players: Dict[int, GamePlayer], agent_id: str) -> Optional[GamePlayer]:
        for p in players.values():
            if p.agent_id == agent_id:
                return p
        return None

    def _validate_target(self, players: Dict[int, GamePlayer], target_id: Optional[int]):
        if target_id is None:
            return None
        return players.get(target_id)

    async def _advance(
        self,
        session: AsyncSession,
        game: GameSession,
        next_phase: PhaseEnum,
        actor: GamePlayer,
        action: str,
        target,
        extra: Optional[Dict] = None,
    ) -> Dict:
        game.phase = next_phase
        return await self._log_and_response(
            session,
            game,
            actor.id,
            action,
            getattr(target, "id", target),
            None,
            extra=extra,
        )

    async def _log_and_response(
        self,
        session: AsyncSession,
        game: GameSession,
        player_id: Optional[int],
        action: str,
        target_id: Optional[int],
        error: Optional[str],
        extra: Optional[Dict] = None,
    ) -> Dict:
        log = ActionLog(
            session_id=game.id,
            player_id=player_id,
            action_type=action,
            target_player_id=target_id,
            payload=extra or {},
            error=error,
        )
        session.add(log)
        await session.flush()
        response = {"success": error is None}
        if error:
            response["error"] = error
        if extra:
            response.update(extra)
        return response

    async def _resolve_votes(self, game: GameSession, players: Dict[int, GamePlayer]):
        votes = game.state_flags.get("votes", {})
        tally: Dict[int, int] = {}
        for target in votes.values():
            tally[target] = tally.get(target, 0) + 1
        if not tally:
            return
        eliminated_id = max(tally, key=tally.get)
        target = players.get(eliminated_id)
        if target:
            target.is_alive = False
            # Hunter death by vote triggers death rattle
            if target.role == RoleEnum.HUNTER and target.status_flags.get("gun_status") == "loaded":
                game.state_flags["hunter_pending"] = target.id
            else:
                game.state_flags["hunter_pending"] = None
        game.state_flags["votes"] = {}
        await self._check_win(game, players)

    async def _resolve_night_deaths(self, game: GameSession, players: Dict[int, GamePlayer]):
        wolf_target_id = game.state_flags.get("wolf_target")
        poison_target_id = game.pending_poison
        # Apply wolf target if not saved
        if wolf_target_id:
            target = players.get(wolf_target_id)
            if target and target.is_alive:
                target.is_alive = False
                # Hunter shot trigger when killed by wolves
                if target.role == RoleEnum.HUNTER and target.status_flags.get("gun_status") == "loaded":
                    game.state_flags["hunter_pending"] = target.id
        # Apply poison
        if poison_target_id:
            target = players.get(poison_target_id)
            if target and target.is_alive:
                target.is_alive = False
                # Hunter dies silently from poison
                if target.role == RoleEnum.HUNTER:
                    game.state_flags["hunter_pending"] = None
        game.pending_poison = None
        game.pending_death = None
        game.state_flags["wolf_target"] = None
        game.state_flags["witch_acted"] = False
        await self._check_win(game, players)

    async def _check_win(self, game: GameSession, players: Dict[int, GamePlayer]):
        alive = [p for p in players.values() if p.is_alive]
        wolves = [p for p in alive if p.role == RoleEnum.WEREWOLF]
        villagers = [p for p in alive if p.role != RoleEnum.WEREWOLF]
        gods = [p for p in alive if p.role in (RoleEnum.SEER, RoleEnum.WITCH, RoleEnum.HUNTER)]
        # Side slaughter rules
        if not wolves:
            game.phase = PhaseEnum.FINISHED
            game.state_flags["winner"] = "TOWN"
            await self._finalize_game(game, "TOWN")
        elif (not villagers) or (not gods):
            game.phase = PhaseEnum.FINISHED
            game.state_flags["winner"] = "WOLF"
            await self._finalize_game(game, "WOLF")

    async def morning_settlement(self, game_id: int) -> Dict:
        """Resolve pending night deaths and advance to discuss."""
        async with self.session_factory() as session:
            game, players = await self._load_for_update(session, game_id)
            await self._resolve_night_deaths(game, players)
            if game.phase != PhaseEnum.FINISHED and game.state_flags.get("hunter_pending"):
                game.phase = PhaseEnum.DEATH_RATTLE
            elif game.phase != PhaseEnum.FINISHED:
                game.phase = PhaseEnum.DAY_DISCUSS
            await session.commit()
            return {"success": True, "phase": game.phase.value, "winner": game.state_flags.get("winner")}

    async def _finalize_game(self, game: GameSession, winner_team: str):
        """
        Placeholder for settlement logic: redistribute pot, etc.
        """
        game.state_flags["settled"] = True
        # Actual settlement would be implemented here (economy hooks)
