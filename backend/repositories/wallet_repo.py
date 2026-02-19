from sqlalchemy import select, update
from sqlalchemy.orm import Session

from backend.models.wallet import AgentWallet
from backend.repositories.db import db_session
from backend.utils.money import to_token


class WalletRepo:
    @staticmethod
    def create(agent_id: int, agent_name: str, token_balance: int = 0, chip_balance: int = 0) -> None:
        token_balance = to_token(token_balance)
        with db_session() as session:
            session.add(
                AgentWallet(
                    agent_id=agent_id,
                    agent_name=agent_name,
                    token_balance=token_balance,
                    chip_balance=chip_balance,
                )
            )

    @staticmethod
    def get(agent_id: int) -> AgentWallet | None:
        with db_session() as session:
            return session.scalar(select(AgentWallet).where(AgentWallet.agent_id == agent_id))

    @staticmethod
    def add_tokens(agent_id: int, amount: int, session: Session | None = None) -> None:
        amount = to_token(amount)
        with db_session(session) as s:
            s.execute(
                update(AgentWallet)
                .where(AgentWallet.agent_id == agent_id)
                .values(token_balance=AgentWallet.token_balance + amount)
            )

    @staticmethod
    def lock_tokens(agent_id: int, amount: int, session: Session | None = None) -> bool:
        amount = to_token(amount)
        with db_session(session) as s:
            result = s.execute(
                update(AgentWallet)
                .where(AgentWallet.agent_id == agent_id, AgentWallet.token_balance >= amount)
                .values(
                    token_balance=AgentWallet.token_balance - amount,
                    token_locked=AgentWallet.token_locked + amount,
                )
            )
            return result.rowcount == 1

    @staticmethod
    def unlock_tokens(agent_id: int, amount: int, session: Session | None = None) -> bool:
        amount = to_token(amount)
        with db_session(session) as s:
            result = s.execute(
                update(AgentWallet)
                .where(AgentWallet.agent_id == agent_id, AgentWallet.token_locked >= amount)
                .values(
                    token_balance=AgentWallet.token_balance + amount,
                    token_locked=AgentWallet.token_locked - amount,
                )
            )
            return result.rowcount == 1

    @staticmethod
    def consume_locked(agent_id: int, amount: int, session: Session | None = None) -> bool:
        amount = to_token(amount)
        with db_session(session) as s:
            result = s.execute(
                update(AgentWallet)
                .where(AgentWallet.agent_id == agent_id, AgentWallet.token_locked >= amount)
                .values(token_locked=AgentWallet.token_locked - amount)
            )
            return result.rowcount == 1
