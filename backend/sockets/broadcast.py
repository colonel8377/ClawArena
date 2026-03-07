from backend.config.settings import get_settings


def room_all(room_id: int) -> str:
    return f"room:all:{room_id}"


def room_members(room_id: int) -> str:
    return f"room:members:{room_id}"


def room_spectators(room_id: int) -> str:
    return f"room:spectators:{room_id}"


async def join_room(server, sid: str, room_id: int, is_spectator: bool) -> None:
    await server.enter_room(sid, room_all(room_id))
    if is_spectator:
        await server.enter_room(sid, room_spectators(room_id))
    else:
        await server.enter_room(sid, room_members(room_id))


async def leave_room(server, sid: str, room_id: int) -> None:
    await server.leave_room(sid, room_all(room_id))
    await server.leave_room(sid, room_members(room_id))
    await server.leave_room(sid, room_spectators(room_id))


async def emit_room_event(server, room_id: int, event: str, payload: dict, private: bool = False) -> None:
    settings = get_settings()
    if private and not settings.private_messages_visible_to_spectators:
        await server.emit(event, payload, room=room_members(room_id))
        return
    await server.emit(event, payload, room=room_all(room_id))
