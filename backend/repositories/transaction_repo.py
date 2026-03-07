from sqlalchemy.orm import Session

from backend.models.transaction import Transaction
from backend.repositories.db import db_session
from backend.utils.money import to_token


class TransactionRepo:
    @staticmethod
    def insert(agent_id: int, agent_name: str, tx_type: int, amount: int, meta: dict | None = None, session: Session | None = None) -> None:
        amount = to_token(amount)
        with db_session(session) as s:
            s.add(Transaction(agent_id=agent_id, agent_name=agent_name, type=tx_type, amount=amount, meta=meta))
