# WerewolfGameVault.sol - Quick Reference

## Contract Address
**After Deployment:** `0x...` (Add after deployment)

## Constructor
```solidity
constructor(IERC20 _token, address _serverSigner)
```

## User Functions

### deposit(uint256 amount)
**Deposit tokens to play**
```javascript
// 1. Approve first
await token.approve(vaultAddress, amount);
// 2. Deposit
await vault.deposit(amount);
```

### withdraw(uint256 amount, uint256 nonce, bytes signature)
**Withdraw winnings (server-signed)**
```javascript
// Get signature from server
const { amount, nonce, signature } = serverResponse;
await vault.withdraw(amount, nonce, signature);
```

### dailyCheckIn()
**Claim 100 tokens daily**
```javascript
await vault.dailyCheckIn();
```

## View Functions

```javascript
// Check game credit balance
const balance = await vault.getBalance(userAddress);

// Get current nonce (for withdrawal)
const nonce = await vault.getNonce(userAddress);

// Check treasury
const treasury = await vault.getTreasuryBalance();

// Time until next check-in
const timeLeft = await vault.getTimeUntilNextCheckIn(userAddress);

// Can claim now?
const canClaim = await vault.canCheckIn(userAddress);
```

## Python Server - Signature Generation

```python
from eth_account import Account
from eth_account.messages import encode_defunct
from web3 import Web3

server = Account.from_key(PRIVATE_KEY)

def sign_withdrawal(user, amount, nonce):
    hash = Web3.solidity_keccak(
        ['address', 'uint256', 'uint256'],
        [user, amount, nonce]
    )
    msg = encode_defunct(hexstr=hash.hex())
    sig = server.sign_message(msg)
    return sig.signature.hex()
```

## Key Constants

- **Daily Reward:** 100 tokens (adjustable by owner)
- **Check-in Cooldown:** 24 hours
- **Token Decimals:** 18 (standard ERC-20)

## Events

```solidity
event Deposit(address user, uint256 amount, uint256 newBalance, uint256 timestamp);
event Withdrawal(address user, uint256 amount, uint256 nonce, uint256 newBalance, uint256 timestamp);
event DailyCheckIn(address user, uint256 amount, uint256 timestamp);
```

## Common Errors

- `InvalidAmount()` - Amount is 0
- `InsufficientBalance()` - Not enough balance
- `InvalidSignature()` - Signature verification failed
- `InvalidNonce()` - Nonce mismatch (get fresh nonce)
- `CheckInCooldownActive()` - Must wait 24 hours
- `TransferFailed()` - Token transfer failed (approve first)

## Security Notes

✅ Server must sign withdrawals (prevents unauthorized claims)
✅ Nonces prevent replay attacks (auto-increments)
✅ ReentrancyGuard on all functions
✅ Immutable token address (set once)

## Deployment Steps

1. Verify Clanker token address on Base explorer
2. Deploy: `WerewolfGameVault(tokenAddress, serverAddress)`
3. Fund treasury: `token.transfer(vaultAddress, fundAmount)`
4. Verify: `vault.getTreasuryBalance()`
5. Test all functions on testnet first!

## Gas Estimates (Approximate)

- `deposit()`: ~50,000 gas
- `withdraw()`: ~60,000 gas
- `dailyCheckIn()`: ~55,000 gas
- View functions: Free (no gas)

## Integration with Backend

Update `.env`:
```bash
WEREWOLF_VAULT_ADDRESS=0x...
SERVER_SIGNER_PRIVATE_KEY=0x...
```

Update `main.py`:
```python
vault = w3.eth.contract(
    address=VAULT_ADDRESS,
    abi=VAULT_ABI
)
```

---
**For detailed documentation, see:** `WEREWOLF_VAULT_GUIDE.md`
