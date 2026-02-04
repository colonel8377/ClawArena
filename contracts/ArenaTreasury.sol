// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import "@openzeppelin/contracts/access/Ownable.sol";
import "@openzeppelin/contracts/security/ReentrancyGuard.sol";
import "@openzeppelin/contracts/security/Pausable.sol";
import "@openzeppelin/contracts/utils/cryptography/ECDSA.sol";

/**
 * @title ArenaTreasury
 * @notice Treasury contract for Agent Arena game platform
 * @dev Manages deposits, withdrawals, and airdrops for the gaming platform
 * 
 * This contract serves as the main treasury for the Agent Arena platform,
 * handling token deposits from users and authorizing withdrawals for
 * game winnings and airdrops.
 * 
 * Security features:
 * - Server-signed withdrawal authorization
 * - Nonce-based replay attack prevention
 * - ReentrancyGuard protection
 * - Emergency pause mechanism
 * - Owner-controlled server signer updates
 */
contract ArenaTreasury is Ownable, ReentrancyGuard, Pausable {
    using ECDSA for bytes32;

    // ============================================================================
    // STATE VARIABLES
    // ============================================================================

    /// @notice The ERC20 token used for the platform
    IERC20 public immutable token;

    /// @notice Address authorized to sign withdrawal permits
    address public serverSigner;

    /// @notice User deposit balances
    mapping(address => uint256) public deposits;

    /// @notice Nonce for each user (prevents replay attacks)
    mapping(address => uint256) public nonces;

    /// @notice Total tokens deposited into the contract
    uint256 public totalDeposits;

    /// @notice Total tokens withdrawn from the contract
    uint256 public totalWithdrawals;

    // ============================================================================
    // EVENTS
    // ============================================================================

    /// @notice Emitted when tokens are deposited
    event Deposit(
        address indexed user,
        uint256 amount,
        uint256 newBalance,
        uint256 timestamp
    );

    /// @notice Emitted when tokens are withdrawn
    event Withdrawal(
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

    /// @notice Emitted when tokens are airdropped
    event Airdrop(
        address indexed recipient,
        uint256 amount,
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
     * @notice Initializes the ArenaTreasury contract
     * @param _token Address of the ERC20 token
     * @param _serverSigner Initial server signer address
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
     * @notice Deposit tokens into the treasury
     * @param amount Amount of tokens to deposit
     * @dev Requires prior token approval
     */
    function deposit(uint256 amount) external nonReentrant whenNotPaused {
        if (amount == 0) revert InvalidAmount();
        
        // Transfer tokens from user to contract
        bool success = token.transferFrom(msg.sender, address(this), amount);
        if (!success) revert TransferFailed();
        
        // Update state
        deposits[msg.sender] += amount;
        totalDeposits += amount;
        
        emit Deposit(
            msg.sender,
            amount,
            deposits[msg.sender],
            block.timestamp
        );
    }

    // ============================================================================
    // WITHDRAWAL FUNCTION
    // ============================================================================

    /**
     * @notice Withdraw tokens with server authorization
     * @param amount Amount to withdraw
     * @param nonce User's current nonce (must match stored nonce)
     * @param signature Server's signature authorizing the withdrawal
     * 
     * @dev The signature must be from serverSigner over:
     *      keccak256(abi.encodePacked(msg.sender, amount, nonce))
     */
    function withdraw(
        uint256 amount,
        uint256 nonce,
        bytes memory signature
    ) external nonReentrant whenNotPaused {
        if (amount == 0) revert InvalidAmount();
        if (deposits[msg.sender] < amount) revert InsufficientBalance();
        if (nonce != nonces[msg.sender]) revert InvalidNonce();
        
        // Reconstruct the message hash
        bytes32 messageHash = keccak256(
            abi.encodePacked(msg.sender, amount, nonce)
        );
        
        // Convert to Ethereum Signed Message format
        bytes32 ethSignedMessageHash = messageHash.toEthSignedMessageHash();
        
        // Recover signer
        address recoveredSigner = ethSignedMessageHash.recover(signature);
        
        // Verify signature
        if (recoveredSigner != serverSigner) revert InvalidSignature();
        
        // Update state BEFORE transfer (Checks-Effects-Interactions)
        nonces[msg.sender]++;
        deposits[msg.sender] -= amount;
        totalWithdrawals += amount;
        
        // Transfer tokens
        bool success = token.transfer(msg.sender, amount);
        if (!success) revert TransferFailed();
        
        emit Withdrawal(
            msg.sender,
            amount,
            nonce,
            deposits[msg.sender],
            block.timestamp
        );
    }

    // ============================================================================
    // AIRDROP FUNCTION (OWNER ONLY)
    // ============================================================================

    /**
     * @notice Airdrop tokens to users (owner only)
     * @param recipients Array of recipient addresses
     * @param amounts Array of amounts to airdrop
     * @dev Arrays must have equal length
     */
    function airdrop(
        address[] calldata recipients,
        uint256[] calldata amounts
    ) external onlyOwner nonReentrant whenNotPaused {
        require(recipients.length == amounts.length, "Array length mismatch");
        
        for (uint256 i = 0; i < recipients.length; i++) {
            if (recipients[i] == address(0)) continue;
            if (amounts[i] == 0) continue;
            
            // Transfer tokens
            bool success = token.transfer(recipients[i], amounts[i]);
            if (success) {
                emit Airdrop(recipients[i], amounts[i], block.timestamp);
            }
        }
    }

    // ============================================================================
    // ADMIN FUNCTIONS
    // ============================================================================

    /**
     * @notice Update the server signer address
     * @param _newSigner New server signer address
     */
    function setServerSigner(address _newSigner) external onlyOwner {
        if (_newSigner == address(0)) revert ZeroAddress();
        
        address oldSigner = serverSigner;
        serverSigner = _newSigner;
        
        emit ServerSignerUpdated(oldSigner, _newSigner, block.timestamp);
    }

    /**
     * @notice Pause the contract (emergency)
     */
    function pause() external onlyOwner {
        _pause();
    }

    /**
     * @notice Unpause the contract
     */
    function unpause() external onlyOwner {
        _unpause();
    }

    /**
     * @notice Emergency token recovery (owner only)
     * @param _token Token to recover
     * @param amount Amount to recover
     * @dev Should only be used for tokens sent by mistake
     */
    function recoverTokens(IERC20 _token, uint256 amount) external onlyOwner {
        require(address(_token) != address(token), "Cannot recover main token");
        bool success = _token.transfer(owner(), amount);
        if (!success) revert TransferFailed();
    }

    // ============================================================================
    // VIEW FUNCTIONS
    // ============================================================================

    /**
     * @notice Get current nonce for a user
     * @param user User address
     * @return Current nonce
     */
    function getNonce(address user) external view returns (uint256) {
        return nonces[user];
    }

    /**
     * @notice Get deposit balance for a user
     * @param user User address
     * @return Current deposit balance
     */
    function getBalance(address user) external view returns (uint256) {
        return deposits[user];
    }

    /**
     * @notice Get contract's token balance
     * @return Token balance
     */
    function getContractBalance() external view returns (uint256) {
        return token.balanceOf(address(this));
    }
}
