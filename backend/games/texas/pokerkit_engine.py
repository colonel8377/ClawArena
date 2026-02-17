"""PokerKit-backed Texas engine adapter."""

from typing import Any, Dict, Optional

from backend.games.texas.texas_engine import TexasEngine


class PokerKitTexasEngine:
    """
    Texas engine contract adapter.

    This adapter currently delegates to the legacy engine while exposing a
    stable contract for TexasGame/TexasService. It is intentionally explicit
    (instead of using __getattr__) so a native PokerKit core can replace each
    method/property without touching callers.
    """

    backend_name = "pokerkit"

    def __init__(self, *, game_id: str, small_blind: int, big_blind: int):
        self._engine = TexasEngine(
            game_id=game_id,
            small_blind=small_blind,
            big_blind=big_blind,
        )

    @property
    def phase(self):
        return self._engine.phase

    @property
    def players(self):
        return self._engine.players

    @property
    def player_order(self):
        return self._engine.player_order

    @property
    def current_player_sid(self):
        return self._engine.current_player_sid

    @property
    def current_bet(self):
        return self._engine.current_bet

    @property
    def last_raise_amount(self):
        return self._engine.last_raise_amount

    @property
    def community_cards(self):
        return self._engine.community_cards

    @property
    def chat_history(self):
        return self._engine.chat_history

    @property
    def hand_number(self):
        return self._engine.hand_number

    @property
    def turn_started_at(self):
        return self._engine.turn_started_at

    @property
    def CHAT_ALLOWED_PHASES(self):
        return self._engine.CHAT_ALLOWED_PHASES

    @property
    def last_hand_winners(self):
        return self._engine.last_hand_winners

    def add_player(self, sid: str, player_id: str, nickname: str, buy_in: int) -> bool:
        return self._engine.add_player(sid=sid, player_id=player_id, nickname=nickname, buy_in=buy_in)

    def remove_player(self, sid: str) -> bool:
        return self._engine.remove_player(sid)

    def can_start(self) -> bool:
        return self._engine.can_start()

    def start_hand(self) -> Dict[str, Any]:
        return self._engine.start_hand()

    def process_move(self, sid: str, action: str, **kwargs) -> Dict[str, Any]:
        return self._engine.process_move(sid, action, **kwargs)

    def get_game_state(
        self,
        sid: Optional[str],
        for_spectator: bool = False,
        reveal_all: bool = False,
    ) -> Dict[str, Any]:
        return self._engine.get_game_state(
            sid,
            for_spectator=for_spectator,
            reveal_all=reveal_all,
        )

    def get_total_pot(self) -> int:
        return self._engine.get_total_pot()

    def cards_to_strings(self, cards) -> list[str]:
        return self._engine.cards_to_strings(cards)

    def get_turn_time_remaining(self) -> int:
        return self._engine.get_turn_time_remaining()

    def is_hand_over(self) -> bool:
        return self._engine.is_hand_over()

    def handle_timeout(self, sid: str) -> Dict[str, Any]:
        return self._engine.handle_timeout(sid)

    def advance_phase(self) -> Dict[str, Any]:
        return self._engine.advance_phase()

    def get_all_hole_cards(self):
        return self._engine.get_all_hole_cards()

    def update_player_sid(self, old_sid: str, new_sid: str):
        return self._engine.update_player_sid(old_sid, new_sid)

    def to_dict(self) -> Dict[str, Any]:
        return self._engine.to_dict()

    @classmethod
    def from_dict(cls, data):
        game_id = data.get("game_id", "restored_table")
        small_blind = int(data.get("small_blind", 10) or 10)
        big_blind = int(data.get("big_blind", 20) or 20)
        adapter = cls(
            game_id=game_id,
            small_blind=small_blind,
            big_blind=big_blind,
        )
        adapter._engine = TexasEngine.from_dict(data)
        return adapter
