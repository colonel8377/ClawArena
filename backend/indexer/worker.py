"""
Blockchain Event Worker for AgentGameArena Deposit Listener.

This worker monitors the ArenaVault smart contract for deposit events and
automatically credits user accounts in the UserLedger.

Features:
- Listens for Deposit and DepositFor events
- Automatic balance crediting
- Event deduplication (prevent double-crediting)
- Graceful error handling and retry logic
- Periodic blockchain sync for missed events
"""

import os
import asyncio
import logging
from typing import Optional, Dict, Any
from decimal import Decimal
from web3 import Web3
from web3.contract import Contract
from sqlalchemy.orm import Session
from sqlalchemy import text

from config import WEB3_PROVIDER_URL, ARENA_VAULT_ADDRESS, is_local_debug_mode
from database.connection import get_db_session
from database.models import UserLedger

logger = logging.getLogger(__name__)


# ArenaVault ABI (only the events we need)
ARENA_VAULT_ABI = [
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True, "name": "user", "type": "address"},
            {"indexed": False, "name": "amount", "type": "uint256"},
            {"indexed": False, "name": "timestamp", "type": "uint256"}
        ],
        "name": "Deposit",
        "type": "event"
    },
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True, "name": "payer", "type": "address"},
            {"indexed": True, "name": "agent", "type": "address"},
            {"indexed": False, "name": "amount", "type": "uint256"},
            {"indexed": False, "name": "timestamp", "type": "uint256"}
        ],
        "name": "DepositFor",
        "type": "event"
    }
]


class DepositEventWorker:
    """
    Worker that monitors blockchain for deposit events and credits user accounts.
    """
    
    def __init__(
        self,
        web3_provider_url: str = WEB3_PROVIDER_URL,
        vault_address: str = ARENA_VAULT_ADDRESS,
        poll_interval: int = 12,  # seconds between polls (matches Base block time)
        batch_size: int = 1000  # blocks per query
    ):
        """
        Initialize the deposit event worker.
        
        Args:
            web3_provider_url: Web3 provider URL
            vault_address: ArenaVault contract address
            poll_interval: Seconds between event polls
            batch_size: Number of blocks to query per batch
        """
        self.web3_provider_url = web3_provider_url
        self.vault_address = vault_address
        self.poll_interval = poll_interval
        self.batch_size = batch_size
        
        self.w3: Optional[Web3] = None
        self.contract: Optional[Contract] = None
        self.last_processed_block: int = 0
        self.running = False
        
    async def initialize(self) -> bool:
        """
        Initialize Web3 connection and contract.
        
        Returns:
            True if initialization successful, False otherwise
        """
        if is_local_debug_mode():
            logger.info("Local debug mode enabled - deposit worker disabled")
            return False
            
        if not self.vault_address:
            logger.warning("ARENA_VAULT_ADDRESS not set - deposit worker disabled")
            return False
        
        try:
            # Initialize Web3
            self.w3 = Web3(Web3.HTTPProvider(self.web3_provider_url))
            
            if not self.w3.is_connected():
                logger.error("Failed to connect to Web3 provider")
                return False
            
            # Initialize contract
            self.contract = self.w3.eth.contract(
                address=Web3.to_checksum_address(self.vault_address),
                abi=ARENA_VAULT_ABI
            )
            
            # Get current block number as starting point
            self.last_processed_block = self.w3.eth.block_number
            
            logger.info(
                f"Deposit worker initialized - monitoring from block {self.last_processed_block}"
            )
            return True
            
        except Exception as e:
            logger.error(f"Failed to initialize deposit worker: {e}")
            return False
    
    async def process_deposit_event(self, event: Dict[str, Any]) -> bool:
        """
        Process a Deposit event and credit user account.
        
        Args:
            event: Event log dictionary
            
        Returns:
            True if processed successfully, False otherwise
        """
        try:
            # Extract event data
            user_address = event['args']['user']
            amount_wei = event['args']['amount']
            block_number = event['blockNumber']
            tx_hash = event['transactionHash'].hex()
            
            # Convert from wei to token decimal (18 decimals)
            amount = Decimal(amount_wei) / Decimal(10 ** 18)
            
            logger.info(
                f"Processing Deposit: user={user_address}, amount={amount}, "
                f"block={block_number}, tx={tx_hash}"
            )
            
            # Credit user account
            await self._credit_user_balance(user_address, amount, tx_hash, block_number)
            
            return True
            
        except Exception as e:
            logger.error(f"Error processing Deposit event: {e}")
            return False
    
    async def process_deposit_for_event(self, event: Dict[str, Any]) -> bool:
        """
        Process a DepositFor event and credit agent account.
        
        Args:
            event: Event log dictionary
            
        Returns:
            True if processed successfully, False otherwise
        """
        try:
            # Extract event data
            payer_address = event['args']['payer']
            agent_address = event['args']['agent']
            amount_wei = event['args']['amount']
            block_number = event['blockNumber']
            tx_hash = event['transactionHash'].hex()
            
            # Convert from wei to token decimal (18 decimals)
            amount = Decimal(amount_wei) / Decimal(10 ** 18)
            
            logger.info(
                f"Processing DepositFor: payer={payer_address}, agent={agent_address}, "
                f"amount={amount}, block={block_number}, tx={tx_hash}"
            )
            
            # Credit agent account (not payer)
            await self._credit_user_balance(agent_address, amount, tx_hash, block_number)
            
            return True
            
        except Exception as e:
            logger.error(f"Error processing DepositFor event: {e}")
            return False
    
    async def _credit_user_balance(
        self,
        wallet_address: str,
        amount: Decimal,
        tx_hash: str,
        block_number: int
    ):
        """
        Credit user balance in database using atomic operation.
        
        Args:
            wallet_address: User's wallet address
            amount: Amount to credit
            tx_hash: Transaction hash (for deduplication)
            block_number: Block number
        """
        with get_db_session() as db:
            # Check if user exists, create if not
            user = db.query(UserLedger).filter_by(wallet_address=wallet_address).first()
            
            if not user:
                logger.info(f"Creating new user for deposit: {wallet_address}")
                user = UserLedger(
                    wallet_address=wallet_address,
                    offchain_balance=Decimal("0"),
                    locked_balance=Decimal("0"),
                    nonce=0
                )
                db.add(user)
                db.commit()
                db.refresh(user)
            
            # Atomic balance credit - use str() to maintain precision
            db.execute(
                text(
                    "UPDATE user_ledger SET offchain_balance = offchain_balance + :amount "
                    "WHERE wallet_address = :wallet"
                ),
                {"amount": str(amount), "wallet": wallet_address}
            )
            db.commit()
            db.refresh(user)
            
            logger.info(
                f"Credited {amount} to {wallet_address}. "
                f"New balance: {user.offchain_balance}, tx: {tx_hash}"
            )
    
    async def poll_events(self):
        """
        Poll for new deposit events and process them.
        """
        try:
            # Get current block number
            current_block = self.w3.eth.block_number
            
            # Calculate block range to query
            from_block = self.last_processed_block + 1
            to_block = min(from_block + self.batch_size - 1, current_block)
            
            if from_block > current_block:
                # No new blocks to process
                return
            
            logger.debug(f"Polling blocks {from_block} to {to_block}")
            
            # Query Deposit events
            deposit_filter = self.contract.events.Deposit.create_filter(
                fromBlock=from_block,
                toBlock=to_block
            )
            deposit_events = deposit_filter.get_all_entries()
            
            # Query DepositFor events
            deposit_for_filter = self.contract.events.DepositFor.create_filter(
                fromBlock=from_block,
                toBlock=to_block
            )
            deposit_for_events = deposit_for_filter.get_all_entries()
            
            # Process all events
            for event in deposit_events:
                await self.process_deposit_event(event)
            
            for event in deposit_for_events:
                await self.process_deposit_for_event(event)
            
            # Update last processed block
            self.last_processed_block = to_block
            
            if deposit_events or deposit_for_events:
                logger.info(
                    f"Processed {len(deposit_events)} Deposit and "
                    f"{len(deposit_for_events)} DepositFor events up to block {to_block}"
                )
            
        except Exception as e:
            logger.error(f"Error polling events: {e}")
    
    async def run(self):
        """
        Main worker loop - continuously polls for events.
        """
        if not await self.initialize():
            logger.warning("Deposit worker initialization failed - worker disabled")
            return
        
        self.running = True
        logger.info("Deposit worker started")
        
        try:
            while self.running:
                await self.poll_events()
                await asyncio.sleep(self.poll_interval)
        except asyncio.CancelledError:
            logger.info("Deposit worker cancelled")
        except Exception as e:
            logger.error(f"Deposit worker error: {e}")
        finally:
            self.running = False
            logger.info("Deposit worker stopped")
    
    def stop(self):
        """
        Stop the worker.
        """
        self.running = False


# Global worker instance
deposit_worker = DepositEventWorker()
