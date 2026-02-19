from backend.queue.base import QueueBase
from backend.queue.match_queue import MatchQueue
from backend.queue.redis_stream import RedisStreamQueue
from backend.queue.redis_zset import RedisZSetQueue

queue_backend: QueueBase = RedisZSetQueue()
message_backend: QueueBase = RedisStreamQueue()
match_queue: MatchQueue = MatchQueue()
