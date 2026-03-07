import time

from backend.config.constants import GameType, TexasPhase
from backend.config.settings import get_settings
from backend.repositories.redis_repo import RedisRepo


class GameStateService:
    @staticmethod
    async def get_state(room_id: int) -> dict | None:
        return await RedisRepo.get_game_state(room_id)

    @staticmethod
    async def save_state(
        room_id: int,
        state: dict,
        prev_state: dict | None = None,
        public_state: dict | None = None,
    ) -> dict:
        state = GameStateService._apply_meta(state, prev_state)
        await RedisRepo.set_game_state(room_id, state)
        if public_state is not None:
            await RedisRepo.set_game_public_state(room_id, public_state)
        await GameStateService._update_texas_deadline(state)
        return state

    @staticmethod
    async def _update_texas_deadline(state: dict | None) -> None:
        if not state:
            return
        if int(state.get("game_type", 0)) != int(GameType.TEXAS):
            return
        room_id = int(state.get("room_id", 0))
        if room_id <= 0:
            return
        phase = state.get("phase")
        if phase == TexasPhase.FINISHED:
            await RedisRepo.remove_texas_turn_deadline(room_id)
            return
        meta = state.get("meta") or {}
        turn_started_ms = int(meta.get("turn_started_ms") or 0)
        if not turn_started_ms:
            turn_started_ms = int(time.time() * 1000)
        timeout_seconds = int(get_settings().texas_action_timeout_seconds)
        deadline_ms = turn_started_ms + timeout_seconds * 1000
        await RedisRepo.set_texas_turn_deadline(room_id, deadline_ms)

    @staticmethod
    def _apply_meta(state: dict, prev_state: dict | None) -> dict:
        now_ms = int(time.time() * 1000)
        meta = dict((prev_state or {}).get("meta") or state.get("meta") or {})

        phase = state.get("phase")
        prev_phase = prev_state.get("phase") if prev_state else None
        if phase is not None and (meta.get("phase_started_ms") is None or phase != prev_phase):
            meta["phase_started_ms"] = now_ms

        current_speaker = state.get("current_speaker")
        prev_speaker = prev_state.get("current_speaker") if prev_state else None
        if current_speaker is None:
            meta["speaker_id"] = None
            meta["speaker_started_ms"] = None
        elif meta.get("speaker_started_ms") is None or current_speaker != prev_speaker:
            meta["speaker_id"] = current_speaker
            meta["speaker_started_ms"] = now_ms

        current_actor = (state.get("state") or {}).get("actor_id")
        prev_actor = (prev_state.get("state") or {}).get("actor_id") if prev_state else None
        if current_actor is None:
            meta["turn_actor_id"] = None
            meta["turn_started_ms"] = None
        elif meta.get("turn_started_ms") is None or current_actor != prev_actor:
            meta["turn_actor_id"] = current_actor
            meta["turn_started_ms"] = now_ms

        state["meta"] = meta
        return state
