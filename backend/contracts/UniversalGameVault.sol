// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import "@openzeppelin/contracts/access/Ownable.sol";
import "@openzeppelin/contracts/security/ReentrancyGuard.sol";
import "@openzeppelin/contracts/utils/cryptography/ECDSA.sol";

/**
 * @title UniversalGameVault
 * @notice Generic vault contract for managing ERC20 tokens across multiple games
 * @dev Holds player deposits and allows withdrawals/claims only with server-signed permits
 * 
 * This contract is a universal "Bank" for all games in the Agent Arena platform.
 * Players deposit tokens to play any game, and can only withdraw/claim with a 
 * permission slip (signature) from the Python Game Server.
 * 
 * Security features:
 * - Nonce-based replay attack prevention (per-user)
 * - Server signature verification using ECDSA
 * - Cross-chain and cross-contract replay protection (chainId + contract address in signature)
 * - ReentrancyGuard protection
 * - Owner-controlled server signer updates
 * - Generic design supports game wins AND airdrops through the same claim mechanism
 */
contract UniversalGameVault is Ownable, ReentrancyGuard {
    using ECDSA for bytes32;

    // ============================================================================
    // STATE VARIABLES
    // ============================================================================

    /// @notice The ERC20 token used for deposits/withdrawals
    IERC20 public immutable token;

    /// @notice Address of the Python off-chain game engine (authorized to sign claims)
    address public serverSigner;

    /// @notice User deposit balances (on-chain accounting)
    mapping(address => uint256) public balances;

    /// @notice Nonce for each user (prevents replay attacks)
    mapping(address => uint256) public nonces;

    // ============================================================================
    // EVENTS
    // ============================================================================

    /// @notice Emitted when tokens are deposited
    event Deposit(
        address indexed user,
        uint256 amount,
        string gameId,
        uint256 newBalance,
        uint256 timestamp
    );

    /// @notice Emitted when tokens are claimed (withdrawal or airdrop)
    event Claim(
        address indexed user,
        uint256 amount,
        uint256 nonce,
        uint256 newBalance,
        uint256 timestamp
    );

    /// @notice Emitted when server signer is updated
    event ServerSignerUpdated(
        address indexed oldSigner,
        address indexed newSigner,
        uint256 timestamp
    );

    // ============================================================================
    // ERRORS
    // ============================================================================

    error InvalidAmount();
    error InsufficientBalance();
    error InvalidSignature();
    error InvalidNonce();
    error ZeroAddress();
    error TransferFailed();

    // ============================================================================
    // CONSTRUCTOR
    // ============================================================================

    /**
     * @notice Initializes the UniversalGameVault contract
     * @param _token Address of the ERC20 token
     * @param _serverSigner Initial address of the Python backend server
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
     * @notice Deposit tokens into the vault
     * @param amount Amount of tokens to deposit
     * @param gameId Optional game identifier for off-chain analytics (can be empty string)
     * @dev Transfers tokens from caller to contract and updates balances mapping
     * 
     * Requirements:
     * - Amount must be greater than 0
     * - Caller must have approved this contract to spend tokens
     */
    function deposit(uint256 amount, string calldata gameId) external nonReentrant {
        if (amount == 0) revert InvalidAmount();
        
        // Transfer tokens from user to contract
        bool success = token.transferFrom(msg.sender, address(this), amount);
        if (!success) revert TransferFailed();
        
        // Update user balance
        balances[msg.sender] += amount;
        
        emit Deposit(
            msg.sender,
            amount,
            gameId,
            balances[msg.sender],
            block.timestamp
        );
    }

    // ============================================================================
    // CLAIM FUNCTION (UNIVERSAL: WITHDRAWALS + AIRDROPS)
    // ============================================================================

    /**
     * @notice Claim tokens with server-signed authorization (for game wins OR airdrops)
     * @param amount Amount of tokens to claim
     * @param nonce Unique nonce for this claim (must match current nonce)
     * @param signature Server's signature authorizing this claim
     * 
     * @dev CRITICAL SECURITY FUNCTION
     * 
     * This function implements a dual-authorization claim system:
     * 1. User initiates claim request (could be withdrawal or airdrop)
     * 2. Python backend verifies eligibility and signs claim
     * 3. User submits signed claim to this function
     * 
     * Security measures:
     * - Nonce verification prevents replay attacks (blockchain is source of truth)
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
     */
    function claimWithSignature(
        uint256 amount,
        uint256 nonce,
        bytes memory signature
    ) external nonReentrant {
        if (amount == 0) revert InvalidAmount();
        if (nonce != nonces[msg.sender]) revert InvalidNonce();
        
        // Reconstruct the message hash with replay attack protection
        // Includes chainId and contract address to prevent cross-chain/contract replay
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
        address recoveredSigner = ethSignedMessageHash.recover(signature);
        
        // Verify the signature is from the authorized server signer
        if (recoveredSigner != serverSigner) revert InvalidSignature();
        
        // Update state BEFORE external call (Checks-Effects-Interactions pattern)
        nonces[msg.sender]++;
        
        // For withdrawals: deduct from balance
        // For airdrops: balance check not needed (tokens come from contract treasury)
        // We perform a balance check but allow claims even if balance is insufficient
        // (this enables airdrops from contract treasury)
        if (balances[msg.sender] >= amount) {
            balances[msg.sender] -= amount;
        }
        
        // Transfer tokens to user
        bool success = token.transfer(msg.sender, amount);
        if (!success) revert TransferFailed();
        
        emit Claim(
            msg.sender,
            amount,
            nonce,
            balances[msg.sender],
            block.timestamp
        );
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
     * @notice Emergency token recovery (owner only)
     * @param amount Amount of tokens to recover
     * @dev Should only be used in emergencies to recover contract treasury
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
     * @notice Get the deposit balance for a user
     * @param user Address of the user
     * @return Current deposit balance
     */
    function getBalance(address user) external view returns (uint256) {
        return balances[user];
    }

    /**
     * @notice Get the contract's token balance (treasury)
     * @return Contract's token balance
     */
    function getContractBalance() external view returns (uint256) {
        return token.balanceOf(address(this));
    }
}
