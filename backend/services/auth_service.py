import secrets
from datetime import datetime

from backend.config.constants import TxType
from backend.config.settings import get_settings
from backend.repositories.agent_repo import AgentRepo
from backend.repositories.reward_repo import RewardRepo
from backend.repositories.transaction_repo import TransactionRepo
from backend.repositories.wallet_repo import WalletRepo
from backend.repositories.kv.kv_repo import KvRepo
from backend.utils.crypto import hash_secret
from backend.utils.redis_lock import RedisLock
from backend.utils.log import get_logger
from backend.utils.money import to_token
from backend.views.errors import AuthError, DomainError

logger = get_logger(__name__)


class AuthService:
    @staticmethod
    async def register(agent_name: str) -> dict:
        lock_key = f"lock:register:{agent_name}"
        async with RedisLock(lock_key, ttl_ms=8000) as lock:
            if not lock.acquired:
                logger.warning("register_lock_busy agent_name=%s", agent_name)
                raise DomainError("register_in_progress", code=40003)

            existing = AgentRepo.get_by_name(agent_name)
            if existing:
                logger.info("register_name_taken agent_name=%s", agent_name)
                raise DomainError("agent_name_taken", code=40002)

            secret = secrets.token_urlsafe(32)
            secret_hash = hash_secret(secret)

            agent = AgentRepo.create(agent_name, secret_hash)
            agent_id = agent.id
            WalletRepo.create(agent_id, agent_name, token_balance=to_token(1000), chip_balance=0)

            today = datetime.utcnow().date()
            RewardRepo.create(agent_id, agent_name, created_date=today, last_reward_date=today)
            TransactionRepo.insert(
                agent_id,
                agent_name,
                int(TxType.LOGIN_REWARD),
                to_token(1000),
                {"reason": "register_reward"},
            )

            token = secrets.token_urlsafe(32)
            settings = get_settings()
            await KvRepo.set_session(token, str(agent_id), settings.token_ttl_seconds)

            logger.info("register_success agent_id=%s agent_name=%s", agent_id, agent_name)
            return {
                "agent_id": agent_id,
                "agent_name": agent_name,
                "secret": secret,
                "token": token,
                "expires_in": settings.token_ttl_seconds,
                "reward_granted": True,
                "reward_amount": int(to_token(1000)),
            }

    @staticmethod
    async def login(agent_id: int, secret: str) -> dict:
        agent = AgentRepo.get_by_id(agent_id)
        if not agent:
            logger.warning("login_invalid_agent agent_id=%s", agent_id)
            raise AuthError("Invalid agent_id")

        if hash_secret(secret) != agent.secret_hash:
            logger.warning("login_invalid_secret agent_id=%s", agent_id)
            raise AuthError("Invalid secret")

        token = secrets.token_urlsafe(32)
        settings = get_settings()
        await KvRepo.set_session(token, str(agent_id), settings.token_ttl_seconds)

        reward_granted, reward_amount = AuthService._grant_daily_reward(agent_id, agent.agent_name)

        logger.info("login_success agent_id=%s reward_granted=%s", agent_id, reward_granted)
        return {
            "agent_id": agent_id,
            "agent_name": agent.agent_name,
            "token": token,
            "expires_in": settings.token_ttl_seconds,
            "reward_granted": reward_granted,
            "reward_amount": reward_amount,
        }

    @staticmethod
    def grant_daily_reward(agent_id: int) -> dict:
        agent = AgentRepo.get_by_id(agent_id)
        if not agent:
            logger.warning("reward_invalid_agent agent_id=%s", agent_id)
            raise AuthError("Invalid agent_id")
        reward_granted, reward_amount = AuthService._grant_daily_reward(agent_id, agent.agent_name)
        logger.info("reward_checked agent_id=%s reward_granted=%s", agent_id, reward_granted)
        return {"reward_granted": reward_granted, "reward_amount": reward_amount}

    @staticmethod
    def _grant_daily_reward(agent_id: int, agent_name: str) -> tuple[bool, int]:
        today = datetime.utcnow().date()
        record = RewardRepo.get(agent_id)

        if not record:
            created = RewardRepo.create_if_absent(agent_id, agent_name, created_date=today, last_reward_date=today)
            if created:
                WalletRepo.add_tokens(agent_id, to_token(1000))
                TransactionRepo.insert(
                    agent_id,
                    agent_name,
                    int(TxType.LOGIN_REWARD),
                    to_token(1000),
                    {"reason": "first_login_reward"},
                )
                logger.info("reward_first_login agent_id=%s", agent_id)
                return True, 1000

        updated = RewardRepo.update_last_reward_date_if_eligible(agent_id, today)
        if not updated:
            return False, 0

        WalletRepo.add_tokens(agent_id, to_token(1000))
        TransactionRepo.insert(
            agent_id,
            agent_name,
            int(TxType.LOGIN_REWARD),
            to_token(1000),
            {"reason": "daily_login_reward"},
        )
        logger.info("reward_daily agent_id=%s", agent_id)
        return True, 1000
