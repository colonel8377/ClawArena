"""Factory for Texas engine backend."""

from backend.games.texas.pokerkit_engine import PokerKitTexasEngine


def create_texas_engine(*, game_id: str, small_blind: int, big_blind: int):
    return PokerKitTexasEngine(
        game_id=game_id,
        small_blind=small_blind,
        big_blind=big_blind,
    )


def restore_texas_engine(data):
    return PokerKitTexasEngine.from_dict(data or {})
