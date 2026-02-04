"""Sign-In with Ethereum (SIWE) authentication."""

import time
from typing import Optional
from eth_account import Account
from eth_account.messages import encode_defunct
from pydantic import BaseModel


class SIWEMessage(BaseModel):
    """SIWE message structure."""
    domain: str
    address: str
    statement: str
    uri: str
    version: str = "1"
    chain_id: int = 1
    nonce: str
    issued_at: str
    expiration_time: Optional[str] = None


class SIWEAuth:
    """Handles Sign-In with Ethereum authentication."""

    def __init__(self, domain: str = "arenapoker.game"):
        self.domain = domain

    def create_message(
        self,
        address: str,
        nonce: str,
        statement: str = "Sign in to Arena Poker"
    ) -> str:
        """Create a SIWE message for signing."""
        issued_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        
        message = (
            f"{self.domain} wants you to sign in with your Ethereum account:\n"
            f"{address}\n\n"
            f"{statement}\n\n"
            f"URI: https://{self.domain}\n"
            f"Version: 1\n"
            f"Chain ID: 1\n"
            f"Nonce: {nonce}\n"
            f"Issued At: {issued_at}"
        )
        return message

    def verify_signature(
        self,
        message: str,
        signature: str,
        expected_address: str
    ) -> bool:
        """Verify a signed SIWE message."""
        try:
            # Encode the message
            message_hash = encode_defunct(text=message)
            
            # Recover the address from the signature
            recovered_address = Account.recover_message(
                message_hash,
                signature=signature
            )
            
            # Compare addresses (case-insensitive)
            return recovered_address.lower() == expected_address.lower()
        except Exception:
            return False

    def generate_nonce(self) -> str:
        """Generate a random nonce for SIWE."""
        import secrets
        return secrets.token_hex(16)
