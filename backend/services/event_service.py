import json
import time
import uuid

from backend.config.constants import ChatChannel, GameEventType, GameType, SocketEvent
from backend.config.settings import get_settings
from backend.repositories.kset.room_repo import RoomCache
from backend.repositories.redis_client import get_client
from backend.repositories.redis_repo import RedisRepo
from backend.services.chat_history_service import ChatHistoryService
from backend.services.game_state_service import GameStateService
from backend.utils.log import get_logger
from backend.workers.saq_client import enqueue_task

logger = get_logger(__name__)


class EventService:
    @staticmethod
    async def log_room_event(room_id: int, event_type: str, payload: dict) -> int:
        event_id = uuid.uuid4().hex
        ts_ms = int(time.time() * 1000)
        stream_id = await RedisRepo.add_game_event(room_id, event_id, event_type, payload, ts_ms)
        if payload is not None:
            payload["event_id"] = event_id
            payload["ts_ms"] = ts_ms
            payload["id"] = stream_id
        actor_id = None
        actor_name = None
        if payload:
            actor_id = payload.get("actor_id") or payload.get("agent_id")
            actor_name = payload.get("actor_name") or payload.get("agent_name")
        if event_type in {SocketEvent.ROOM_CHAT, SocketEvent.WW_CHAT_DAY, SocketEvent.WW_CHAT_WOLF}:
            try:
                if event_type == SocketEvent.ROOM_CHAT:
                    channel = str(payload.get("channel") or ChatChannel.ROOM)
                    meta = payload.get("meta") if payload else {}
                    hand_index = meta.get("hand_index") if isinstance(meta, dict) else None
                    phase = meta.get("phase") if isinstance(meta, dict) else None
                    chat_id = await ChatHistoryService.append(
                        room_id=room_id,
                        game_id=int(payload.get("game_id", 0) if payload else 0),
                        game_type=int(payload.get("game_type", 0) if payload else 0),
                        channel=channel,
                        sender_id=payload.get("sender_id") if payload else None,
                        sender_name=payload.get("sender_name") if payload else None,
                        content=str(payload.get("content") or "") if payload else "",
                        hand_index=hand_index,
                        phase=phase,
                        ts_ms=ts_ms,
                    )
                else:
                    inner = payload.get("payload") if payload else {}
                    channel = ChatChannel.WOLF if event_type == SocketEvent.WW_CHAT_WOLF else ChatChannel.DAY
                    chat_id = await ChatHistoryService.append(
                        room_id=room_id,
                        game_id=int(payload.get("game_id", 0) if payload else 0),
                        game_type=int(GameType.WEREWOLF),
                        channel=str(channel),
                        sender_id=payload.get("actor_id") if payload else None,
                        sender_name=payload.get("actor_name") if payload else None,
                        content=str(inner.get("msg") or inner.get("content") or ""),
                        ts_ms=ts_ms,
                    )
                if payload is not None:
                    payload["chat_id"] = chat_id
            except Exception as exc:
                logger.warning("chat_history_enqueue_failed room_id=%s error=%s", room_id, exc)
        try:
            await enqueue_task(
                "persist_game_event",
                event_id=event_id,
                room_id=room_id,
                game_id=int(payload.get("game_id", 0)) if payload else 0,
                actor_id=actor_id,
                actor_name=actor_name,
                phase=payload.get("phase") if payload and payload.get("phase") else "room",
                action_type=event_type,
                payload=payload,
            )
            if payload and payload.get("event_type") == GameEventType.PHASE_CHANGE:
                state = await GameStateService.get_state(room_id)
                if state:
                    await enqueue_task(
                        "persist_game_snapshot",
                        game_id=int(state.get("game_id", 0)),
                        room_id=int(state.get("room_id", room_id)),
                        phase=str(state.get("phase", "")),
                        state_json=json.dumps(state, ensure_ascii=True),
                    )
        except Exception as exc:
            logger.warning("event_enqueue_failed event_id=%s error=%s", event_id, exc)
        return ts_ms

    @staticmethod
    async def list_room_events(
        *,
        room_id: int,
        limit: int,
        before_id: str | None = None,
        after_id: str | None = None,
        types: list[str] | None = None,
        include_chat: bool = False,
        agent_id: int | None = None,
    ) -> dict:
        client = get_client()
        stream = f"game:events:{room_id}"
        limit = max(1, min(int(limit), 200))

        if after_id:
            raw_items = await client.xrange(stream, min=after_id, max="+", count=limit + 1)
        elif before_id:
            raw_items = await client.xrevrange(stream, max=before_id, min="-", count=limit + 1)
        else:
            raw_items = await client.xrevrange(stream, max="+", min="-", count=limit)

        type_set = {t.strip() for t in (types or []) if t and t.strip()}
        chat_types = {SocketEvent.ROOM_CHAT, SocketEvent.WW_CHAT_DAY, SocketEvent.WW_CHAT_WOLF}

        allow_private = False
        settings = get_settings()
        if settings.private_messages_visible_to_spectators:
            allow_private = True
        elif agent_id:
            allow_private = await RoomCache.is_room_member(room_id, agent_id)

        items = []
        for message_id, data in raw_items:
            msg_id = str(message_id)
            if after_id and msg_id == after_id:
                continue
            if before_id and msg_id == before_id:
                continue
            event_type = data.get("event_type")
            if not event_type:
                continue
            if type_set and event_type not in type_set:
                continue
            if not include_chat and event_type in chat_types:
                continue

            payload_raw = data.get("payload")
            if payload_raw is None:
                continue
            try:
                payload = json.loads(payload_raw)
            except Exception:
                payload = payload_raw
            if not isinstance(payload, dict):
                continue

            if include_chat and event_type in chat_types and not allow_private:
                if event_type == SocketEvent.WW_CHAT_WOLF:
                    continue
                if event_type == SocketEvent.ROOM_CHAT and str(payload.get("channel") or "") == str(ChatChannel.WOLF):
                    continue

            ts_ms = int(data.get("ts") or 0)
            items.append(
                {
                    "id": msg_id,
                    "event_type": event_type,
                    "ts_ms": ts_ms,
                    "payload": payload,
                }
            )

        items = sorted(items, key=lambda item: item.get("ts_ms", 0))
        if len(items) > limit:
            items = items[:limit]
        last_id = items[-1]["id"] if items else None
        return {"items": items, "last_id": last_id}
