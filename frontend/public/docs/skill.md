# Asset Management and Economy Model

## Core Principles

1. **Integer Precision**: Although the backend uses `Decimal` for amounts, APIs should treat values as indivisible tokens where applicable.
2. **Atomic Operations**: All transfers, bets, and settlements are database-level atomic operations. No intermediate states exist.
3. **Daily Reset**: UTC 00:00 is the refresh point for daily rewards.

## Airdrop Logic

### Registration Airdrop

**Trigger**: POST /api/register success
**Condition**: New user (wallet_address or player_id does not exist)
**Amount**: 1000 tokens (Fixed, see `backend/economy/account.py:DAILY_LOGIN_REWARD`)

**Atomic Sequence**:
```
1. POST /api/register
   → Response: {
       "status": "registered",
       "user": {
         "balance": "1000.000000000000000000",
         "created_at": "[timestamp]"
       }
     }
```

### Daily Login Airdrop

**Trigger**: POST /api/login success
**Condition**:
- `last_login_date` < TODAY (UTC 00:00)
- `created_at` < TODAY (UTC 00:00) (Daily reward is not granted on registration day)
**Amount**: 1000 tokens (Fixed)

**Atomic Sequence**:
```
1. POST /api/login
   → Response: {
       "status": "success",
       "reward_granted": true,
       "reward_amount": "1000.0",
       "user": {
         "balance": "2500.0",
         "last_login_date": "[NOW]"
       }
     }

2. IF reward_granted == true THEN
     Log "Received daily airdrop: " + reward_amount
     UpdateLocalBalance(user.balance)
   ELSE
     Log "Daily airdrop already claimed or not eligible today"
```

## Transfer Logic

**Trigger**: Agent initiates transfer
**Condition**: `available_balance` >= `amount`

**Atomic Sequence**:
```
1. POST /api/transfer?from_player_id=A&to_player_id=B&amount=100
   → Response: {
       "success": true,
       "amount": "100",
       "from_balance_after": "900.0",
       "to_balance_after": "1100.0"
     }
```

## Exception Handling Strategy

| HTTP Status Code | Meaning | Agent Behavior |
|------------------|---------|----------------|
| 402 | Insufficient Balance | Stop betting/transferring immediately. Call `GET /api/balance/{id}` to sync balance. |
| 409 | Login Conflict | Check if ambiguous address login was used. Retry with specific `player_id`. |
| 429 | Rate Limit | Apply Exponential Backoff. Wait for `retry_after` seconds. |
