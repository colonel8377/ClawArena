"""Pydantic view models for account endpoints."""

from typing import Optional


from pydantic import BaseModel


class UserView(BaseModel):
    player_id: str
    player_name: str
    address: Optional[str] = None
    balance: Optional[str] = None
    locked_balance: Optional[str] = None
    created_at: Optional[str] = None
    last_login_date: Optional[str] = None


class BalanceResponse(BaseModel):
    player_id: str
    balance: str


class BatchBalanceRequest(BaseModel):
    player_ids: list[str]


class BatchBalanceResponse(BaseModel):
    balances: dict[str, str]


class TransactionView(BaseModel):
    id: int
    type: str
    amount: str
    balance_before: str
    balance_after: str
    description: Optional[str] = None
    created_at: Optional[str] = None


class AccountSummaryResponse(BaseModel):
    status: str
    wallet_address: str
    offchain_balance: str
    locked_balance: str
    available_balance: str
    onchain_balance: Optional[str] = None
    nonce: Optional[int] = None
    last_updated: Optional[str] = None
    balance_mismatch: Optional[bool] = None
    recent_transactions: list[TransactionView] = []
    transaction_error: Optional[str] = None


class LeaderboardEntry(BaseModel):
    rank: int
    player_id: str
    player_name: str
    balance: str


class LeaderboardResponse(BaseModel):
    entries: list[LeaderboardEntry]
    total: int
    updated_at: str


class RegisterQuery(BaseModel):
    player_name: str
    address: Optional[str] = None


class RegisterResponse(BaseModel):
    user: UserView
    login_secret: Optional[str] = None
    local_debug_mode: Optional[bool] = None


class LoginRequest(BaseModel):
    grant_reward: Optional[bool] = True


class LoginResponse(BaseModel):
    reward_granted: bool
    reward_amount: str
    user: UserView
    local_debug_mode: Optional[bool] = None


class BotTokenRequest(BaseModel):
    fingerprint: str
    player_id: str
    login_secret: str

class BotTokenResponse(BaseModel):
    token: str
    player_id: str
    expires_in: int
    message: str

