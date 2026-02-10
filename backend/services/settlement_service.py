"""Settlement and balance adjustment helpers."""

from decimal import Decimal
from typing import Iterable

from database.models import TransactionType
from economy.account import add_balance, deduct_balance, unlock_balance


class SettlementService:
    """Handles token settlement (unlock/refund/prizes) for games."""

    def __init__(self, state, sio) -> None:
        self._state = state
        self._sio = sio

    async def settle_texas_player(
        self,
        wallet_address: str,
        buy_in_tokens: Decimal,
        chips_tokens: Decimal,
        table_id: str,
        principal_description: str,
        win_description: str,
        loss_description: str,
    ) -> None:
        if not wallet_address:
            return

        if buy_in_tokens > 0:
            await unlock_balance(
                wallet_address,
                buy_in_tokens,
                game_session_id=table_id,
                description=principal_description,
            )

        pnl_delta = chips_tokens - buy_in_tokens
        if pnl_delta > 0:
            await add_balance(
                wallet_address,
                pnl_delta,
                tx_type=TransactionType.GAME_WIN,
                description=win_description,
            )
        elif pnl_delta < 0:
            await deduct_balance(
                wallet_address,
                -pnl_delta,
                tx_type=TransactionType.GAME_ENTRY,
                description=loss_description,
            )

    async def refund_werewolf_entry_fees(
        self,
        players: Iterable[dict],
        game_id: str,
        description: str,
    ) -> None:
        for player in players:
            entry_fee = player.get("entry_fee_paid") or Decimal("0")
            if entry_fee <= 0:
                continue
            await unlock_balance(
                player["wallet_address"],
                entry_fee,
                game_session_id=game_id,
                description=description,
            )

    async def award_werewolf_prizes(
        self,
        winners: Iterable[str],
        prize_pool: Decimal,
        description: str,
    ) -> None:
        winners = list(winners)
        if not winners:
            return

        prize_per_winner = prize_pool / len(winners)
        for winner_address in winners:
            await add_balance(
                winner_address,
                prize_per_winner,
                tx_type=TransactionType.GAME_WIN,
                description=description,
            )