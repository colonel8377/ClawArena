from __future__ import annotations

from typing import Any, Protocol

from backend.config.constants import (
    WerewolfAction,
    WerewolfNightActionKey,
    WerewolfPhase,
    WerewolfWitchStateKey,
)


class WerewolfEngineLike(Protocol):
    _alive: set[int]
    _ready: set[int]
    _wolf_chat_ready: set[int]
    _votes: dict[int, int]
    _night_actions: dict[str, Any]
    _witch_state: dict[str, bool]

    def _event(self, actor_id: int, action: int, payload: dict[str, Any]) -> dict[str, Any]: ...
    def _phase_event(self, payload: dict[str, Any]) -> dict[str, Any]: ...
    def _phase_payload(self, extra: dict[str, Any] | None = None) -> dict[str, Any]: ...
    def _merge_payload(self, payload: dict[str, Any] | None, base: dict[str, Any] | None = None) -> dict[str, Any]: ...
    def _start_night(self, events: list[dict[str, Any]], is_new_day: bool) -> None: ...
    def _alive_wolves(self) -> set[int]: ...
    def _set_phase(self, phase: WerewolfPhase) -> None: ...
    def _advance_after_night_action(self, events: list[dict[str, Any]], phase: WerewolfPhase) -> None: ...
    def _advance_speaker(self, events: list[dict[str, Any]]) -> None: ...
    def _resolve_day_vote(self, events: list[dict[str, Any]], reason: str | None = None, forced_target_id: int | None = None) -> list[int]: ...


class PhaseHandler:
    phase: WerewolfPhase
    allowed_actions: set[WerewolfAction]

    def apply(self, engine: WerewolfEngineLike, actor_id: int, action: WerewolfAction, payload: dict[str, Any]) -> list[dict[str, Any]]:
        raise NotImplementedError


class LobbyHandler(PhaseHandler):
    phase = WerewolfPhase.LOBBY
    allowed_actions = {WerewolfAction.READY}

    def apply(self, engine: WerewolfEngineLike, actor_id: int, action: WerewolfAction, payload: dict[str, Any]) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        engine._ready.add(actor_id)
        events.append(engine._event(actor_id, action.value, engine._merge_payload(payload)))
        if engine._ready == engine._alive:
            engine._start_night(events, is_new_day=True)
        return events


class WolfChatHandler(PhaseHandler):
    phase = WerewolfPhase.WOLF_CHAT
    allowed_actions = {WerewolfAction.WOLF_CHAT, WerewolfAction.SKIP}

    def apply(self, engine: WerewolfEngineLike, actor_id: int, action: WerewolfAction, payload: dict[str, Any]) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        events.append(engine._event(actor_id, action.value, engine._merge_payload(payload)))
        if action == WerewolfAction.SKIP:
            engine._wolf_chat_ready.add(actor_id)
            if engine._wolf_chat_ready >= engine._alive_wolves():
                engine._set_phase(WerewolfPhase.WOLF_KILL)
                events.append(engine._phase_event(engine._phase_payload()))
        return events


class WolfKillHandler(PhaseHandler):
    phase = WerewolfPhase.WOLF_KILL
    allowed_actions = {WerewolfAction.WOLF_KILL, WerewolfAction.SKIP}

    def apply(self, engine: WerewolfEngineLike, actor_id: int, action: WerewolfAction, payload: dict[str, Any]) -> list[dict[str, Any]]:
        if action == WerewolfAction.WOLF_KILL:
            engine._night_actions[WerewolfNightActionKey.WOLF_KILL] = payload.get("target_id")
        else:
            engine._night_actions[WerewolfNightActionKey.WOLF_KILL] = None
        merged = engine._merge_payload(payload, {"target_id": engine._night_actions[WerewolfNightActionKey.WOLF_KILL]})
        events = [engine._event(actor_id, action.value, merged)]
        engine._advance_after_night_action(events, WerewolfPhase.WOLF_KILL)
        return events


class WitchHandler(PhaseHandler):
    phase = WerewolfPhase.WITCH
    allowed_actions = {WerewolfAction.WITCH_SAVE, WerewolfAction.WITCH_POISON, WerewolfAction.SKIP}

    def apply(self, engine: WerewolfEngineLike, actor_id: int, action: WerewolfAction, payload: dict[str, Any]) -> list[dict[str, Any]]:
        base_payload: dict[str, Any] = {}
        if action == WerewolfAction.WITCH_SAVE:
            engine._night_actions[WerewolfNightActionKey.WITCH_SAVE] = True
            engine._witch_state[WerewolfWitchStateKey.SAVE_USED] = True
        elif action == WerewolfAction.WITCH_POISON:
            engine._night_actions[WerewolfNightActionKey.WITCH_POISON] = payload.get("target_id")
            engine._witch_state[WerewolfWitchStateKey.POISON_USED] = True
            base_payload = {"target_id": engine._night_actions[WerewolfNightActionKey.WITCH_POISON]}
        events = [engine._event(actor_id, action.value, engine._merge_payload(payload, base_payload))]
        engine._advance_after_night_action(events, WerewolfPhase.WITCH)
        return events


class SeerHandler(PhaseHandler):
    phase = WerewolfPhase.SEER
    allowed_actions = {WerewolfAction.SEER_CHECK, WerewolfAction.SKIP}

    def apply(self, engine: WerewolfEngineLike, actor_id: int, action: WerewolfAction, payload: dict[str, Any]) -> list[dict[str, Any]]:
        base_payload: dict[str, Any] = {}
        if action == WerewolfAction.SEER_CHECK:
            engine._night_actions[WerewolfNightActionKey.SEER] = payload.get("target_id")
            base_payload = {"target_id": engine._night_actions[WerewolfNightActionKey.SEER]}
        events = [engine._event(actor_id, action.value, engine._merge_payload(payload, base_payload))]
        engine._advance_after_night_action(events, WerewolfPhase.SEER)
        return events


class GuardHandler(PhaseHandler):
    phase = WerewolfPhase.GUARD
    allowed_actions = {WerewolfAction.GUARD, WerewolfAction.SKIP}

    def apply(self, engine: WerewolfEngineLike, actor_id: int, action: WerewolfAction, payload: dict[str, Any]) -> list[dict[str, Any]]:
        base_payload: dict[str, Any] = {}
        if action == WerewolfAction.GUARD:
            engine._night_actions[WerewolfNightActionKey.GUARD] = payload.get("target_id")
            base_payload = {"target_id": engine._night_actions[WerewolfNightActionKey.GUARD]}
        events = [engine._event(actor_id, action.value, engine._merge_payload(payload, base_payload))]
        engine._advance_after_night_action(events, WerewolfPhase.GUARD)
        return events


class DayDebateHandler(PhaseHandler):
    phase = WerewolfPhase.DAY_DEBATE
    allowed_actions = {WerewolfAction.SPEAK}

    def apply(self, engine: WerewolfEngineLike, actor_id: int, action: WerewolfAction, payload: dict[str, Any]) -> list[dict[str, Any]]:
        events = [engine._event(actor_id, action.value, engine._merge_payload(payload))]
        engine._advance_speaker(events)
        return events


class DayVoteHandler(PhaseHandler):
    phase = WerewolfPhase.DAY_VOTE
    allowed_actions = {WerewolfAction.VOTE}

    def apply(self, engine: WerewolfEngineLike, actor_id: int, action: WerewolfAction, payload: dict[str, Any]) -> list[dict[str, Any]]:
        target_id = payload.get("target_id")
        engine._votes[actor_id] = target_id
        events = [engine._event(actor_id, action.value, engine._merge_payload(payload, {"target_id": target_id}))]
        if len(engine._votes) >= len(engine._alive):
            engine._vote_timeout_count = 0
            engine._resolve_day_vote(events)
        return events


PHASE_HANDLERS: dict[WerewolfPhase, PhaseHandler] = {
    LobbyHandler.phase: LobbyHandler(),
    WolfChatHandler.phase: WolfChatHandler(),
    WolfKillHandler.phase: WolfKillHandler(),
    WitchHandler.phase: WitchHandler(),
    SeerHandler.phase: SeerHandler(),
    GuardHandler.phase: GuardHandler(),
    DayDebateHandler.phase: DayDebateHandler(),
    DayVoteHandler.phase: DayVoteHandler(),
}
