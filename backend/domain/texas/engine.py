import random
from typing import Any

from pokerkit import Automation, NoLimitTexasHoldem

from backend.config.constants import GameEventType, GameType, TexasAction, TexasPhase
from backend.domain.engine_base import GameEngine
from backend.views.errors import DomainError


class TexasEngine(GameEngine):
    AUTOMATIONS = (
        Automation.ANTE_POSTING,
        Automation.BET_COLLECTION,
        Automation.BLIND_OR_STRADDLE_POSTING,
        Automation.CARD_BURNING,
        Automation.HOLE_DEALING,
        Automation.BOARD_DEALING,
        Automation.HOLE_CARDS_SHOWING_OR_MUCKING,
        Automation.HAND_KILLING,
        Automation.CHIPS_PUSHING,
        Automation.CHIPS_PULLING,
    )

    SMALL_BLIND = 1
    BIG_BLIND = 2
    MIN_BET = 2
    ANTE = 0

    def __init__(self, game_id: int, room_id: int, players: list[dict[str, Any]], seed: int | None = None) -> None:
        super().__init__(game_id, room_id, players, seed)
        self._rng = random.Random(seed)
        self._players_by_id = {int(p["agent_id"]): p for p in players}
        self._seat_order = sorted(players, key=lambda p: p.get("seat", 0))
        self._seat_ids = [int(p["agent_id"]) for p in self._seat_order]
        self._stacks = {int(p["agent_id"]): int(p.get("chips", 1000)) for p in players}
        self._left_players: set[int] = set()
        self._hand_index = 0
        self._hand_seed = self._derive_hand_seed(self._hand_index)
        self._hand_actions: list[dict[str, Any]] = []
        self._end_votes: dict[int, bool] = {}
        self._player_order = self._build_hand_order()
        self._player_ids = [int(p["agent_id"]) for p in self._player_order]
        self._player_index = {agent_id: idx for idx, agent_id in enumerate(self._player_ids)}
        self._state = self._create_state(self._hand_seed)
        self._phase = self._phase_from_state() if self._state else TexasPhase.FINISHED

    @property
    def phase(self) -> str:
        return self._phase

    def get_state(self) -> dict[str, Any]:
        return {
            "phase": self._phase,
            "hand_index": self._hand_index,
            "actor_id": self._actor_id(),
            "board": self._board_cards(),
            "hole_cards": self._hole_cards(),
            "pot": int(self._state.total_pot_amount) if self._state else 0,
            "small_blind": int(self.SMALL_BLIND),
            "big_blind": int(self.BIG_BLIND),
            "stacks": dict(self._stacks),
            "bets": self._bet_map(),
            "statuses": self._status_map(),
            "active_players": list(self._active_ids()),
        }

    def build_view_state(self, viewer_id: int | None, reveal_all: bool = False) -> dict[str, Any]:
        state = self.get_state()
        if reveal_all:
            return state
        hole_cards = state.get("hole_cards", [])
        masked: list[list[str]] = []
        for idx, cards in enumerate(hole_cards):
            agent_id = None
            if idx < len(self._player_ids):
                agent_id = int(self._player_ids[idx])
            if viewer_id is not None and agent_id == int(viewer_id):
                masked.append(cards)
            else:
                masked.append(["??" for _ in cards])
        state["hole_cards"] = masked
        return state

    def build_public_state(self) -> dict[str, Any]:
        state = self.dump_state()
        state["state"] = self.build_view_state(None, reveal_all=False)
        state.pop("seed", None)
        state.pop("hand_seed", None)
        state.pop("hand_actions", None)
        state.pop("end_votes", None)
        return state

    def dump_state(self) -> dict[str, Any]:
        state = self.get_state()
        payload = {
            "game_type": int(GameType.TEXAS),
            "game_id": self.game_id,
            "room_id": self.room_id,
            "seed": self.seed,
            "players": self.players,
            "phase": self._phase,
            "state": state,
            "hand_index": self._hand_index,
            "hand_seed": self._hand_seed,
            "hand_actions": self._hand_actions,
            "stacks": self._stacks,
            "end_votes": self._end_votes,
            "left_players": list(self._left_players),
        }
        if self._phase == TexasPhase.FINISHED:
            payload["winner_ids"] = self._winner_ids()
        return payload

    @classmethod
    def from_state(cls, state: dict[str, Any]) -> "TexasEngine":
        engine = cls(
            int(state.get("game_id", 0)),
            int(state.get("room_id", 0)),
            state.get("players", []),
            seed=state.get("seed"),
        )
        stacks = state.get("stacks")
        if stacks:
            engine._stacks = {int(k): int(v) for k, v in stacks.items()}
        engine._hand_index = int(state.get("hand_index", 0))
        engine._hand_seed = int(state.get("hand_seed", engine._derive_hand_seed(engine._hand_index)))
        engine._hand_actions = list(state.get("hand_actions", []))
        engine._end_votes = {int(k): bool(v) for k, v in (state.get("end_votes") or {}).items()}
        engine._left_players = set(int(v) for v in (state.get("left_players") or []))
        engine._player_order = engine._build_hand_order()
        engine._player_ids = [int(p["agent_id"]) for p in engine._player_order]
        engine._player_index = {agent_id: idx for idx, agent_id in enumerate(engine._player_ids)}
        engine._state = engine._create_state(engine._hand_seed)
        if engine._state:
            engine._replay_actions()
            engine._sync_stacks_from_state()
            engine._phase = engine._phase_from_state()
        else:
            engine._phase = TexasPhase.FINISHED
        return engine

    def validate_action(self, actor_id: int, action: int, payload: dict[str, Any]) -> None:
        if action not in {a.value for a in TexasAction}:
            raise DomainError("invalid_action", code=40023)
        if self._phase == TexasPhase.FINISHED or self._state is None:
            raise DomainError("game_finished", code=40024)
        if actor_id not in self._players_by_id:
            raise DomainError("actor_not_in_game", code=40025)
        if self._stacks.get(actor_id, 0) <= 0:
            raise DomainError("actor_busted", code=40027)

        action_enum = TexasAction(action)
        if action_enum == TexasAction.VOTE_END:
            return

        if self._actor_id() != actor_id:
            raise DomainError("not_actor_turn", code=40026)
        if not self._status_map().get(actor_id):
            raise DomainError("actor_not_active", code=40027)

        if action_enum == TexasAction.FOLD:
            if not self._state.can_fold():
                raise DomainError("cannot_fold", code=40028)
        elif action_enum in {TexasAction.CHECK, TexasAction.CALL}:
            if not self._state.can_check_or_call():
                raise DomainError("cannot_check_or_call", code=40029)
        else:
            amount = payload.get("amount")
            if amount is None:
                raise DomainError("missing_bet_amount", code=40030)
            if not self._state.can_complete_bet_or_raise_to(int(amount)):
                raise DomainError("invalid_bet_amount", code=40031)

    def apply_action(self, actor_id: int, action: int, payload: dict[str, Any]) -> list[dict[str, Any]]:
        self.validate_action(actor_id, action, payload)
        action_enum = TexasAction(action)
        events: list[dict[str, Any]] = []

        if action_enum == TexasAction.VOTE_END:
            agree = bool(payload.get("agree", True)) if payload else True
            self._end_votes[int(actor_id)] = agree
            active = list(self._active_ids())
            yes_count = sum(1 for aid in active if self._end_votes.get(aid))
            total = len(active)
            if yes_count > total // 2:
                self._phase = TexasPhase.FINISHED
                events.append(self._event(actor_id, action_enum.value, {"result": "passed"}))
                events.append(self._phase_event(self._phase_payload({"vote_end": True})))
            return events

        before_phase = self._phase_from_state() if self._state else TexasPhase.FINISHED
        amount = self._apply_turn_action(action_enum, payload)

        entry = {"action_type": action_enum.value, "actor_id": actor_id}
        if amount is not None:
            entry["amount"] = amount
        self._hand_actions.append(entry)

        self._sync_stacks_from_state()
        events.append(self._event(actor_id, action_enum.value, self._event_payload(payload, amount)))

        if self._state and not self._state.status:
            self._handle_hand_end(events)
            return events

        self._phase = self._phase_from_state()
        if self._phase != before_phase:
            events.append(self._phase_event(self._phase_payload()))
        return events

    def apply_leave(self, actor_id: int) -> list[dict[str, Any]]:
        if self._phase == TexasPhase.FINISHED or self._state is None:
            return []
        self._left_players.add(int(actor_id))
        current_actor = self._actor_id()
        if current_actor is not None and int(current_actor) == int(actor_id):
            return self.apply_action(
                int(actor_id),
                int(TexasAction.FOLD),
                {"meta": {"auto": True, "reason": "leave"}},
            )
        return []

    def is_left(self, actor_id: int) -> bool:
        return int(actor_id) in self._left_players

    def _create_state(self, hand_seed: int):
        if len(self._player_ids) < 2:
            return None
        stacks = tuple(int(self._stacks.get(agent_id, 0)) for agent_id in self._player_ids)
        rng_state = random.getstate()
        random.seed(hand_seed)
        try:
            return NoLimitTexasHoldem.create_state(
                self.AUTOMATIONS,
                True,
                self.ANTE,
                (self.SMALL_BLIND, self.BIG_BLIND),
                self.MIN_BET,
                stacks,
                len(stacks),
            )
        finally:
            random.setstate(rng_state)

    def _replay_actions(self) -> None:
        for entry in self._hand_actions:
            actor_id = entry.get("actor_id")
            if actor_id is not None and self._actor_id() != actor_id:
                raise DomainError("action_replay_mismatch", code=50031)
            self._apply_to_state(int(entry.get("action_type", 0)), entry.get("amount"))

    def _apply_to_state(self, action: int, amount: int | None) -> None:
        action_enum = TexasAction(action)
        if action_enum == TexasAction.FOLD:
            if self._state.can_fold():
                self._state.fold()
            return
        if action_enum in {TexasAction.CHECK, TexasAction.CALL}:
            if self._state.can_check_or_call():
                self._state.check_or_call()
            return
        if amount is None:
            raise DomainError("missing_bet_amount", code=50032)
        if self._state.can_complete_bet_or_raise_to(int(amount)):
            self._state.complete_bet_or_raise_to(int(amount))

    def _apply_turn_action(self, action_enum: TexasAction, payload: dict[str, Any]) -> int | None:
        if action_enum == TexasAction.FOLD:
            self._state.fold()
            return None
        if action_enum in {TexasAction.CHECK, TexasAction.CALL}:
            self._state.check_or_call()
            return None
        amount = int(payload.get("amount"))
        self._state.complete_bet_or_raise_to(amount)
        return amount

    def _phase_from_state(self) -> str:
        if not self._state or not self._state.status:
            return TexasPhase.FINISHED
        street = self._state.street_index
        if street is None:
            return TexasPhase.SHOWDOWN
        if street == 0:
            return TexasPhase.PREFLOP
        if street == 1:
            return TexasPhase.FLOP
        if street == 2:
            return TexasPhase.TURN
        if street == 3:
            return TexasPhase.RIVER
        return TexasPhase.SHOWDOWN

    def _derive_hand_seed(self, hand_index: int) -> int:
        base = self.seed if self.seed is not None else self._rng.randint(1, 1_000_000_000)
        return int(base) + int(hand_index)

    def _active_ids(self) -> list[int]:
        return [agent_id for agent_id in self._seat_ids if self._stacks.get(agent_id, 0) > 0]

    def _build_hand_order(self) -> list[dict[str, Any]]:
        active = [agent_id for agent_id in self._seat_ids if self._stacks.get(agent_id, 0) > 0]
        if len(active) < 2:
            return []
        rotate = self._hand_index % len(active)
        ordered_ids = active[rotate:] + active[:rotate]
        return [self._players_by_id[agent_id] for agent_id in ordered_ids]

    def _sync_stacks_from_state(self) -> None:
        if not self._state:
            return
        for idx, agent_id in enumerate(self._player_ids):
            self._stacks[agent_id] = int(self._state.stacks[idx])

    def _handle_hand_end(self, events: list[dict[str, Any]]) -> None:
        self._sync_stacks_from_state()
        active = [agent_id for agent_id in self._active_ids()]
        if len(active) <= 1:
            self._phase = TexasPhase.FINISHED
            events.append(self._phase_event(self._phase_payload({"winner_ids": active})))
            return
        self._hand_index += 1
        self._hand_seed = self._derive_hand_seed(self._hand_index)
        self._hand_actions = []
        self._end_votes = {}
        self._player_order = self._build_hand_order()
        self._player_ids = [int(p["agent_id"]) for p in self._player_order]
        self._player_index = {agent_id: idx for idx, agent_id in enumerate(self._player_ids)}
        self._state = self._create_state(self._hand_seed)
        self._phase = self._phase_from_state() if self._state else TexasPhase.FINISHED
        events.append(self._phase_event(self._phase_payload({"hand_index": self._hand_index})))

    def _actor_id(self) -> int | None:
        if not self._state:
            return None
        index = self._state.actor_index
        if index is None:
            return None
        if index >= len(self._player_ids):
            return None
        return int(self._player_ids[index])

    def _board_cards(self) -> list[str]:
        if not self._state or not self._state.board_cards:
            return []
        board = self._state.board_cards[0] if self._state.board_cards else []
        return [str(card) if card is not None else "??" for card in board]

    def _hole_cards(self) -> list[list[str]]:
        if not self._state:
            return []
        cards: list[list[str]] = []
        for hand in self._state.hole_cards:
            cards.append([str(card) if card is not None else "??" for card in hand])
        return cards

    def _stack_map(self) -> dict[int, int]:
        if not self._state:
            return {agent_id: int(self._stacks.get(agent_id, 0)) for agent_id in self._seat_ids}
        return {agent_id: int(self._state.stacks[idx]) for idx, agent_id in enumerate(self._player_ids)}

    def _bet_map(self) -> dict[int, int]:
        if not self._state:
            return {agent_id: 0 for agent_id in self._seat_ids}
        return {agent_id: int(self._state.bets[idx]) for idx, agent_id in enumerate(self._player_ids)}

    def _status_map(self) -> dict[int, bool]:
        if not self._state:
            return {agent_id: self._stacks.get(agent_id, 0) > 0 for agent_id in self._seat_ids}
        return {agent_id: bool(self._state.statuses[idx]) for idx, agent_id in enumerate(self._player_ids)}

    def _event_payload(self, payload: dict[str, Any], amount: int | None) -> dict[str, Any]:
        result: dict[str, Any] = {}
        msg = payload.get("msg") if payload else None
        if msg:
            result["msg"] = msg
        if amount is not None:
            result["amount"] = int(amount)
        return self._merge_payload(payload, result)

    def _phase_payload(self, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = {
            "phase": self._phase,
            "hand_index": self._hand_index,
            "actor_id": self._actor_id(),
            "board": self._board_cards(),
            "pot": int(self._state.total_pot_amount) if self._state else 0,
            "small_blind": int(self.SMALL_BLIND),
            "big_blind": int(self.BIG_BLIND),
            "stacks": dict(self._stacks),
            "bets": self._bet_map(),
        }
        if self._phase == TexasPhase.FINISHED:
            payload["winner_ids"] = self._winner_ids()
        if extra:
            payload.update(extra)
        return payload

    def _winner_ids(self) -> list[int]:
        if not self._stacks:
            return []
        max_stack = max(self._stacks.values())
        if max_stack is None:
            return []
        return sorted([int(pid) for pid, stack in self._stacks.items() if stack == max_stack])

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
