"""Central coordinator for cross-service runtime orchestration."""

from datetime import datetime

from backend.config.arena_config import is_local_debug_mode
from backend.constant.socket_error import SocketError
from backend.app.state import RuntimeState
from backend.database.connection import get_async_db_session
from backend.database.models import GameSession, GameStatus
from backend.database.persistence_manager import persistence_manager
from backend.database.redis_manager import redis_manager
from backend.games.texas import TexasGame
from backend.games.werewolf.werewolf_game import WerewolfGame
from backend.services.matchmaking_socket_service import MatchmakingSocketService
from backend.services.common_socket_service import is_read_only_session, reject_if_read_only
from backend.utils import log
from sqlalchemy import select, update


class StateCoordinator:
    """Coordinates matchmaking flow and startup recovery."""

    def __init__(self, sio, state: RuntimeState, texas_service, werewolf_service) -> None:
        self._sio = sio
        self._state = state
        self._texas_service = texas_service
        self._werewolf_service = werewolf_service
        self._matchmaking_service = MatchmakingSocketService(
            sio=sio,
            state=state,
            texas_service=texas_service,
            werewolf_service=werewolf_service,
        )

    async def join_texas_matchmaking(self, sid: str, payload) -> None:
        await self._matchmaking_service.join_texas_matchmaking(sid)

    async def leave_texas_matchmaking(self, sid: str, payload) -> None:
        await self._matchmaking_service.leave_texas_matchmaking(sid)

    async def get_texas_matchmaking_status(self, sid: str, payload) -> None:
        await self._matchmaking_service.get_texas_matchmaking_status(sid)

    async def join_werewolf_matchmaking(self, sid: str, payload) -> None:
        await self._matchmaking_service.join_werewolf_matchmaking(sid)

    async def leave_werewolf_matchmaking(self, sid: str, payload) -> None:
        await self._matchmaking_service.leave_werewolf_matchmaking(sid)

    async def get_werewolf_matchmaking_status(self, sid: str, payload) -> None:
        await self._matchmaking_service.get_werewolf_matchmaking_status(sid)

    async def recover_on_startup(self) -> None:
        """Restore persisted active game states from Redis snapshot storage."""
        active_game_ids = await redis_manager.list_active_games()
        if not active_game_ids:
            log.info("No persisted games found")
            return

        log.info(f"Found {len(active_game_ids)} persisted games")
        restored_count = 0

        for game_id in active_game_ids:
            try:
                state_data = await persistence_manager.restore_game_state(game_id)
                if not state_data or not state_data.get("state"):
                    continue

                state = state_data["state"]
                game_type = state_data.get("game_type", "unknown")
                phase = state.get("phase", "unknown")

                if game_type == "werewolf":
                    if phase in ["waiting", "finished", "aborted"]:
                        await redis_manager.delete_game_data(game_id)
                        continue
                    self._state.register_werewolf_game(game_id, WerewolfGame.from_dict(state))
                    restored_count += 1
                    log.info(
                        f"  ✓ Restored werewolf game: {game_id} (phase: {phase})"
                    )
                    continue

                if game_type == "texas":
                    if phase in ["finished", "aborted"]:
                        await redis_manager.delete_game_data(game_id)
                        continue
                    self._state.register_poker_table(game_id, TexasGame.from_dict(state))
                    restored_count += 1
                    log.info(
                        f"  ✓ Restored poker table: {game_id} (phase: {phase})"
                    )
                    continue

                log.warning(f"  ⚠ Unknown game type: {game_type} for {game_id}")
            except Exception as exc:
                log.warning(f"  ⚠ Error restoring game {game_id}: {exc}")

        log.info(f"✓ Restored {restored_count} active games")

    @staticmethod
    def _status_from_phase(phase: str) -> str:
        if phase == "waiting":
            return GameStatus.WAITING.value
        if phase == "aborted":
            return GameStatus.ABORTED.value
        if phase == "finished":
            return GameStatus.FINISHED.value
        return GameStatus.ACTIVE.value

    async def _sync_texas_state(self, table_id: str, event_type: str = "manual") -> None:
        table = self._state.poker_tables.get(table_id)
        if not table:
            return
        await table.save_state_to_redis()
        await persistence_manager.save_poker_checkpoint(
            table_id,
            table.to_dict(),
            event_type=event_type,
        )

    async def _sync_werewolf_state(self, game_id: str) -> None:
        game = self._state.werewolf_games.get(game_id)
        if not game:
            return

        await game.save_state_to_redis()

        snapshot = game.to_dict()
        phase = str(snapshot.get("phase") or "unknown")
        status = self._status_from_phase(phase)
        now = datetime.utcnow()
        player_count = len(snapshot.get("players") or [])

        async with get_async_db_session() as db:
            result = await db.execute(
                select(GameSession).where(GameSession.game_id == game_id)
            )
            session = result.scalar_one_or_none()
            if not session:
                db.add(
                    GameSession(
                        game_id=game_id,
                        game_type="werewolf",
                        status=status,
                        player_count=player_count,
                        current_phase=phase,
                        state_snapshot=snapshot,
                        created_at=now,
                        updated_at=now,
                    )
                )
            else:
                await db.execute(
                    update(GameSession)
                    .where(GameSession.game_id == game_id)
                    .values(
                        status=status,
                        player_count=player_count,
                        current_phase=phase,
                        state_snapshot=snapshot,
                        updated_at=now,
                    )
                )
            await db.commit()

    async def _run_mutation(self, sid: str, action: str, mutate, sync=None) -> None:
        if await reject_if_read_only(self._sio, self._state, sid, action):
            return
        await mutate()
        if sync is not None:
            await sync()

    async def start_texas_hand(self, sid: str, payload) -> None:
        await self._run_mutation(
            sid,
            "start_hand",
            mutate=lambda: self._texas_service.start_hand(payload.table_id, sid),
            sync=lambda: self._sync_texas_state(payload.table_id, event_type="hand_start"),
        )

    async def texas_player_move(self, sid: str, payload) -> None:
        amount = payload.amount or 0
        if amount < 0:
            raise SocketError("Invalid amount: must be non-negative")
        await self._run_mutation(
            sid,
            "player_move",
            mutate=lambda: self._texas_service.player_move(
                payload.table_id,
                sid,
                payload.action,
                amount,
                payload.message,
            ),
            sync=lambda: self._sync_texas_state(payload.table_id, event_type="action"),
        )

    async def get_texas_state(self, sid: str, payload) -> None:
        table_id = payload.table_id
        table = self._state.poker_tables.get(table_id)
        if not table_id or not table:
            raise SocketError("Invalid table_id")
        await self._sio.emit("game_state", table.get_game_state(sid), room=sid)

    async def leave_texas_game(self, sid: str, payload) -> None:
        table_id = payload.table_id
        await self._run_mutation(
            sid,
            "leave_game",
            mutate=lambda: self._texas_service.leave_game(payload.table_id, sid),
            sync=lambda: self._sync_texas_state(table_id, event_type="manual"),
        )

    async def create_werewolf_game(self, sid: str, payload) -> None:
        await self._run_mutation(
            sid,
            "create_werewolf_game",
            mutate=lambda: self._werewolf_service.create_game(sid, payload.game_id, payload.entry_fee),
            sync=lambda: self._sync_werewolf_state(payload.game_id),
        )

    async def join_werewolf_game(self, sid: str, payload) -> None:
        await self._run_mutation(
            sid,
            "join_werewolf_game",
            mutate=lambda: self._werewolf_service.join_game(sid, payload.game_id),
            sync=lambda: self._sync_werewolf_state(payload.game_id),
        )

    async def start_werewolf_game(self, sid: str, payload) -> None:
        await self._run_mutation(
            sid,
            "start_werewolf_game",
            mutate=lambda: self._werewolf_service.start_game(sid, payload.game_id),
            sync=lambda: self._sync_werewolf_state(payload.game_id),
        )

    async def werewolf_action(self, sid: str, payload) -> None:
        await self._run_mutation(
            sid,
            "werewolf_action",
            mutate=lambda: self._werewolf_service.process_action(
                sid,
                payload.game_id,
                payload.action,
                payload.target_sid,
                payload.message,
            ),
            sync=lambda: self._sync_werewolf_state(payload.game_id),
        )

    async def advance_werewolf_phase(self, sid: str, payload) -> None:
        if not is_local_debug_mode():
            raise SocketError(
                "advance_werewolf_phase is disabled outside LOCAL_DEBUG_MODE",
                error_code="DEBUG_ONLY",
            )
        if not payload.game_id or payload.game_id not in self._state.werewolf_games:
            raise SocketError("Invalid game_id")
        await self._run_mutation(
            sid,
            "advance_werewolf_phase",
            mutate=lambda: self._werewolf_service.advance_phase(sid, payload.game_id),
            sync=lambda: self._sync_werewolf_state(payload.game_id),
        )

    async def get_werewolf_state(self, sid: str, payload) -> None:
        game = self._state.werewolf_games.get(payload.game_id)
        if not payload.game_id or not game:
            raise SocketError("Invalid game_id")
        reveal_requested = bool(payload.reveal)
        reveal = reveal_requested and is_read_only_session(self._state, sid)
        if reveal_requested and not reveal:
            raise SocketError(
                "Reveal mode is only available to spectator sessions",
                error_code="REVEAL_FORBIDDEN",
            )
        await self._sio.emit("werewolf_state", game.get_game_state(sid, reveal_all=reveal), room=sid)
