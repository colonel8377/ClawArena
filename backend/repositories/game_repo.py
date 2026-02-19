from sqlalchemy.orm import Session

from backend.models.game import Game
from backend.repositories.db import db_session


class GameRepo:
    @staticmethod
    def get_by_id(game_id: int, session: Session | None = None) -> Game | None:
        with db_session(session) as s:
            return s.get(Game, game_id)

    @staticmethod
    def create(game_type: int, status: int, prize_pool_tokens: int = 0, session: Session | None = None) -> Game:
        with db_session(session) as s:
            game = Game(game_type=game_type, status=status, prize_pool_tokens=prize_pool_tokens)
            s.add(game)
            s.flush()
            return game

    @staticmethod
    def update_status(game_id: int, status: int, ended_at=None, session: Session | None = None) -> Game | None:
        with db_session(session) as s:
            game = s.get(Game, game_id)
            if not game:
                return None
            game.status = status
            if ended_at is not None:
                game.ended_at = ended_at
            s.add(game)
            return game
