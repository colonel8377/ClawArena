"""Settlement and balance adjustment helpers."""

from decimal import Decimal
from typing import Iterable

from ..database.models import TransactionType
from ..economy.account import add_balance, deduct_balance, unlock_balance


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

        from ..database.connection import get_async_db_session

        async with get_async_db_session() as db:
            try:
                if buy_in_tokens > 0:
                    await unlock_balance(
                        wallet_address,
                        buy_in_tokens,
                        game_session_id=table_id,
                        description=principal_description,
                        db_session=db
                    )

                pnl_delta = chips_tokens - buy_in_tokens
                if pnl_delta > 0:
                    await add_balance(
                        wallet_address,
                        pnl_delta,
                        tx_type=TransactionType.GAME_WIN,
                        description=win_description,
                        db_session=db
                    )
                elif pnl_delta < 0:
                    await deduct_balance(
                        wallet_address,
                        -pnl_delta,
                        tx_type=TransactionType.GAME_ENTRY,
                        description=loss_description,
                        db_session=db
                    )
                
                await db.commit()
            except Exception as e:
                await db.rollback()
                raise e

    async def process_werewolf_settlement(
        self,
        players: Iterable[dict],
        winners: Iterable[str],
        game_id: str,
        prize_pool: Decimal,
    ) -> None:
        """
        Process full settlement for a werewolf game.
        
        1. Unlock all locked balances (refund entry fee holds).
        2. Deduct entry fees from ALL players (pay for the game).
        3. Award prize pool to winners.
        
        Uses a single transaction to ensure atomicity.
        """
        from ..database.connection import get_async_db_session
        
        async with get_async_db_session() as db:
            try:
                # 1. Unlock & Deduct (Net result: User pays entry fee)
                for player in players:
                    wallet = player["wallet_address"]
                    entry_fee = player.get("entry_fee_paid") or Decimal("0")
                    
                    if entry_fee <= 0:
                        continue

                    # Unlock the hold
                    await unlock_balance(
                        wallet,
                        entry_fee,
                        game_session_id=game_id,
                        description="Werewolf entry fee unlock (settlement)",
                        db_session=db
                    )
                    
                    # Deduct the fee
                    await deduct_balance(
                        wallet,
                        entry_fee,
                        tx_type=TransactionType.GAME_ENTRY,
                        description=f"Werewolf game entry fee ({game_id})",
                        db_session=db
                    )

                # 2. Award Prizes
                if winners:
                    prize_per_winner = prize_pool / len(winners)
                    for winner_address in winners:
                        await add_balance(
                            winner_address,
                            prize_per_winner,
                            tx_type=TransactionType.GAME_WIN,
                            description=f"Werewolf game prize ({game_id})",
                            db_session=db
                        )
                
                # Commit all changes at once
                await db.commit()
                
            except Exception as e:
                # Rollback everything on error
                await db.rollback()
                raise e