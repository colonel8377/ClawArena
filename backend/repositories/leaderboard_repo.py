from sqlalchemy import desc, select

from backend.models.wallet import AgentWallet
from backend.repositories.db import db_session


class LeaderboardRepo:
    @staticmethod
    def top_by_token(limit: int) -> list[dict]:
        with db_session() as session:
            rows = (
                session.execute(
                    select(
                        AgentWallet.agent_id.label("agent_id"),
                        AgentWallet.agent_name.label("agent_name"),
                    )
                    .order_by(desc(AgentWallet.token_balance + AgentWallet.token_locked), AgentWallet.agent_id)
                    .limit(limit)
                )
                .mappings()
                .all()
            )
            return [dict(row) for row in rows]
