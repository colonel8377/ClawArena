import json
import time
from typing import Any

from backend.config.constants import ChatChannel, ChatChannelCode
from backend.config.settings import get_settings
from backend.queues.provider import message_backend
from backend.repositories.kset.room_repo import RoomCache
from backend.repositories.redis_client import get_client
from backend.utils.log import get_logger
from backend.workers.saq_client import enqueue_task

logger = get_logger(__name__)


class ChatHistoryService:
    @staticmethod
    def _stream_key(room_id: int) -> str:
        return f"room:chat:{room_id}"

    @staticmethod
    def _channel_code(channel: str) -> int:
        if channel == ChatChannel.DAY:
            return int(ChatChannelCode.DAY)
        if channel == ChatChannel.WOLF:
            return int(ChatChannelCode.WOLF)
        if channel == ChatChannel.ROOM:
            return int(ChatChannelCode.ROOM)
        return int(ChatChannelCode.SYSTEM)

    @staticmethod
    async def append(
        *,
        room_id: int,
        game_id: int,
        game_type: int,
        channel: str,
        sender_id: int | None,
        sender_name: str | None,
        content: str,
        hand_index: int | None = None,
        phase: str | None = None,
        ts_ms: int | None = None,
        event_id: str | None = None,
        action_id: str | None = None,
    ) -> str:
        settings = get_settings()
        ts_ms = int(ts_ms or time.time() * 1000)
        payload = {
            "room_id": room_id,
            "game_id": game_id,
            "game_type": game_type,
            "channel": channel,
            "sender_id": sender_id,
            "sender_name": sender_name,
            "content": content,
            "ts_ms": ts_ms,
        }
        if event_id:
            payload["event_id"] = event_id
        if action_id:
            payload["action_id"] = action_id
        if hand_index is not None:
            payload["hand_index"] = int(hand_index)
        if phase is not None:
            payload["phase"] = str(phase)
        stream = ChatHistoryService._stream_key(room_id)
        stream_id = await message_backend.publish(stream, payload, maxlen=settings.chat_history_limit)
        try:
            await enqueue_task(
                "persist_chat_message",
                stream_id=stream_id,
                event_id=event_id,
                action_id=action_id,
                room_id=room_id,
                game_id=game_id,
                game_type=game_type,
                channel=ChatHistoryService._channel_code(channel),
                sender_id=sender_id,
                sender_name=sender_name,
                content=content,
                ts_ms=ts_ms,
            )
        except Exception as exc:
            logger.warning("chat_enqueue_failed stream_id=%s error=%s", stream_id, exc)
        return stream_id

    @staticmethod
    async def list_history(
        *,
        room_id: int,
        limit: int,
        before_id: str | None = None,
        after_id: str | None = None,
        agent_id: int | None = None,
        hand_index: int | None = None,
        allow_private_override: bool | None = None,
    ) -> dict[str, Any]:
        client = get_client()
        stream = ChatHistoryService._stream_key(room_id)
        limit = max(1, min(int(limit), 200))

        if after_id:
            raw_items = await client.xrange(stream, min=after_id, max="+", count=limit + 1)
        elif before_id:
            raw_items = await client.xrevrange(stream, max=before_id, min="-", count=limit + 1)
        else:
            raw_items = await client.xrevrange(stream, max="+", min="-", count=limit)

        messages = []
        for message_id, data in raw_items:
            if after_id and message_id == after_id:
                continue
            if before_id and message_id == before_id:
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
            if hand_index is not None:
                try:
                    if int(payload.get("hand_index")) != int(hand_index):
                        continue
                except Exception:
                    continue
            messages.append((str(message_id), payload))

        allow_private = False
        settings = get_settings()
        if allow_private_override is True:
            allow_private = True
        elif allow_private_override is False:
            allow_private = False
        elif settings.private_messages_visible_to_spectators:
            allow_private = True
        elif agent_id:
            allow_private = await RoomCache.is_room_member(room_id, agent_id)

        filtered: list[dict[str, Any]] = []
        for message_id, payload in messages:
            channel = str(payload.get("channel") or "")
            if channel == ChatChannel.WOLF and not allow_private:
                continue
            filtered.append(
                {
                    "id": message_id,
                    "room_id": int(payload.get("room_id") or room_id),
                    "game_id": int(payload.get("game_id") or 0),
                    "game_type": int(payload.get("game_type") or 0),
                    "channel": channel,
                    "sender_id": payload.get("sender_id"),
                    "sender_name": payload.get("sender_name"),
                    "content": payload.get("content") or "",
                    "ts_ms": int(payload.get("ts_ms") or 0),
                    "event_id": payload.get("event_id"),
                    "action_id": payload.get("action_id"),
                    "hand_index": payload.get("hand_index"),
                    "phase": payload.get("phase"),
                }
            )

        filtered = sorted(filtered, key=lambda item: item.get("ts_ms", 0))
        if len(filtered) > limit:
            filtered = filtered[:limit]

        last_id = filtered[-1]["id"] if filtered else None
        return {"items": filtered, "last_id": last_id}
