# WerewolfGameVault.sol - Complete Guide

## Overview

`WerewolfGameVault.sol` is a smart contract designed for managing Clanker ERC-20 tokens in an Agent-based Werewolf game on Base Chain. It provides secure deposit/withdrawal mechanisms with server-side authorization and daily reward airdrops.

## Core Features

### 1. Deposit System
Players deposit Clanker tokens to receive game credits for playing Werewolf.

### 2. Withdrawal System (Settlement)
Winners can withdraw tokens after server verification using ECDSA signatures.

### 3. Daily Check-In (Airdrop)
Users can claim 100 tokens once every 24 hours from the contract treasury.

## Smart Contract Functions

### Public Functions

#### `deposit(uint256 amount)`
Deposit tokens into the vault to receive game credits.

**Requirements:**
- User must first approve the contract: `token.approve(vaultAddress, amount)`
- Amount must be greater than 0

**Example:**
```javascript
// Step 1: Approve
await tokenContract.methods.approve(vaultAddress, amount).send({from: userAddress});

// Step 2: Deposit
await vaultContract.methods.deposit(amount).send({from: userAddress});
```

#### `withdraw(uint256 amount, uint256 nonce, bytes signature)`
Withdraw tokens with server authorization (after winning a game).

**Parameters:**
- `amount`: Tokens to withdraw
- `nonce`: Current nonce for the user (get from `getNonce(user)`)
- `signature`: Server-generated ECDSA signature

**Security:**
- Requires valid signature from server signer
- Prevents replay attacks via nonce
- Can only withdraw up to user's balance

#### `dailyCheckIn()`
Claim daily reward of 100 tokens.

**Requirements:**
- 24 hours must have passed since last check-in
- Contract must have sufficient treasury balance

**Example:**
```javascript
await vaultContract.methods.dailyCheckIn().send({from: userAddress});
```

### View Functions

#### `getNonce(address user)`
Get current nonce for a user (needed for withdrawal).

#### `getBalance(address user)`
Get user's game credit balance.

#### `getTreasuryBalance()`
Get contract's treasury balance (for airdrops).

#### `getTimeUntilNextCheckIn(address user)`
Get seconds until next check-in is available.

#### `canCheckIn(address user)`
Check if user can claim check-in reward now.

### Admin Functions (Owner Only)

#### `setServerSigner(address newSigner)`
Update the authorized server signer address.

#### `setDailyReward(uint256 newReward)`
Update the daily check-in reward amount.

#### `emergencyWithdraw(uint256 amount)`
Emergency withdrawal from treasury (owner only).

## Workflow Guide

### Step 1: Verify Clanker Token Address

Before deployment, verify your Clanker token:

```javascript
// Check token details
const name = await tokenContract.methods.name().call();
const symbol = await tokenContract.methods.symbol().call();
const decimals = await tokenContract.methods.decimals().call(); // Should be 18
const totalSupply = await tokenContract.methods.totalSupply().call();

// Verify you have tokens
const yourBalance = await tokenContract.methods.balanceOf(yourAddress).call();
console.log(`You have ${yourBalance / 10**18} ${symbol}`);
```

### Step 2: Deploy the Contract

**Constructor Parameters:**
- `_token`: Clanker token contract address
- `_serverSigner`: Python server's wallet address

**Deployment Example (Hardhat):**
```javascript
const WerewolfGameVault = await ethers.getContractFactory("WerewolfGameVault");
const vault = await WerewolfGameVault.deploy(
  "0xYourClankerTokenAddress",  // Clanker token
  "0xYourServerSignerAddress"   // Python server address
);
await vault.deployed();
console.log("Vault deployed to:", vault.address);
```

**Deployment Example (Foundry):**
```bash
forge create WerewolfGameVault \
  --constructor-args <CLANKER_TOKEN_ADDRESS> <SERVER_SIGNER_ADDRESS> \
  --private-key <DEPLOYER_PRIVATE_KEY> \
  --rpc-url https://mainnet.base.org
```

### Step 3: Fund the Contract Treasury

To enable `dailyCheckIn()`, the contract needs a token treasury:

**Option A: Direct Transfer**
```javascript
// Transfer tokens to the vault
await tokenContract.methods.transfer(
  vaultAddress,
  ethers.utils.parseEther("100000") // 100,000 tokens
).send({from: ownerAddress});
```

**Option B: Deposit (Credits Yourself)**
```javascript
// Approve first
await tokenContract.methods.approve(
  vaultAddress,
  ethers.utils.parseEther("100000")
).send({from: ownerAddress});

// Deposit (increases your balance too)
await vaultContract.methods.deposit(
  ethers.utils.parseEther("100000")
).send({from: ownerAddress});
```

**Verify Treasury:**
```javascript
const treasury = await vaultContract.methods.getTreasuryBalance().call();
console.log(`Treasury: ${treasury / 10**18} tokens`);
```

**Funding Calculation:**
- For 1,000 daily check-ins: 100 tokens × 1,000 = 100,000 tokens
- Recommended: Fund for at least 30-90 days of expected usage

### Step 4: Python Server Integration

The Python server authorizes withdrawals for game winners.

**Server Setup:**
```python
from eth_account import Account
from eth_account.messages import encode_defunct
from web3 import Web3

# Initialize Web3 and contract
w3 = Web3(Web3.HTTPProvider('https://mainnet.base.org'))
vault_contract = w3.eth.contract(address=vault_address, abi=vault_abi)

# Server account (keep private key secure!)
server_account = Account.from_key('0xYourServerPrivateKey')
print(f"Server signer: {server_account.address}")

# Verify this matches the contract's serverSigner
contract_signer = vault_contract.functions.serverSigner().call()
assert contract_signer == server_account.address, "Signer mismatch!"
```

**Generate Withdrawal Signature:**
```python
def create_withdrawal_signature(user_address, amount, nonce):
    """
    Create ECDSA signature for user withdrawal.
    
    Args:
        user_address: Winner's wallet address
        amount: Tokens to withdraw (in wei)
        nonce: Current nonce from contract
        
    Returns:
        dict: {signature, nonce, amount}
    """
    # Create message hash (must match Solidity's keccak256(abi.encodePacked(...)))
    message_hash = Web3.solidity_keccak(
        ['address', 'uint256', 'uint256'],
        [Web3.to_checksum_address(user_address), amount, nonce]
    )
    
    # Sign the hash
    message = encode_defunct(hexstr=message_hash.hex())
    signed = server_account.sign_message(message)
    
    return {
        'signature': signed.signature.hex(),
        'nonce': nonce,
        'amount': amount,
        'user': user_address
    }

# Example: User wins 50 tokens
user_address = '0xWinnerAddress'
win_amount = Web3.to_wei(50, 'ether')  # 50 tokens

# Get current nonce
nonce = vault_contract.functions.getNonce(user_address).call()

# Create signature
sig_data = create_withdrawal_signature(user_address, win_amount, nonce)

print(f"Signature data: {sig_data}")
# Send this to the user so they can call withdraw()
```

**Game Server Workflow:**
```python
# 1. Track game state off-chain
class WerewolfGameServer:
    def __init__(self, vault_contract, server_account):
        self.vault = vault_contract
        self.server = server_account
        
    def process_game_end(self, game_id, winner_address, prize_amount):
        """Process game completion and generate withdrawal signature."""
        
        # Get user's current nonce
        nonce = self.vault.functions.getNonce(winner_address).call()
        
        # Create withdrawal signature
        sig_data = create_withdrawal_signature(
            winner_address,
            Web3.to_wei(prize_amount, 'ether'),
            nonce
        )
        
        # Store in database or send to user
        return sig_data
```

### Step 5: User Workflow

**Complete User Journey:**

```javascript
// === 1. DEPOSIT TO PLAY ===
// Check current balance
const balance = await vaultContract.methods.getBalance(userAddress).call();
console.log(`Current balance: ${balance / 10**18} tokens`);

// Approve vault
const depositAmount = ethers.utils.parseEther("10"); // 10 tokens
await tokenContract.methods.approve(vaultAddress, depositAmount).send({from: userAddress});

// Deposit
await vaultContract.methods.deposit(depositAmount).send({from: userAddress});
console.log("Deposited 10 tokens!");

// === 2. PLAY WEREWOLF GAME ===
// (Game happens off-chain via WebSocket/API)

// === 3. WITHDRAW WINNINGS ===
// Server sends: {amount, nonce, signature}
const { amount, nonce, signature } = serverResponse;

// Withdraw
await vaultContract.methods.withdraw(amount, nonce, signature).send({from: userAddress});
console.log(`Withdrew ${amount / 10**18} tokens!`);

// === 4. DAILY CHECK-IN ===
// Check if available
const canCheckIn = await vaultContract.methods.canCheckIn(userAddress).call();

if (canCheckIn) {
  await vaultContract.methods.dailyCheckIn().send({from: userAddress});
  console.log("Claimed 100 token daily reward!");
} else {
  const timeLeft = await vaultContract.methods.getTimeUntilNextCheckIn(userAddress).call();
  console.log(`Next check-in in ${timeLeft / 3600} hours`);
}
```

## Security Features

### 1. ECDSA Signature Verification
- Only server-signed withdrawals are accepted
- Prevents unauthorized token withdrawals
- Server maintains game integrity

### 2. Nonce-Based Replay Protection
- Each user has incrementing nonce
- Old signatures are invalid
- Prevents signature replay attacks

### 3. ReentrancyGuard
- All state-changing functions protected
- Prevents reentrancy attacks
- Follows Check-Effects-Interactions pattern

### 4. Access Control
- Owner-only admin functions
- Server signer can be updated
- Emergency withdrawal capability

## Testing Checklist

### Before Production
- [ ] Verify Clanker token address on Base Chain explorer
- [ ] Test deposit with small amount
- [ ] Test withdrawal with server signature
- [ ] Test daily check-in cooldown
- [ ] Verify nonce increments correctly
- [ ] Test emergency functions (testnet only)
- [ ] Fund treasury adequately
- [ ] Monitor treasury balance
- [ ] Set up server signer securely (use HSM/KMS in production)

### Security Audits
- [ ] Review signature generation logic
- [ ] Verify message hash matches between Python and Solidity
- [ ] Test replay attack prevention
- [ ] Confirm server signer security
- [ ] Check arithmetic overflow/underflow (Solidity 0.8+ auto-checks)

## Common Issues & Solutions

### Issue: "TransferFailed" on deposit
**Solution:** User must approve the contract first:
```javascript
await tokenContract.methods.approve(vaultAddress, amount).send({from: user});
```

### Issue: "InvalidSignature" on withdrawal
**Solution:** Ensure Python signature matches Solidity expectation:
- Message hash must use same encoding: `keccak256(abi.encodePacked(address, uint256, uint256))`
- Use `encode_defunct` in Python to match Ethereum signed message format

### Issue: "InvalidNonce" on withdrawal
**Solution:** Get current nonce from contract before creating signature:
```python
nonce = vault_contract.functions.getNonce(user_address).call()
```

### Issue: "CheckInCooldownActive"
**Solution:** User must wait 24 hours between check-ins. Check time remaining:
```javascript
const timeLeft = await vault.methods.getTimeUntilNextCheckIn(user).call();
```

### Issue: "InsufficientContractBalance" on check-in
**Solution:** Contract treasury needs funding:
```javascript
await token.methods.transfer(vaultAddress, fundAmount).send({from: owner});
```

## Gas Optimization Tips

- Batch deposits when possible
- Users can claim check-in during low network activity
- Consider setting gas price limits
- Monitor Base Chain gas prices

## Monitoring & Maintenance

### Regular Checks
1. **Treasury Balance**: Ensure sufficient funds for check-ins
   ```javascript
   const treasury = await vault.methods.getTreasuryBalance().call();
   ```

2. **Total User Balances**: Monitor total deposits
   ```python
   total_deposits = sum(vault.functions.getBalance(user).call() for user in all_users)
   ```

3. **Server Signer**: Verify signer hasn't changed
   ```javascript
   const signer = await vault.methods.serverSigner().call();
   ```

### Treasury Refill Strategy
```python
# Alert when treasury is low
treasury = vault.functions.getTreasuryBalance().call()
min_balance = Web3.to_wei(10000, 'ether')  # 10,000 tokens

if treasury < min_balance:
    # Refill treasury
    refill_amount = Web3.to_wei(50000, 'ether')
    token.functions.transfer(vault_address, refill_amount).send()
```

## Integration with Existing Backend

The vault integrates with your existing `/backend/` structure:

### Update main.py
```python
from web3 import Web3
from eth_account import Account

# Initialize vault contract
VAULT_ADDRESS = os.getenv('WEREWOLF_VAULT_ADDRESS')
vault_contract = w3.eth.contract(address=VAULT_ADDRESS, abi=vault_abi)

# Add new API endpoint
@app.post("/api/werewolf/claim-winnings")
async def claim_winnings(wallet_address: str, amount: int):
    """Generate withdrawal signature for winner."""
    nonce = vault_contract.functions.getNonce(wallet_address).call()
    sig_data = create_withdrawal_signature(wallet_address, amount, nonce)
    return sig_data
```

## License

MIT License - Same as the repository

## Support

For issues or questions about WerewolfGameVault.sol:
1. Check this documentation
2. Review the extensive in-code comments
3. Test on Base Sepolia testnet first
4. Open an issue in the repository

---

**Remember:** Always test thoroughly on testnet before deploying to mainnet!
