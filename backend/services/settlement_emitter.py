from backend.config.constants import SocketEvent
from backend.repositories.redis_client import get_client
from backend.repositories.redis_repo import RedisRepo
from backend.services.event_service import EventService
from backend.sockets.broadcast import emit_room_event
from backend.utils.log import get_logger
from backend.views.response import TexasSettlementPayload, ok

logger = get_logger(__name__)

_TX_PAYLOAD_TTL_SECONDS = 86400


class SettlementEmitter:
    @staticmethod
    async def emit_texas(server, room_id: int, result: dict | None) -> None:
        payload = None
        payload_key = f"settlement:tx:payload:{room_id}"
        emit_key = f"settlement:tx:emitted:{room_id}"

        if result and result.get("status") == "settled":
            stacks = result.get("stacks") or {}
            busted_ids = [int(agent_id) for agent_id, chips in stacks.items() if int(chips) <= 0]
            payload = TexasSettlementPayload.model_validate(
                {
                    "game_id": result["game_id"],
                    "room_id": result["room_id"],
                    "prize_pool": result["prize_pool"],
                    "payouts": result["payouts"],
                    "stacks": stacks,
                    "busted_ids": busted_ids,
                }
            ).model_dump()
            await RedisRepo.set_json(payload_key, payload, ttl_seconds=_TX_PAYLOAD_TTL_SECONDS)
        else:
            payload = await RedisRepo.get_json(payload_key)
            if not payload:
                return

        client = get_client()
        ok_emit = await client.set(emit_key, "1", nx=True, ex=_TX_PAYLOAD_TTL_SECONDS)
        if not ok_emit:
            return

        envelope = await EventService.log_room_event(room_id, SocketEvent.TX_SETTLEMENT, payload)
        await emit_room_event(server, room_id, SocketEvent.TX_SETTLEMENT, ok(envelope), private=False)
        logger.info("tx_settlement_emitted room_id=%s", room_id)
