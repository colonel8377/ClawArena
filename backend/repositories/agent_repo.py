from typing import Optional

from sqlalchemy import select

from backend.models.agent import Agent
from backend.repositories.db import db_session


class AgentRepo:
    @staticmethod
    def get_by_name(agent_name: str) -> Optional[Agent]:
        with db_session() as session:
            return session.scalar(select(Agent).where(Agent.agent_name == agent_name))

    @staticmethod
    def get_by_id(agent_id: int) -> Optional[Agent]:
        with db_session() as session:
            return session.scalar(select(Agent).where(Agent.id == agent_id))

    @staticmethod
    def create(agent_name: str, secret_hash: str) -> Agent:
        with db_session() as session:
            agent = Agent(agent_name=agent_name, secret_hash=secret_hash, status=1)
            session.add(agent)
            session.flush()
            return agent

    @staticmethod
    def get_names_by_ids(agent_ids: list[int]) -> dict[int, str]:
        if not agent_ids:
            return {}
        with db_session() as session:
            rows = session.execute(select(Agent.id, Agent.agent_name).where(Agent.id.in_(agent_ids))).all()
            return {int(row[0]): row[1] for row in rows}
