from backend.queues.base import QueueBase
from backend.queues.match_queue import MatchQueue
from backend.queues.redis_stream import RedisStreamQueue
from backend.queues.redis_zset import RedisZSetQueue

queue_backend: QueueBase = RedisZSetQueue()
message_backend: QueueBase = RedisStreamQueue()
match_queue: MatchQueue = MatchQueue()
