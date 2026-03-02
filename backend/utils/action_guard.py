import asyncio
import json
import secrets
import time
from decimal import Decimal
from typing import Optional, Any

from backend.repositories.redis_client import get_client
from backend.utils.log import get_logger
from backend.views.errors import DomainError

logger = get_logger(__name__)

# Lua script to release lock safely (only if token matches)
_RELEASE_SCRIPT = """
if redis.call("get", KEYS[1]) == ARGV[1] then
  return redis.call("del", KEYS[1])
else
  return 0
end
"""

def _json_encoder(obj):
    """Custom JSON encoder for ActionGuard"""
    if isinstance(obj, Decimal):
        return float(obj)
    return str(obj)

class ActionGuard:
    """
    业务动作守卫：提供“幂等性拦截”和“阻塞式锁等待”功能。
    用于替代单纯的 RedisLock，解决高并发下的锁竞争报错和重复请求问题。
    """
    def __init__(
        self, 
        room_id: int, 
        action_id: Optional[str] = None, 
        timeout: float = 2.0, 
        lock_ttl_ms: int = 3000,
        key_prefix: str = "lock:action"
    ):
        self.room_id = room_id
        self.action_id = action_id
        self.timeout = timeout
        self.lock_ttl_ms = lock_ttl_ms
        
        self.lock_key = f"{key_prefix}:{room_id}"
        # 幂等结果 key，仅当提供了 action_id 时有效
        self.result_key = f"action:result:{action_id}" if action_id else None
        
        self.redis = get_client()
        self.token: Optional[str] = None
        self._acquired = False
        
        # 状态标记
        self.is_cached = False
        self.result: Any = None

    async def __aenter__(self) -> "ActionGuard":
        # 1. 第一道防线：幂等性检查 (Fast Path)
        # 如果结果已经存在，直接返回，不再参与锁竞争
        if await self._check_cache():
            return self

        # 2. 第二道防线：阻塞式获取锁 (Blocking Wait)
        # 在 timeout 时间内自旋重试，而不是立即报错
        start_time = time.time()
        self.token = secrets.token_urlsafe(16)
        
        while True:
            # 尝试加锁
            if await self.redis.set(self.lock_key, self.token, nx=True, px=self.lock_ttl_ms):
                self._acquired = True
                break
            
            # 检查是否超时
            if time.time() - start_time > self.timeout:
                logger.warning(f"ActionGuard: Lock timeout for room_id={self.room_id} action_id={self.action_id}")
                raise DomainError("action_in_progress", code=40911)
            
            # 自旋等待：50ms ~ 100ms 随机抖动，避免所有请求同时唤醒
            await asyncio.sleep(0.05 + secrets.randbelow(50) / 1000.0)

        # 3. 第三道防线：双重检查 (Double Check)
        # 防止在排队等待锁的过程中，前一个持有锁的请求已经处理完了这个 action_id
        if await self._check_cache():
            # 既然已经处理完了，释放刚才拿到的锁
            await self._release_lock()
            return self

        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        try:
            # 如果是缓存命中，直接返回，不需要做任何清理（因为没拿锁或已释放）
            if self.is_cached:
                return

            # 如果业务执行成功，且有 action_id，缓存结果
            if exc_type is None and self.result is not None and self.result_key:
                try:
                    # 序列化结果，设置 10 分钟过期
                    # default=_json_encoder 处理 Decimal 为 float，保持 JSON 数字类型
                    await self.redis.set(
                        self.result_key, 
                        json.dumps(self.result, default=_json_encoder), 
                        ex=600
                    )
                except Exception as e:
                    logger.error(f"ActionGuard: Failed to cache result for action_id={self.action_id}: {e}")

        finally:
            # 确保释放锁
            await self._release_lock()

    async def _check_cache(self) -> bool:
        """检查是否存在缓存结果"""
        if not self.result_key:
            return False
            
        try:
            cached_data = await self.redis.get(self.result_key)
            if cached_data:
                self.result = json.loads(cached_data)
                self.is_cached = True
                # 仅在第一次命中时打印，避免刷屏
                if not self._acquired:
                    logger.info(f"ActionGuard: Idempotency hit for action_id={self.action_id}")
                return True
        except Exception as e:
            logger.warning(f"ActionGuard: Failed to read cache for action_id={self.action_id}: {e}")
        
        return False

    async def _release_lock(self):
        """释放分布式锁"""
        if self._acquired and self.token:
            await self.redis.eval(_RELEASE_SCRIPT, 1, self.lock_key, self.token)
            self._acquired = False

    def set_result(self, result: Any):
        """设置业务执行结果，用于退出时缓存"""
        self.result = result
