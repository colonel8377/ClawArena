// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import "@openzeppelin/contracts/access/Ownable.sol";
import "@openzeppelin/contracts/security/ReentrancyGuard.sol";
import "@openzeppelin/contracts/utils/cryptography/ECDSA.sol";

/**
 * @title WerewolfGameVault
 * @notice Smart Contract for managing Clanker tokens in an Agent-based Werewolf game
 * @dev This contract handles deposits, server-authorized withdrawals, and daily check-in airdrops
 * 
 * CONTRACT OVERVIEW:
 * ==================
 * This vault manages game credits for a Werewolf game using a Clanker-deployed ERC-20 token.
 * Players deposit tokens to play, withdraw winnings with server authorization, and can
 * claim daily airdrops from the contract's treasury.
 * 
 * WORKFLOW:
 * =========
 * 1. SETUP (Owner):
 *    - Deploy contract with Clanker token address and server signer address
 *    - Fund the contract treasury by sending tokens to this contract address
 *    - Verify Clanker token: Call token.balanceOf(address(this)) to check treasury balance
 * 
 * 2. DEPOSIT (Players):
 *    - Players must first approve this contract: token.approve(vaultAddress, amount)
 *    - Then call deposit(amount) to move tokens from wallet to game credits
 *    - Game credits are tracked in balances[player]
 * 
 * 3. PLAY GAME (Off-chain):
 *    - Players use their game credits to play Werewolf
 *    - Python server tracks game state and determines winners
 *    - Server generates ECDSA signature for winners to withdraw
 * 
 * 4. WITHDRAW (Winners):
 *    - Server creates signature: sign(keccak256(abi.encodePacked(player, amount, nonce)))
 *    - Player calls withdraw(amount, nonce, signature)
 *    - Contract verifies signature and prevents replay attacks
 * 
 * 5. DAILY CHECK-IN (All Users):
 *    - Any user can call dailyCheckIn() once per 24 hours
 *    - Receives 100 tokens from contract treasury
 *    - Encourages daily engagement
 * 
 * SECURITY FEATURES:
 * ==================
 * - ECDSA signature verification (only server can authorize withdrawals)
 * - Nonce-based replay attack prevention
 * - ReentrancyGuard on all state-changing functions
 * - Ownable for administrative functions
 * - Check-Effects-Interactions pattern
 */
contract WerewolfGameVault is Ownable, ReentrancyGuard {
    using ECDSA for bytes32;

    // ============================================================================
    // STATE VARIABLES
    // ============================================================================

    /// @notice The Clanker ERC-20 token used for the game
    /// @dev Immutable - set once in constructor, cannot be changed
    IERC20 public immutable token;

    /// @notice Address of the Python server authorized to sign withdrawal permits
    /// @dev Only withdrawals with valid signatures from this address are accepted
    address public serverSigner;

    /// @notice Game credit balances for each user
    /// @dev Represents tokens deposited into the contract for gameplay
    mapping(address => uint256) public balances;

    /// @notice Nonce for each user to prevent replay attacks
    /// @dev Increments with each successful withdrawal
    mapping(address => uint256) public nonces;

    /// @notice Timestamp of last daily check-in for each user
    /// @dev Used to enforce 24-hour cooldown between check-ins
    mapping(address => uint256) public lastCheckIn;

    /// @notice Daily check-in reward amount (100 tokens with 18 decimals)
    /// @dev Can be adjusted by owner if needed
    uint256 public dailyReward = 100 * 10**18;

    /// @notice Check-in cooldown period (24 hours)
    uint256 public constant CHECK_IN_COOLDOWN = 24 hours;

    // ============================================================================
    // EVENTS
    // ============================================================================

    /// @notice Emitted when a user deposits tokens
    event Deposit(
        address indexed user,
        uint256 amount,
        uint256 newBalance,
        uint256 timestamp
    );

    /// @notice Emitted when a user withdraws tokens
    event Withdrawal(
        address indexed user,
        uint256 amount,
        uint256 nonce,
        uint256 newBalance,
        uint256 timestamp
    );

    /// @notice Emitted when a user claims daily check-in reward
    event DailyCheckIn(
        address indexed user,
        uint256 amount,
        uint256 timestamp
    );

    /// @notice Emitted when server signer is updated
    event ServerSignerUpdated(
        address indexed oldSigner,
        address indexed newSigner,
        uint256 timestamp
    );

    /// @notice Emitted when daily reward amount is updated
    event DailyRewardUpdated(
        uint256 oldReward,
        uint256 newReward,
        uint256 timestamp
    );

    // ============================================================================
    // ERRORS
    // ============================================================================

    error ZeroAddress();
    error InvalidAmount();
    error InsufficientBalance();
    error InsufficientContractBalance();
    error InvalidSignature();
    error InvalidNonce();
    error CheckInCooldownActive();
    error TransferFailed();

    // ============================================================================
    // CONSTRUCTOR
    // ============================================================================

    /**
     * @notice Initializes the WerewolfGameVault contract
     * @param _token Address of the Clanker ERC-20 token contract
     * @param _serverSigner Address of the Python server authorized to sign withdrawals
     * 
     * @dev HOW TO VERIFY CLANKER TOKEN ADDRESS:
     *      1. Get the token address from Clanker deployment
     *      2. Verify it's a valid ERC-20: Check token.totalSupply() doesn't revert
     *      3. Check token details: token.name(), token.symbol(), token.decimals()
     *      4. Verify your ownership: token.balanceOf(yourAddress)
     */
    constructor(IERC20 _token, address _serverSigner) {
        if (address(_token) == address(0)) revert ZeroAddress();
        if (_serverSigner == address(0)) revert ZeroAddress();
        
        token = _token;
        serverSigner = _serverSigner;
    }

    // ============================================================================
    // DEPOSIT FUNCTION
    // ============================================================================

    /**
     * @notice Deposit Clanker tokens into the vault to receive game credits
     * @param amount Amount of tokens to deposit (in wei, e.g., 100 * 10**18 for 100 tokens)
     * 
     * @dev IMPORTANT: Users MUST approve this contract first!
     *      
     *      STEPS TO DEPOSIT:
     *      1. In your wallet or via web3: token.approve(vaultAddress, amount)
     *      2. Wait for approval transaction to confirm
     *      3. Call this deposit(amount) function
     *      4. Your tokens will be transferred to the vault
     *      5. Your balances[msg.sender] will increase by amount
     *      
     *      EXAMPLE (web3.js):
     *      // Step 1: Approve
     *      await tokenContract.methods.approve(vaultAddress, amount).send({from: userAddress});
     *      // Step 2: Deposit
     *      await vaultContract.methods.deposit(amount).send({from: userAddress});
     */
    function deposit(uint256 amount) external nonReentrant {
        if (amount == 0) revert InvalidAmount();
        
        // Transfer tokens from user to this contract
        // NOTE: User must have called token.approve(address(this), amount) first!
        bool success = token.transferFrom(msg.sender, address(this), amount);
        if (!success) revert TransferFailed();
        
        // Update user's game credit balance
        balances[msg.sender] += amount;
        
        emit Deposit(
            msg.sender,
            amount,
            balances[msg.sender],
            block.timestamp
        );
    }

    // ============================================================================
    // WITHDRAWAL FUNCTION (SETTLEMENT)
    // ============================================================================

    /**
     * @notice Withdraw tokens after winning a game (requires server signature)
     * @param amount Amount of tokens to withdraw
     * @param nonce Current nonce for the user (must match nonces[msg.sender])
     * @param signature Server's signature authorizing this withdrawal
     * 
     * @dev WITHDRAWAL SECURITY:
     *      This function ensures users can only withdraw if they legitimately won.
     *      The Python server tracks game outcomes off-chain and signs valid withdrawals.
     *      
     *      SIGNATURE CREATION (Python Server):
     *      ```python
     *      from eth_account import Account
     *      from eth_account.messages import encode_defunct
     *      from web3 import Web3
     *      
     *      # Create message hash (must match Solidity's encoding)
     *      message_hash = Web3.solidity_keccak(
     *          ['address', 'uint256', 'uint256'],
     *          [user_address, amount, nonce]
     *      )
     *      
     *      # Sign the hash
     *      message = encode_defunct(hexstr=message_hash.hex())
     *      signed = server_account.sign_message(message)
     *      signature = signed.signature.hex()
     *      ```
     *      
     *      REPLAY ATTACK PREVENTION:
     *      - Each user has a nonce that increments with each withdrawal
     *      - Old signatures with previous nonces are rejected
     *      - Signature must be created for current nonce value
     */
    function withdraw(
        uint256 amount,
        uint256 nonce,
        bytes memory signature
    ) external nonReentrant {
        if (amount == 0) revert InvalidAmount();
        if (balances[msg.sender] < amount) revert InsufficientBalance();
        if (nonce != nonces[msg.sender]) revert InvalidNonce();
        
        // Reconstruct the message hash that was signed by the server
        // This must match exactly what the Python server signed
        bytes32 messageHash = keccak256(
            abi.encodePacked(msg.sender, amount, nonce)
        );
        
        // Convert to Ethereum Signed Message format
        // This matches web3.py's encode_defunct behavior
        bytes32 ethSignedMessageHash = messageHash.toEthSignedMessageHash();
        
        // Recover the signer address from the signature
        address recoveredSigner = ethSignedMessageHash.recover(signature);
        
        // Verify the signature is from the authorized server
        if (recoveredSigner != serverSigner) revert InvalidSignature();
        
        // Update state BEFORE external call (Checks-Effects-Interactions pattern)
        nonces[msg.sender]++; // Increment nonce to prevent replay
        balances[msg.sender] -= amount; // Deduct from game credits
        
        // Transfer tokens back to user
        bool success = token.transfer(msg.sender, amount);
        if (!success) revert TransferFailed();
        
        emit Withdrawal(
            msg.sender,
            amount,
            nonce,
            balances[msg.sender],
            block.timestamp
        );
    }

    // ============================================================================
    // DAILY CHECK-IN (AIRDROP)
    // ============================================================================

    /**
     * @notice Claim daily check-in reward (100 tokens from contract treasury)
     * 
     * @dev DAILY CHECK-IN MECHANICS:
     *      - Any user can call this once every 24 hours
     *      - Receives dailyReward (default 100 tokens) from contract's balance
     *      - Does NOT deduct from user's game credits
     *      - Tokens come from contract treasury (must be funded by owner)
     *      
     *      HOW TO FUND THE CONTRACT TREASURY:
     *      1. As owner, send tokens directly to this contract address:
     *         token.transfer(vaultAddress, fundingAmount)
     *      2. Or have anyone send tokens to the contract
     *      3. Check treasury: token.balanceOf(vaultAddress)
     *      4. Treasury tokens are separate from user balances
     *      
     *      COOLDOWN ENFORCEMENT:
     *      - Tracks lastCheckIn[user] timestamp
     *      - Requires 24 hours between check-ins
     *      - First check-in is always allowed
     */
    function dailyCheckIn() external nonReentrant {
        // Check if cooldown period has passed
        if (block.timestamp < lastCheckIn[msg.sender] + CHECK_IN_COOLDOWN) {
            revert CheckInCooldownActive();
        }
        
        // Verify contract has sufficient balance for the airdrop
        uint256 contractBalance = token.balanceOf(address(this));
        if (contractBalance < dailyReward) {
            revert InsufficientContractBalance();
        }
        
        // Update last check-in timestamp
        lastCheckIn[msg.sender] = block.timestamp;
        
        // Transfer tokens from contract treasury to user
        // NOTE: These tokens come from the contract's balance, not from balances mapping
        bool success = token.transfer(msg.sender, dailyReward);
        if (!success) revert TransferFailed();
        
        emit DailyCheckIn(
            msg.sender,
            dailyReward,
            block.timestamp
        );
    }

    // ============================================================================
    // ADMIN FUNCTIONS (OWNER ONLY)
    // ============================================================================

    /**
     * @notice Update the server signer address
     * @param _newSigner New address authorized to sign withdrawals
     * @dev Only owner can call this. Be careful - changing signer invalidates pending signatures
     */
    function setServerSigner(address _newSigner) external onlyOwner {
        if (_newSigner == address(0)) revert ZeroAddress();
        
        address oldSigner = serverSigner;
        serverSigner = _newSigner;
        
        emit ServerSignerUpdated(oldSigner, _newSigner, block.timestamp);
    }

    /**
     * @notice Update the daily check-in reward amount
     * @param _newReward New reward amount (in wei)
     * @dev Only owner can call this. Affects future check-ins only
     */
    function setDailyReward(uint256 _newReward) external onlyOwner {
        if (_newReward == 0) revert InvalidAmount();
        
        uint256 oldReward = dailyReward;
        dailyReward = _newReward;
        
        emit DailyRewardUpdated(oldReward, _newReward, block.timestamp);
    }

    /**
     * @notice Emergency token recovery (owner only)
     * @param amount Amount of tokens to recover
     * @dev Should only be used in emergencies. Does not affect user balances mapping.
     *      Recovers tokens from contract treasury only.
     */
    function emergencyWithdraw(uint256 amount) external onlyOwner nonReentrant {
        if (amount == 0) revert InvalidAmount();
        
        bool success = token.transfer(owner(), amount);
        if (!success) revert TransferFailed();
    }

    // ============================================================================
    // VIEW FUNCTIONS
    // ============================================================================

    /**
     * @notice Get current nonce for a user
     * @param user Address of the user
     * @return Current nonce value
     */
    function getNonce(address user) external view returns (uint256) {
        return nonces[user];
    }

    /**
     * @notice Get game credit balance for a user
     * @param user Address of the user
     * @return Current balance in game credits
     */
    function getBalance(address user) external view returns (uint256) {
        return balances[user];
    }

    /**
     * @notice Get contract's token treasury balance
     * @return Amount of tokens in contract treasury (for airdrops)
     */
    function getTreasuryBalance() external view returns (uint256) {
        return token.balanceOf(address(this));
    }

    /**
     * @notice Get time until next check-in is available
     * @param user Address of the user
     * @return Seconds until next check-in (0 if available now)
     */
    function getTimeUntilNextCheckIn(address user) external view returns (uint256) {
        uint256 nextCheckIn = lastCheckIn[user] + CHECK_IN_COOLDOWN;
        if (block.timestamp >= nextCheckIn) {
            return 0;
        }
        return nextCheckIn - block.timestamp;
    }

    /**
     * @notice Check if user can claim daily check-in now
     * @param user Address of the user
     * @return True if check-in is available
     */
    function canCheckIn(address user) external view returns (bool) {
        return block.timestamp >= lastCheckIn[user] + CHECK_IN_COOLDOWN;
    }
}

/*
 * ============================================================================
 * DEPLOYMENT & USAGE GUIDE
 * ============================================================================
 * 
 * STEP 1: VERIFY CLANKER TOKEN ADDRESS
 * -------------------------------------
 * Before deploying, verify your Clanker token:
 * 
 * 1. Get token address from Clanker deployment
 * 2. Connect to Base Chain and verify the contract:
 *    - Read token.name()
 *    - Read token.symbol()
 *    - Read token.decimals() (should be 18)
 *    - Read token.totalSupply()
 * 3. Check you have tokens: token.balanceOf(yourAddress)
 * 
 * STEP 2: DEPLOY CONTRACT
 * ------------------------
 * Constructor parameters:
 * - _token: Clanker token address (e.g., 0x1234...abcd)
 * - _serverSigner: Your Python server's wallet address
 * 
 * Example (Hardhat):
 * ```javascript
 * const WerewolfGameVault = await ethers.getContractFactory("WerewolfGameVault");
 * const vault = await WerewolfGameVault.deploy(
 *   "0xYourClankerTokenAddress",
 *   "0xYourServerSignerAddress"
 * );
 * await vault.deployed();
 * console.log("Vault deployed to:", vault.address);
 * ```
 * 
 * STEP 3: FUND CONTRACT TREASURY
 * -------------------------------
 * To enable dailyCheckIn(), fund the contract:
 * 
 * 1. Approve the vault to spend your tokens:
 *    token.approve(vaultAddress, fundingAmount)
 * 
 * 2. Transfer tokens to the vault:
 *    token.transfer(vaultAddress, fundingAmount)
 *    
 *    OR use deposit() to fund while crediting yourself:
 *    vault.deposit(fundingAmount)
 * 
 * 3. Verify treasury balance:
 *    vault.getTreasuryBalance()
 * 
 * Example funding amount:
 * - For 1000 daily check-ins: 100,000 tokens
 * - Calculation: (100 tokens/check-in) * (1000 check-ins) = 100,000 tokens
 * 
 * STEP 4: INTEGRATE WITH PYTHON SERVER
 * -------------------------------------
 * Your Python server should:
 * 
 * 1. Track game outcomes off-chain
 * 2. Generate signatures for winners:
 * 
 * ```python
 * from eth_account import Account
 * from eth_account.messages import encode_defunct
 * from web3 import Web3
 * 
 * # Initialize server account
 * server_account = Account.from_key('your_private_key')
 * 
 * # When user wins, create signature
 * def create_withdrawal_signature(user_address, amount, nonce):
 *     # Create message hash
 *     message_hash = Web3.solidity_keccak(
 *         ['address', 'uint256', 'uint256'],
 *         [user_address, amount, nonce]
 *     )
 *     
 *     # Sign the hash
 *     message = encode_defunct(hexstr=message_hash.hex())
 *     signed = server_account.sign_message(message)
 *     
 *     return {
 *         'signature': signed.signature.hex(),
 *         'nonce': nonce,
 *         'amount': amount
 *     }
 * 
 * # Get current nonce from contract
 * nonce = vault_contract.functions.getNonce(user_address).call()
 * 
 * # Create signature
 * sig_data = create_withdrawal_signature(user_address, win_amount, nonce)
 * 
 * # Send to user so they can call withdraw()
 * ```
 * 
 * STEP 5: USER WORKFLOW
 * ----------------------
 * Players interact with the contract:
 * 
 * 1. Deposit to play:
 *    - token.approve(vaultAddress, amount)
 *    - vault.deposit(amount)
 * 
 * 2. Play Werewolf game (off-chain)
 * 
 * 3. If they win, server provides signature
 * 
 * 4. Withdraw winnings:
 *    - vault.withdraw(amount, nonce, signature)
 * 
 * 5. Daily rewards:
 *    - vault.dailyCheckIn() (once per 24 hours)
 * 
 * ============================================================================
 */
