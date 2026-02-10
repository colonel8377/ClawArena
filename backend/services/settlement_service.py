"""Settlement and balance adjustment helpers."""

from decimal import Decimal
from typing import Iterable

from backend.database.models import TransactionType
from backend.economy.account import add_balance, deduct_balance, unlock_balance
from backend.database.redis_manager import redis_manager


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
        seat_session_id: str = None,
    ) -> None:
        if not wallet_address:
            return

        idempotency_key = f"texas_settle:{wallet_address}"
        if seat_session_id:
            idempotency_key += f":{seat_session_id}"

        should_settle = await redis_manager.mark_settlement_stage_once(
            table_id,
            idempotency_key,
        )
        if not should_settle:
            return

        from backend.database.connection import get_async_db_session

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
                # Clear idempotency marker to allow retry
                await redis_manager.clear_settlement_stage(
                    table_id,
                    idempotency_key,
                )
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
        from backend.database.connection import get_async_db_session
        
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
                    # Convert iterable to list to safely use len()
                    winner_list = list(winners)
                    if winner_list:
                        # Use explicit rounding logic for precision
                        # We use simple division here, assuming backend uses high-precision Decimal
                        # Any remainder from division is currently left in the void (dust).
                        # For exact accounting, one might want to distribute dust to the first winner.
                        prize_per_winner = prize_pool / len(winner_list)
                        
                        # Handle dust (remainder) to ensure total payout equals prize_pool
                        total_distributed = prize_per_winner * len(winner_list)
                        remainder = prize_pool - total_distributed
                        
                        for i, winner_address in enumerate(winner_list):
                            amount = prize_per_winner
                            if i == 0 and remainder > 0:
                                amount += remainder
                                
                            await add_balance(
                                winner_address,
                                amount,
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

    async def refund_werewolf_entry_fees(
        self,
        players: Iterable[dict],
        game_id: str,
        description: str = "Werewolf entry fee refund",
    ) -> None:
        """Unlock held entry fees for all players in a single transaction."""
        from ..database.connection import get_async_db_session

        async with get_async_db_session() as db:
            try:
                for player in players:
                    wallet = player.get("wallet_address")
                    entry_fee = player.get("entry_fee_paid") or Decimal("0")

                    if not wallet or entry_fee <= 0:
                        continue

                    await unlock_balance(
                        wallet,
                        entry_fee,
                        game_session_id=game_id,
                        description=description,
                        db_session=db,
                    )

                await db.commit()
            except Exception as e:
                await db.rollback()
                raise e

    async def award_werewolf_prizes(
        self,
        winners: Iterable[str],
        prize_pool: Decimal,
        description: str = "Werewolf game prize",
    ) -> None:
        """Split prize pool across winners in a single transaction."""
        from ..database.connection import get_async_db_session

        winner_list = list(winners or [])
        if not winner_list or prize_pool <= 0:
            return

        async with get_async_db_session() as db:
            try:
                prize_per_winner = prize_pool / len(winner_list)
                total_distributed = prize_per_winner * len(winner_list)
                remainder = prize_pool - total_distributed

                for i, winner_address in enumerate(winner_list):
                    amount = prize_per_winner
                    if i == 0 and remainder > 0:
                        amount += remainder

                    await add_balance(
                        winner_address,
                        amount,
                        tx_type=TransactionType.GAME_WIN,
                        description=description,
                        db_session=db,
                    )

                await db.commit()
            except Exception as e:
                await db.rollback()
                raise e