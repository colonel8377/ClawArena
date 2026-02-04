// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import "@openzeppelin/contracts/access/Ownable.sol";
import "@openzeppelin/contracts/utils/ReentrancyGuard.sol";
import "@openzeppelin/contracts/utils/cryptography/ECDSA.sol";
import "@openzeppelin/contracts/utils/cryptography/MessageHashUtils.sol";

/**
 * @title ArenaVault
 * @notice The Secure Vault for OpenClaw Agent Arena. It knows nothing about game rules.
 * @dev Manages ERC20 token deposits/withdrawals for AI agents playing games on Base Chain.
 * 
 * This contract is the "Bank" for all games in the Agent Arena platform.
 * Players deposit tokens to play games, and can only withdraw with a 
 * server-signed permit (signature). Also supports daily check-in rewards.
 * 
 * Security features:
 * - Nonce-based replay attack prevention (per-user)
 * - Server signature verification using ECDSA
 * - Cross-chain and cross-contract replay protection (chainId + contract address)
 * - ReentrancyGuard protection
 * - Owner-controlled server signer and treasury
 * - Daily check-in rate limiting (once per 24h)
 */
contract ArenaVault is Ownable, ReentrancyGuard {
    using ECDSA for bytes32;
    using MessageHashUtils for bytes32;

    // ============================================================================
    // STATE VARIABLES
    // ============================================================================

    /// @notice The ERC20 token used for deposits/withdrawals (Clanker Token)
    IERC20 public immutable token;

    /// @notice Address of the Python off-chain game engine (authorized to sign withdrawals)
    address public serverSigner;

    /// @notice Treasury address for daily check-in rewards
    address public treasury;

    /// @notice Daily check-in reward amount
    uint256 public dailyCheckInReward;

    /// @notice Nonce for each user (prevents replay attacks)
    mapping(address => uint256) public nonces;

    /// @notice Last check-in timestamp for each user (for 24h rate limiting)
    mapping(address => uint256) public lastCheckIn;

    // ============================================================================
    // EVENTS
    // ============================================================================

    /// @notice Emitted when tokens are deposited by user for themselves
    event Deposit(
        address indexed user,
        uint256 amount,
        uint256 timestamp
    );

    /// @notice Emitted when tokens are deposited by a human for an agent
    event DepositFor(
        address indexed payer,
        address indexed agent,
        uint256 amount,
        uint256 timestamp
    );

    /// @notice Emitted when tokens are withdrawn with server signature
    event Withdraw(
        address indexed user,
        uint256 amount,
        uint256 nonce,
        uint256 timestamp
    );

    /// @notice Emitted when daily check-in reward is claimed
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

    /// @notice Emitted when treasury is updated
    event TreasuryUpdated(
        address indexed oldTreasury,
        address indexed newTreasury,
        uint256 timestamp
    );

    /// @notice Emitted when daily check-in reward amount is updated
    event DailyCheckInRewardUpdated(
        uint256 oldAmount,
        uint256 newAmount,
        uint256 timestamp
    );

    // ============================================================================
    // ERRORS
    // ============================================================================

    error InvalidAmount();
    error InvalidSignature();
    error InvalidNonce();
    error ZeroAddress();
    error TransferFailed();
    error InsufficientTreasuryBalance();
    error CheckInTooEarly();

    // ============================================================================
    // CONSTRUCTOR
    // ============================================================================

    /**
     * @notice Initializes the ArenaVault contract
     * @param _token Address of the ERC20 token (Clanker Token on Base Chain)
     * @param _serverSigner Initial address of the Python backend server
     * @param _treasury Address of the treasury for daily check-in rewards
     * @param _dailyCheckInReward Amount of tokens for daily check-in reward
     */
    constructor(
        IERC20 _token,
        address _serverSigner,
        address _treasury,
        uint256 _dailyCheckInReward
    ) Ownable(msg.sender) {
        if (address(_token) == address(0)) revert ZeroAddress();
        if (_serverSigner == address(0)) revert ZeroAddress();
        if (_treasury == address(0)) revert ZeroAddress();
        
        token = _token;
        serverSigner = _serverSigner;
        treasury = _treasury;
        dailyCheckInReward = _dailyCheckInReward;
    }

    // ============================================================================
    // DEPOSIT FUNCTIONS
    // ============================================================================

    /**
     * @notice Deposit tokens into the vault for yourself
     * @param amount Amount of tokens to deposit
     * @dev Pulls tokens from msg.sender and emits Deposit event
     * 
     * Requirements:
     * - Amount must be greater than 0
     * - Caller must have approved this contract to spend tokens
     */
    function deposit(uint256 amount) external nonReentrant {
        if (amount == 0) revert InvalidAmount();
        
        // Transfer tokens from user to contract
        bool success = token.transferFrom(msg.sender, address(this), amount);
        if (!success) revert TransferFailed();
        
        emit Deposit(msg.sender, amount, block.timestamp);
    }

    /**
     * @notice Deposit tokens into the vault for an agent (paid by human)
     * @param agent Address of the agent receiving the deposit credit
     * @param amount Amount of tokens to deposit
     * @dev Crucial: Allows a Human to pay, but emits event for the Agent's address
     * 
     * Requirements:
     * - Amount must be greater than 0
     * - Agent address must not be zero
     * - Caller must have approved this contract to spend tokens
     */
    function depositFor(address agent, uint256 amount) external nonReentrant {
        if (amount == 0) revert InvalidAmount();
        if (agent == address(0)) revert ZeroAddress();
        
        // Transfer tokens from payer to contract
        bool success = token.transferFrom(msg.sender, address(this), amount);
        if (!success) revert TransferFailed();
        
        // Emit event with agent address for backend tracking
        emit DepositFor(msg.sender, agent, amount, block.timestamp);
    }

    // ============================================================================
    // WITHDRAW FUNCTION
    // ============================================================================

    /**
     * @notice Withdraw tokens with server-signed authorization
     * @param amount Amount of tokens to withdraw
     * @param nonce Unique nonce for this withdrawal (must match current nonce)
     * @param signature Server's signature authorizing this withdrawal
     * 
     * @dev CRITICAL SECURITY FUNCTION
     * 
     * Security measures:
     * - Nonce verification prevents replay attacks
     * - Signature verification ensures backend authorization
     * - ChainId and contract address prevent cross-chain/cross-contract replay
     * - ReentrancyGuard prevents reentrancy attacks
     * - Checks-Effects-Interactions pattern
     * 
     * The signature must be over:
     * keccak256(abi.encodePacked(user, amount, nonce, block.chainid, address(this)))
     * 
     * Requirements:
     * - Amount must be greater than 0
     * - Nonce must match current nonce for user
     * - Signature must be valid and from serverSigner
     * - Contract must have sufficient balance
     */
    function withdraw(
        uint256 amount,
        uint256 nonce,
        bytes memory signature
    ) external nonReentrant {
        if (amount == 0) revert InvalidAmount();
        if (nonce != nonces[msg.sender]) revert InvalidNonce();
        
        // Reconstruct the message hash with replay attack protection
        bytes32 messageHash = keccak256(
            abi.encodePacked(
                msg.sender,
                amount,
                nonce,
                block.chainid,
                address(this)
            )
        );
        
        // Convert to Ethereum Signed Message format
        bytes32 ethSignedMessageHash = messageHash.toEthSignedMessageHash();
        
        // Recover the signer from the signature
        address recoveredSigner = ECDSA.recover(ethSignedMessageHash, signature);
        
        // Verify the signature is from the authorized server signer
        if (recoveredSigner != serverSigner) revert InvalidSignature();
        
        // Update state BEFORE external call (Checks-Effects-Interactions pattern)
        nonces[msg.sender]++;
        
        // Transfer tokens to user
        bool success = token.transfer(msg.sender, amount);
        if (!success) revert TransferFailed();
        
        emit Withdraw(msg.sender, amount, nonce, block.timestamp);
    }

    // ============================================================================
    // DAILY CHECK-IN FUNCTION
    // ============================================================================

    /**
     * @notice Claim daily check-in reward (once per 24 hours)
     * @dev Sends small amount of tokens from Treasury to msg.sender
     * 
     * Requirements:
     * - At least 24 hours must have passed since last check-in
     * - Treasury must have sufficient balance
     */
    function dailyCheckIn() external nonReentrant {
        // Check if 24 hours have passed since last check-in
        if (block.timestamp < lastCheckIn[msg.sender] + 24 hours) {
            revert CheckInTooEarly();
        }
        
        // Check treasury balance
        uint256 treasuryBalance = token.balanceOf(treasury);
        if (treasuryBalance < dailyCheckInReward) {
            revert InsufficientTreasuryBalance();
        }
        
        // Update last check-in timestamp BEFORE external call
        lastCheckIn[msg.sender] = block.timestamp;
        
        // Transfer reward from treasury to user
        // NOTE: Treasury must have approved this contract to spend tokens
        bool success = token.transferFrom(treasury, msg.sender, dailyCheckInReward);
        if (!success) revert TransferFailed();
        
        emit DailyCheckIn(msg.sender, dailyCheckInReward, block.timestamp);
    }

    // ============================================================================
    // ADMIN FUNCTIONS
    // ============================================================================

    /**
     * @notice Update the server signer address
     * @param _newSigner New address for the Python backend server
     * @dev Only owner can update the server signer
     */
    function setServerSigner(address _newSigner) external onlyOwner {
        if (_newSigner == address(0)) revert ZeroAddress();
        
        address oldSigner = serverSigner;
        serverSigner = _newSigner;
        
        emit ServerSignerUpdated(oldSigner, _newSigner, block.timestamp);
    }

    /**
     * @notice Update the treasury address
     * @param _newTreasury New treasury address
     * @dev Only owner can update the treasury
     */
    function setTreasury(address _newTreasury) external onlyOwner {
        if (_newTreasury == address(0)) revert ZeroAddress();
        
        address oldTreasury = treasury;
        treasury = _newTreasury;
        
        emit TreasuryUpdated(oldTreasury, _newTreasury, block.timestamp);
    }

    /**
     * @notice Update the daily check-in reward amount
     * @param _newReward New reward amount
     * @dev Only owner can update the reward amount
     */
    function setDailyCheckInReward(uint256 _newReward) external onlyOwner {
        uint256 oldReward = dailyCheckInReward;
        dailyCheckInReward = _newReward;
        
        emit DailyCheckInRewardUpdated(oldReward, _newReward, block.timestamp);
    }

    /**
     * @notice Emergency token recovery (owner only)
     * @param amount Amount of tokens to recover
     * @dev Should only be used in emergencies
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
     * @notice Get the current nonce for a user
     * @param user Address of the user
     * @return Current nonce value
     */
    function getNonce(address user) external view returns (uint256) {
        return nonces[user];
    }

    /**
     * @notice Get the last check-in timestamp for a user
     * @param user Address of the user
     * @return Last check-in timestamp (0 if never checked in)
     */
    function getLastCheckIn(address user) external view returns (uint256) {
        return lastCheckIn[user];
    }

    /**
     * @notice Check if a user can claim daily check-in reward
     * @param user Address of the user
     * @return True if user can check in, false otherwise
     */
    function canCheckIn(address user) external view returns (bool) {
        return block.timestamp >= lastCheckIn[user] + 24 hours;
    }

    /**
     * @notice Get time until next check-in is available
     * @param user Address of the user
     * @return Seconds until next check-in (0 if available now)
     */
    function timeUntilNextCheckIn(address user) external view returns (uint256) {
        uint256 nextCheckIn = lastCheckIn[user] + 24 hours;
        if (block.timestamp >= nextCheckIn) {
            return 0;
        }
        return nextCheckIn - block.timestamp;
    }

    /**
     * @notice Get the contract's token balance
     * @return Contract's token balance
     */
    function getContractBalance() external view returns (uint256) {
        return token.balanceOf(address(this));
    }
}
