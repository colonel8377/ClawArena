"""FastAPI application and API endpoints."""

import time
import secrets
from typing import Dict, Optional
from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from web3 import Web3
from eth_account import Account
from eth_account.messages import encode_defunct

from arena_poker.models import (
    ActionRequest, WithdrawalRequest, WithdrawalPayload
)
from arena_poker.auth import SIWEAuth
from arena_poker.game import PokerGame
from arena_poker.config import settings


class GameManager:
    """Manages multiple poker games."""

    def __init__(self):
        self.games: Dict[str, PokerGame] = {}
        self.nonces: Dict[str, str] = {}
        self.withdrawal_nonces: Dict[str, int] = {}
        
        # Initialize server account for signing withdrawals
        self.server_account = Account.from_key(settings.SERVER_PRIVATE_KEY)

    def create_game(self, game_id: str, small_blind: int = 10, big_blind: int = 20) -> PokerGame:
        """Create a new game."""
        if game_id in self.games:
            raise ValueError(f"Game {game_id} already exists")
        
        game = PokerGame(game_id, small_blind, big_blind)
        self.games[game_id] = game
        return game

    def get_game(self, game_id: str) -> Optional[PokerGame]:
        """Get a game by ID."""
        return self.games.get(game_id)

    def delete_game(self, game_id: str) -> bool:
        """Delete a game."""
        if game_id in self.games:
            del self.games[game_id]
            return True
        return False


# Global game manager
game_manager = GameManager()
siwe_auth = SIWEAuth()

# FastAPI app
app = FastAPI(
    title="Arena Poker API",
    description="Game engine API for Arena Poker",
    version="1.0.0"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "name": "Arena Poker API",
        "version": "1.0.0",
        "status": "running"
    }


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy"}


@app.post("/auth/nonce")
async def get_nonce(wallet_address: str):
    """Get a nonce for SIWE authentication."""
    nonce = siwe_auth.generate_nonce()
    game_manager.nonces[wallet_address.lower()] = nonce
    
    message = siwe_auth.create_message(wallet_address, nonce)
    
    return {
        "nonce": nonce,
        "message": message
    }


@app.post("/auth/verify")
async def verify_signature(wallet_address: str, signature: str):
    """Verify a SIWE signature."""
    wallet_lower = wallet_address.lower()
    
    if wallet_lower not in game_manager.nonces:
        raise HTTPException(status_code=400, detail="No nonce found for this address")
    
    nonce = game_manager.nonces[wallet_lower]
    message = siwe_auth.create_message(wallet_address, nonce)
    
    is_valid = siwe_auth.verify_signature(message, signature, wallet_address)
    
    if not is_valid:
        raise HTTPException(status_code=401, detail="Invalid signature")
    
    # Clear the used nonce
    del game_manager.nonces[wallet_lower]
    
    return {
        "verified": True,
        "wallet_address": wallet_address
    }


@app.post("/games")
async def create_game(game_id: str, small_blind: int = 10, big_blind: int = 20):
    """Create a new poker game."""
    try:
        game = game_manager.create_game(game_id, small_blind, big_blind)
        return {
            "game_id": game_id,
            "created": True,
            "state": game.get_public_state()
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/games/{game_id}")
async def get_game_state(game_id: str, wallet_address: Optional[str] = None):
    """Get the current state of a game."""
    game = game_manager.get_game(game_id)
    if not game:
        raise HTTPException(status_code=404, detail="Game not found")
    
    return game.get_public_state(wallet_address)


@app.delete("/games/{game_id}")
async def delete_game(game_id: str):
    """Delete a game."""
    success = game_manager.delete_game(game_id)
    if not success:
        raise HTTPException(status_code=404, detail="Game not found")
    
    return {"deleted": True}


@app.get("/games")
async def list_games():
    """List all active games."""
    return {
        "games": [
            {
                "game_id": game_id,
                "players": len(game.game_state.players),
                "stage": game.game_state.stage
            }
            for game_id, game in game_manager.games.items()
        ]
    }


@app.post("/withdrawal/create")
async def create_withdrawal(request: WithdrawalRequest):
    """Create a signed withdrawal payload."""
    # Generate nonce for this withdrawal
    wallet_lower = request.wallet_address.lower()
    
    if wallet_lower not in game_manager.withdrawal_nonces:
        game_manager.withdrawal_nonces[wallet_lower] = 0
    
    nonce = game_manager.withdrawal_nonces[wallet_lower]
    game_manager.withdrawal_nonces[wallet_lower] += 1
    
    timestamp = int(time.time())
    
    # Create message to sign
    message = (
        f"Withdraw {request.amount} chips\n"
        f"Address: {request.wallet_address}\n"
        f"Nonce: {nonce}\n"
        f"Timestamp: {timestamp}"
    )
    
    # Sign with server private key
    message_hash = encode_defunct(text=message)
    signed_message = game_manager.server_account.sign_message(message_hash)
    
    payload = WithdrawalPayload(
        wallet_address=request.wallet_address,
        amount=request.amount,
        nonce=nonce,
        signature=signed_message.signature.hex(),
        timestamp=timestamp
    )
    
    return payload.model_dump()


@app.post("/withdrawal/verify")
async def verify_withdrawal(payload: WithdrawalPayload):
    """Verify a withdrawal payload signature."""
    message = (
        f"Withdraw {payload.amount} chips\n"
        f"Address: {payload.wallet_address}\n"
        f"Nonce: {payload.nonce}\n"
        f"Timestamp: {payload.timestamp}"
    )
    
    try:
        message_hash = encode_defunct(text=message)
        recovered_address = Account.recover_message(
            message_hash,
            signature=payload.signature
        )
        
        # Verify against server's address
        is_valid = recovered_address.lower() == game_manager.server_account.address.lower()
        
        return {
            "valid": is_valid,
            "signer": recovered_address,
            "expected_signer": game_manager.server_account.address
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid signature: {str(e)}")


# Export for use in Socket.IO
def get_game_manager() -> GameManager:
    """Get the global game manager instance."""
    return game_manager

