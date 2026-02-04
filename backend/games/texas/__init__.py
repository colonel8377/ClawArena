from .texas_game import TexasGame
from .poker_engine import PokerEngine, create_poker_game


def create_texas_game(game_id: str = None, small_blind: int = 25, big_blind: int = 50) -> TexasGame:
    """
    Create a new Texas Hold'em game instance using the unified BaseGame architecture.
    
    Args:
        game_id: Optional custom game ID (auto-generated if not provided)
        small_blind: Small blind amount
        big_blind: Big blind amount
        
    Returns:
        New TexasGame instance
    """
    import uuid
    if game_id is None:
        game_id = f"poker_{uuid.uuid4().hex[:12]}"
    
    return TexasGame(
        game_id=game_id,
        small_blind=small_blind,
        big_blind=big_blind
    )


__all__ = ['TexasGame', 'PokerEngine', 'create_poker_game', 'create_texas_game']
