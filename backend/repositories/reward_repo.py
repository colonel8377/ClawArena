from datetime import date
from typing import Optional

from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError

from backend.models.login_reward import AgentLoginReward
from backend.repositories.db import db_session


class RewardRepo:
    @staticmethod
    def get(agent_id: int) -> Optional[AgentLoginReward]:
        with db_session() as session:
            return session.scalar(select(AgentLoginReward).where(AgentLoginReward.agent_id == agent_id))

    @staticmethod
    def create(agent_id: int, agent_name: str, created_date: date, last_reward_date: Optional[date]) -> None:
        with db_session() as session:
            session.add(
                AgentLoginReward(
                    agent_id=agent_id,
                    agent_name=agent_name,
                    created_date=created_date,
                    last_reward_date=last_reward_date,
                )
            )

    @staticmethod
    def create_if_absent(agent_id: int, agent_name: str, created_date: date, last_reward_date: Optional[date]) -> bool:
        try:
            RewardRepo.create(agent_id, agent_name, created_date, last_reward_date)
            return True
        except IntegrityError:
            return False

    @staticmethod
    def update_last_reward_date(agent_id: int, last_reward_date: date) -> None:
        with db_session() as session:
            session.execute(
                update(AgentLoginReward)
                .where(AgentLoginReward.agent_id == agent_id)
                .values(last_reward_date=last_reward_date)
            )

    @staticmethod
    def update_last_reward_date_if_eligible(agent_id: int, today: date) -> bool:
        with db_session() as session:
            result = session.execute(
                update(AgentLoginReward)
                .where(
                    AgentLoginReward.agent_id == agent_id,
                    AgentLoginReward.created_date != today,
                    or_(AgentLoginReward.last_reward_date.is_(None), AgentLoginReward.last_reward_date != today),
                )
                .values(last_reward_date=today)
            )
            return bool(result.rowcount)
