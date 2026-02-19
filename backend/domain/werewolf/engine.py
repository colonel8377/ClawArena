import random
from typing import Any

from backend.config.constants import (
    GameEventType,
    GameType,
    WerewolfAction,
    WerewolfNightActionKey,
    WerewolfPhase,
    WerewolfRole,
    WerewolfWitchStateKey,
    WerewolfWinner,
)
from backend.domain.engine_base import GameEngine
from backend.domain.werewolf.phase_handlers import PHASE_HANDLERS
from backend.domain.werewolf.rules import get_roles_by_player_count, ROLE_LABELS
from backend.views.errors import DomainError


class WerewolfEngine(GameEngine):
    PHASE_FLOW = [
        WerewolfPhase.LOBBY,
        WerewolfPhase.WOLF_CHAT,
        WerewolfPhase.WOLF_KILL,
        WerewolfPhase.WITCH,
        WerewolfPhase.SEER,
        WerewolfPhase.GUARD,
        WerewolfPhase.DAY_ANNOUNCE,
        WerewolfPhase.DAY_DEBATE,
        WerewolfPhase.DAY_VOTE,
        WerewolfPhase.DAY_RESOLVE,
    ]

    def __init__(self, game_id: int, room_id: int, players: list[dict[str, Any]], seed: int | None = None) -> None:
        super().__init__(game_id, room_id, players, seed)
        self._rng = random.Random(seed)
        self._phase = WerewolfPhase.LOBBY
        self._phase_index = 0
        self._day = 0
        self._alive = {p["agent_id"] for p in players}
        self._roles = self._assign_roles(players)
        self._ready: set[int] = set()
        self._wolf_chat_ready: set[int] = set()
        self._speech_order: list[int] = []
        self._current_speaker: int | None = None
        self._speaker_index: int = 0
        self._votes: dict[int, int] = {}
        self._vote_timeout_count: int = 0
        self._night_actions: dict[str, Any] = {
            WerewolfNightActionKey.WOLF_KILL: None,
            WerewolfNightActionKey.GUARD: None,
            WerewolfNightActionKey.SEER: None,
            WerewolfNightActionKey.WITCH_SAVE: False,
            WerewolfNightActionKey.WITCH_POISON: None,
        }
        self._witch_state: dict[str, bool] = {
            WerewolfWitchStateKey.SAVE_USED: False,
            WerewolfWitchStateKey.POISON_USED: False,
        }
        self._winner: str | None = None

    @property
    def phase(self) -> str:
        return self._phase

    def get_state(self) -> dict[str, Any]:
        return {
            "day": self._day,
            "phase": self._phase,
            "alive": list(self._alive),
            "roles": self._roles,
            "speech_order": self._speech_order,
            "current_speaker": self._current_speaker,
            "winner": self._winner,
        }

    def build_public_state(self) -> dict[str, Any]:
        state = self.dump_state()
        state.pop("seed", None)
        state.pop("night_actions", None)
        state.pop("witch_state", None)
        state.pop("votes", None)
        state.pop("ready", None)
        state.pop("wolf_chat_ready", None)
        masked_roles: dict[int, dict[str, Any]] = {}
        for agent_id in self._roles.keys():
            masked_roles[int(agent_id)] = {"role": 0, "label": "unknown"}
        state["roles"] = masked_roles
        return state

    def build_view_state(self, viewer_id: int | None, reveal_all: bool = False) -> dict[str, Any]:
        if reveal_all:
            return self.dump_state()
        state = self.build_public_state()
        if self._phase == WerewolfPhase.FINISHED or self._winner:
            full_roles: dict[int, dict[str, Any]] = {}
            for agent_id, role_info in self._roles.items():
                full_roles[int(agent_id)] = role_info
            state["roles"] = full_roles
            return state
        if viewer_id is None:
            return state
        role_info = self._roles.get(int(viewer_id))
        if role_info:
            state.setdefault("roles", {})[int(viewer_id)] = role_info
        return state

    def dump_state(self) -> dict[str, Any]:
        return {
            "game_type": int(GameType.WEREWOLF),
            "game_id": self.game_id,
            "room_id": self.room_id,
            "seed": self.seed,
            "players": self.players,
            "phase": self._phase,
            "phase_index": self._phase_index,
            "day": self._day,
            "alive": list(self._alive),
            "roles": self._roles,
            "ready": list(self._ready),
            "wolf_chat_ready": list(self._wolf_chat_ready),
            "speech_order": self._speech_order,
            "current_speaker": self._current_speaker,
            "speaker_index": self._speaker_index,
            "votes": self._votes,
            "vote_timeout_count": self._vote_timeout_count,
            "night_actions": self._night_actions,
            "witch_state": self._witch_state,
            "winner": self._winner,
        }

    @classmethod
    def from_state(cls, state: dict[str, Any]) -> "WerewolfEngine":
        engine = cls(
            int(state.get("game_id", 0)),
            int(state.get("room_id", 0)),
            state.get("players", []),
            seed=state.get("seed"),
        )
        phase = state.get("phase", WerewolfPhase.LOBBY)
        engine._phase = WerewolfPhase(phase) if not isinstance(phase, WerewolfPhase) else phase
        engine._phase_index = int(state.get("phase_index", 0))
        engine._day = int(state.get("day", 0))
        engine._alive = set(state.get("alive", []))
        roles = state.get("roles", {})
        engine._roles = {int(k): v for k, v in roles.items()}
        engine._ready = set(state.get("ready", []))
        engine._wolf_chat_ready = set(state.get("wolf_chat_ready", []))
        engine._speech_order = state.get("speech_order", [])
        engine._current_speaker = state.get("current_speaker")
        engine._speaker_index = int(state.get("speaker_index", 0))
        votes = state.get("votes", {})
        engine._votes = {int(k): int(v) for k, v in votes.items()} if isinstance(votes, dict) else {}
        engine._vote_timeout_count = int(state.get("vote_timeout_count", 0))
        engine._night_actions = state.get("night_actions", {}) or {
            WerewolfNightActionKey.WOLF_KILL: None,
            WerewolfNightActionKey.GUARD: None,
            WerewolfNightActionKey.SEER: None,
            WerewolfNightActionKey.WITCH_SAVE: False,
            WerewolfNightActionKey.WITCH_POISON: None,
        }
        engine._witch_state = state.get(
            "witch_state",
            {WerewolfWitchStateKey.SAVE_USED: False, WerewolfWitchStateKey.POISON_USED: False},
        )
        engine._winner = state.get("winner")
        return engine

    def validate_action(self, actor_id: int, action: int, payload: dict[str, Any]) -> None:
        if self._phase == WerewolfPhase.FINISHED:
            raise DomainError("game_finished", code=40018)
        if actor_id not in self._alive:
            raise DomainError("actor_not_alive", code=40011)
        if action not in {a.value for a in WerewolfAction}:
            raise DomainError("invalid_action", code=40012)

        action_enum = WerewolfAction(action)
        handler = PHASE_HANDLERS.get(self._phase)
        allowed_actions = handler.allowed_actions if handler else set()
        if action_enum not in allowed_actions:
            raise DomainError("invalid_phase_action", code=40013)

        if self._phase == WerewolfPhase.WOLF_CHAT and action_enum == WerewolfAction.SKIP:
            self._require_role(actor_id, WerewolfRole.WEREWOLF)
        if self._phase == WerewolfPhase.WOLF_KILL and action_enum == WerewolfAction.SKIP:
            self._require_role(actor_id, WerewolfRole.WEREWOLF)

        self._validate_role(actor_id, action_enum)
        self._validate_payload(actor_id, action_enum, payload)

    def apply_action(self, actor_id: int, action: int, payload: dict[str, Any]) -> list[dict[str, Any]]:
        self.validate_action(actor_id, action, payload)
        action_enum = WerewolfAction(action)
        handler = PHASE_HANDLERS.get(self._phase)
        if not handler:
            raise DomainError("invalid_phase_action", code=40013)
        return handler.apply(self, actor_id, action_enum, payload)

    def apply_leave(self, actor_id: int) -> list[dict[str, Any]]:
        events = self.apply_offline_death(actor_id)
        if not events:
            return []
        for event in events:
            payload = event.get("payload")
            if isinstance(payload, dict) and "reason" not in payload:
                payload["reason"] = "leave"
                event["payload"] = payload
        return events

    def next_phase(self) -> str:
        if self._phase_index < len(self.PHASE_FLOW) - 1:
            self._phase_index += 1
            self._phase = self.PHASE_FLOW[self._phase_index]
        return self._phase

    def build_speech_order(self, seats: list[int], start_index: int = 0) -> list[int]:
        if not seats:
            return []
        start_index = max(0, min(start_index, len(seats) - 1))
        return seats[start_index:] + seats[:start_index]

    def _assign_roles(self, players: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
        roles = get_roles_by_player_count(len(players))
        if not roles or len(roles) != len(players):
            raise DomainError("invalid_player_count", code=40015)
        self._rng.shuffle(roles)
        role_map: dict[int, dict[str, Any]] = {}
        for player, role in zip(players, roles, strict=True):
            role_map[player["agent_id"]] = {"role": int(role), "label": ROLE_LABELS[role]}
        return role_map

    def _validate_role(self, actor_id: int, action: WerewolfAction) -> None:
        if action in {WerewolfAction.WOLF_CHAT, WerewolfAction.WOLF_KILL}:
            self._require_role(actor_id, WerewolfRole.WEREWOLF)
        if action == WerewolfAction.SEER_CHECK:
            self._require_role(actor_id, WerewolfRole.SEER)
        if action in {WerewolfAction.WITCH_SAVE, WerewolfAction.WITCH_POISON}:
            self._require_role(actor_id, WerewolfRole.WITCH)
        if action == WerewolfAction.GUARD:
            self._require_role(actor_id, WerewolfRole.GUARD)

    def _validate_payload(self, actor_id: int, action: WerewolfAction, payload: dict[str, Any]) -> None:
        if action == WerewolfAction.SPEAK:
            if self._current_speaker != actor_id:
                raise DomainError("invalid_speaker_turn", code=40019)
        if action == WerewolfAction.VOTE:
            target_id = payload.get("target_id")
            if not target_id or target_id not in self._alive:
                raise DomainError("invalid_vote_target", code=40014)
            if actor_id in self._votes:
                raise DomainError("already_voted", code=40020)
        if action == WerewolfAction.WOLF_KILL:
            target_id = payload.get("target_id")
            if not target_id or target_id not in self._alive:
                raise DomainError("invalid_kill_target", code=40021)
        if action == WerewolfAction.SEER_CHECK:
            target_id = payload.get("target_id")
            if not target_id or target_id not in self._alive:
                raise DomainError("invalid_seer_target", code=40022)
        if action == WerewolfAction.GUARD:
            target_id = payload.get("target_id")
            if not target_id or target_id not in self._alive:
                raise DomainError("invalid_guard_target", code=40023)
        if action == WerewolfAction.WITCH_SAVE:
            if self._witch_state.get(WerewolfWitchStateKey.SAVE_USED):
                raise DomainError("witch_save_used", code=40024)
            if not self._night_actions.get(WerewolfNightActionKey.WOLF_KILL):
                raise DomainError("witch_save_invalid", code=40025)
        if action == WerewolfAction.WITCH_POISON:
            if self._witch_state.get(WerewolfWitchStateKey.POISON_USED):
                raise DomainError("witch_poison_used", code=40026)
            target_id = payload.get("target_id")
            if not target_id or target_id not in self._alive:
                raise DomainError("invalid_poison_target", code=40027)

    def _require_role(self, actor_id: int, role: WerewolfRole) -> None:
        assigned = self._roles.get(actor_id, {}).get("role")
        if assigned != int(role):
            raise DomainError("invalid_role_action", code=40016)

    def _alive_wolves(self) -> set[int]:
        return {agent_id for agent_id in self._alive if self._roles.get(agent_id, {}).get("role") == int(WerewolfRole.WEREWOLF)}

    def _set_phase(self, phase: WerewolfPhase) -> None:
        self._phase = phase
        if phase in self.PHASE_FLOW:
            self._phase_index = self.PHASE_FLOW.index(phase)
        if phase == WerewolfPhase.WOLF_CHAT:
            self._wolf_chat_ready = set()
            self._night_actions = {
                WerewolfNightActionKey.WOLF_KILL: None,
                WerewolfNightActionKey.GUARD: None,
                WerewolfNightActionKey.SEER: None,
                WerewolfNightActionKey.WITCH_SAVE: False,
                WerewolfNightActionKey.WITCH_POISON: None,
            }
        if phase == WerewolfPhase.DAY_DEBATE:
            self._build_speech_order()
        if phase == WerewolfPhase.DAY_VOTE:
            self._votes = {}

    def _build_speech_order(self) -> None:
        seat_map = {p["agent_id"]: p.get("seat", 0) for p in self.players}
        ordered = sorted(self._alive, key=lambda aid: seat_map.get(aid, 0))
        self._speech_order = ordered
        self._speaker_index = 0
        self._current_speaker = ordered[0] if ordered else None

    def _start_night(self, events: list[dict[str, Any]], is_new_day: bool) -> None:
        if is_new_day:
            self._day = 1 if self._day <= 0 else self._day + 1
        self._set_phase(WerewolfPhase.WOLF_CHAT)
        events.append(self._phase_event(self._phase_payload()))

    def _advance_after_night_action(self, events: list[dict[str, Any]], phase: WerewolfPhase) -> None:
        next_phase = self._next_night_phase(phase)
        if next_phase == WerewolfPhase.DAY_ANNOUNCE:
            self._enter_day(events)
            return
        self._set_phase(next_phase)
        events.append(self._phase_event(self._phase_payload()))

    def _next_night_phase(self, current_phase: WerewolfPhase) -> WerewolfPhase:
        night_order = [WerewolfPhase.WITCH, WerewolfPhase.SEER, WerewolfPhase.GUARD]
        start_index = -1
        if current_phase in night_order:
            start_index = night_order.index(current_phase)
        for phase in night_order[start_index + 1 :]:
            if self._role_alive_for_phase(phase):
                return phase
        return WerewolfPhase.DAY_ANNOUNCE

    def _role_alive_for_phase(self, phase: WerewolfPhase) -> bool:
        role_map = {
            WerewolfPhase.WITCH: WerewolfRole.WITCH,
            WerewolfPhase.SEER: WerewolfRole.SEER,
            WerewolfPhase.GUARD: WerewolfRole.GUARD,
        }
        role = role_map.get(phase)
        if not role:
            return True
        return any(self._roles.get(agent_id, {}).get("role") == int(role) for agent_id in self._alive)

    def _enter_day(self, events: list[dict[str, Any]]) -> None:
        deaths = self._resolve_night()
        winner = self._check_winner()
        self._set_phase(WerewolfPhase.DAY_ANNOUNCE)
        events.append(self._phase_event(self._phase_payload({"deaths": deaths})))
        if winner:
            self._winner = winner
            self._set_phase(WerewolfPhase.FINISHED)
            events.append(self._phase_event(self._phase_payload({"winner": winner})))
            return
        self._set_phase(WerewolfPhase.DAY_DEBATE)
        events.append(
            self._phase_event(
                self._phase_payload(
                    {"speech_order": self._speech_order, "current_speaker": self._current_speaker}
                )
            )
        )

    def _resolve_night(self) -> list[int]:
        deaths: list[int] = []
        wolf_target = self._night_actions.get(WerewolfNightActionKey.WOLF_KILL)
        guard_target = self._night_actions.get(WerewolfNightActionKey.GUARD)
        witch_save = bool(self._night_actions.get(WerewolfNightActionKey.WITCH_SAVE))
        poison_target = self._night_actions.get(WerewolfNightActionKey.WITCH_POISON)

        if wolf_target and wolf_target in self._alive:
            if guard_target != wolf_target and not witch_save:
                deaths.append(int(wolf_target))
        if poison_target and poison_target in self._alive:
            deaths.append(int(poison_target))

        unique_deaths = []
        for target in deaths:
            if target not in unique_deaths:
                unique_deaths.append(target)
        for target in unique_deaths:
            self._alive.discard(target)
        return unique_deaths

    def _advance_speaker(self, events: list[dict[str, Any]]) -> None:
        if not self._speech_order:
            self._set_phase(WerewolfPhase.DAY_VOTE)
            events.append(self._phase_event(self._phase_payload()))
            return
        self._speaker_index += 1
        if self._speaker_index >= len(self._speech_order):
            self._set_phase(WerewolfPhase.DAY_VOTE)
            events.append(self._phase_event(self._phase_payload()))
            return
        self._current_speaker = self._speech_order[self._speaker_index]
        events.append(
            self._phase_event(
                self._phase_payload({"current_speaker": self._current_speaker, "speech_order": self._speech_order})
            )
        )

    def _resolve_day_vote(
        self,
        events: list[dict[str, Any]],
        reason: str | None = None,
        forced_target_id: int | None = None,
    ) -> list[int]:
        counts: dict[int, int] = {}
        for target in self._votes.values():
            if target in self._alive:
                counts[target] = counts.get(target, 0) + 1
        eliminated: list[int] = []
        forced = False
        if forced_target_id and forced_target_id in self._alive:
            eliminated = [int(forced_target_id)]
            forced = True
        elif counts:
            max_votes = max(counts.values())
            top = [t for t, c in counts.items() if c == max_votes]
            eliminated = [top[0]] if len(top) == 1 else []

        for target in eliminated:
            self._alive.discard(target)

        self._set_phase(WerewolfPhase.DAY_RESOLVE)
        payload: dict[str, Any] = {"eliminated": eliminated, "vote_counts": counts}
        if reason:
            payload["reason"] = reason
        if forced:
            payload["forced"] = True
        events.append(self._phase_event(self._phase_payload(payload)))
        if eliminated:
            self._vote_timeout_count = 0
        winner = self._check_winner()
        if winner:
            self._winner = winner
            self._set_phase(WerewolfPhase.FINISHED)
            events.append(self._phase_event(self._phase_payload({"winner": winner})))
            return eliminated
        self._start_night(events, is_new_day=True)
        return eliminated

    def apply_offline_death(self, agent_id: int) -> list[dict[str, Any]]:
        if self._phase == WerewolfPhase.FINISHED:
            return []
        if agent_id not in self._alive:
            return []

        self._alive.discard(agent_id)
        self._ready.discard(agent_id)
        self._wolf_chat_ready.discard(agent_id)
        self._votes.pop(agent_id, None)

        if agent_id in self._speech_order:
            idx = self._speech_order.index(agent_id)
            self._speech_order.pop(idx)
            if idx <= self._speaker_index and self._speaker_index > 0:
                self._speaker_index -= 1

        if self._speech_order:
            if self._speaker_index >= len(self._speech_order):
                self._speaker_index = len(self._speech_order) - 1
            self._current_speaker = self._speech_order[self._speaker_index]
        else:
            self._current_speaker = None

        extra = {"offline_deaths": [agent_id]}
        if self._phase == WerewolfPhase.DAY_DEBATE:
            extra.update({"speech_order": self._speech_order, "current_speaker": self._current_speaker})

        events: list[dict[str, Any]] = [self._phase_event(self._phase_payload(extra))]

        winner = self._check_winner()
        if winner:
            self._winner = winner
            self._set_phase(WerewolfPhase.FINISHED)
            events.append(self._phase_event(self._phase_payload({"winner": winner})))
            return events

        if self._phase == WerewolfPhase.DAY_DEBATE and not self._speech_order:
            self._set_phase(WerewolfPhase.DAY_VOTE)
            events.append(self._phase_event(self._phase_payload()))

        if self._phase == WerewolfPhase.DAY_VOTE and len(self._votes) >= len(self._alive):
            self._resolve_day_vote(events)
            return events

        if self._phase == WerewolfPhase.WOLF_CHAT and self._wolf_chat_ready >= self._alive_wolves():
            self._set_phase(WerewolfPhase.WOLF_KILL)
            events.append(self._phase_event(self._phase_payload()))

        return events

    def apply_speaker_timeout(self) -> list[dict[str, Any]]:
        if self._phase != WerewolfPhase.DAY_DEBATE or not self._current_speaker:
            return []
        payload = {"msg": "", "meta": {"auto": True, "reason": "timeout"}}
        return self.apply_action(int(self._current_speaker), int(WerewolfAction.SPEAK), payload)

    def apply_vote_timeout(self, max_idle_rounds: int | None = None) -> list[dict[str, Any]]:
        if self._phase != WerewolfPhase.DAY_VOTE:
            return []
        self._vote_timeout_count += 1
        forced_target = None
        if max_idle_rounds and self._vote_timeout_count >= max_idle_rounds:
            forced_target = self._select_timeout_elimination()
        events: list[dict[str, Any]] = []
        self._resolve_day_vote(events, reason="timeout", forced_target_id=forced_target)
        return events

    def apply_phase_timeout(self) -> list[dict[str, Any]]:
        if self._phase == WerewolfPhase.WOLF_CHAT:
            self._wolf_chat_ready = self._alive_wolves()
            self._set_phase(WerewolfPhase.WOLF_KILL)
            return [self._phase_event(self._phase_payload({"reason": "timeout"}))]
        if self._phase in {WerewolfPhase.WOLF_KILL, WerewolfPhase.WITCH, WerewolfPhase.SEER, WerewolfPhase.GUARD}:
            actor_id = self._actor_for_phase()
            if actor_id is None:
                events: list[dict[str, Any]] = []
                self._advance_after_night_action(events, self._phase)
                return events
            return self.apply_action(
                int(actor_id),
                int(WerewolfAction.SKIP),
                {"meta": {"auto": True, "reason": "timeout"}},
            )
        return []

    def _check_winner(self) -> str | None:
        wolves = self._alive_wolves()
        if not wolves:
            return WerewolfWinner.VILLAGERS
        if len(wolves) >= (len(self._alive) - len(wolves)):
            return WerewolfWinner.WOLVES
        return None

    def _actor_for_phase(self) -> int | None:
        if self._phase in {WerewolfPhase.WOLF_CHAT, WerewolfPhase.WOLF_KILL}:
            return self._any_actor_with_role(WerewolfRole.WEREWOLF)
        if self._phase == WerewolfPhase.WITCH:
            return self._any_actor_with_role(WerewolfRole.WITCH)
        if self._phase == WerewolfPhase.SEER:
            return self._any_actor_with_role(WerewolfRole.SEER)
        if self._phase == WerewolfPhase.GUARD:
            return self._any_actor_with_role(WerewolfRole.GUARD)
        return None

    def _any_actor_with_role(self, role: WerewolfRole) -> int | None:
        for agent_id in self._alive:
            if self._roles.get(agent_id, {}).get("role") == int(role):
                return int(agent_id)
        return None

    def _select_timeout_elimination(self) -> int | None:
        if not self._alive:
            return None
        seat_map = {p["agent_id"]: p.get("seat", 0) for p in self.players}
        ordered = sorted(self._alive, key=lambda aid: seat_map.get(aid, 0))
        return int(ordered[0]) if ordered else None

    def _merge_payload(self, payload: dict[str, Any] | None, base: dict[str, Any] | None = None) -> dict[str, Any]:
        result = dict(base or {})
        if payload:
            for key, value in payload.items():
                if key not in result:
                    result[key] = value
        return self._normalize_payload(result)

    def _normalize_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        result = dict(payload or {})
        meta = dict(result.get("meta") or {})
        if "auto" in result:
            meta.setdefault("auto", bool(result.get("auto")))
        if "reason" in result:
            meta.setdefault("reason", result.get("reason"))
        if meta:
            result["meta"] = meta
        return result

    def _phase_payload(self, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = {
            "phase": self._phase,
            "day": self._day,
            "alive": list(self._alive),
        }
        if extra:
            payload.update(extra)
        return payload

    def _event(self, actor_id: int, action: int, payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "game_id": self.game_id,
            "room_id": self.room_id,
            "actor_id": actor_id,
            "phase": self._phase,
            "action_type": action,
            "payload": payload,
        }

    def _phase_event(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "game_id": self.game_id,
            "room_id": self.room_id,
            "phase": self._phase,
            "event_type": GameEventType.PHASE_CHANGE,
            "payload": payload,
        }
