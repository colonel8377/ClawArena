import time

from backend.config.constants import GameType, TexasPhase, WerewolfPhase
from backend.config.settings import get_settings


class TimerService:
    @staticmethod
    def build(state: dict | None) -> dict | None:
        if not state:
            return None
        settings = get_settings()
        now_ms = int(time.time() * 1000)
        timers: dict[str, int] = {"now_ms": now_ms}

        meta = state.get("meta") or {}
        game_type = int(state.get("game_type", 0))
        phase = state.get("phase")

        def _apply_deadline(key: str, start_ms: int | None, timeout_seconds: int) -> None:
            if not start_ms:
                return
            deadline = int(start_ms) + int(timeout_seconds) * 1000
            timers[f"{key}_deadline_ms"] = deadline
            timers[f"{key}_remaining_ms"] = max(0, int(deadline - now_ms))

        if game_type == int(GameType.WEREWOLF):
            phase_started_ms = int(meta.get("phase_started_ms") or 0)
            speaker_started_ms = int(meta.get("speaker_started_ms") or 0)
            if phase == WerewolfPhase.LOBBY:
                if settings.werewolf_lobby_timeout_seconds > 0:
                    _apply_deadline("phase", phase_started_ms, settings.werewolf_lobby_timeout_seconds)
            elif phase == WerewolfPhase.DAY_DEBATE:
                _apply_deadline("speaker", speaker_started_ms, settings.werewolf_speak_timeout_seconds)
            elif phase == WerewolfPhase.DAY_VOTE:
                _apply_deadline("phase", phase_started_ms, settings.werewolf_vote_timeout_seconds)
            elif phase in {
                WerewolfPhase.WOLF_CHAT,
                WerewolfPhase.WOLF_KILL,
                WerewolfPhase.WITCH,
                WerewolfPhase.SEER,
                WerewolfPhase.GUARD,
            }:
                _apply_deadline("phase", phase_started_ms, settings.werewolf_phase_timeout_seconds)
        elif game_type == int(GameType.TEXAS):
            turn_started_ms = int(meta.get("turn_started_ms") or 0)
            if phase != TexasPhase.FINISHED:
                _apply_deadline("turn", turn_started_ms, settings.texas_action_timeout_seconds)

        return timers
