from datetime import datetime

from sqlalchemy import update
from sqlalchemy.orm import Session

from backend.repositories.db import db_session
from backend.models.room import GameRoom


class RoomRepo:
    @staticmethod
    def get_by_id(room_id: int, session: Session | None = None) -> GameRoom | None:
        with db_session(session) as s:
            return s.get(GameRoom, room_id)

    @staticmethod
    def create(game_id: int, min_players: int, max_players: int, room_state: int, session: Session | None = None) -> GameRoom:
        with db_session(session) as s:
            room = GameRoom(
                game_id=game_id,
                min_players=min_players,
                max_players=max_players,
                room_state=room_state,
            )
            s.add(room)
            s.flush()
            return room

    @staticmethod
    def update_state(
        room_id: int, room_state: int, ended_at: datetime | None = None, session: Session | None = None
    ) -> GameRoom | None:
        with db_session(session) as s:
            room = s.get(GameRoom, room_id)
            if not room:
                return None
            room.room_state = room_state
            if ended_at is not None:
                room.ended_at = ended_at
            s.add(room)
            return room

    @staticmethod
    def attach_game(
        room_id: int,
        game_id: int,
        room_state: int | None = None,
        expected_state: int | None = None,
        session: Session | None = None,
    ) -> GameRoom | None:
        with db_session(session) as s:
            if expected_state is not None:
                values = {"game_id": game_id}
                if room_state is not None:
                    values["room_state"] = room_state
                result = s.execute(
                    update(GameRoom)
                    .where(GameRoom.id == room_id, GameRoom.room_state == expected_state)
                    .values(**values)
                )
                if result.rowcount != 1:
                    return None
                return s.get(GameRoom, room_id)

            room = s.get(GameRoom, room_id)
            if not room:
                return None
            room.game_id = game_id
            if room_state is not None:
                room.room_state = room_state
            s.add(room)
            return room
