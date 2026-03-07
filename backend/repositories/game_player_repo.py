from sqlalchemy.orm import Session
from sqlalchemy import case, func

from backend.models.game_player import GamePlayer
from backend.repositories.db import db_session
from backend.models.game import Game
from backend.config.constants import GameStatus


class GamePlayerRepo:
    @staticmethod
    def create_many(game_id: int, room_id: int, players: list[dict], session: Session | None = None) -> None:
        with db_session(session) as s:
            for player in players:
                s.add(
                    GamePlayer(
                        game_id=game_id,
                        room_id=room_id,
                        agent_id=player["agent_id"],
                        agent_name=player["agent_name"],
                        seat=player["seat"],
                        status=player["status"],
                        result=player.get("result", 0),
                        role_id=player.get("role_id"),
                        chips=player.get("chips", 0),
                    )
                )

    @staticmethod
    def update_chips(game_id: int, agent_id: int, chips: int, session: Session | None = None) -> None:
        with db_session(session) as s:
            player = s.query(GamePlayer).filter_by(game_id=game_id, agent_id=agent_id).first()
            if not player:
                return
            player.chips = chips
            s.add(player)

    @staticmethod
    def update_status_and_result(game_id: int, agent_id: int, status: int, result: int | None = None) -> None:
        with db_session() as session:
            player = session.query(GamePlayer).filter_by(game_id=game_id, agent_id=agent_id).first()
            if not player:
                return
            player.status = status
            if result is not None:
                player.result = result
            session.add(player)

    @staticmethod
    def update_results(game_id: int, results: dict[int, int], session: Session | None = None) -> None:
        if not results:
            return
        with db_session(session) as s:
            for agent_id, result in results.items():
                player = s.query(GamePlayer).filter_by(game_id=game_id, agent_id=agent_id).first()
                if not player:
                    continue
                player.result = int(result)
                s.add(player)

    @staticmethod
    def list_by_game(game_id: int, session: Session | None = None) -> list[GamePlayer]:
        with db_session(session) as s:
            return list(s.query(GamePlayer).filter_by(game_id=game_id).all())

    @staticmethod
    def list_history(agent_id: int, limit: int, offset: int) -> list[dict]:
        with db_session() as session:
            query = (
                session.query(GamePlayer, Game)
                .join(Game, Game.id == GamePlayer.game_id)
                .filter(GamePlayer.agent_id == agent_id)
                .filter(Game.status == int(GameStatus.ENDED))
                .order_by(GamePlayer.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
            items: list[dict] = []
            for player, game in query.all():
                items.append(
                    {
                        "game_id": int(player.game_id),
                        "room_id": int(player.room_id),
                        "game_type": int(game.game_type),
                        "result": int(player.result),
                        "created_at": player.created_at.isoformat() if player.created_at else None,
                        "ended_at": game.ended_at.isoformat() if game.ended_at else None,
                    }
                )
            return items

    @staticmethod
    def list_recent(agent_id: int, limit: int) -> list[dict]:
        with db_session() as session:
            query = (
                session.query(GamePlayer, Game)
                .join(Game, Game.id == GamePlayer.game_id)
                .filter(GamePlayer.agent_id == agent_id)
                .filter(Game.status == int(GameStatus.ENDED))
                .order_by(Game.ended_at.desc(), GamePlayer.created_at.desc())
                .limit(limit)
            )
            items: list[dict] = []
            for player, game in query.all():
                items.append(
                    {
                        "game_id": int(player.game_id),
                        "room_id": int(player.room_id),
                        "game_type": int(game.game_type),
                        "result": int(player.result),
                        "ended_at": game.ended_at.isoformat() if game.ended_at else None,
                    }
                )
            return items

    @staticmethod
    def get_stats(agent_id: int) -> dict:
        with db_session() as session:
            wins = func.sum(case((GamePlayer.result == 1, 1), else_=0))
            losses = func.sum(case((GamePlayer.result == 2, 1), else_=0))
            query = (
                session.query(wins.label("wins"), losses.label("losses"))
                .join(Game, Game.id == GamePlayer.game_id)
                .filter(GamePlayer.agent_id == agent_id)
                .filter(Game.status == int(GameStatus.ENDED))
            )
            row = query.one()
            return {"wins": int(row.wins or 0), "losses": int(row.losses or 0)}
