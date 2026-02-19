from backend.services.queue_service import QueueService
from backend.middleware.decorators import socket_handler
from backend.views.requests import QueueJoinRequest, QueueLeaveRequest
from backend.sockets.guards import socket_rate_limit, socket_require_agent, socket_validate, validate_response
from backend.config.constants import SocketEvent
from backend.views.response import QueueJoinResponse, QueueLeaveResponse


def register(server):
    @server.on(SocketEvent.QUEUE_JOIN)
    @socket_validate(QueueJoinRequest)
    @socket_require_agent(server)
    @socket_rate_limit(server, "10/minute")
    @socket_handler(server)
    async def queue_join(sid, agent_id, payload):
        result = await QueueService.join(agent_id, payload.game_type)
        return validate_response(QueueJoinResponse, result)

    @server.on(SocketEvent.QUEUE_LEAVE)
    @socket_validate(QueueLeaveRequest)
    @socket_require_agent(server)
    @socket_rate_limit(server, "10/minute")
    @socket_handler(server)
    async def queue_leave(sid, agent_id, payload):
        result = await QueueService.leave(agent_id, payload.game_type)
        return validate_response(QueueLeaveResponse, result)
