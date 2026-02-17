"""Shared game orchestration helpers."""

import asyncio
from datetime import datetime
from typing import Dict, Iterable, Optional


class GameService:
    """Common helpers for game orchestration and spectator routing."""

    POKER_SPECTATOR_ROOM_PREFIX = "spectate:poker:"
    WEREWOLF_SPECTATOR_ROOM_PREFIX = "spectate:werewolf:"

    def __init__(self, state, sio) -> None:
        self._state = state
        self._sio = sio

    def poker_spectator_room(self, table_id: str) -> str:
        return f"{self.POKER_SPECTATOR_ROOM_PREFIX}{table_id}"

    def werewolf_spectator_room(self, game_id: str) -> str:
        return f"{self.WEREWOLF_SPECTATOR_ROOM_PREFIX}{game_id}"

    def set_spectator_subscription(
        self, sid: str, game_type: str, room_id: str, reveal: bool
    ) -> None:
        """Track spectator reveal preference per room."""
        self._state.spectator_subscriptions.subscribe(sid, game_type, room_id, reveal)

    def remove_spectator_subscription(
        self, sid: str, game_type: str, room_id: Optional[str] = None
    ) -> None:
        """Remove one or all spectator subscriptions for a sid/game type."""
        self._state.spectator_subscriptions.unsubscribe(sid, game_type, room_id)

    def is_read_only_session(self, sid: str) -> bool:
        return self._state.player_sessions.is_read_only(sid)

    async def reject_if_read_only(self, sid: str, action_name: str) -> bool:
        """Return True when action should be stopped due to read-only session."""
        if self.is_read_only_session(sid):
            await self._sio.emit(
                "error",
                {
                    "message": (
                        f"Read-only spectator session cannot perform '{action_name}'"
                    ),
                    "error_code": "SPECTATOR_READ_ONLY",
                },
                room=sid,
            )
            return True
        return False

    def iter_reveal_spectators(self, game_type: str, room_id: str) -> Iterable[str]:
        """Yield sids that subscribed with reveal=True for this room."""
        for sid, sid_subs in self._state.spectator_subscriptions.items():
            # Defense-in-depth: only read-only spectator sessions can receive
            # reveal-all state so active players cannot subscribe to hidden info.
            if sid_subs.is_reveal_enabled(game_type, room_id) and self.is_read_only_session(sid):
                yield sid

    async def emit_to_sids(self, event: str, payload: Dict, sids: Iterable[str]) -> None:
        """Emit same payload to many sockets concurrently."""
        sids = list(sids)
        if not sids:
            return
        await asyncio.gather(
            *(self._sio.emit(event, payload, room=target_sid) for target_sid in sids),
            return_exceptions=True,
        )

    async def emit_poker_event(self, table_id: str, event: str, payload: Dict) -> None:
        """Emit an event to poker players and spectator room."""
        await self._sio.emit(event, payload, room=table_id)
        await self._sio.emit(event, payload, room=self.poker_spectator_room(table_id))

    async def emit_werewolf_event(self, game_id: str, event: str, payload: Dict) -> None:
        """Emit an event to werewolf players and spectator room."""
        await self._sio.emit(event, payload, room=game_id)
        await self._sio.emit(event, payload, room=self.werewolf_spectator_room(game_id))

    async def emit_werewolf_action_trace(
        self,
        game,
        sid: str,
        action: str,
        result: Dict,
        target_sid: Optional[str],
        message: Optional[str],
    ) -> None:
        """Emit action timeline events to spectators (masked + reveal modes)."""
        game_id = game.game_id
        masked_payload = self._build_werewolf_action_trace(
            game, sid, action, result, target_sid, message, reveal=False
        )
        await self._sio.emit(
            "werewolf_action_trace",
            masked_payload,
            room=self.werewolf_spectator_room(game_id),
        )

        reveal_sids = list(self.iter_reveal_spectators("werewolf", game_id))
        if reveal_sids:
            reveal_payload = self._build_werewolf_action_trace(
                game, sid, action, result, target_sid, message, reveal=True
            )
            await self.emit_to_sids("werewolf_action_trace", reveal_payload, reveal_sids)

    @staticmethod
    def _is_night_phase(phase: str) -> bool:
        return phase.startswith("night_")

    def _build_werewolf_action_trace(
        self,
        game,
        sid: str,
        action: str,
        result: Dict,
        target_sid: Optional[str],
        message: Optional[str],
        reveal: bool,
    ) -> Dict:
        """Build spectator action trace payload with masked/reveal variants."""
        actor = next((p for p in game.players if p.get("sid") == sid), None)
        actor_nickname = actor.get("nickname", "Unknown") if actor else "Unknown"
        phase = game.phase.value
        target_player = (
            next((p for p in game.players if p.get("sid") == target_sid), None)
            if target_sid
            else None
        )
        target_nickname = target_player.get("nickname") if target_player else None

        payload: Dict = {
            "game_id": game.game_id,
            "phase": phase,
            "actor_sid": sid,
            "actor_nickname": actor_nickname,
            "action": action,
            "timestamp": datetime.utcnow().isoformat(),
        }

        hide_target = self._is_night_phase(phase) and not reveal
        if action == "wolf_chat":
            payload["message"] = (message or "") if reveal else "[hidden wolf chat]"
            payload["visibility"] = "reveal_only" if reveal else "hidden"
        elif action in {"chat", "speak"}:
            payload["message"] = message or ""
            payload["visibility"] = "public"
        elif action in {"night_kill", "seer_check", "witch_poison", "hunter_shoot", "vote"}:
            if target_sid is None:
                payload["target"] = None
            elif hide_target:
                payload["target"] = {"sid": target_sid, "nickname": "Hidden Target"}
            else:
                payload["target"] = {
                    "sid": target_sid,
                    "nickname": target_nickname or "Unknown",
                }
        elif action == "witch_save":
            payload["target"] = None if hide_target else {
                "sid": game.pending_wolf_kill,
                "nickname": (
                    next(
                        (
                            p.get("nickname")
                            for p in game.players
                            if p.get("sid") == game.pending_wolf_kill
                        ),
                        None,
                    )
                    or "Unknown"
                )
                if game.pending_wolf_kill
                else None,
            }

        if action == "seer_check" and reveal and result.get("result"):
            payload["seer_result"] = result.get("result")

        return payload
