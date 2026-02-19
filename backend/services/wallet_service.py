from backend.repositories.wallet_repo import WalletRepo
from backend.views.errors import DomainError


class WalletService:
    @staticmethod
    def get_balance(agent_id: int) -> dict:
        wallet = WalletRepo.get(agent_id)
        if not wallet:
            raise DomainError("wallet_not_found", code=40401)
        return {
            "agent_id": wallet.agent_id,
            "agent_name": wallet.agent_name,
            "token_balance": wallet.token_balance
        }
